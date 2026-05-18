"""Audit-events partition lifecycle.

`audit_events` is partitioned by month on `created_at`. We need to:
  1. Create the next month's partition before month-end (so inserts at
     midnight on the 1st have a target partition).
  2. Drop partitions older than retention.

This module provides both as callable functions. F.1 doesn't auto-
schedule them; F.2 (or operator cron) wires them up.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session


def _partition_name(year: int, month: int) -> str:
    return f"audit_events_y{year}m{month:02d}"


def _month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start, end


def ensure_next_month_partition(db: Session, now: datetime | None = None) -> str:
    """Create next month's partition if it doesn't exist.

    Idempotent: uses `CREATE TABLE IF NOT EXISTS`. Returns the
    partition name (created or pre-existing).
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if now.month == 12:
        target_year, target_month = now.year + 1, 1
    else:
        target_year, target_month = now.year, now.month + 1
    name = _partition_name(target_year, target_month)
    start, end = _month_bounds(target_year, target_month)
    db.execute(text(
        f"CREATE TABLE IF NOT EXISTS {name} PARTITION OF audit_events "
        f"FOR VALUES FROM ('{start.isoformat()}') TO ('{end.isoformat()}');"
    ))
    return name


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
        if not name.startswith("audit_events_y"):
            continue
        # Parse y<year>m<month> from the suffix
        suffix = name[len("audit_events_y"):]
        try:
            year_str, month_str = suffix.split("m")
            year, month = int(year_str), int(month_str)
        except (ValueError, IndexError):
            continue
        _, partition_end = _month_bounds(year, month)
        if partition_end <= cutoff:
            db.execute(text(f"DROP TABLE {name};"))
            dropped.append(name)
    return dropped
