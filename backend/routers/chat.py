import asyncio
import json
import logging
from typing import Optional, List

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import tuple_, func as sqlfunc
from sqlalchemy.orm import Session

from core import ai_engine, cookie_auth
from core.audit import EventType, log_event
from core.deps import get_http_client
from core.engine_config import engine_config_for
from core.llm_metrics import get_last_chat_snapshot as _last_chat_metric_snapshot
from core.workspace_access import verify_workspace_owns, workspace_query_dep
from db import database, models
from schemas import (InferenceRequest, SessionResponse, SessionUpdate,
                     MessageHistory, BranchRequest, MessageUpdate)
from services import condense, ingest_broker
from tools.registry import build_tool_set

_log = logging.getLogger(__name__)


def _attachment_filenames(db: Session, attachment_ids: list[str], workspace_id: str) -> list[str]:
    """Best-effort filename lookup for the audit payload. Cross-workspace
    ids silently drop out — the analyze endpoint already filters those."""
    if not attachment_ids:
        return []
    rows = db.query(models.Document.filename).filter(
        models.Document.id.in_(attachment_ids),
        models.Document.workspace_id == workspace_id,
    ).all()
    return [r[0] for r in rows]


def _accumulate_tool_event(acc: list, event: dict) -> None:
    """Append/update tool-call accumulator from a streamed event.

    Pairs by ORDER (not by name): a tool_result always completes the most-
    recent entry whose result is still None. A tool_result with no open
    entry is logged and dropped (defensive guard against engine bugs)."""
    etype = event.get("type")
    if etype == "tool_call":
        acc.append({
            "name": event.get("name", ""),
            "args": event.get("args") or {},
            "result": None,
        })
    elif etype == "tool_result":
        for i in range(len(acc) - 1, -1, -1):
            if acc[i]["result"] is None:
                acc[i]["result"] = event.get("result", "")
                return
        _log.warning("tool_result %r arrived with no open tool_call; dropping", event.get("name"))


def _finalize_tool_calls(acc: list) -> list:
    """Drop entries with no result (left unpaired by a mid-stream disconnect).

    Returned list is safe to persist as the assistant row's tool_calls JSONB."""
    return [tc for tc in acc if tc.get("result") is not None]


def build_safe_messages(history) -> list[dict]:
    """Convert DB Message rows into the structured shape ai_engine consumes.

    Legacy rows (tool_calls NULL) emit one flat {role, content}. New rows
    with structured tool_calls emit one {role: "assistant", content,
    tool_calls: [...]} followed by one {role: "tool", name, content: result}
    per call, in order. Malformed tool_calls (non-list) is treated as legacy.

    OpenAI-spec compliance matters: llama-swap strictly requires
    tool_calls[].id, tool_calls[].type=="function", arguments as a JSON
    string, and {role:"tool"}.tool_call_id matching back. We synthesise
    deterministic ids from the row id + index since we don't round-trip
    the LLM's original call ids through the JSONB column."""
    out: list[dict] = []
    for msg in history:
        tcs = getattr(msg, "tool_calls", None)
        if msg.role == "assistant" and isinstance(tcs, list) and tcs:
            call_ids = [f"call_{i}_{msg.id}" for i in range(len(tcs))]
            out.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": call_ids[i],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc.get("args") or {}),
                        },
                    }
                    for i, tc in enumerate(tcs)
                ],
            })
            for i, tc in enumerate(tcs):
                out.append({
                    "role": "tool",
                    "tool_call_id": call_ids[i],
                    "name": tc["name"],
                    "content": tc.get("result") or "",
                })
        else:
            out.append({"role": msg.role, "content": msg.content})
    return out


def _error_envelope(exc: Exception) -> dict:
    """Map an exception to a {error, code} envelope for the SSE stream.

    Codes:
      llm_unreachable — connection refused, DNS fail, etc.
      llm_timeout     — read timeout (model hung)
      tool_timeout    — a tool exceeded TOOL_TIMEOUT_SECONDS
      engine_error    — anything else (generic catch-all)
    """
    if isinstance(exc, httpx.ConnectError):
        return {"error": "LLM server is not reachable.", "code": "llm_unreachable"}
    if isinstance(exc, (httpx.ReadTimeout, httpx.PoolTimeout)):
        return {"error": "LLM server took too long to respond.", "code": "llm_timeout"}
    if isinstance(exc, asyncio.TimeoutError):
        return {"error": "Tool execution timed out.", "code": "tool_timeout"}
    return {"error": str(exc) or "Engine error.", "code": "engine_error"}


