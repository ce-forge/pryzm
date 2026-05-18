"""current_user accepts cookie OR bearer; bearer resolves to bootstrap admin."""
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
    db_session.add(u); db_session.commit(); db_session.refresh(u)
    return u


def test_current_user_returns_user_from_valid_cookie(db_session):
    u = _make_user(db_session, username="alice")
    sid = create_session(db_session, u.id)
    result = current_user(pryzm_session=sid, authorization=None, token=None, db=db_session)
    assert result.id == u.id


def test_current_user_with_bearer_resolves_to_bootstrap_admin(db_session, monkeypatch):
    admin = _make_user(db_session, username="admin", is_admin=True)
    _make_user(db_session, username="bob", is_admin=False)

    monkeypatch.setattr("config.settings.PRYZM_API_TOKEN", "test-token")
    result = current_user(
        pryzm_session=None,
        authorization="Bearer test-token",
        token=None,
        db=db_session,
    )
    assert result.id == admin.id


def test_current_user_with_bearer_token_query_param(db_session, monkeypatch):
    admin = _make_user(db_session, username="admin", is_admin=True)
    monkeypatch.setattr("config.settings.PRYZM_API_TOKEN", "test-token")
    result = current_user(
        pryzm_session=None,
        authorization=None,
        token="test-token",
        db=db_session,
    )
    assert result.id == admin.id


def test_current_user_with_wrong_bearer_raises_401(db_session, monkeypatch):
    _make_user(db_session, username="admin", is_admin=True)
    monkeypatch.setattr("config.settings.PRYZM_API_TOKEN", "real-token")
    with pytest.raises(HTTPException) as exc:
        current_user(
            pryzm_session=None,
            authorization="Bearer wrong-token",
            token=None,
            db=db_session,
        )
    assert exc.value.status_code == 401


def test_current_user_with_no_auth_raises_401(db_session):
    with pytest.raises(HTTPException) as exc:
        current_user(pryzm_session=None, authorization=None, token=None, db=db_session)
    assert exc.value.status_code == 401


def test_current_user_cookie_takes_precedence_over_bearer(db_session, monkeypatch):
    _make_user(db_session, username="admin", is_admin=True)
    bob = _make_user(db_session, username="bob")
    sid = create_session(db_session, bob.id)
    monkeypatch.setattr("config.settings.PRYZM_API_TOKEN", "test-token")
    result = current_user(
        pryzm_session=sid,
        authorization="Bearer test-token",
        token=None,
        db=db_session,
    )
    assert result.id == bob.id  # cookie wins
