"""Unit tests for services.condense.

The advisory lock test uses TWO separate SessionLocal connections to prove that
the lock actually blocks across connections (not just within one transaction).
"""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
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


def test_session_advisory_lock_releases_on_acquisition_error(db_session, monkeypatch):
    """If acquiring the advisory lock raises mid-way, the helper must not
    leak a half-acquired lock back into the pool.

    Simulates: the lock SELECT actually succeeds at the DB level (lock is now
    held) but the call site raises before `acquired` can be assigned. Pre-fix,
    the helper's try/finally is bypassed entirely and the lock leaks.
    """
    call_count = {"n": 0}
    original_execute = db_session.execute

    def flaky_execute(stmt, *args, **kwargs):
        call_count["n"] += 1
        result = original_execute(stmt, *args, **kwargs)
        # Let the first call (hashtextextended) return normally so we have a
        # key, then on the second call (pg_try_advisory_lock) actually acquire
        # the lock but raise after — mimicking a mid-fetch failure.
        if call_count["n"] == 2:
            # Force materialization so the lock is genuinely taken server-side.
            result.scalar()
            raise OperationalError("statement", {}, Exception("simulated"))
        return result

    monkeypatch.setattr(db_session, "execute", flaky_execute)

    with pytest.raises(OperationalError):
        with condense._session_advisory_lock(db_session, "sess-x"):
            pass

    monkeypatch.setattr(db_session, "execute", original_execute)
    held = db_session.execute(
        text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory'")
    ).scalar()
    assert held == 0