router = APIRouter(tags=["AI Chat"])


# Bound on how long /analyze will wait for in-flight attachments to
# finish ingestion. Larger than typical captioning (~10-15s) so we
# don't bail prematurely; smaller than a runaway "stuck task" so we
# can degrade gracefully to "no RAG context for that doc" instead.
_ATTACHMENT_WAIT_TIMEOUT_SECONDS = 60.0


async def _wait_for_processing_attachments(
    attachment_ids: list[str],
    workspace_id: str,
    db: Session,
) -> None:
    """Wait for any 'processing' attachments to reach terminal state.

    Subscribes to the ingest broker for each in-flight doc and awaits
    the first terminal event (or the global timeout). Already-terminal
    docs are skipped. Reads status fresh from DB after subscribing —
    if it flipped between the check and subscribe, we won't block.
    """
    if not attachment_ids:
        return
    docs = (
        db.query(models.Document)
        .filter(
            models.Document.id.in_(attachment_ids),
            models.Document.workspace_id == workspace_id,
        )
        .all()
    )
    processing_ids = [d.id for d in docs if d.status == "processing"]
    if not processing_ids:
        return

    broker = ingest_broker.broker()
    queues: dict[str, asyncio.Queue] = {
        doc_id: broker.subscribe(doc_id) for doc_id in processing_ids
    }
    deadline = asyncio.get_event_loop().time() + _ATTACHMENT_WAIT_TIMEOUT_SECONDS
    try:
        for doc_id, queue in queues.items():
            # Re-check status — task may have finished between subscribe
            # call above and now. Avoids waiting on an already-terminal
            # row that never publishes again.
            db.expire_all()
            doc = db.query(models.Document).filter(models.Document.id == doc_id).first()
            if doc is None or doc.status in ("ready", "error"):
                continue
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                break
            try:
                await asyncio.wait_for(queue.get(), timeout=remaining)
            except asyncio.TimeoutError:
                # Bail out of the wait; the auto-RAG path will still run,
                # just without context from the still-processing doc.
                break
    finally:
        for doc_id, queue in queues.items():
            broker.unsubscribe(doc_id, queue)


def _message_in_workspace_or_404(
    message_id: str,
    workspace_id: str,
    db: Session,
) -> models.Message:
    """Return the message if it belongs to a session in workspace_id, else 404.

    Message has no direct workspace_id — it's scoped via Session.workspace_id.
    Returns 404 (not 403) on cross-workspace access to avoid info leakage,
    matching the convention in core.workspace_access.
    """
    msg = (
        db.query(models.Message)
        .join(models.Session, models.Message.session_id == models.Session.id)
        .filter(
            models.Message.id == message_id,
            models.Session.workspace_id == workspace_id,
        )
        .first()
    )
    if msg is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return msg


@router.get("/sessions", response_model=List[SessionResponse])
def get_sessions(
    workspace: models.Workspace = Depends(workspace_query_dep),
    folder_id: Optional[str] = None,
    limit: Optional[int] = None,
    offset: int = 0,
    db: Session = Depends(database.get_db),
):
    """List sessions for a workspace, newest first.

    folder_id (optional) — restrict to a single folder. Omit to return all
    sessions in the workspace; "unsorted" sessions (folder_id NULL) are
    currently filtered client-side, since query params can't cleanly express
    'null match'.

    limit/offset (optional) — pagination. With no params the response is
    unbounded to preserve the existing frontend's 'load all' behaviour.
    """
    q = db.query(models.Session).filter(models.Session.workspace_id == workspace.id)
    if folder_id is not None:
        q = q.filter(models.Session.folder_id == folder_id)
    q = q.order_by(models.Session.created_at.desc())
    if offset:
        q = q.offset(offset)
    if limit is not None:
        q = q.limit(limit)
    return q.all()

