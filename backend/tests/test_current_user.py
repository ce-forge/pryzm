"""current_user dependency: cookie → User resolution."""
import pytest
from fastapi import HTTPException

from core.cookie_auth import current_user, create_session
from db import models


def _make_user(db_session, **kwargs):
    u = models.User(
        username=kwargs.get("username", "alice"),
        password_hash="dummy",
        is_admin=kwargs.get("is_admin", False),
        is_active=kwargs.get("is_active", True),
    )
    db_session.add(u)
    db_session.commit()
    return u


def test_current_user_returns_user_for_valid_cookie(db_session):
    u = _make_user(db_session)
    sid = create_session(db_session, u.id)
    result = current_user(pryzm_session=sid, authorization=None, token=None, db=db_session)
    assert result.id == u.id


def test_current_user_raises_401_for_missing_cookie(db_session):
    with pytest.raises(HTTPException) as exc:
        current_user(pryzm_session=None, authorization=None, token=None, db=db_session)
    assert exc.value.status_code == 401


def test_current_user_raises_401_for_invalid_cookie(db_session):
    with pytest.raises(HTTPException) as exc:
        current_user(pryzm_session="not-a-real-sid", authorization=None, token=None, db=db_session)
    assert exc.value.status_code == 401


def test_current_user_raises_401_for_deactivated_user(db_session):
    u = _make_user(db_session, is_active=False)
    sid = create_session(db_session, u.id)
    with pytest.raises(HTTPException) as exc:
        current_user(pryzm_session=sid, authorization=None, token=None, db=db_session)
    assert exc.value.status_code == 401
