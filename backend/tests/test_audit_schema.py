"""audit_events schema: append-only trigger, FK SET NULL, partition exists."""
import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError, InternalError

from db import models


def _seed_event(db_session):
    user = models.User(
        username="alice",
        password_hash="dummy",
        is_admin=False,
        is_active=True,
    )
    db_session.add(user); db_session.commit(); db_session.refresh(user)
    e = models.AuditEvent(
        user_id=user.id,
        user_display_name_at_event="alice",
        event_type="auth.login_success",
        payload={"k": "v"},
    )
    db_session.add(e); db_session.commit(); db_session.refresh(e)
    return user, e


def test_update_raises(db_session):
    _, e = _seed_event(db_session)
    with pytest.raises(Exception) as exc_info:
        db_session.execute(text(
            "UPDATE audit_events SET event_type = 'tampered' WHERE id = :id"
        ), {"id": e.id})
        db_session.commit()
    assert "append-only" in str(exc_info.value).lower()


def test_delete_raises(db_session):
    _, e = _seed_event(db_session)
    with pytest.raises(Exception) as exc_info:
        db_session.execute(text(
            "DELETE FROM audit_events WHERE id = :id"
        ), {"id": e.id})
        db_session.commit()
    assert "append-only" in str(exc_info.value).lower()


def test_user_fk_set_null_on_user_delete(db_session):
    user, e = _seed_event(db_session)
    # Hard-delete the user (rare in production but the audit row should survive)
    db_session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user.id})
    db_session.commit()
    refreshed = db_session.query(models.AuditEvent).filter_by(id=e.id).first()
    assert refreshed is not None
    assert refreshed.user_id is None
    # Display name snapshot survives
    assert refreshed.user_display_name_at_event == "alice"


def test_current_month_partition_exists(db_session):
    rows = db_session.execute(text("""
        SELECT inhrelid::regclass::text AS name
        FROM pg_inherits
        WHERE inhparent = 'audit_events'::regclass
    """)).fetchall()
    names = [r[0].split(".")[-1] for r in rows]
    assert any(n.startswith("audit_events_y") for n in names), names