@router.get("/sessions/{session_id}", response_model=List[MessageHistory])
def get_session_history(
    session_id: str,
    limit: Optional[int] = None,
    offset: int = 0,
    workspace: models.Workspace = Depends(workspace_query_dep),
    db: Session = Depends(database.get_db),
):
    """Return user/assistant messages in chronological order.

    Scoped to workspace — cross-workspace 404s. limit/offset (optional)
    paginate; defaults preserve the existing 'load everything' behaviour.
    """
    verify_workspace_owns(session_id, models.Session, workspace.id, db)

    q = db.query(models.Message).filter(
        models.Message.session_id == session_id,
        models.Message.role.in_(["user", "assistant"]),
    ).order_by(models.Message.created_at)
    if offset:
        q = q.offset(offset)
    if limit is not None:
        q = q.limit(limit)
    messages = q.all()

    return [
        MessageHistory(
            id=m.id,
            role=m.role,
            content=m.content,
            status=m.status,
            timestamp=m.created_at.isoformat() if m.created_at else None,
            referenced_files=m.referenced_docs or None,
            tool_calls=m.tool_calls or None,
            reasoning_content=m.reasoning_content or None,
            reasoning_duration_s=m.reasoning_duration_s,
        )
        for m in messages
    ]

@router.patch("/sessions/{session_id}")
def update_session(
    session_id: str,
    payload: SessionUpdate,
    workspace: models.Workspace = Depends(workspace_query_dep),
    db: Session = Depends(database.get_db),
):
    """Update session metadata (title, folder_id, ...). Scoped to workspace
    — cross-workspace 404s."""
    db_session = verify_workspace_owns(session_id, models.Session, workspace.id, db)
    update_data = payload.model_dump(exclude_unset=True)
    # Cross-workspace folder_id rejected at the boundary.
    if "folder_id" in update_data and update_data["folder_id"] is not None:
        verify_workspace_owns(update_data["folder_id"], models.Folder, workspace.id, db)
    for key, value in update_data.items():
        setattr(db_session, key, value)
    db.commit()
    return {"status": "success"}

@router.delete("/sessions/{session_id}")
def delete_session(
    session_id: str,
    request: Request,
    workspace: models.Workspace = Depends(workspace_query_dep),
    db: Session = Depends(database.get_db),
    user: models.User = Depends(cookie_auth.current_user),
):
    """Delete a session and its messages. Scoped to workspace —
    cross-workspace 404s."""
    session = verify_workspace_owns(session_id, models.Session, workspace.id, db)
    deleted_title = session.title

    db.delete(session)

    log_event(
        db,
        EventType.CHAT_SESSION_DELETED,
        user=user,
        workspace=workspace,
        resource_type="session",
        resource_id=session_id,
        payload={"title": deleted_title},
        request=request,
    )
    db.commit()
    return {"status": "deleted"}

