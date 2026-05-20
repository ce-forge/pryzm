"""current_user dependency: cookie → User resolution."""
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from core.cookie_auth import current_user, create_session
from db import models


def _fake_request(path: str = "/some/endpoint") -> Request:
    """Minimal ASGI scope sufficient for `Request.url.path`."""
    return Request({"type": "http", "method": "GET", "path": path, "headers": []})


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
    result = current_user(request=_fake_request(), pryzm_session=sid, db=db_session)
    assert result.id == u.id


def test_current_user_raises_401_for_missing_cookie(db_session):
    with pytest.raises(HTTPException) as exc:
        current_user(request=_fake_request(), pryzm_session=None, db=db_session)
    assert exc.value.status_code == 401


def test_current_user_raises_401_for_invalid_cookie(db_session):
    with pytest.raises(HTTPException) as exc:
        current_user(request=_fake_request(), pryzm_session="not-a-real-sid", db=db_session)
    assert exc.value.status_code == 401


def test_current_user_raises_401_for_deactivated_user(db_session):
    u = _make_user(db_session, is_active=False)
    sid = create_session(db_session, u.id)
    with pytest.raises(HTTPException) as exc:
        current_user(request=_fake_request(), pryzm_session=sid, db=db_session)
    assert exc.value.status_code == 401


def test_current_user_must_change_state_403s_protected_path(db_session):
    """Direct-call coverage of the must_change_password gate."""
    u = _make_user(db_session, username="must-change-direct")
    u.must_change_password = True
    db_session.commit()
    sid = create_session(db_session, u.id)
    with pytest.raises(HTTPException) as exc:
        current_user(request=_fake_request("/workspaces"), pryzm_session=sid, db=db_session)
    assert exc.value.status_code == 403


def test_current_user_must_change_state_allows_password_path(db_session):
    """Direct-call coverage: /api/auth/password is on the allowlist."""
    u = _make_user(db_session, username="must-change-allowed")
    u.must_change_password = True
    db_session.commit()
    sid = create_session(db_session, u.id)
    result = current_user(
        request=_fake_request("/api/auth/password"),
        pryzm_session=sid,
        db=db_session,
    )
    assert result.id == u.id
