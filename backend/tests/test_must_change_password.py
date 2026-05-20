"""Server-side enforcement of must_change_password.

The flag was historically a UI hint only — `current_user` did not
consult it. A scripted client could bypass the forced-change screen
entirely. These tests pin the server-side behaviour: a user in the
must-change state hits 403 on every protected endpoint except the
narrow allowlist that lets them complete the password change.
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from core import cookie_auth
from db import database, models
from main import app


def _seed_user_in_must_change_state(db_session_factory, *, is_admin: bool = False):
    """Create a fresh user with must_change_password=True and an auth session."""
    with db_session_factory() as seed_db:
        user = models.User(
            username=f"mustchange-{is_admin}",
            password_hash=cookie_auth.hash_password("old-pw-12chars"),
            is_admin=is_admin,
            is_active=True,
            can_create_workspaces=True,
            must_change_password=True,
        )
        seed_db.add(user)
        seed_db.commit()
        seed_db.refresh(user)
        sid = cookie_auth.create_session(seed_db, user.id)
        return user.id, sid


def _mount(db_at_head, monkeypatch):
    TestSessionLocal = sessionmaker(bind=db_at_head, autocommit=False, autoflush=False)

    def _test_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(database, "init_db", lambda: None)
    monkeypatch.setattr(database, "SessionLocal", TestSessionLocal)
    app.dependency_overrides[database.get_db] = _test_get_db
    return TestSessionLocal


def test_must_change_blocks_workspaces_endpoint(db_at_head, monkeypatch):
    TestSessionLocal = _mount(db_at_head, monkeypatch)
    _, sid = _seed_user_in_must_change_state(TestSessionLocal)
    try:
        with TestClient(app) as c:
            c.cookies.set(cookie_auth.COOKIE_NAME, sid)
            resp = c.get("/workspaces")
        assert resp.status_code == 403, f"got {resp.status_code} body={resp.text[:200]}"
        assert "password" in resp.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()


def test_must_change_allows_password_endpoint(db_at_head, monkeypatch):
    """The forced-change flow itself must remain reachable."""
    TestSessionLocal = _mount(db_at_head, monkeypatch)
    _, sid = _seed_user_in_must_change_state(TestSessionLocal)
    try:
        with TestClient(app) as c:
            c.cookies.set(cookie_auth.COOKIE_NAME, sid)
            resp = c.post(
                "/api/auth/password",
                json={
                    "current_password": "old-pw-12chars",
                    "new_password": "new-pw-12chars",
                },
            )
        # 200 on success or 401/400 if something else fails — never 403,
        # which would mean the must-change guard incorrectly blocked the
        # very endpoint meant to clear it.
        assert resp.status_code != 403, f"got {resp.status_code} body={resp.text[:200]}"
    finally:
        app.dependency_overrides.clear()


def test_must_change_allows_me_endpoint(db_at_head, monkeypatch):
    """The /me endpoint must remain reachable so the UI can read the flag."""
    TestSessionLocal = _mount(db_at_head, monkeypatch)
    _, sid = _seed_user_in_must_change_state(TestSessionLocal)
    try:
        with TestClient(app) as c:
            c.cookies.set(cookie_auth.COOKIE_NAME, sid)
            resp = c.get("/api/auth/me")
        assert resp.status_code == 200
        assert resp.json()["must_change_password"] is True
    finally:
        app.dependency_overrides.clear()


def test_must_change_allows_logout(db_at_head, monkeypatch):
    """Logout must remain reachable so the user can bail out of the flow."""
    TestSessionLocal = _mount(db_at_head, monkeypatch)
    _, sid = _seed_user_in_must_change_state(TestSessionLocal)
    try:
        with TestClient(app) as c:
            c.cookies.set(cookie_auth.COOKIE_NAME, sid)
            resp = c.post("/api/auth/logout")
        assert resp.status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_must_change_blocks_admin_endpoints(db_at_head, monkeypatch):
    """An admin in must-change state is still locked out of admin APIs."""
    TestSessionLocal = _mount(db_at_head, monkeypatch)
    _, sid = _seed_user_in_must_change_state(TestSessionLocal, is_admin=True)
    try:
        with TestClient(app) as c:
            c.cookies.set(cookie_auth.COOKIE_NAME, sid)
            resp = c.get("/api/admin/users")
        assert resp.status_code == 403, f"got {resp.status_code} body={resp.text[:200]}"
    finally:
        app.dependency_overrides.clear()