@router.post("/analyze")
async def analyze_data(
    http_request: Request,
    request: InferenceRequest,
    background_tasks: BackgroundTasks,
    workspace: models.Workspace = Depends(workspace_query_dep),
    http_client: httpx.AsyncClient = Depends(get_http_client),
    user: models.User = Depends(cookie_auth.current_user),
):
    # Resolve engine config and tool set once at the boundary.
    engine_config = engine_config_for(workspace)
    tool_set = build_tool_set(workspace)

    # We manage the upfront DB session manually instead of using
    # Depends(get_db) so the connection is returned to the pool BEFORE the
    # long-lived streaming response begins. With Depends, the dependency's
    # cleanup runs after the StreamingResponse finishes, which can hold the
    # connection for the full generation lifetime and exhaust the pool when
    # multiple sessions stream concurrently.
    db = database.SessionLocal()
    try:
        chat_session = None

        if request.session_id:
            chat_session = (
                db.query(models.Session)
                .filter(
                    models.Session.id == request.session_id,
                    models.Session.workspace_id == workspace.id,
                )
                .first()
            )
            if chat_session is None:
                raise HTTPException(status_code=404, detail="Session not found.")

        if not chat_session:
            generated_title = await ai_engine.generate_title(http_client, request.prompt, engine_config=engine_config)
            chat_session = models.Session(
                title=generated_title,
                workspace_id=workspace.id,
                user_id=user.id,
            )
            db.add(chat_session)
            db.commit()
            db.refresh(chat_session)
            log_event(
                db,
                EventType.CHAT_SESSION_CREATED,
                user=user,
                workspace=workspace,
                session=chat_session,
                resource_type="session",
                resource_id=chat_session.id,
                payload={
                    "title": chat_session.title,
                    "source": "analyze",
                },
                request=http_request,
            )
            db.commit()
        elif chat_session.title in ["Document Upload Session", "New Diagnostic Session", "New Diagnostic Chat"]:
            chat_session.title = await ai_engine.generate_title(http_client, request.prompt, engine_config=engine_config)
            db.commit()
            db.refresh(chat_session)

        if request.attachments:
            # Scope the claim to documents the caller already owns. Without this
            # filter, a client could attach foreign-workspace document ids and the
            # update would re-parent them into the caller's workspace — silent
            # cross-workspace data theft.
            db.query(models.Document).filter(
                models.Document.id.in_(request.attachments),
                models.Document.workspace_id == workspace.id,
            ).update(
                {"session_id": chat_session.id},
                synchronize_session=False,
            )
            db.commit()

            # Frontend may have submitted before all attached docs finished
            # processing. Wait for terminal status on each via the broker
            # so auto-RAG sees the captions when we hit knowledge.retrieve_*.
            # Bounded so a stuck ingestion doesn't deadlock the chat call.
            await _wait_for_processing_attachments(
                request.attachments, workspace.id, db,
            )

        user_message_id: Optional[str] = None
        if not request.skip_db_save:
            user_msg = models.Message(session_id=chat_session.id, role="user", content=request.prompt)
            db.add(user_msg)
            db.commit()
            db.refresh(user_msg)
            user_message_id = user_msg.id

            log_event(
                db,
                EventType.CHAT_MESSAGE_SENT,
                user=user,
                workspace=workspace,
                session=chat_session,
                resource_type="message",
                resource_id=user_msg.id,
                payload={
                    "content_preview": request.prompt[:200],
                    "token_count": len(request.prompt) // 4,
                    "has_attachments": bool(request.attachments),
                    "attachment_filenames": _attachment_filenames(
                        db, request.attachments or [], workspace.id
                    ),
                },
                request=http_request,
            )
            db.commit()

        history = db.query(models.Message).filter(models.Message.session_id == chat_session.id).order_by(models.Message.created_at).all()
        safe_messages = build_safe_messages(history)

        # Capture identifiers needed inside the generator so we don't reach into
        # `chat_session` after the local `db` is closed below.
        session_id = chat_session.id
        workspace_id = workspace.id
        user_id = user.id
    finally:
        db.close()

    async def generate():
        from core.llm_metrics import set_request_context
        set_request_context(workspace_id=workspace_id, session_id=session_id)

        # `user_message_id` is sent here so the client can swap its optimistic
        # temp-u id for the real DB UUID at the moment of stream start — no
        # post-stream /sessions/{id} refetch needed (and therefore no race
        # against the next send).
        yield json.dumps({
            "status": "started",
            "session_id": session_id,
            "user_message_id": user_message_id,
        }) + "\n"

        full_response = ""
        full_reasoning = ""
        reasoning_duration_s: Optional[float] = None
        completed = False
        disconnected = False
        assistant_message_id: Optional[str] = None
        tool_calls_acc: list[dict] = []
        referenced_docs: list[dict] | None = None
        # Routing metadata captured from the upfront `route` typed event
        # ai_engine emits right after the router picks. Surfaced into the
        # audit payload so post-hoc prompt-tuning has full context — which
        # model handled the turn, why that tier was picked, how many
        # tools fired, did reasoning_mode kick in.
        route_model: str | None = None
        route_tier: str | None = None

        try:
            async for chunk in ai_engine.stream_chat(
                http_client,
                safe_messages,
                workspace_id=workspace_id,
                engine_config=engine_config,
                tool_set=tool_set,
                session_id=session_id,
                is_disconnected=http_request.is_disconnected,
                modes=request.modes,
                user_id=user_id,
            ):
                if await http_request.is_disconnected():
                    disconnected = True
                    break
                if isinstance(chunk, dict):
                    ctype = chunk.get("type")
                    if ctype in ("tool_call", "tool_result"):
                        _accumulate_tool_event(tool_calls_acc, chunk)
                    elif ctype == "files_referenced":
                        # Accumulate image-document refs from auto-RAG and
                        # search_knowledge_base into the assistant row so
                        # inline previews survive page reload. Dedupe by id.
                        files = chunk.get("files") or []
                        merged = list(referenced_docs or [])
                        seen = {f["id"] for f in merged}
                        for f in files:
                            if f.get("id") and f["id"] not in seen:
                                merged.append(f)
                                seen.add(f["id"])
                        referenced_docs = merged or None
                    elif ctype == "reasoning_chunk":
                        full_reasoning += chunk.get("chunk") or ""
                    elif ctype == "reasoning_done":
                        d = chunk.get("duration_s")
                        if isinstance(d, (int, float)):
                            reasoning_duration_s = float(d)
                    elif ctype == "route":
                        route_model = chunk.get("model")
                        route_tier = chunk.get("tier")
                    yield json.dumps(chunk) + "\n"
                    continue
                full_response += chunk
                yield json.dumps({"chunk": chunk}) + "\n"

            if not disconnected:
                # Persist the assistant message inline so the terminating
                # `done` event can carry its real DB id; clients use that
                # id to swap their optimistic placeholder without refetching.
                if full_response.strip():
                    save_db = database.SessionLocal()
                    try:
                        ai_msg = models.Message(
                            session_id=session_id,
                            role="assistant",
                            content=full_response,
                            status="complete",
                            tool_calls=_finalize_tool_calls(tool_calls_acc) or None,
                            referenced_docs=referenced_docs,
                            reasoning_content=full_reasoning.strip() or None,
                            reasoning_duration_s=reasoning_duration_s,
                        )
                        save_db.add(ai_msg)
                        save_db.commit()
                        save_db.refresh(ai_msg)
                        assistant_message_id = ai_msg.id

                        usage_for_audit = _last_chat_metric_snapshot() or {}
                        prompt_tokens = int(usage_for_audit.get("prompt_tokens") or 0)
                        completion_tokens = int(usage_for_audit.get("completion_tokens") or 0)
                        tool_names = sorted({tc.get("name") for tc in tool_calls_acc if tc.get("name")})
                        log_event(
                            save_db,
                            EventType.CHAT_MESSAGE_RECEIVED,
                            user=save_db.query(models.User).filter_by(id=user.id).first(),
                            workspace=save_db.query(models.Workspace).filter_by(id=workspace_id).first(),
                            session=save_db.query(models.Session).filter_by(id=session_id).first(),
                            resource_type="message",
                            resource_id=ai_msg.id,
                            payload={
                                "content_preview": full_response[:200],
                                # Which model + tier the router picked. Captured
                                # from the upfront `route` SSE event so it's
                                # accurate even when the metric snapshot's
                                # `model` field is empty (e.g. tool-only turns).
                                "model": route_model or usage_for_audit.get("model") or "",
                                "tier": route_tier or "",
                                # Tools that actually fired this turn.
                                "tools_used": tool_names,
                                "tools_count": len(tool_calls_acc),
                                # Reasoning visibility: surfaces whether the
                                # model spent time thinking and how long.
                                "reasoning": reasoning_duration_s is not None,
                                "reasoning_duration_s": reasoning_duration_s,
                                # Token + timing breakdown.
                                "prompt_tokens": prompt_tokens,
                                "completion_tokens": completion_tokens,
                                "token_count": prompt_tokens + completion_tokens,
                                "duration_ms": int(usage_for_audit.get("duration_ms") or 0),
                                "ttft_ms": int(usage_for_audit.get("ttft_ms") or 0),
                                "tokens_per_sec": float(usage_for_audit.get("tokens_per_sec") or 0.0),
                                "finished_cleanly": True,
                            },
                        )
                        save_db.commit()
                    except Exception as e:
                        save_db.rollback()
                        _log.exception("Failed to save assistant message: %s", e)
                    finally:
                        save_db.close()

                # The terminating chunk now carries an aggregate `usage` block so
                # bench_llm.py can read it directly without scraping logs. Token counts
                # come from the LAST chat call's snapshot (the call that produced the
                # user-visible answer). Earlier tool-loop iterations are intentionally
                # not summed — bench_llm asks "how fast was the FINAL answer", not
                # "how many tokens did the agentic loop burn in total."
                usage = _last_chat_metric_snapshot()
                yield json.dumps({
                    "done": True,
                    "usage": usage,
                    "assistant_message_id": assistant_message_id,
                }) + "\n"
                completed = True

        except asyncio.CancelledError:
            # Client disconnected. Re-raise so the framework cleans up cleanly.
            raise
        except Exception as e:
            yield json.dumps(_error_envelope(e)) + "\n"
            # Don't re-raise; the response ends here gracefully.
            return

        finally:
            # Save aborted/failed responses here. The clean-completion path
            # already saved before yielding `done`; this branch only fires
            # when the stream ended without `completed=True`.
            if not completed:
                if disconnected:
                    status = "aborted"
                    full_response += "\n\n*[Response aborted by user.]*"
                else:
                    status = "failed"

                if full_response.strip():
                    background_db = database.SessionLocal()
                    try:
                        ai_msg = models.Message(
                            session_id=session_id,
                            role="assistant",
                            content=full_response,
                            status=status,
                            reasoning_content=full_reasoning.strip() or None,
                            reasoning_duration_s=reasoning_duration_s,
                        )
                        background_db.add(ai_msg)
                        background_db.commit()
                        background_db.refresh(ai_msg)

                        log_event(
                            background_db,
                            EventType.CHAT_MESSAGE_RECEIVED,
                            user=background_db.query(models.User).filter_by(id=user.id).first(),
                            workspace=background_db.query(models.Workspace).filter_by(id=workspace_id).first(),
                            session=background_db.query(models.Session).filter_by(id=session_id).first(),
                            resource_type="message",
                            resource_id=ai_msg.id,
                            payload={
                                "content_preview": full_response[:200],
                                "model": route_model or "",
                                "tier": route_tier or "",
                                "tools_used": sorted({tc.get("name") for tc in tool_calls_acc if tc.get("name")}),
                                "tools_count": len(tool_calls_acc),
                                "reasoning": reasoning_duration_s is not None,
                                "reasoning_duration_s": reasoning_duration_s,
                                "finished_cleanly": False,
                                "status": status,
                            },
                        )
                        background_db.commit()
                    except Exception as e:
                        background_db.rollback()
                        _log.exception("Failed to save assistant message: %s", e)
                    finally:
                        background_db.close()

    # Schedule condensation to run after the response is fully sent.
    # The advisory lock in condense_for_session ensures only one condenser
    # runs per session at a time — concurrent requests skip silently.
    background_tasks.add_task(
        condense.condense_for_session,
        http_client,
        session_id,
        engine_config,
    )

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        background=background_tasks,
    )

