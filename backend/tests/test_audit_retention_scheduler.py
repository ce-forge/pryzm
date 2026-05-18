"""Audit retention scheduler — per-tick + loop cancellation behaviour.

The asyncio loop itself is the trivial part (sleep + tick); the
interesting unit is `run_one_tick`. Tests use the same `db_session`
fixture as the rest of the audit tests so DDL changes are committed
visibly.
"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from db import database
from services import audit_retention_scheduler


def test_run_one_tick_creates_next_month_and_returns_drops(
    db_session, monkeypatch
):
    """First tick on a fresh DB ensures next month's partition exists."""
    # Redirect database.SessionLocal at the test engine so the helper writes
    # land in pryzm_test, not the production pryzm DB.
    test_session_local = sessionmaker(
        bind=db_session.bind, autoflush=False, autocommit=False
    )
    monkeypatch.setattr(database, "SessionLocal", test_session_local)

    ensured, dropped = audit_retention_scheduler.run_one_tick()
    assert ensured.startswith("audit_events_y")
    # On a fresh test DB there's nothing to drop yet.
    assert dropped == []


def test_run_one_tick_drops_past_partitions(db_session, monkeypatch):
    """Manually seed a partition from a year ago; verify the tick drops it."""
    test_session_local = sessionmaker(
        bind=db_session.bind, autoflush=False, autocommit=False
    )
    monkeypatch.setattr(database, "SessionLocal", test_session_local)
    # Force a small retention window so a year-ago partition is past cutoff.
    from config import settings
    monkeypatch.setattr(settings, "AUDIT_RETENTION_DAYS", 30)

    # Create a partition for a date well before the cutoff.
    old_year = (datetime.now(timezone.utc) - timedelta(days=400)).year
    old_month = 6
    name = f"audit_events_y{old_year}m{old_month:02d}"
    start = f"{old_year}-{old_month:02d}-01"
    end = f"{old_year}-{old_month:02d}-15"  # narrow range, doesn't matter for the drop test
    db_session.execute(text(
        f"CREATE TABLE IF NOT EXISTS {name} PARTITION OF audit_events "
        f"FOR VALUES FROM ('{start} 00:00:00+00') TO ('{end} 00:00:00+00');"
    ))
    db_session.commit()

    _ensured, dropped = audit_retention_scheduler.run_one_tick()
    assert name in dropped


@pytest.mark.asyncio
async def test_loop_swallows_tick_failures_and_keeps_running(monkeypatch):
    """A failing tick must not kill the loop."""
    calls = {"n": 0}

    def boom():
        calls["n"] += 1
        raise RuntimeError("synthetic tick failure")

    monkeypatch.setattr(audit_retention_scheduler, "run_one_tick", boom)

    task = asyncio.create_task(
        audit_retention_scheduler.audit_retention_loop(interval_seconds=0.01)
    )
    # Let it loop a few times.
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert calls["n"] >= 2, f"expected multiple ticks despite failures, got {calls['n']}"


@pytest.mark.asyncio
async def test_loop_exits_cleanly_on_cancel(monkeypatch):
    """The loop swallows its own CancelledError and returns. Verify the
    task completes (not raises) within a small timeout after cancel."""
    monkeypatch.setattr(
        audit_retention_scheduler, "run_one_tick", lambda: ("x", []),
    )
    task = asyncio.create_task(
        audit_retention_scheduler.audit_retention_loop(interval_seconds=60.0)
    )
    await asyncio.sleep(0.02)
    task.cancel()
    await asyncio.wait_for(task, timeout=1.0)
    assert task.done()
