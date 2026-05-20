"""Audit-events partition lifecycle.

`audit_events` is partitioned by month on `created_at`. We need to:
  1. Create the next month's partition before month-end (so inserts at
     midnight on the 1st have a target partition).
  2. Drop partitions older than retention.

This module provides both as callable functions. F.1 doesn't auto-
schedule them; F.2 (or operator cron) wires them up.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session


# Lock the parsable-name pattern. The prune path reads partition names
# from pg_inherits and passes them straight to DROP TABLE; any name that
# doesn't match this gets skipped. Today every name comes from
# _partition_name() so the regex is a no-op guard, but if anyone ever
# attaches a manually-named partition the prune path can't accidentally
# DROP it.
_PARTITION_NAME_RE = re.compile(r"^audit_events_y\d{4}m\d{2}$")


def _partition_name(year: int, month: int) -> str:
    return f"audit_events_y{year}m{month:02d}"


def _month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start, end


def _ensure_partition(db: Session, year: int, month: int) -> str:
    """Create a single month's partition if it doesn't exist."""
    name = _partition_name(year, month)
    start, end = _month_bounds(year, month)
    db.execute(text(
        f"CREATE TABLE IF NOT EXISTS {name} PARTITION OF audit_events "
        f"FOR VALUES FROM ('{start.isoformat()}') TO ('{end.isoformat()}');"
    ))
    return name


def ensure_next_month_partition(db: Session, now: datetime | None = None) -> str:
    """Create the CURRENT and NEXT month's partitions if either is missing.

    Returns the next month's partition name (kept for backwards compat
    with callers that read the return value). Despite the function
    name, *both* partitions are ensured — a backend offline across two
    month boundaries would otherwise miss the recovery month and the
    first INSERT on day 1 would fail with "no partition of relation
    found for row".

    Idempotent. The CURRENT-month partition is the boring no-op every
    other day; on the recovery day it's the load-bearing call.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    # Current month
    _ensure_partition(db, now.year, now.month)
    # Next month
    if now.month == 12:
        target_year, target_month = now.year + 1, 1
    else:
        target_year, target_month = now.year, now.month + 1
    return _ensure_partition(db, target_year, target_month)


def prune_old_partitions(
    db: Session,
    retention_days: int,
    now: datetime | None = None,
) -> list[str]:
    """Drop partitions whose upper bound is older than now - retention_days.

    Returns the list of dropped partition names.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=retention_days)

    # Discover all child partitions of audit_events
    rows = db.execute(text("""
        SELECT inhrelid::regclass::text AS name
        FROM pg_inherits
        WHERE inhparent = 'audit_events'::regclass
    """)).fetchall()

    dropped: list[str] = []
    for (raw_name,) in rows:
        # Strip schema prefix if present
        name = raw_name.split(".")[-1]
        if not _PARTITION_NAME_RE.match(name):
            continue
        # Parse y<year>m<month> from the matched suffix
        suffix = name[len("audit_events_y"):]
        year_str, month_str = suffix.split("m")
        year, month = int(year_str), int(month_str)
        _, partition_end = _month_bounds(year, month)
        if partition_end <= cutoff:
            db.execute(text(f"DROP TABLE {name};"))
            dropped.append(name)
    return dropped