@router.patch("/messages/{message_id}")
def update_message(
    message_id: str,
    payload: MessageUpdate,
    workspace: models.Workspace = Depends(workspace_query_dep),
    db: Session = Depends(database.get_db),
):
    """Edit the content of a message. Scoped to workspace — cross-workspace
    attempts return 404 (not 403) for info-leak protection."""
    msg = _message_in_workspace_or_404(message_id, workspace.id, db)
    msg.content = payload.content
    db.commit()
    return {"status": "success"}

@router.delete("/messages/{message_id}")
def delete_message(
    message_id: str,
    workspace: models.Workspace = Depends(workspace_query_dep),
    db: Session = Depends(database.get_db),
):
    msg = _message_in_workspace_or_404(message_id, workspace.id, db)
    session_id_resp = msg.session_id
    db.delete(msg)
    db.commit()
    return {"status": "success", "session_id": session_id_resp}

@router.post("/sessions/{session_id}/branch")
def branch_session(
    session_id: str,
    body: BranchRequest,
    request: Request,
    workspace: models.Workspace = Depends(workspace_query_dep),
    db: Session = Depends(database.get_db),
    user: models.User = Depends(cookie_auth.current_user),
):
    """Copy a session up to (and including) up_to_message_id into a new
    session. Source session is scoped to workspace — cross-workspace 404s."""
    old_session = verify_workspace_owns(session_id, models.Session, workspace.id, db)

    target = db.query(models.Message).filter(
        models.Message.id == body.up_to_message_id,
        models.Message.session_id == session_id,
    ).first()
    if not target:
        raise HTTPException(status_code=404, detail="up_to_message_id does not belong to this session")

    # Avoid stacking "(Branch) (Branch) (Branch) ..." when re-branching a branch.
    branched_title = old_session.title if old_session.title.endswith("(Branch)") else f"{old_session.title} (Branch)"
    new_session = models.Session(title=branched_title, workspace_id=old_session.workspace_id, user_id=user.id)
    db.add(new_session)
    db.commit()
    db.refresh(new_session)

    # Pull only user/assistant rows in chronological order. Memory rows are
    # skipped because their JSON payload references message IDs that won't
    # exist in the new branch and would corrupt the condenser state.
    messages = db.query(models.Message).filter(
        models.Message.session_id == session_id,
        models.Message.role.in_(["user", "assistant"]),
    ).order_by(models.Message.created_at, models.Message.id).all()

    for m in messages:
        # clock_timestamp() returns real wall-clock time per row, so each
        # copy gets a distinct created_at. The default `now()` would have
        # given every row in this transaction the same timestamp, breaking
        # any later truncate that orders by created_at.
        new_msg = models.Message(
            session_id=new_session.id,
            role=m.role,
            content=m.content,
            status=m.status,
            created_at=sqlfunc.clock_timestamp(),
        )
        db.add(new_msg)
        if m.id == body.up_to_message_id:
            break

    log_event(
        db,
        EventType.CHAT_SESSION_CREATED,
        user=user,
        workspace=workspace,
        session=new_session,
        resource_type="session",
        resource_id=new_session.id,
        payload={
            "title": new_session.title,
            "source": "branch",
            "branched_from_session_id": session_id,
            "branched_from_message_id": body.up_to_message_id,
        },
        request=request,
    )
    db.commit()
    return {"new_session_id": new_session.id}

