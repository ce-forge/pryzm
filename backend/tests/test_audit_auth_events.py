"""Auth router emits audit events at the right call sites."""
from fastapi.testclient import TestClient

from core import cookie_auth
from db import database, models
from main import app


def _seed_admin(db_session, password="admin-pw"):
    admin = models.User(
        username="admin",
        password_hash=cookie_auth.hash_password(password),
        is_admin=True,
        is_active=True,
    )
    db_session.add(admin); db_session.commit(); db_session.refresh(admin)
    return admin


def test_login_success_emits_event(db_session, monkeypatch):
    admin = _seed_admin(db_session)
    app.dependency_overrides[database.get_db] = lambda: db_session
    try:
        c = TestClient(app)
        r = c.post("/api/auth/login", json={"username": "admin", "password": "admin-pw"})
        assert r.status_code == 200
        events = db_session.query(models.AuditEvent).filter_by(
            event_type="auth.login_success", user_id=admin.id
        ).all()
        assert len(events) == 1
    finally:
        app.dependency_overrides.clear()


def test_login_failure_emits_event(db_session, monkeypatch):
    _seed_admin(db_session)
    app.dependency_overrides[database.get_db] = lambda: db_session
    try:
        c = TestClient(app)
        r = c.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
        assert r.status_code == 401
        events = db_session.query(models.AuditEvent).filter_by(
            event_type="auth.login_failure"
        ).all()
        assert len(events) == 1
        assert events[0].payload["username_attempted"] == "admin"
        assert events[0].payload["reason"] == "wrong_password"
    finally:
        app.dependency_overrides.clear()


def test_logout_emits_event(db_session, monkeypatch):
    admin = _seed_admin(db_session)
    sid = cookie_auth.create_session(db_session, admin.id)
    app.dependency_overrides[database.get_db] = lambda: db_session
    try:
        c = TestClient(app)
        c.cookies.set(cookie_auth.COOKIE_NAME, sid)
        r = c.post("/api/auth/logout")
        assert r.status_code == 200
        events = db_session.query(models.AuditEvent).filter_by(
            event_type="auth.logout", user_id=admin.id
        ).all()
        assert len(events) == 1
    finally:
        app.dependency_overrides.clear()


def test_password_change_emits_event(db_session, monkeypatch):
    # Voluntary password changes are 403'd now; the endpoint only allows
    # the forced-first-login flow. Set the flag so the path is reachable.
    admin = _seed_admin(db_session, password="old-pw")
    admin.must_change_password = True
    db_session.commit()
    sid = cookie_auth.create_session(db_session, admin.id)
    app.dependency_overrides[database.get_db] = lambda: db_session
    try:
        c = TestClient(app)
        c.cookies.set(cookie_auth.COOKIE_NAME, sid)
        r = c.post("/api/auth/password", json={
            "current_password": "old-pw",
            "new_password": "new-pw",
        })
        assert r.status_code == 200
        events = db_session.query(models.AuditEvent).filter_by(
            event_type="auth.password_changed", user_id=admin.id
        ).all()
        assert len(events) == 1
    finally:
        app.dependency_overrides.clear()
