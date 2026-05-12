import os
import requests
import json
import inspect
import time
import re

from db import database
from services import knowledge
from config import settings
import tools
from tools.registry import AVAILABLE_TOOLS, TOOL_DEFINITIONS
from core.prompt_manager import MICRO_PROMPTS
from utils.formatters import (
    format_tool_execution, 
    format_file_analyzed, 
    format_code_block,
    format_knowledge_reference, 
    format_error
)

BASE_OLLAMA_URL = settings.OLLAMA_URL.strip().rstrip('/')

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

def condense_chat_memory(old_memory: str, messages: list, model_name: str) -> str:
    """Runs asynchronously to summarize older messages and prevent context window overflow."""
    url = f"{BASE_OLLAMA_URL}/api/generate"
    
    chat_text = "\n".join([f"{m['role'].capitalize()}: {m['content']}" for m in messages if m['role'] in ['user', 'assistant']])
    
    prompt = f"{MICRO_PROMPTS['memory_condenser_system']}\n\n"
    
    if old_memory:
        prompt += f"--- PREVIOUS MEMORY ---\n{old_memory}\n\n"
    prompt += f"--- NEW CHAT HISTORY TO ADD ---\n{chat_text}\n"

    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
        "options": {"num_ctx": 8192}
    }
    
    try:
        resp = requests.post(url, json=payload, timeout=60)
        resp.raise_for_status()
        return resp.json().get("response", "").strip()
    except Exception as e:
        print(f"Memory Condensation Failed: {e}")
        return old_memory

def stream_chat(messages: list, workspace_id: str, session_id: str = None, model_name: str = "gemma4:e4b"):
    from services.workspaces import resolve_tools_for_workspace, resolve_model_for_request

    url = f"{BASE_OLLAMA_URL}/api/chat"

    # Fetch the workspace once (needed for tool list, prompt, and model pin).
    from db import models as db_models
    db = database.SessionLocal()
    try:
        workspace = db.query(db_models.Workspace).filter(
            db_models.Workspace.id == workspace_id
        ).first()
        if not workspace:
            yield f"\n[Engine Error: Workspace {workspace_id} not found.]"
            return

        workspace_tools, workspace_tool_defs = resolve_tools_for_workspace(workspace)
        effective_model = resolve_model_for_request(workspace, model_name)

        # Substitute {tool_names} placeholder in the workspace's stored
        # system prompt.
        tool_names = ", ".join(workspace_tools.keys())
        system_content = (workspace.system_prompt or "").replace("{tool_names}", tool_names)

        if workspace_tools:
            tools_payload = workspace_tool_defs
        else:
            tools_payload = None

        system_msg = {"role": "system", "content": system_content}
        workspace_slug = workspace.slug
    finally:
        db.close()

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
                rag_data = knowledge.retrieve_relevant_chunks(
                    db, query=rag_query, workspace_id=workspace_id, session_id=session_id,
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
            loop_count += 1
            payload = {
                "model": effective_model,
                "messages": full_messages,
                "stream": False,
                "options": {"num_ctx": 8192},
            }
            if tools_payload:
                payload["tools"] = tools_payload

            resp = requests.post(url, json=payload, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            message = data.get("message", {})

            if message.get("tool_calls"):
                full_messages.append(message)
                for tool in message["tool_calls"]:
                    func_name = tool["function"]["name"]
                    args = tool["function"]["arguments"]
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except Exception:
                            args = {}
                    if func_name in workspace_tools:
                        func = workspace_tools[func_name]
                        valid_params = inspect.signature(func).parameters.keys()
                        safe_args = {k: v for k, v in args.items() if k in valid_params}
                        if "workspace" in valid_params:
                            safe_args["workspace"] = workspace_slug
                        if "session_id" in valid_params:
                            safe_args["session_id"] = session_id
                        yield format_tool_execution(func_name, safe_args)
                        try:
                            result = func(**safe_args)
                        except Exception as tool_err:
                            result = f"Tool execution failed: {str(tool_err)}"
                        yield format_code_block(result)
                        full_messages.append({
                            "role": "tool",
                            "content": result,
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
                    yield word + (" " if i < len(words) - 1 else "")
                    time.sleep(0.01)

                finished_cleanly = True
                break

        if not finished_cleanly:
            yield MICRO_PROMPTS["warning_max_loops"]

    except Exception as e:
        yield f"\n[Engine Error: {str(e)}]"

def generate_title(prompt: str, model_name: str = "gemma4:e4b") -> str:
    url = f"{BASE_OLLAMA_URL}/api/generate"
    
    clean_prompt = re.sub(r'\[Attached_File:.*?\]', '', prompt).strip()
    if not clean_prompt:
        return MICRO_PROMPTS["title_document_default"]

    system_prompt = f"{MICRO_PROMPTS['title_generator_system']} Message: {clean_prompt}"

    payload = {
        "model": model_name, 
        "prompt": system_prompt, 
        "stream": False,
        "options": {"num_ctx": 4096}
        }    
    
    try:
        response = requests.post(url, json=payload, timeout=5)
        response.raise_for_status()
        text = response.json().get("response", "").strip(' \n"\'*.')
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