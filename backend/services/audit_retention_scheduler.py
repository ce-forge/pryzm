"""Periodic loop that keeps audit_events partitions provisioned + pruned.

Runs as a single asyncio task spawned in the app's lifespan. Each tick:
  1. Ensures next month's partition exists (so inserts at midnight on
     the 1st have a target table).
  2. Drops partitions whose upper bound is older than the retention
     window (AUDIT_RETENTION_DAYS).

Per-tick work happens in a thread pool — DB calls are synchronous and we
don't want to block the event loop. Failures inside a tick are logged
and swallowed; the loop keeps running. A cancellation (e.g. shutdown)
exits cleanly.
"""
from __future__ import annotations

import asyncio
import logging

from config import settings
from db import database
from services.audit_partitions import (
    ensure_next_month_partition,
    prune_old_partitions,
)


_logger = logging.getLogger(__name__)


DEFAULT_INTERVAL_SECONDS = 24 * 3600


def run_one_tick() -> tuple[str, list[str]]:
    """One sync pass through the retention work. Returns (ensured_partition,
    dropped_partitions) for tests + observability."""
    db = database.SessionLocal()
    try:
        ensured = ensure_next_month_partition(db)
        dropped = prune_old_partitions(db, settings.AUDIT_RETENTION_DAYS)
        db.commit()
        return ensured, dropped
    finally:
        db.close()


async def audit_retention_loop(interval_seconds: int = DEFAULT_INTERVAL_SECONDS) -> None:
    """Long-running coroutine. Spawn via asyncio.create_task in lifespan;
    cancel on shutdown."""
    while True:
        try:
            ensured, dropped = await asyncio.to_thread(run_one_tick)
            if dropped:
                _logger.info(
                    "audit retention: ensured=%s dropped=%s",
                    ensured, dropped,
                )
        except asyncio.CancelledError:
            return
        except Exception:
            # Tick failures must not kill the loop. The next tick gets
            # another shot; a failing tick is visible in logs but does not
            # cascade.
            _logger.exception("audit retention tick failed")
        try:
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            return
