"""HTTP-level smoke probes for Phase 2 auth + workspace boundary.

These exercise the full request path via FastAPI's TestClient. The unit tests
in tests/test_auth.py and tests/test_workspace_boundary.py are tighter; this
file confirms the wire protocol matches expectations.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from config import settings
from db import database, models
from main import app


@pytest.fixture
def client(db_at_head, monkeypatch):
    """TestClient with a known token, a migrated test DB, and DB dependency
    overridden to use the test engine so seeds inserted via db_session are
    visible to routes.
    """
    monkeypatch.setattr(settings, "PRYZM_API_TOKEN", "smoke-test-token")

    # Prevent the lifespan startup from running alembic against production DB.
    monkeypatch.setattr(database, "init_db", lambda: None)

    # Route the get_db dependency through the test engine.
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

    yield TestClient(app)

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
    monkeypatch.setattr(settings, "PRYZM_API_TOKEN", "smoke-test-token")
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
    try:
        yield TestClient(app), session
    finally:
        session.close()
        app.dependency_overrides.clear()


def _auth_headers(token: str = "smoke-test-token") -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_health_exempt_from_auth(client):
    """/health is the only route that doesn't require a token."""
    resp = client.get("/health")
    assert resp.status_code == 200


def test_route_without_token_401(client):
    resp = client.get("/workspaces")  # no Authorization header
    assert resp.status_code == 401


def test_route_with_wrong_token_401(client):
    resp = client.get("/workspaces", headers=_auth_headers("wrong"))
    assert resp.status_code == 401


def test_route_with_correct_token_passes_auth(client):
    """With the right token, the auth gate passes; downstream may still return
    other codes for unrelated reasons, but it must not 401."""
    resp = client.get("/workspaces", headers=_auth_headers())
    assert resp.status_code != 401


def test_reset_rejects_non_builtin_400(client_and_session):
    """POST /workspaces/{slug}/reset on a non-builtin workspace returns 400."""
    client, session = client_and_session
    ws = models.Workspace(
        id="non-builtin", slug="non-builtin", display_name="x",
        system_prompt="", enabled_tools=[], is_builtin=False,
        engine_config={"backend": "ollama", "model": "gemma4:e4b"},
    )
    session.add(ws)
    session.commit()
    resp = client.post(
        "/workspaces/non-builtin/reset", headers=_auth_headers(),
    )
    assert resp.status_code == 400


def test_message_edit_cross_workspace_404(client_and_session):
    """Editing a message via a workspace that doesn't own it returns 404."""
    client, session = client_and_session
    ws_a = models.Workspace(
        id="ws-a", slug="ws-a", display_name="A",
        system_prompt="", enabled_tools=[], is_builtin=False,
        engine_config={"backend": "ollama", "model": "gemma4:e4b"},
    )
    ws_b = models.Workspace(
        id="ws-b", slug="ws-b", display_name="B",
        system_prompt="", enabled_tools=[], is_builtin=False,
        engine_config={"backend": "ollama", "model": "gemma4:e4b"},
    )
    sess_a = models.Session(id="sess-a", workspace_id="ws-a", title="t")
    msg_a = models.Message(id="msg-a", session_id="sess-a", role="user", content="x")
    session.add_all([ws_a, ws_b, sess_a, msg_a])
    session.commit()

    # Edit msg-a while claiming workspace=ws-b → 404.
    resp = client.patch(
        "/messages/msg-a?workspace=ws-b",
        json={"content": "tampered"},
        headers=_auth_headers(),
    )
    assert resp.status_code == 404


def test_message_edit_missing_returns_404(client_and_session):
    """Editing a nonexistent message id returns 404 (not 500 or 422)."""
    client, session = client_and_session
    ws = models.Workspace(
        id="ws-x", slug="ws-x", display_name="X",
        system_prompt="", enabled_tools=[], is_builtin=False,
        engine_config={"backend": "ollama", "model": "gemma4:e4b"},
    )
    session.add(ws)
    session.commit()
    resp = client.patch(
        "/messages/nonexistent-id?workspace=ws-x",
        json={"content": "x"},
        headers=_auth_headers(),
    )
    assert resp.status_code == 404


def test_message_edit_missing_workspace_param_422(client):
    """PATCH /messages/:id without ?workspace= returns 422 (validation error)."""
    resp = client.patch(
        "/messages/anything",
        json={"content": "x"},
        headers=_auth_headers(),
    )
    assert resp.status_code == 422
