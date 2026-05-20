"""Service helpers for the /analyze chat pipeline.

Extracted from `routers/chat.py` to keep the router thin and to collapse
two near-identical assistant-persist branches into one function.
"""

import asyncio
import logging
from typing import Any, Optional

import httpx
from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from core import ai_engine
from core.audit import EventType, log_event
from db import database, models
from services import ingest_broker

_log = logging.getLogger(__name__)


# Bound on how long we'll wait for in-flight attachments to finish
# ingestion. Larger than typical captioning (~10-15s) so we don't bail
# prematurely; smaller than a runaway "stuck task" so we can degrade
# gracefully to "no RAG context for that doc" instead.
_ATTACHMENT_WAIT_TIMEOUT_SECONDS = 60.0


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


async def resolve_or_create_session(
    db: Session,
    user: models.User,
    workspace: models.Workspace,
    prompt: str,
    session_id: Optional[str],
    http_client: httpx.AsyncClient,
    engine_config,
    request: Request,
) -> models.Session:
    """Return the existing session (if `session_id` supplied) or create a new
    one with a generated title. Also regenerates the title on the legacy
    placeholder titles. Emits CHAT_SESSION_CREATED on new sessions."""
    chat_session: Optional[models.Session] = None

    if session_id:
        chat_session = (
            db.query(models.Session)
            .filter(
                models.Session.id == session_id,
                models.Session.workspace_id == workspace.id,
            )
            .first()
        )
        if chat_session is None:
            raise HTTPException(status_code=404, detail="Session not found.")

    if not chat_session:
        generated_title = await ai_engine.generate_title(http_client, prompt, engine_config=engine_config)
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
            request=request,
        )
        db.commit()
    elif chat_session.title in ["Document Upload Session", "New Diagnostic Session", "New Diagnostic Chat"]:
        chat_session.title = await ai_engine.generate_title(http_client, prompt, engine_config=engine_config)
        db.commit()
        db.refresh(chat_session)

    return chat_session


async def claim_attachments(
    db: Session,
    workspace_id: str,
    session: models.Session,
    attachment_ids: Optional[list[str]],
) -> None:
    """Re-parent caller-owned attachments to this session and wait for any
    still-processing ones to reach terminal state so auto-RAG can read them.

    Cross-workspace ids are silently dropped — without the workspace filter
    a client could attach foreign-workspace document ids and the update
    would re-parent them, enabling silent cross-workspace data theft."""
    if not attachment_ids:
        return

    db.query(models.Document).filter(
        models.Document.id.in_(attachment_ids),
        models.Document.workspace_id == workspace_id,
    ).update(
        {"session_id": session.id},
        synchronize_session=False,
    )
    db.commit()

    await _wait_for_processing_attachments(attachment_ids, workspace_id, db)


def persist_user_message(
    db: Session,
    session: models.Session,
    prompt: str,
    user: models.User,
    workspace: models.Workspace,
    attachments: Optional[list[str]],
    request: Request,
) -> str:
    """Create the user Message row and emit CHAT_MESSAGE_SENT. Returns the
    new message id. Caller decides whether to invoke this — skip_db_save
    short-circuits at the call site."""
    user_msg = models.Message(session_id=session.id, role="user", content=prompt)
    db.add(user_msg)
    db.commit()
    db.refresh(user_msg)

    log_event(
        db,
        EventType.CHAT_MESSAGE_SENT,
        user=user,
        workspace=workspace,
        session=session,
        resource_type="message",
        resource_id=user_msg.id,
        payload={
            "content_preview": prompt[:200],
            "token_count": len(prompt) // 4,
            "has_attachments": bool(attachments),
            "attachment_filenames": _attachment_filenames(
                db, attachments or [], workspace.id
            ),
        },
        request=request,
    )
    db.commit()
    return user_msg.id


def persist_assistant_message(
    *,
    session_id: str,
    workspace_id: str,
    user_id: str,
    full_response: str,
    status: str,
    tool_calls_acc: list[dict],
    tool_calls_for_row: Optional[list[dict]],
    referenced_docs: Optional[list[dict]],
    reasoning: Optional[str],
    reasoning_duration_s: Optional[float],
    route_meta: dict,
    usage: Optional[dict],
    finished_cleanly: bool,
) -> Optional[str]:
    """Persist the assistant Message row and emit CHAT_MESSAGE_RECEIVED.

    Used by both the clean-completion branch and the abort/fail branch:
      - clean: status="complete", row carries tool_calls/referenced_docs,
        usage carries token + timing snapshot.
      - aborted/failed: status="aborted" or "failed", row leaves
        tool_calls/referenced_docs unset, usage is None and the
        token/timing payload keys are omitted. Mid-stream tool fires
        are still reflected in the audit payload via tool_calls_acc.

    `tool_calls_acc` is the live accumulator: audit `tools_used` /
    `tools_count` are derived from it in both branches. `tool_calls_for_row`
    is what (if anything) to write to the Message row's tool_calls column —
    pass the finalized list on clean completion, None on abort/fail.

    Returns the saved message id, or None if the save failed.
    """
    save_db = database.SessionLocal()
    try:
        ai_msg = models.Message(
            session_id=session_id,
            role="assistant",
            content=full_response,
            status=status,
            tool_calls=tool_calls_for_row or None,
            referenced_docs=referenced_docs,
            reasoning_content=(reasoning.strip() if reasoning else None) or None,
            reasoning_duration_s=reasoning_duration_s,
        )
        save_db.add(ai_msg)
        save_db.commit()
        save_db.refresh(ai_msg)

        tool_names = sorted({tc.get("name") for tc in tool_calls_acc if tc.get("name")})
        payload: dict[str, Any] = {
            "content_preview": full_response[:200],
            # Which model + tier the router picked. Captured from the upfront
            # `route` SSE event so it's accurate even when the metric
            # snapshot's `model` field is empty (e.g. tool-only turns).
            "model": route_meta.get("model") or (usage or {}).get("model") or "",
            "tier": route_meta.get("tier") or "",
            # Tools that actually fired this turn.
            "tools_used": tool_names,
            "tools_count": len(tool_calls_acc),
            # Reasoning visibility.
            "reasoning": reasoning_duration_s is not None,
            "reasoning_duration_s": reasoning_duration_s,
            "finished_cleanly": finished_cleanly,
        }
        if usage is not None:
            prompt_tokens = int(usage.get("prompt_tokens") or 0)
            completion_tokens = int(usage.get("completion_tokens") or 0)
            payload.update({
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "token_count": prompt_tokens + completion_tokens,
                "duration_ms": int(usage.get("duration_ms") or 0),
                "ttft_ms": int(usage.get("ttft_ms") or 0),
                "tokens_per_sec": float(usage.get("tokens_per_sec") or 0.0),
            })
        if not finished_cleanly:
            payload["status"] = status

        log_event(
            save_db,
            EventType.CHAT_MESSAGE_RECEIVED,
            user=save_db.query(models.User).filter_by(id=user_id).first(),
            workspace=save_db.query(models.Workspace).filter_by(id=workspace_id).first(),
            session=save_db.query(models.Session).filter_by(id=session_id).first(),
            resource_type="message",
            resource_id=ai_msg.id,
            payload=payload,
        )
        save_db.commit()
        return ai_msg.id
    except Exception as e:
        save_db.rollback()
        _log.exception("Failed to save assistant message: %s", e)
        return None
    finally:
        save_db.close()
