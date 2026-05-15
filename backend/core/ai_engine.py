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
from core import llm_server
from core.engine_config import EngineConfig
from core.llm_router import Tier, get_router
from core.llm_metrics import emit_route, emit_escalate
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


# Filename pattern for natural-language mentions ("show me screenshot.png").
# Restricted to the extensions we actually ingest — keeps false positives
# down (e.g. "version 1.5.2" is not a filename in our world).
_FILENAME_MENTION_RE = re.compile(
    r'\b([\w\-]+\.(?:jpg|jpeg|png|webp|pdf|txt|md|py|csv|json|log|yaml|yml|conf|ini))\b',
    re.IGNORECASE,
)


_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")


def _image_document_refs(
    db,
    filenames: list[str],
    workspace_id: str,
    session_id: Optional[str],
) -> list[dict]:
    """Resolve a list of filenames to {id, filename, mime} entries for
    image documents only. Non-image sources (PDF/text) return nothing
    because we don't persist their bytes for inline rendering.

    Looks up by exact-filename + workspace + (session OR is_global)
    scope — same scoping the auto-RAG path uses, so we never surface
    a doc the user couldn't see via the chunks.
    """
    if not filenames:
        return []
    image_filenames = [f for f in filenames if f.lower().endswith(_IMAGE_EXTS)]
    if not image_filenames:
        return []
    from sqlalchemy import or_ as sa_or
    rows = (
        db.query(models.Document.id, models.Document.filename)
        .filter(
            models.Document.workspace_id == workspace_id,
            models.Document.filename.in_(image_filenames),
            sa_or(
                models.Document.session_id == session_id,
                models.Document.is_global == True,  # noqa: E712 — SQLAlchemy column compare
            ),
            models.Document.storage_path.isnot(None),
        )
        .all()
    )
    refs: list[dict] = []
    seen_ids: set[str] = set()
    for doc_id, filename in rows:
        if doc_id in seen_ids:
            continue
        seen_ids.add(doc_id)
        ext = filename.lower().rsplit(".", 1)[-1]
        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
                "png": "image/png", "webp": "image/webp"}.get(ext, "application/octet-stream")
        refs.append({"id": doc_id, "filename": filename, "mime": mime})
    return refs


