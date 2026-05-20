import asyncio
import json
import inspect
import logging
import re
import time
from typing import Awaitable, Callable, Optional

logger = logging.getLogger(__name__)

import httpx

from core.audit import EventType, log_event
from db import database, models
from services import knowledge
from config import settings
import tools  # triggers @tool registration as a side effect
from core.prompt_manager import MICRO_PROMPTS
from core import llm_server
from core.engine_config import EngineConfig
from core.llm_router import Tier, get_router
from core.llm_metrics import emit_route, emit_escalate
from tools.registry import ResolvedToolSet, render_tool_directives
from core.modes import apply_modes
from utils.formatters import (
    format_file_analyzed,
    format_knowledge_reference,
    format_error
)

# Filename pattern for natural-language mentions ("show me screenshot.png").
# Restricted to the extensions we actually ingest — keeps false positives
# down (e.g. "version 1.5.2" is not a filename in our world).
_FILENAME_MENTION_RE = re.compile(
    r'\b([\w\-]+\.(?:jpg|jpeg|png|webp|pdf|txt|md|py|csv|json|log|yaml|yml|conf|ini))\b',
    re.IGNORECASE,
)

# Image extensions whose original bytes we persist (Document.storage_path
# is non-NULL) and can re-render inline in the chat surface via
# GET /documents/{id}/raw. PDFs/text are stored as chunks only.
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


def _inject_tool_directives(prompt: str, rendered: str) -> str:
    """Substitute {tool_directives} in the prompt with the rendered block.

    If the placeholder is missing, append the block after the prompt with a
    blank line separator — keeps hand-edited workspace prompts (that forgot the
    placeholder) functional. If the rendered block is empty (no tool has any
    directive AND no module has a MODULE_DIRECTIVE), the prompt is returned
    unchanged regardless of whether the placeholder is present.
    """
    if not rendered:
        # Strip the placeholder along with any blank lines that surrounded it.
        # Without this, removing a mid-prompt placeholder leaves a double blank
        # line between the surrounding sections.
        return re.sub(r"\n*\{tool_directives\}\n*", "\n\n", prompt).rstrip()
    if "{tool_directives}" in prompt:
        return prompt.replace("{tool_directives}", rendered)
    logger.debug("Workspace prompt missing {tool_directives} placeholder; appending block at end.")
    return f"{prompt}\n\n{rendered}"


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
        # Use the always-on small model. The on-demand tier may not fit
        # in VRAM alongside reasoning-tier models that are resident, and
        # summarisation doesn't need the larger model's capability.
        response = await llm_server.generate(
            client, prompt=prompt,
            model=llm_server.DEFAULT_SMALL_CHAT_MODEL,
            options={"num_ctx": 8192},
        )
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


def _audit_chat_event(
    user_id: Optional[str],
    workspace_id: str,
    session_id: Optional[str],
    event_type: str,
    payload: dict,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
) -> None:
    """Open a short-lived session, write one audit row, commit, close.

    Used by stream_chat's tool loop and auto-RAG path. The router's DB
    session is closed before the generator runs, so audit writes here
    can't piggyback on it. Errors are swallowed — losing one chat audit
    row should not break the user-visible response."""
    audit_db = database.SessionLocal()
    try:
        user_obj = (
            audit_db.query(models.User).filter_by(id=user_id).first()
            if user_id
            else None
        )
        ws_obj = audit_db.query(models.Workspace).filter_by(id=workspace_id).first()
        sess_obj = (
            audit_db.query(models.Session).filter_by(id=session_id).first()
            if session_id
            else None
        )
        log_event(
            audit_db,
            event_type,
            user=user_obj,
            workspace=ws_obj,
            session=sess_obj,
            resource_type=resource_type,
            resource_id=resource_id,
            payload=payload,
        )
        audit_db.commit()
    except Exception:
        audit_db.rollback()
    finally:
        audit_db.close()


