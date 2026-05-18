"""Partition lifecycle helpers."""
from datetime import datetime, timezone

from sqlalchemy import text

from services.audit_partitions import (
    ensure_next_month_partition,
    prune_old_partitions,
)


def test_ensure_next_month_idempotent(db_session):
    fixed = datetime(2026, 3, 15, tzinfo=timezone.utc)
    name1 = ensure_next_month_partition(db_session, now=fixed)
    db_session.commit()
    name2 = ensure_next_month_partition(db_session, now=fixed)
    db_session.commit()
    assert name1 == name2 == "audit_events_y2026m04"
    # Verify it actually exists
    rows = db_session.execute(text("""
        SELECT inhrelid::regclass::text FROM pg_inherits
        WHERE inhparent = 'audit_events'::regclass
    """)).fetchall()
    assert any(r[0].endswith("audit_events_y2026m04") for r in rows)


def test_prune_drops_old_partitions(db_session):
    # Create an old partition far in the past
    db_session.execute(text("""
        CREATE TABLE IF NOT EXISTS audit_events_y2020m01 PARTITION OF audit_events
        FOR VALUES FROM ('2020-01-01') TO ('2020-02-01');
    """))
    db_session.commit()

    dropped = prune_old_partitions(db_session, retention_days=90,
                                    now=datetime(2026, 5, 18, tzinfo=timezone.utc))
    db_session.commit()
    assert "audit_events_y2020m01" in dropped


def test_prune_keeps_recent_partitions(db_session):
    fixed_now = datetime(2026, 5, 18, tzinfo=timezone.utc)
    # The current month partition (y2026m05) was created by the migration.
    dropped = prune_old_partitions(db_session, retention_days=90, now=fixed_now)
    db_session.commit()
    assert "audit_events_y2026m05" not in dropped
