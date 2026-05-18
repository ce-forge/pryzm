"""Last-admin guard: cannot demote/deactivate/delete the last active admin."""
import pytest
from fastapi import HTTPException

from core.cookie_auth import assert_not_removing_last_admin
from db import models


def _make_user(db_session, **kwargs):
    u = models.User(
        username=kwargs.get("username", "x"),
        password_hash="dummy",
        is_admin=kwargs.get("is_admin", False),
        is_active=kwargs.get("is_active", True),
    )
    db_session.add(u); db_session.commit(); db_session.refresh(u)
    return u


def test_guard_allows_when_two_admins_exist(db_session):
    a = _make_user(db_session, username="admin1", is_admin=True)
    _make_user(db_session, username="admin2", is_admin=True)
    assert_not_removing_last_admin(
        db_session, target_user_id=a.id, would_be_admin=False, would_be_active=True,
    )


def test_guard_blocks_when_demoting_last_admin(db_session):
    a = _make_user(db_session, username="admin1", is_admin=True)
    _make_user(db_session, username="bob", is_admin=False)
    with pytest.raises(HTTPException) as exc:
        assert_not_removing_last_admin(
            db_session, target_user_id=a.id, would_be_admin=False, would_be_active=True,
        )
    assert exc.value.status_code == 400


def test_guard_blocks_when_deactivating_last_admin(db_session):
    a = _make_user(db_session, username="admin1", is_admin=True)
    with pytest.raises(HTTPException):
        assert_not_removing_last_admin(
            db_session, target_user_id=a.id, would_be_admin=True, would_be_active=False,
        )


def test_guard_allows_when_target_stays_active_admin(db_session):
    a = _make_user(db_session, username="admin1", is_admin=True)
    # Edit that keeps admin status intact — guard is a no-op
    assert_not_removing_last_admin(
        db_session, target_user_id=a.id, would_be_admin=True, would_be_active=True,
    )


def test_guard_ignores_inactive_admins(db_session):
    a = _make_user(db_session, username="admin1", is_admin=True, is_active=True)
    _make_user(db_session, username="admin2", is_admin=True, is_active=False)
    # admin2 is inactive, so demoting admin1 still blocks (only counts active)
    with pytest.raises(HTTPException):
        assert_not_removing_last_admin(
            db_session, target_user_id=a.id, would_be_admin=False, would_be_active=True,
        )
