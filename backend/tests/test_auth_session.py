"""AuthSession lifecycle helpers."""
import secrets
from datetime import datetime, timedelta, timezone

import pytest

from core import cookie_auth
from db import models


def _make_user(db_session, username="alice"):
    u = models.User(
        username=username,
        password_hash="dummy",
        is_admin=False,
        is_active=True,
    )
    db_session.add(u)
    db_session.commit()
    return u


def test_create_session_inserts_row_and_returns_id(db_session):
    u = _make_user(db_session)
    sid = cookie_auth.create_session(db_session, u.id)
    assert isinstance(sid, str) and len(sid) > 20  # base64url, ~43 chars
    row = db_session.query(models.AuthSession).filter_by(id=sid).one()
    assert row.user_id == u.id
    assert row.expires_at > datetime.now(timezone.utc)


def test_get_session_returns_user_when_valid(db_session):
    u = _make_user(db_session)
    sid = cookie_auth.create_session(db_session, u.id)
    user = cookie_auth.get_session_user(db_session, sid)
    assert user is not None
    assert user.id == u.id


def test_get_session_returns_none_for_unknown_sid(db_session):
    assert cookie_auth.get_session_user(db_session, "nonexistent") is None


def test_get_session_returns_none_for_expired(db_session):
    u = _make_user(db_session)
    sid = cookie_auth.create_session(db_session, u.id)
    # Force-expire
    row = db_session.query(models.AuthSession).filter_by(id=sid).one()
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()
    assert cookie_auth.get_session_user(db_session, sid) is None


def test_invalidate_session_removes_row(db_session):
    u = _make_user(db_session)
    sid = cookie_auth.create_session(db_session, u.id)
    cookie_auth.invalidate_session(db_session, sid)
    assert db_session.query(models.AuthSession).filter_by(id=sid).first() is None


def test_invalidate_user_sessions_removes_all_for_user(db_session):
    u = _make_user(db_session)
    sid_1 = cookie_auth.create_session(db_session, u.id)
    sid_2 = cookie_auth.create_session(db_session, u.id)
    cookie_auth.invalidate_user_sessions(db_session, u.id)
    assert db_session.query(models.AuthSession).filter_by(user_id=u.id).count() == 0


def test_get_session_updates_last_seen_at(db_session):
    u = _make_user(db_session)
    sid = cookie_auth.create_session(db_session, u.id)
    first_seen = db_session.query(models.AuthSession).filter_by(id=sid).one().last_seen_at
    # Re-fetch
    cookie_auth.get_session_user(db_session, sid)
    db_session.expire_all()
    second_seen = db_session.query(models.AuthSession).filter_by(id=sid).one().last_seen_at
    assert second_seen >= first_seen
