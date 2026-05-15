"""Unit tests for the in-process ingest broker (PR 2 of the async-
ingestion spec). Pure pub/sub semantics — no DB, no HTTP."""
from __future__ import annotations

import asyncio

import pytest

from services import ingest_broker


@pytest.mark.asyncio
async def test_subscribe_then_publish_delivers_event():
    b = ingest_broker.IngestBroker()
    q = b.subscribe("doc-x")
    await b.publish("doc-x", {"status": "ready"})
    event = await asyncio.wait_for(q.get(), timeout=1.0)
    assert event == {"status": "ready"}


@pytest.mark.asyncio
async def test_publish_with_no_subscribers_is_noop():
    """Publishing for an unknown doc_id must not raise — the SSE
    handler may not have subscribed yet when ingestion completes."""
    b = ingest_broker.IngestBroker()
    await b.publish("nobody-listens", {"status": "ready"})


@pytest.mark.asyncio
async def test_multiple_subscribers_each_get_their_own_copy():
    """Each subscriber owns a queue so a slow consumer can't starve
    a fast one (or the publisher)."""
    b = ingest_broker.IngestBroker()
    q1 = b.subscribe("doc-y")
    q2 = b.subscribe("doc-y")
    await b.publish("doc-y", {"status": "ready"})
    e1 = await asyncio.wait_for(q1.get(), timeout=1.0)
    e2 = await asyncio.wait_for(q2.get(), timeout=1.0)
    assert e1 == e2 == {"status": "ready"}


@pytest.mark.asyncio
async def test_unsubscribe_stops_delivering():
    b = ingest_broker.IngestBroker()
    q = b.subscribe("doc-z")
    b.unsubscribe("doc-z", q)
    await b.publish("doc-z", {"status": "ready"})
    # If unsubscribe worked the queue stays empty; with a small
    # timeout we confirm nothing was queued.
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(q.get(), timeout=0.05)


@pytest.mark.asyncio
async def test_add_task_holds_strong_reference_until_done():
    """asyncio.create_task is GC-vulnerable when the caller drops
    the Task reference. add_task must keep a strong ref in the
    module-level set so background coroutines run to completion."""
    started = asyncio.Event()
    finished = asyncio.Event()

    async def work() -> None:
        started.set()
        await asyncio.sleep(0.01)
        finished.set()

    task = ingest_broker.add_task(work())
    await asyncio.wait_for(started.wait(), timeout=1.0)
    # The task is still mid-flight; module set must hold it.
    assert task in ingest_broker._active_tasks
    await asyncio.wait_for(finished.wait(), timeout=1.0)
    # Drain done-callbacks so _active_tasks reflects completion.
    await asyncio.sleep(0)
    assert task not in ingest_broker._active_tasks


@pytest.mark.asyncio
async def test_add_task_surfaces_exceptions_to_log(caplog):
    """Background tasks that raise unhandled exceptions must not
    disappear silently — the done-callback logs them at ERROR."""
    import logging

    async def boom() -> None:
        raise RuntimeError("boom")

    # caplog only captures root by default; the broker logs to its
    # own module logger. Wire propagation on for the test.
    pkg_logger = logging.getLogger("services.ingest_broker")
    original_propagate = pkg_logger.propagate
    pkg_logger.propagate = True
    try:
        task = ingest_broker.add_task(boom())
        with caplog.at_level(logging.ERROR, logger="services.ingest_broker"):
            with pytest.raises(RuntimeError):
                await task
            # Yield once so the done_callback runs.
            await asyncio.sleep(0)
        assert any("background task raised" in r.getMessage() for r in caplog.records)
    finally:
        pkg_logger.propagate = original_propagate
