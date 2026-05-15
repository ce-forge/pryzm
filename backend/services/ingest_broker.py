"""In-process pub/sub for document-ingestion status events.

Async-ingestion infrastructure (docs/specs/2026-05-15-async-ingestion.md).
Today only the class itself ships — PR 3 wires it into the live
upload flow. Building this in PR 2 lets PR 3 focus on the route-shape
flip without having to also stand up the broker at the same time.

The shape is deliberately small: subscribe, unsubscribe, publish,
plus an `add_task` helper that holds asyncio.Task references in a
module-level set so background coroutines don't get garbage-collected
mid-run.

When this ingestion path scales beyond one uvicorn worker, swap the
backing store for Redis pub/sub. The class interface stays the same;
the subscriber gets a queue, the publisher writes to a channel.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable

_logger = logging.getLogger(__name__)


class IngestBroker:
    """Multi-subscriber, doc-id-keyed event broker.

    Each subscriber gets its own asyncio.Queue so subscribers don't
    fight each other for events — the SSE handler reads from its own
    queue, doesn't drain a shared one. Slow subscribers block their
    own queue but not the publisher (Queue defaults to unbounded; on
    real load we'd cap and drop).
    """

    def __init__(self) -> None:
        self._waiters: dict[str, list[asyncio.Queue[dict]]] = {}

    def subscribe(self, doc_id: str) -> asyncio.Queue[dict]:
        q: asyncio.Queue[dict] = asyncio.Queue()
        self._waiters.setdefault(doc_id, []).append(q)
        return q

    def unsubscribe(self, doc_id: str, q: asyncio.Queue[dict]) -> None:
        lst = self._waiters.get(doc_id) or []
        if q in lst:
            lst.remove(q)
        if not lst:
            self._waiters.pop(doc_id, None)

    async def publish(self, doc_id: str, event: dict) -> None:
        for q in list(self._waiters.get(doc_id, [])):
            await q.put(event)


# Module-level singleton. The instance is intentionally not held in
# app.state — there's only one uvicorn worker in this deployment, and
# tests want to be able to swap it via monkeypatch without reaching
# into FastAPI's app fixture.
_broker = IngestBroker()


def broker() -> IngestBroker:
    return _broker


# ---------------------------------------------------------------------------
# Background-task lifecycle. asyncio.create_task returns a Task whose
# strong reference must be held externally — Python may otherwise GC
# the task while it's still running. We keep a module-level set and
# the task removes itself on completion via add_done_callback.
# ---------------------------------------------------------------------------

_active_tasks: set[asyncio.Task] = set()


def add_task(coro: Awaitable[None]) -> asyncio.Task:
    """asyncio.create_task wrapper that keeps a strong reference to
    the resulting Task in a module-level set. Callers use this instead
    of bare create_task to avoid the GC-mid-run hazard."""
    task = asyncio.create_task(coro)
    _active_tasks.add(task)
    task.add_done_callback(_on_task_done)
    return task


def _on_task_done(task: asyncio.Task) -> None:
    _active_tasks.discard(task)
    # Surface unhandled exceptions to the log. ingest_pipeline.ingest_doc
    # is supposed to catch its own; this is a belt-and-braces guard so
    # crashes in the broker layer itself don't disappear silently.
    if not task.cancelled():
        exc = task.exception()
        if exc is not None:
            _logger.error("background task raised", exc_info=exc)
