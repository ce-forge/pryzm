"""Auth router: /api/auth/login."""
import pytest
from fastapi.testclient import TestClient

from core import cookie_auth
from db import database, models
from main import app


def _setup_user(db_session, username="alice", password="hunter2hunter2", is_active=True):
    u = models.User(
        username=username,
        password_hash=cookie_auth.hash_password(password),
        is_admin=False,
        is_active=is_active,
    )
    db_session.add(u)
    db_session.commit()
    return u


def _client(db_session, monkeypatch):
    monkeypatch.setattr("config.settings.PRYZM_API_TOKEN", "test-token")
    app.dependency_overrides[database.get_db] = lambda: db_session
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    cookie_auth.login_rate_limiter = cookie_auth.LoginRateLimiter()
    yield


def test_login_success_sets_cookie_and_returns_user(db_session, monkeypatch):
    u = _setup_user(db_session)
    try:
        c = _client(db_session, monkeypatch)
        r = c.post("/api/auth/login", json={"username": "alice", "password": "hunter2hunter2"})
        assert r.status_code == 200
        body = r.json()
        assert body["username"] == "alice"
        assert body["id"] == u.id
        assert body["is_admin"] is False
        assert cookie_auth.COOKIE_NAME in r.cookies
    finally:
        app.dependency_overrides.clear()


def test_login_wrong_password_returns_401(db_session, monkeypatch):
    _setup_user(db_session)
    try:
        c = _client(db_session, monkeypatch)
        r = c.post("/api/auth/login", json={"username": "alice", "password": "wrong"})
        assert r.status_code == 401
        assert cookie_auth.COOKIE_NAME not in r.cookies
    finally:
        app.dependency_overrides.clear()


def test_login_unknown_username_returns_401(db_session, monkeypatch):
    try:
        c = _client(db_session, monkeypatch)
        r = c.post("/api/auth/login", json={"username": "nobody", "password": "wrong"})
        assert r.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_login_deactivated_user_returns_401(db_session, monkeypatch):
    _setup_user(db_session, is_active=False)
    try:
        c = _client(db_session, monkeypatch)
        r = c.post("/api/auth/login", json={"username": "alice", "password": "hunter2hunter2"})
        assert r.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_login_case_insensitive_username(db_session, monkeypatch):
    _setup_user(db_session, username="Alice")
    try:
        c = _client(db_session, monkeypatch)
        r = c.post("/api/auth/login", json={"username": "ALICE", "password": "hunter2hunter2"})
        assert r.status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_login_locks_out_after_threshold(db_session, monkeypatch):
    _setup_user(db_session)
    try:
        c = _client(db_session, monkeypatch)
        for _ in range(cookie_auth.RATE_LIMIT_FAILURES):
            c.post("/api/auth/login", json={"username": "alice", "password": "wrong"})
        # Even correct password should now be rejected
        r = c.post("/api/auth/login", json={"username": "alice", "password": "hunter2hunter2"})
        assert r.status_code in (401, 429)
    finally:
        app.dependency_overrides.clear()


def test_logout_clears_cookie_and_session(db_session, monkeypatch):
    _setup_user(db_session)
    try:
        c = _client(db_session, monkeypatch)
        c.post("/api/auth/login", json={"username": "alice", "password": "hunter2hunter2"})
        # session row exists
        assert db_session.query(models.AuthSession).count() == 1

        r = c.post("/api/auth/logout")
        assert r.status_code == 200
        # session row deleted
        db_session.expire_all()
        assert db_session.query(models.AuthSession).count() == 0
        # cookie cleared (max-age=0 on the response sets it to expire)
        assert r.cookies.get(cookie_auth.COOKIE_NAME) in (None, "")
    finally:
        app.dependency_overrides.clear()


def test_logout_without_cookie_returns_200_idempotent(db_session, monkeypatch):
    try:
        c = _client(db_session, monkeypatch)
        r = c.post("/api/auth/logout")
        assert r.status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_me_returns_user_when_authenticated(db_session, monkeypatch):
    _setup_user(db_session)
    try:
        c = _client(db_session, monkeypatch)
        c.post("/api/auth/login", json={"username": "alice", "password": "hunter2hunter2"})
        r = c.get("/api/auth/me")
        assert r.status_code == 200
        body = r.json()
        assert body["username"] == "alice"
        assert body["is_admin"] is False
    finally:
        app.dependency_overrides.clear()


def test_me_returns_401_when_no_cookie(db_session, monkeypatch):
    try:
        c = _client(db_session, monkeypatch)
        r = c.get("/api/auth/me")
        assert r.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_me_returns_user_and_workspaces(db_session, monkeypatch):
    admin = models.User(
        username="admin",
        password_hash=cookie_auth.hash_password("admin-pw-12chars"),
        is_admin=True,
        is_active=True,
        can_create_workspaces=True,
    )
    db_session.add(admin); db_session.commit(); db_session.refresh(admin)

    ws = models.Workspace(
        slug="my-ws", display_name="My WS", system_prompt="",
        enabled_tools=[], engine_config={"backend": "llama_cpp"},
        user_id=admin.id, owner_can_edit=True, position=0,
    )
    db_session.add(ws); db_session.commit()

    sid = cookie_auth.create_session(db_session, admin.id)
    monkeypatch.setattr("config.settings.PRYZM_API_TOKEN", "test-token")
    app.dependency_overrides[database.get_db] = lambda: db_session
    try:
        c = TestClient(app)
        c.cookies.set(cookie_auth.COOKIE_NAME, sid)
        r = c.get("/api/auth/me")
        assert r.status_code == 200
        body = r.json()
        assert body["username"] == "admin"
        assert body["is_admin"] is True
        assert body["can_create_workspaces"] is True
        assert body["must_change_password"] in (True, False)
        assert len(body["workspaces"]) == 1
        assert body["workspaces"][0]["slug"] == "my-ws"
        assert body["workspaces"][0]["owner_can_edit"] is True
    finally:
        app.dependency_overrides.clear()
