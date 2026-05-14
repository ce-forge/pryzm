import asyncio
import json
import inspect
import re
from typing import Awaitable, Callable, Optional

import httpx

from db import database, models
from services import knowledge
from config import settings
import tools  # triggers @tool registration as a side effect
from core.prompt_manager import MICRO_PROMPTS
from core import ollama
from core.engine_config import EngineConfig
from tools.registry import ResolvedToolSet
from utils.formatters import (
    format_tool_execution,
    format_file_analyzed,
    format_code_block,
    format_knowledge_reference,
    format_error
)

# Reasoning models (Qwen 3.x, DeepSeek-R1, etc.) wrap their inner monologue
# in <think>/<thinking> blocks that should never reach the user. We strip
# *paired* blocks only, and only for an explicit tag allowlist — so legitimate
# angle-bracket content (Vec<i32>, <email@x>, <3, HTML examples) passes through
# untouched. KNOWN LIMITATION: if the assistant tries to *teach* the user about
# <think> tags, the example will be stripped along with everything between the
# tags. Re-run with rephrasing if you hit that case.
_THINK_BLOCK_RE = re.compile(
    r'<(think|thinking|scratchpad)\b[^>]*>.*?</\1>',
    re.DOTALL | re.IGNORECASE,
)

async def condense_chat_memory(
    client: httpx.AsyncClient,
    old_memory: str,
    messages: list,
    *,
    engine_config: EngineConfig,
) -> str:
    """Runs asynchronously to summarize older messages and prevent context window overflow."""
    chat_text = "\n".join([f"{m['role'].capitalize()}: {m['content']}" for m in messages if m['role'] in ['user', 'assistant']])

    prompt = f"{MICRO_PROMPTS['memory_condenser_system']}\n\n"

    if old_memory:
        prompt += f"--- PREVIOUS MEMORY ---\n{old_memory}\n\n"
    prompt += f"--- NEW CHAT HISTORY TO ADD ---\n{chat_text}\n"

    try:
        response = await ollama.generate(client, prompt=prompt, model=engine_config.model, options={"num_ctx": 8192})
        return response.strip()
    except Exception as e:
        print(f"Memory Condensation Failed: {e}")
        return old_memory

async def _execute_tool(tool_call: dict, workspace_tools: dict) -> str:
    """Run one tool call from the agentic loop.

    Sync tools go through asyncio.to_thread so they don't block the event
    loop. Async tools (if any are added later) are awaited directly.
    The caller wraps this in asyncio.wait_for for timeout enforcement.
    """
    name = tool_call["function"]["name"]
    args = tool_call["function"].get("arguments", {})
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except Exception:
            args = {}

    func = workspace_tools[name]
    valid_params = inspect.signature(func).parameters.keys()
    safe_args = {k: v for k, v in args.items() if k in valid_params}

    if asyncio.iscoroutinefunction(func):
        return await func(**safe_args)
    return await asyncio.to_thread(func, **safe_args)


