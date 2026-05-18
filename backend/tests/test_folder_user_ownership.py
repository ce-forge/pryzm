"""POST /folders inherits current_user.id."""
from fastapi.testclient import TestClient

from core import cookie_auth
from db import database, models
from main import app


def test_folder_create_assigns_user_id(db_session, monkeypatch):
    # Create a regular user (not admin)
    u = models.User(
        username="alice", password_hash=cookie_auth.hash_password("alice-pw-12chars"),
        is_admin=False, is_active=True, can_create_workspaces=True,
    )
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)

    # Create a workspace owned by the user
    ws = models.Workspace(
        slug="ws-folder", display_name="F", system_prompt="",
        enabled_tools=[],
        user_id=u.id, engine_config={"backend": "llama_cpp"},
    )
    db_session.add(ws)
    db_session.commit()
    db_session.refresh(ws)

    # Create a session cookie for the user
    sid = cookie_auth.create_session(db_session, u.id)

    monkeypatch.setattr("config.settings.PRYZM_API_TOKEN", "test-token")
    app.dependency_overrides[database.get_db] = lambda: db_session
    try:
        c = TestClient(app)
        # Set both cookie (for current_user) and bearer token (for router-level require_token)
        c.cookies.set(cookie_auth.COOKIE_NAME, sid)
        c.headers.update({"Authorization": "Bearer test-token"})
        r = c.post("/folders", json={"name": "Notes", "workspace": "ws-folder"})
        assert r.status_code == 200, r.text
        body = r.json()
        folder = db_session.query(models.Folder).filter_by(id=body["id"]).one()
        assert folder.user_id == u.id
    finally:
        app.dependency_overrides.clear()
