"""Unit tests for services.condense.

The advisory lock test uses TWO separate SessionLocal connections to prove that
the lock actually blocks across connections (not just within one transaction).
"""
import pytest
from sqlalchemy.orm import sessionmaker

from services import condense


def test_advisory_lock_acquires_and_blocks_concurrent_acquirer(db_at_head):
    """Two simultaneous lock attempts on the same session id: first wins, second skips.

    Uses two separate Connections so the lock genuinely crosses connection
    boundaries (otherwise a session-level lock would let the same connection
    re-acquire).
    """
    engine = db_at_head
    MakeSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    sid = "test-session-x"
    db1 = MakeSession()
    db2 = MakeSession()
    try:
        with condense._session_advisory_lock(db1, sid) as first_acquired:
            assert first_acquired is True

            with condense._session_advisory_lock(db2, sid) as second_acquired:
                assert second_acquired is False  # blocked by db1's lock

        # After db1's `with` exits and releases the lock, db2 should now succeed.
        with condense._session_advisory_lock(db2, sid) as third_acquired:
            assert third_acquired is True
    finally:
        db1.close()
        db2.close()


def test_advisory_lock_different_session_ids_dont_block(db_at_head):
    """Locks keyed on different session ids do NOT block each other."""
    engine = db_at_head
    MakeSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    db1 = MakeSession()
    db2 = MakeSession()
    try:
        with condense._session_advisory_lock(db1, "sid-a") as a:
            with condense._session_advisory_lock(db2, "sid-b") as b:
                assert a is True
                assert b is True
    finally:
        db1.close()
        db2.close()