async def stream_chat(
    client: httpx.AsyncClient,
    messages: list,
    *,
    workspace_id: str,
    engine_config: EngineConfig,
    tool_set: ResolvedToolSet,
    session_id: str = None,
    is_disconnected: Optional[Callable[[], Awaitable[bool]]] = None,
):
    workspace_tools = tool_set.callables
    effective_model = engine_config.model

    # Substitute {tool_names} placeholder in the workspace's stored
    # system prompt. We need the system_prompt from the DB but do NOT
    # need a full workspace fetch — retrieve it with a targeted query.
    db = database.SessionLocal()
    try:
        workspace = db.query(models.Workspace).filter(
            models.Workspace.id == workspace_id
        ).first()
        if not workspace:
            yield f"\n[Engine Error: Workspace {workspace_id} not found.]"
            return
        system_prompt_raw = workspace.system_prompt or ""
    finally:
        db.close()

    tool_names = ", ".join(workspace_tools.keys())
    system_content = system_prompt_raw.replace("{tool_names}", tool_names)

    tools_payload = tool_set.definitions if workspace_tools else None
    system_msg = {"role": "system", "content": system_content}

    memory_content = ""
    active_messages = []

    for m in messages:
        if m.get("role") == "memory":
            try:
                mem_data = json.loads(m.get("content"))
                memory_content = mem_data.get("summary", "")
            except Exception:
                memory_content = m.get("content")
        else:
            active_messages.append(m)

    recent_limit = settings.MEMORY_CONTEXT_WINDOW
    recent_messages = active_messages[-recent_limit:] if len(active_messages) > recent_limit else active_messages

    if memory_content:
        system_msg["content"] += f"\n\n[SYSTEM MEMORY LOG: The following is a dense summary of earlier interactions in this session.]\n{memory_content}"

    if recent_messages and recent_messages[-1].get("role") == "user":
        last_query = recent_messages[-1].get("content", "")
        has_attachment = "[Attached_File:" in last_query
        clean_user_text = re.sub(r'\[Attached_File:.*?\]', '', last_query).strip()
        if has_attachment:
            rag_query = clean_user_text if clean_user_text else "document overview"
            db = database.SessionLocal()
            try:
                rag_data = await knowledge.retrieve_relevant_chunks(
                    client, db, query=rag_query, workspace_id=workspace_id, session_id=session_id,
                )
                if rag_data and rag_data.get("context"):
                    rag_context = rag_data["context"]
                    sources_list = rag_data["sources"]
                    recent_messages[-1]["content"] = f"I have attached a file. Relevant context:\n{rag_context}\n\nMy message: {clean_user_text}\n\n{MICRO_PROMPTS['rag_file_upload_instruction']}"
                    yield format_file_analyzed(sources_list)
            except Exception as rag_err:
                yield format_error(str(rag_err), "File Read Error")
            finally:
                db.close()
        else:
            recent_messages[-1]["content"] = clean_user_text

    full_messages = [system_msg] + recent_messages
    max_loops = settings.MAXIMUM_TOOL_LOOPS
    loop_count = 0
    finished_cleanly = False

    try:
        while loop_count < max_loops:
            if is_disconnected and await is_disconnected():
                return

            loop_count += 1
            data = await ollama.chat(
                client,
                messages=full_messages,
                tools=tools_payload,
                model=effective_model,
            )
            message = data.get("message", {})

            if message.get("tool_calls"):
                full_messages.append(message)
                for tool_call in message["tool_calls"]:
                    func_name = tool_call["function"]["name"]
                    if func_name not in workspace_tools:
                        continue

                    # Inject implicit params before the tool runs.
                    raw_args = tool_call["function"].get("arguments", {})
                    if isinstance(raw_args, str):
                        try:
                            raw_args = json.loads(raw_args)
                        except Exception:
                            raw_args = {}
                    func = workspace_tools[func_name]
                    valid_params = inspect.signature(func).parameters.keys()
                    if "workspace_id" in valid_params:
                        raw_args["workspace_id"] = workspace_id
                    if "session_id" in valid_params:
                        raw_args["session_id"] = session_id

                    # Rebuild tool_call with enriched args so _execute_tool
                    # picks them up (it re-reads arguments from the dict).
                    enriched_call = {
                        "function": {"name": func_name, "arguments": raw_args}
                    }

                    display_args = {k: v for k, v in raw_args.items()
                                    if k in valid_params}
                    yield format_tool_execution(func_name, display_args)

                    try:
                        result = await asyncio.wait_for(
                            _execute_tool(enriched_call, workspace_tools),
                            timeout=settings.TOOL_TIMEOUT_SECONDS,
                        )
                    except asyncio.TimeoutError:
                        result = (
                            f"Tool {func_name} timed out after "
                            f"{settings.TOOL_TIMEOUT_SECONDS}s. "
                            "Continue with what you have."
                        )
                    except Exception as tool_err:
                        result = f"Tool execution failed: {str(tool_err)}"

                    yield format_code_block(result)
                    full_messages.append({
                        "role": "tool",
                        "content": str(result),
                        "name": func_name,
                    })
                continue

            else:
                content = message.get("content")
                if content is None:
                    content = ""

                content = _THINK_BLOCK_RE.sub('', content).strip()

                # Catch the model stalling out: a one-or-two-word "thought"
                # emission, or echoing the tool-loop instruction back at us.
                # Tightened from the old "starts with 'thought'" check, which
                # false-positived on any legitimate answer beginning with
                # "Thoughts on …".
                stripped = content.strip().lower()
                is_thought_stall = (
                    stripped in {"thought", "thoughts", "thought.", "thought:"}
                    or "i must wait for the search results" in stripped
                )
                if is_thought_stall:
                    content = MICRO_PROMPTS["fallback_thought_loop"]

                if not content.strip():
                    if loop_count > 1:
                        content = MICRO_PROMPTS["fallback_tool_failure"]
                    else:
                        content = MICRO_PROMPTS["fallback_generic"]

                words = content.split(" ")
                for i, word in enumerate(words):
                    if is_disconnected and await is_disconnected():
                        return
                    yield word + (" " if i < len(words) - 1 else "")
                    await asyncio.sleep(0.01)

                finished_cleanly = True
                break

        if not finished_cleanly:
            yield MICRO_PROMPTS["warning_max_loops"]

    except Exception as e:
        yield f"\n[Engine Error: {str(e)}]"

async def generate_title(
    client: httpx.AsyncClient,
    prompt: str,
    *,
    engine_config: EngineConfig,
) -> str:
    clean_prompt = re.sub(r'\[Attached_File:.*?\]', '', prompt).strip()
    if not clean_prompt:
        return MICRO_PROMPTS["title_document_default"]

    system_prompt = f"{MICRO_PROMPTS['title_generator_system']} Message: {clean_prompt}"

    try:
        text = await ollama.generate(client, prompt=system_prompt, model=engine_config.model, options={"num_ctx": 4096})
        text = text.strip(' \n"\'*.')
        if not text:
            return MICRO_PROMPTS["title_default"]
        # Cap rather than discard — a 6-word title from the model is usually
        # better than the first 3 words of the user's prompt. Truncate to
        # 5 words + ellipsis only when the title is genuinely over-long.
        title_words = text.split()
        if len(title_words) > 5:
            text = " ".join(title_words[:5]) + "..."
        return text
    except Exception:
        words = clean_prompt.split()
        return " ".join(words[:3]) + "..." if len(words) > 3 else MICRO_PROMPTS["title_default"]
