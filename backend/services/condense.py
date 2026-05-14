"""Background memory condensation.

Runs out-of-band after /analyze closes (scheduled via FastAPI BackgroundTasks).
Uses a Postgres advisory lock keyed on the session id so concurrent requests
for the same session don't both condense at once.

The condense logic itself (load prior memory, slice messages, call the LLM,
persist new memory row) is lifted from what was previously inline in
routers/chat.py's stream generator finally block.
"""
from __future__ import annotations

import json
import logging
from contextlib import contextmanager

import httpx
from sqlalchemy import text

from config import settings
from core import ai_engine
from db import database, models

logger = logging.getLogger(__name__)


@contextmanager
def _session_advisory_lock(db, session_id: str):
    """Try to acquire a Postgres advisory lock keyed on the session.

    Yields True if acquired, False otherwise. Caller decides what to do
    when the lock is held (typically: skip silently).

    Uses pg_try_advisory_lock(bigint) which is non-blocking — perfect for
    "skip if someone else is already doing this" semantics. The bigint key is
    derived from a 64-bit hash of the session id via hashtextextended.

    Important: no commit is issued between key computation and lock acquisition.
    A mid-lock commit would cause SQLAlchemy to return the physical connection
    to the pool, releasing the session-level advisory lock prematurely.
    The commit is deferred to the finally block after unlock.
    """
    key = db.execute(
        text("SELECT hashtextextended(:k, 0)").bindparams(k=f"condense:{session_id}")
    ).scalar()

    acquired = db.execute(
        text("SELECT pg_try_advisory_lock(:k)").bindparams(k=key)
    ).scalar()

    try:
        yield acquired
    finally:
        if acquired:
            db.execute(
                text("SELECT pg_advisory_unlock(:k)").bindparams(k=key)
            )
        db.commit()


async def condense_for_session(
    client: httpx.AsyncClient,
    session_id: str,
    model_name: str,
):
    """Condense the messages for `session_id` if the threshold is met.

    Idempotent under concurrent calls — the advisory lock ensures only one
    condenser runs per session at a time. Other invocations skip silently.
    """
    db = database.SessionLocal()
    try:
        with _session_advisory_lock(db, session_id) as acquired:
            if not acquired:
                logger.info("condense skipped (lock held): session %s", session_id)
                return

            await _condense_inner(db, client, session_id, model_name)
    except Exception:
        logger.exception("condense failed for session %s", session_id)
    finally:
        db.close()


async def _condense_inner(
    db,
    client: httpx.AsyncClient,
    session_id: str,
    model_name: str,
):
    """The actual condense logic — lifted from routers/chat.py's old finally.

    Only runs on status=complete exchanges to avoid baking noise (aborted /
    failed turns) into long-term memory.
    """
    all_msgs = (
        db.query(models.Message)
        .filter(models.Message.session_id == session_id)
        .order_by(models.Message.created_at)
        .all()
    )

    memory_msg = next((m for m in all_msgs if m.role == "memory"), None)

    last_id = None
    old_summary = ""
    if memory_msg:
        try:
            mem_data = json.loads(memory_msg.content)
            last_id = mem_data.get("last_summarized_id")
            old_summary = mem_data.get("summary", "")
        except Exception:
            old_summary = memory_msg.content

    active_msgs = [
        m for m in all_msgs
        if m.role in ["user", "assistant"] and m.status == "complete"
    ]

    start_idx = 0
    if last_id:
        for i, m in enumerate(active_msgs):
            if m.id == last_id:
                start_idx = i + 1
                break

    unsummarized = active_msgs[start_idx:]

    if len(unsummarized) <= settings.MEMORY_CONDENSE_THRESHOLD:
        return

    retain_count = settings.MEMORY_CONDENSE_RETAIN
    to_summarize = unsummarized[:-retain_count]
    new_last_id = to_summarize[-1].id

    msg_dicts = [{"role": m.role, "content": m.content} for m in to_summarize]
    new_summary_text = await ai_engine.condense_chat_memory(
        client, old_summary, msg_dicts, model_name
    )

    new_mem_data = {
        "last_summarized_id": new_last_id,
        "summary": new_summary_text,
    }

    if memory_msg:
        memory_msg.content = json.dumps(new_mem_data)
    else:
        db.add(models.Message(
            session_id=session_id,
            role="memory",
            content=json.dumps(new_mem_data),
        ))

    db.commit()