def _resolve_routed_model(
    router,
    tier_hint: str | None,
    default_model_id: str,
    default_reason: str,
) -> tuple[str, str]:
    """Apply a mode-declared tier override on top of the router's heuristic pick.

    `tier_hint` is the third element returned by `apply_modes`. Today only the
    web_search mode sets one (`tier_override="web"`). Lookup is generic:
    `{hint}` -> `router.{hint}_capable_model()` if the method exists. Falls back
    to the heuristic pick when no model carries the tag or no hint is supplied.

    Returns `(model_id, reason)` — reason is the keyword emitted to the route
    audit event so we can tell heuristic picks from mode overrides in logs.
    """
    if tier_hint is None:
        return default_model_id, default_reason
    lookup = getattr(router, f"{tier_hint}_capable_model", None)
    if lookup is None:
        return default_model_id, default_reason
    candidate = lookup()
    if candidate is None:
        return default_model_id, default_reason
    return candidate, f"mode_tier_override:{tier_hint}"


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
    modes: Optional[list[str]] = None,
    user_id: Optional[str] = None,
):
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

    # Apply per-turn modes BEFORE rendering tool_names + directives so any
    # force-included tool appears in both the LLM-visible tool list and the
    # `== AVAILABLE TOOLS ==` directive block. Always called — even with an
    # empty `modes` list — because apply_modes runs the gating pass that
    # hides mode-gated tools (web_search) when their mode isn't active.
    # The tier hint is consumed below: after the heuristic router picks a model,
    # _resolve_routed_model checks whether a mode-declared override should swap
    # it for a tag-matched model (e.g. web_search mode -> web-tagged model).
    tool_set, system_prompt_raw, tier_hint_from_modes = apply_modes(
        tool_set, system_prompt_raw, modes or [],
    )

    workspace_tools = tool_set.callables
    tool_names = ", ".join(workspace_tools.keys())
    system_content = system_prompt_raw.replace("{tool_names}", tool_names)
    rendered_directives = render_tool_directives(tool_set)
    system_content = _inject_tool_directives(system_content, rendered_directives)

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
        routed_model, route_reason = _resolve_routed_model(
            router, tier_hint_from_modes, routed_model, route_reason,
        )
        emit_route(
            model=routed_model,
            tier=tier.value,
            reason=route_reason,
            prompt_len=len(prompt_for_routing),
        )
    else:
        # Escalation re-entry — tier was passed in explicitly. Mode tier
        # overrides do NOT apply here: escalation is a stronger signal
        # ("this turn needs more compute") than a mode's default-model
        # preference, so we honour the escalated tier verbatim.
        routed_model = router.small if tier is Tier.SMALL else router.large

    # Only models tagged `reasoning` in the catalog have their
    # `reasoning_content` surfaced to the UI. Small chat models emit
    # short, low-signal chain-of-thought that adds noise on regular
    # turns; gating here keeps the pill (and DB column) empty for them.
    surface_reasoning = "reasoning" in router.catalog.get(routed_model, set())

    # Tell the client which tier this turn picked and whether it's
    # reasoning-tagged, so the ProcessingAnimation can switch its label
    # to `Thinking…` before any deltas arrive. Catalog tag is the single
    # source of truth — same gate as the reasoning_chunk emission below.
    yield {
        "type": "route",
        "model": routed_model,
        "tier": tier.value,
        "is_reasoning": surface_reasoning,
    }

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
                    _audit_chat_event(
                        user_id, workspace_id, session_id,
                        EventType.CHAT_RAG_RETRIEVED,
                        {
                            "query_preview": (rag_query or "")[:200],
                            "num_results": len(sources_list),
                            "source_filenames": list(sources_list),
                            "mode": "auto",
                        },
                    )
                    # Single source of truth for image content is the
                    # caption written at upload time (see
                    # services/image_describe.py). We deliberately do NOT
                    # re-attach the original bytes here — the caption is
                    # detailed (text-extraction-first) and the duplicate
                    # analysis was costing 700-1000 prompt tokens per
                    # turn for no real fidelity gain on typical
                    # follow-up questions. If a future need surfaces for
                    # pixel-level review, that warrants its own spec
                    # rather than always-on re-attach.
                    recent_messages[-1]["content"] = (
                        f"I have attached a file. Relevant context:\n{rag_context}\n\n"
                        f"My message: {clean_user_text}\n\n"
                        f"{MICRO_PROMPTS['rag_file_upload_instruction']}"
                    )
                    yield format_file_analyzed(sources_list)
                    # Surface image-typed sources to the frontend so it
                    # can render an inline preview below the assistant
                    # turn. Non-image sources (PDF/text) are filtered out
                    # by _image_document_refs because we don't persist
                    # their bytes for re-rendering.
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

            # Stream from llama-server. reasoning_content and content
            # deltas forward to the caller in real time; tool_calls
            # deltas accumulate by index for end-of-stream detection.
            # See docs/internal/2026-05-20-llama-server-sse-shape.md
            # for the wire format we're consuming.
            acc_content = ""
            acc_reasoning = ""
            acc_tool_calls: dict[int, dict] = {}
            reasoning_started_at: float | None = None
            reasoning_done_emitted = False

            async for delta in llm_server.chat_stream(
                client,
                messages=full_messages,
                tools=tools_payload,
                model=routed_model,
            ):
                if is_disconnected and await is_disconnected():
                    return

                rc = delta.get("reasoning_content")
                if rc:
                    # Accumulate regardless of surface_reasoning so the
                    # message reconstruction below carries it (the
                    # router downstream may want it for logging). Only
                    # forward to the client when the model is tagged.
                    acc_reasoning += rc
                    if surface_reasoning:
                        if reasoning_started_at is None:
                            reasoning_started_at = time.perf_counter()
                        yield {"type": "reasoning_chunk", "chunk": rc}

                ct = delta.get("content")
                if ct:
                    # First content token closes the reasoning phase.
                    if reasoning_started_at is not None and not reasoning_done_emitted:
                        yield {
                            "type": "reasoning_done",
                            "duration_s": round(
                                time.perf_counter() - reasoning_started_at, 1,
                            ),
                        }
                        reasoning_done_emitted = True
                    acc_content += ct
                    yield ct

                # Tool-call deltas: llama-server streams the function name
                # and opening `{` on the first delta of a slot, then
                # arguments token-by-token across subsequent deltas. Key
                # by `index` and concatenate the arguments string.
                for tc_delta in (delta.get("tool_calls") or []):
                    idx = tc_delta.get("index", 0)
                    slot = acc_tool_calls.setdefault(idx, {
                        "id": None,
                        "type": "function",
                        "function": {"name": "", "arguments": ""},
                    })
                    if tc_delta.get("id"):
                        slot["id"] = tc_delta["id"]
                    fn = tc_delta.get("function") or {}
                    if fn.get("name"):
                        slot["function"]["name"] = fn["name"]
                    if fn.get("arguments"):
                        slot["function"]["arguments"] += fn["arguments"]

            # finish_reason=length can end the stream mid-think before any
            # content arrives — close the reasoning channel so the UI gets
            # a duration even in that case.
            if reasoning_started_at is not None and not reasoning_done_emitted:
                yield {
                    "type": "reasoning_done",
                    "duration_s": round(
                        time.perf_counter() - reasoning_started_at, 1,
                    ),
                }

            # Reconstruct the message dict the rest of the loop body
            # expects (tool-call branch, stall-detection, fallback).
            message = {
                "role": "assistant",
                "content": acc_content,
                "reasoning_content": acc_reasoning,
            }
            tool_calls_list = [acc_tool_calls[i] for i in sorted(acc_tool_calls)]
            if tool_calls_list:
                message["tool_calls"] = tool_calls_list

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
                    yield {"type": "tool_call", "name": func_name, "args": display_args}

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

                    yield {"type": "tool_result", "name": func_name, "result": result}

                    # Emit specialized audit event per tool — search_knowledge_base
                    # → chat.rag_retrieved, web_search → chat.web_search, everything
                    # else → chat.tool_invoked. No double-emit.
                    is_error_result = isinstance(result, str) and (
                        result.startswith("Tool execution failed:")
                        or "timed out after" in result
                    )
                    succeeded = not is_error_result
                    audit_args = {
                        k: v for k, v in raw_args.items()
                        if k not in ("workspace_id", "session_id")
                    }
                    if func_name == "search_knowledge_base":
                        source_filenames = []
                        if isinstance(result, str):
                            source_filenames = list(set(
                                re.findall(r'\[from ([^\]]+)\]', result)
                            ))
                        _audit_chat_event(
                            user_id, workspace_id, session_id,
                            EventType.CHAT_RAG_RETRIEVED,
                            {
                                "query_preview": str(audit_args.get("query", ""))[:200],
                                "num_results": len(source_filenames),
                                "source_filenames": source_filenames,
                                "mode": "tool",
                            },
                        )
                    elif func_name == "web_search":
                        from tools.web import get_last_stats as _web_stats
                        stats = _web_stats()
                        _audit_chat_event(
                            user_id, workspace_id, session_id,
                            EventType.CHAT_WEB_SEARCH,
                            {
                                "query_preview": str(audit_args.get("query", ""))[:200],
                                "k_requested": stats.get("k_requested", 0),
                                "k_returned_by_searxng": stats.get("k_returned_by_searxng", 0),
                                "k_fetched_ok": stats.get("k_fetched_ok", 0),
                                "k_failed": stats.get("k_failed", 0),
                                "failure_reasons": stats.get("failure_reasons", {}),
                                "fetch_wall_clock_ms": stats.get("fetch_wall_clock_ms", 0),
                                "extracted_bytes_total": stats.get("extracted_bytes_total", 0),
                                "synthesis_model_id": routed_model,
                            },
                        )
                    else:
                        tool_payload = {
                            "tool_name": func_name,
                            "arg_values": audit_args,
                            "succeeded": succeeded,
                        }
                        if not succeeded and isinstance(result, str):
                            tool_payload["error_message"] = result[:200]
                        _audit_chat_event(
                            user_id, workspace_id, session_id,
                            EventType.CHAT_TOOL_INVOKED,
                            tool_payload,
                        )

                    # When search_knowledge_base returns chunks from image
                    # documents, surface them as files_referenced so the
                    # inline preview renders. Mirrors the auto-RAG path's
                    # emission. Filenames are parsed from the result's
                    # `[from <filename>]` markers that _label_chunk emits.
                    if func_name == "search_knowledge_base" and isinstance(result, str):
                        from_filenames = re.findall(r'\[from ([^\]]+)\]', result)
                        if from_filenames:
                            tool_db = database.SessionLocal()
                            try:
                                refs = _image_document_refs(
                                    tool_db, list(set(from_filenames)),
                                    workspace_id, session_id,
                                )
                            finally:
                                tool_db.close()
                            if refs:
                                yield {"type": "files_referenced", "files": refs}

                    full_messages.append({
                        "role": "tool",
                        "content": str(result),
                        "name": func_name,
                        "tool_call_id": tool_call["id"],
                    })
                continue

            else:
                # Stall + empty-content fallbacks. In streaming mode the
                # content already reached the client during the chat_stream
                # loop above; if the accumulated content is a known stall
                # phrase or genuinely empty, append a fallback so the user
                # sees something useful. The stall outputs are very short
                # (`thought.`, `thoughts:`), so the appended fallback reads
                # naturally as a continuation.
                stripped = acc_content.strip().lower()
                is_thought_stall = (
                    stripped in {"thought", "thoughts", "thought.", "thought:"}
                    or "i must wait for the search results" in stripped
                )

                fallback_text = ""
                if is_thought_stall:
                    fallback_text = MICRO_PROMPTS["fallback_thought_loop"]
                elif not acc_content.strip():
                    if loop_count > 1:
                        # Only claim failure if a tool actually errored.
                        # If tools succeeded and the model just had nothing
                        # to add (e.g., after a `rename_chat_session` that
                        # returned "Success! ..."), say nothing — the tool
                        # result block already shows what happened.
                        if had_tool_error:
                            fallback_text = MICRO_PROMPTS["fallback_tool_failure"]
                    else:
                        fallback_text = MICRO_PROMPTS["fallback_generic"]

                if fallback_text:
                    prefix = "\n\n" if acc_content.strip() else ""
                    words = (prefix + fallback_text).split(" ")
                    for i, word in enumerate(words):
                        if is_disconnected and await is_disconnected():
                            return
                        yield word + (" " if i < len(words) - 1 else "")
                        await asyncio.sleep(0.01)
                    # Reflect what was actually sent to the client so
                    # downstream persistence (routers/chat.py's
                    # full_response accumulator) matches the user's view.
                    acc_content = acc_content + prefix + fallback_text

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
                modes=modes,
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