@router.delete("/sessions/{session_id}/truncate/{message_id}")
def truncate_session(
    session_id: str,
    message_id: str,
    workspace: models.Workspace = Depends(workspace_query_dep),
    db: Session = Depends(database.get_db),
):
    """Delete all messages in a session that occurred AFTER the specified message_id.

    Uses (created_at, id) as a tuple ordering so two messages sharing a
    created_at (which can happen when multiple rows commit in the same
    transaction — see branch_session) still produce a deterministic split.

    Scoped to workspace — cross-workspace 404s.
    """
    # Look up the session AND target message in one go, both scoped by workspace.
    target_msg = (
        db.query(models.Message)
        .join(models.Session, models.Message.session_id == models.Session.id)
        .filter(
            models.Message.id == message_id,
            models.Message.session_id == session_id,
            models.Session.workspace_id == workspace.id,
        )
        .first()
    )
    if not target_msg:
        raise HTTPException(status_code=404, detail="Target message not found")

    deleted_count = db.query(models.Message).filter(
        models.Message.session_id == session_id,
        tuple_(models.Message.created_at, models.Message.id) >
            (target_msg.created_at, target_msg.id),
    ).delete(synchronize_session=False)

    # If the memory row references a now-deleted message_id, the condenser
    # would silently restart from index 0 next time and re-summarize content
    # already baked into the summary. Easier and safer to just drop the
    # memory row whenever the session is truncated — the next condense pass
    # rebuilds from whatever survives.
    db.query(models.Message).filter(
        models.Message.session_id == session_id,
        models.Message.role == "memory",
    ).delete(synchronize_session=False)

    db.commit()
    return {"status": "success", "deleted_count": deleted_count}
