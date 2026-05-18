"""HTTP-level smoke probes for auth + workspace boundary.

Exercises the full request path via FastAPI's TestClient. The unit tests
in tests/test_auth.py and tests/test_workspace_boundary.py are tighter;
this file confirms the wire protocol matches expectations.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from core import cookie_auth
from core.cookie_auth import hash_password
from db import database, models
from main import app


SMOKE_ADMIN_ID = "u-smoke-admin"


def _seed_smoke_admin(seed_db) -> models.User:
    admin = seed_db.query(models.User).filter_by(id=SMOKE_ADMIN_ID).first()
    if admin is None:
        admin = models.User(
            id=SMOKE_ADMIN_ID,
            username="smoke-admin",
            password_hash=hash_password("test-pw-12chars"),
            is_admin=True, is_active=True, can_create_workspaces=True,
        )
        seed_db.add(admin)
        seed_db.commit()
        seed_db.refresh(admin)
    return admin


@pytest.fixture
def client(db_at_head, monkeypatch):
    """TestClient with an authenticated cookie, a migrated test DB, and DB
    dependency overridden to use the test engine so seeds inserted via
    db_session are visible to routes.
    """
    monkeypatch.setattr(database, "init_db", lambda: None)

    test_engine = db_at_head
    TestSessionLocal = sessionmaker(
        bind=test_engine, autocommit=False, autoflush=False,
    )

    def _test_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[database.get_db] = _test_get_db

    with TestSessionLocal() as seed_db:
        admin = _seed_smoke_admin(seed_db)
        sid = cookie_auth.create_session(seed_db, admin.id)

    c = TestClient(app)
    c.cookies.set(cookie_auth.COOKIE_NAME, sid)
    yield c

    app.dependency_overrides.clear()


@pytest.fixture
def client_and_session(db_at_head, monkeypatch):
    """TestClient + Session sharing a single SessionLocal.

    Tests that seed data with one session and then call HTTP routes need the
    TestClient's get_db dependency to open its session from the SAME
    SessionLocal — otherwise the test-side commit lands in a different
    connection's transaction view and the route handler sees no rows. The
    client fixture above can't do this because it doesn't expose a test-side
    session. This fixture yields both so they share the bind.
    """
    monkeypatch.setattr(database, "init_db", lambda: None)

    test_engine = db_at_head
    TestSessionLocal = sessionmaker(
        bind=test_engine, autocommit=False, autoflush=False,
    )

    def _test_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[database.get_db] = _test_get_db

    session = TestSessionLocal()
    admin = _seed_smoke_admin(session)
    sid = cookie_auth.create_session(session, admin.id)
    c = TestClient(app)
    c.cookies.set(cookie_auth.COOKIE_NAME, sid)
    try:
        yield c, session
    finally:
        session.close()
        app.dependency_overrides.clear()


def test_health_exempt_from_auth(client):
    """/health is the only route that doesn't require auth."""
    resp = client.get("/health")
    assert resp.status_code == 200


def test_route_without_cookie_401(client):
    client.cookies.clear()
    resp = client.get("/workspaces")
    assert resp.status_code == 401


def test_route_with_bad_cookie_401(client):
    client.cookies.set(cookie_auth.COOKIE_NAME, "not-a-real-session-id")
    resp = client.get("/workspaces")
    assert resp.status_code == 401


def test_route_with_valid_cookie_passes_auth(client):
    """With a valid session cookie, the auth gate passes; downstream may
    still return other codes for unrelated reasons, but it must not 401."""
    resp = client.get("/workspaces")
    assert resp.status_code != 401


def test_reset_rejects_non_builtin_400(client_and_session):
    """POST /workspaces/{slug}/reset on a non-builtin workspace returns 400."""
    client, session = client_and_session
    ws = models.Workspace(
        id="non-builtin", slug="non-builtin", display_name="x",
        system_prompt="", enabled_tools=[],
        engine_config={"backend": "ollama", "model": "gemma4:e4b"},
        user_id=SMOKE_ADMIN_ID,
    )
    session.add(ws)
    session.commit()
    resp = client.post("/workspaces/non-builtin/reset")
    assert resp.status_code == 400


def test_message_edit_cross_workspace_404(client_and_session):
    """Editing a message via a workspace that doesn't own it returns 404."""
    client, session = client_and_session
    ws_a = models.Workspace(
        id="ws-a", slug="ws-a", display_name="A",
        system_prompt="", enabled_tools=[],
        engine_config={"backend": "ollama", "model": "gemma4:e4b"},
        user_id=SMOKE_ADMIN_ID,
    )
    ws_b = models.Workspace(
        id="ws-b", slug="ws-b", display_name="B",
        system_prompt="", enabled_tools=[],
        engine_config={"backend": "ollama", "model": "gemma4:e4b"},
        user_id=SMOKE_ADMIN_ID,
    )
    sess_a = models.Session(
        id="sess-a", workspace_id="ws-a", title="t", user_id=SMOKE_ADMIN_ID,
    )
    msg_a = models.Message(id="msg-a", session_id="sess-a", role="user", content="x")
    session.add_all([ws_a, ws_b, sess_a, msg_a])
    session.commit()

    # Edit msg-a while claiming workspace=ws-b → 404.
    resp = client.patch(
        "/messages/msg-a?workspace=ws-b",
        json={"content": "tampered"},
    )
    assert resp.status_code == 404


def test_message_edit_missing_returns_404(client_and_session):
    """Editing a nonexistent message id returns 404 (not 500 or 422)."""
    client, session = client_and_session
    ws = models.Workspace(
        id="ws-x", slug="ws-x", display_name="X",
        system_prompt="", enabled_tools=[],
        engine_config={"backend": "ollama", "model": "gemma4:e4b"},
        user_id=SMOKE_ADMIN_ID,
    )
    session.add(ws)
    session.commit()
    resp = client.patch(
        "/messages/nonexistent-id?workspace=ws-x",
        json={"content": "x"},
    )
    assert resp.status_code == 404


def test_message_edit_missing_workspace_param_422(client):
    """PATCH /messages/:id without ?workspace= returns 422 (validation error)."""
    resp = client.patch(
        "/messages/anything",
        json={"content": "x"},
    )
    assert resp.status_code == 422