def _match_session_filename_mentions(
    text: str,
    *,
    workspace_id: str,
    session_id: Optional[str],
) -> list[str]:
    """Return filenames mentioned in `text` that match a Document in the
    current session (or workspace globals). Empty list if none.

    Used by stream_chat as a fallback when no [Attached_File:] marker
    is present — lets the user reference earlier uploads by filename
    in natural conversation without re-attaching.
    """
    candidates = _FILENAME_MENTION_RE.findall(text)
    if not candidates:
        return []
    # Lowercase + dedupe so ILIKE-style matching is straightforward.
    candidates_lower = list({c.lower() for c in candidates})
    db = database.SessionLocal()
    try:
        from sqlalchemy import func, or_
        rows = (
            db.query(models.Document.filename)
            .filter(
                models.Document.workspace_id == workspace_id,
                func.lower(models.Document.filename).in_(candidates_lower),
                or_(
                    models.Document.session_id == session_id,
                    models.Document.is_global == True,  # noqa: E712 — SQLAlchemy column comparison
                ),
            )
            .all()
        )
        return [r[0] for r in rows]
    finally:
        db.close()

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
        response = await llm_server.generate(client, prompt=prompt, model=llm_server.DEFAULT_CHAT_MODEL, options={"num_ctx": 8192})
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
    tier: Optional[Tier] = None,
    escalated: bool = False,
):
    workspace_tools = tool_set.callables

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

    # Route BEFORE the RAG/clean-text step below mutates recent_messages[-1] —
    # the heuristic needs the original user text (incl. the [Attached_File:]
    # marker) to detect attachments. If `tier` was passed in, we're inside an
    # escalation re-entry and skip the router.
    router = get_router()
    if tier is None:
        last_user = recent_messages[-1] if recent_messages and recent_messages[-1].get("role") == "user" else None
        prompt_for_routing = (last_user or {}).get("content", "") or ""
        attachments_for_routing = ["file"] if "[Attached_File:" in prompt_for_routing else []
        history_for_routing = recent_messages[:-1] if last_user else recent_messages
        routed_model, tier, route_reason = router.pick(
            prompt_for_routing, history_for_routing, attachments_for_routing,
        )
        emit_route(
            model=routed_model,
            tier=tier.value,
            reason=route_reason,
            prompt_len=len(prompt_for_routing),
        )
    else:
        routed_model = router.small if tier is Tier.SMALL else router.large

    if memory_content:
        system_msg["content"] += f"\n\n[SYSTEM MEMORY LOG: The following is a dense summary of earlier interactions in this session.]\n{memory_content}"

    if recent_messages and recent_messages[-1].get("role") == "user":
        last_query = recent_messages[-1].get("content", "")
        # Two ways to scope auto-RAG to a specific document:
        #   1. Explicit [Attached_File:X] marker from this turn's upload.
        #   2. Natural-language filename mention that matches a Document
        #      already in this session/workspace (e.g. "what's in
        #      screenshot.png" referring to an earlier upload).
        # Marker path strips the marker from the visible user text;
        # mention path leaves the filename in place (it's part of the
        # real prompt).
        marker_filenames = re.findall(r'\[Attached_File:\s*([^\]]+?)\s*\]', last_query)
        has_attachment = bool(marker_filenames)
        attached_filenames: list[str] = marker_filenames
        clean_user_text = re.sub(r'\[Attached_File:.*?\]', '', last_query).strip() if has_attachment else last_query.strip()

        if not has_attachment:
            mention_match = _match_session_filename_mentions(
                last_query, workspace_id=workspace_id, session_id=session_id,
            )
            if mention_match:
                attached_filenames = mention_match
                has_attachment = True

        if has_attachment:
            # No user text alongside the attachment → caller wants an overview
            # of the file, not a semantic search. Flag instead of magic-string.
            overview_mode = not clean_user_text
            rag_query = clean_user_text if clean_user_text else ""
            db = database.SessionLocal()
            try:
                rag_data = await knowledge.retrieve_relevant_chunks(
                    client, db, query=rag_query, workspace_id=workspace_id, session_id=session_id,
                    overview_mode=overview_mode,
                    restrict_to_filenames=attached_filenames or None,
                )
                if rag_data and rag_data.get("context"):
                    rag_context = rag_data["context"]
                    sources_list = rag_data["sources"]
                    # Caption is the canonical record of image content
                    # (see services/image_describe.py). We do NOT re-
                    # attach the original bytes for re-analysis — the
                    # caption already covers what the model needs.
                    recent_messages[-1]["content"] = (
                        f"I have attached a file. Relevant context:\n{rag_context}\n\n"
                        f"My message: {clean_user_text}\n\n"
                        f"{MICRO_PROMPTS['rag_file_upload_instruction']}"
                    )
                    yield format_file_analyzed(sources_list)
                    # Emit a structured event listing image docs among
                    # the sources so the frontend can render an inline
                    # preview below the assistant turn. Image docs are
                    # identified by filename extension; non-image
                    # sources (PDF/text) get no preview (no original
                    # bytes persisted today). See routers/chat.py
                    # GET /documents/{id}/raw for the bytes endpoint.
                    image_refs = _image_document_refs(db, sources_list, workspace_id, session_id)
                    if image_refs:
                        yield {"type": "files_referenced", "files": image_refs}
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
    had_tool_error = False

    try:
        while loop_count < max_loops:
            if is_disconnected and await is_disconnected():
                return

            loop_count += 1
            data = await llm_server.chat(
                client,
                messages=full_messages,
                tools=tools_payload,
                model=routed_model,
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

                    # Hide auto-injected context params from the user-visible
                    # System Action line — they're plumbing, not signal. The
                    # user cares about `query` / `hostname` / `port` etc., not
                    # workspace_id or session_id which are always the same.
                    _hidden = {"workspace_id", "session_id"}
                    display_args = {k: v for k, v in raw_args.items()
                                    if k in valid_params and k not in _hidden}
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
                        had_tool_error = True
                    except Exception as tool_err:
                        result = f"Tool execution failed: {str(tool_err)}"
                        had_tool_error = True

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
                        # Only claim failure if a tool actually errored.
                        # If tools succeeded and the model just had nothing
                        # to add (e.g., after a `rename_chat_session` that
                        # returned "Success! ..."), say nothing — the tool
                        # result block already shows what happened.
                        if had_tool_error:
                            content = MICRO_PROMPTS["fallback_tool_failure"]
                    else:
                        content = MICRO_PROMPTS["fallback_generic"]

                if content.strip():
                    words = content.split(" ")
                    for i, word in enumerate(words):
                        if is_disconnected and await is_disconnected():
                            return
                        yield word + (" " if i < len(words) - 1 else "")
                        await asyncio.sleep(0.01)

                finished_cleanly = True
                break

        # Escalation gate. Two triggers per [[project-router-escalation-triggers]]:
        # max-iterations (loop exhausted without a clean answer) or tool-error
        # (any tool raised during the loop). Single-step: an already-escalated
        # request cannot re-escalate.
        escalation_reason = None
        if not finished_cleanly:
            escalation_reason = "max_iterations"
        elif had_tool_error:
            escalation_reason = "tool_error"

        if tier is Tier.SMALL and not escalated and escalation_reason:
            emit_escalate(
                from_model=routed_model,
                to_model=router.large,
                reason=escalation_reason,
            )
            async for chunk in stream_chat(
                client,
                messages,
                workspace_id=workspace_id,
                engine_config=engine_config,
                tool_set=tool_set,
                session_id=session_id,
                is_disconnected=is_disconnected,
                tier=Tier.LARGE,
                escalated=True,
            ):
                yield chunk
            return

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
        text = await llm_server.generate(client, prompt=system_prompt, model=llm_server.DEFAULT_SMALL_CHAT_MODEL, options={"num_ctx": 4096})
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
