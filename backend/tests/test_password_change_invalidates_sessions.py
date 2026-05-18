"""POST /api/auth/password invalidates other sessions, keeps the current one."""
import pytest
from fastapi.testclient import TestClient

from core import cookie_auth
from db import database, models
from main import app


def _setup(db_session, monkeypatch):
    u = models.User(
        username="alice", password_hash=cookie_auth.hash_password("old-pw-12chars"),
        is_admin=False, is_active=True, must_change_password=True,
    )
    db_session.add(u); db_session.commit(); db_session.refresh(u)
    sid_current = cookie_auth.create_session(db_session, u.id)
    sid_other = cookie_auth.create_session(db_session, u.id)
    monkeypatch.setattr("config.settings.PRYZM_API_TOKEN", "test-token")
    app.dependency_overrides[database.get_db] = lambda: db_session
    c = TestClient(app)
    c.cookies.set(cookie_auth.COOKIE_NAME, sid_current)
    return c, u, sid_current, sid_other


def test_password_change_invalidates_other_sessions(db_session, monkeypatch):
    try:
        c, u, sid_current, sid_other = _setup(db_session, monkeypatch)
        assert db_session.query(models.AuthSession).filter_by(user_id=u.id).count() == 2

        r = c.post("/api/auth/password", json={
            "current_password": "old-pw-12chars",
            "new_password": "new-pw-12chars",
        })
        assert r.status_code == 200

        db_session.expire_all()
        remaining = {row.id for row in db_session.query(models.AuthSession).filter_by(user_id=u.id).all()}
        assert remaining == {sid_current}
        refreshed = db_session.query(models.User).filter_by(id=u.id).one()
        assert refreshed.must_change_password is False
    finally:
        app.dependency_overrides.clear()


def test_password_change_wrong_current_returns_401(db_session, monkeypatch):
    try:
        c, u, _, _ = _setup(db_session, monkeypatch)
        r = c.post("/api/auth/password", json={
            "current_password": "wrong",
            "new_password": "new-pw-12chars",
        })
        assert r.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_password_change_short_password_returns_400(db_session, monkeypatch):
    try:
        c, u, _, _ = _setup(db_session, monkeypatch)
        r = c.post("/api/auth/password", json={
            "current_password": "old-pw-12chars",
            "new_password": "abc",
        })
        assert r.status_code == 400
    finally:
        app.dependency_overrides.clear()
