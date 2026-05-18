"""POST /workspaces/{slug}/reset re-copies settings from template."""
from fastapi.testclient import TestClient

from core import cookie_auth
from db import database, models
from main import app


def test_reset_workspace_from_template(db_session, monkeypatch):
    admin = models.User(
        username="admin", password_hash=cookie_auth.hash_password("admin-pw-12chars"),
        is_admin=True, is_active=True,
    )
    db_session.add(admin); db_session.commit(); db_session.refresh(admin)
    tmpl = models.WorkspaceTemplate(
        id="t-1", slug="t-1", display_name="T", system_prompt="ORIGINAL",
        enabled_tools=["get_local_time"], engine_config={"backend": "llama_cpp"},
    )
    db_session.add(tmpl); db_session.commit()
    ws = models.Workspace(
        slug="t-1", display_name="T", system_prompt="EDITED",
        enabled_tools=[], engine_config={"backend": "llama_cpp"},
        user_id=admin.id, template_id="t-1", owner_can_edit=True,
    )
    db_session.add(ws); db_session.commit()

    sid = cookie_auth.create_session(db_session, admin.id)
    monkeypatch.setattr("config.settings.PRYZM_API_TOKEN", "test-token")
    app.dependency_overrides[database.get_db] = lambda: db_session
    try:
        c = TestClient(app)
        c.cookies.set(cookie_auth.COOKIE_NAME, sid)
        c.headers.update({"Authorization": "Bearer test-token"})
        r = c.post("/workspaces/t-1/reset")
        assert r.status_code == 200, r.text
        db_session.expire_all()
        refreshed = db_session.query(models.Workspace).filter_by(slug="t-1", user_id=admin.id).one()
        assert refreshed.system_prompt == "ORIGINAL"
        assert refreshed.enabled_tools == ["get_local_time"]
    finally:
        app.dependency_overrides.clear()


def test_reset_workspace_without_template_returns_400(db_session, monkeypatch):
    admin = models.User(
        username="admin", password_hash=cookie_auth.hash_password("admin-pw-12chars"),
        is_admin=True, is_active=True,
    )
    db_session.add(admin); db_session.commit(); db_session.refresh(admin)
    ws = models.Workspace(
        slug="orphan", display_name="O", system_prompt="x",
        enabled_tools=[], engine_config={"backend": "llama_cpp"},
        user_id=admin.id, template_id=None,
    )
    db_session.add(ws); db_session.commit()

    sid = cookie_auth.create_session(db_session, admin.id)
    monkeypatch.setattr("config.settings.PRYZM_API_TOKEN", "test-token")
    app.dependency_overrides[database.get_db] = lambda: db_session
    try:
        c = TestClient(app)
        c.cookies.set(cookie_auth.COOKIE_NAME, sid)
        c.headers.update({"Authorization": "Bearer test-token"})
        r = c.post("/workspaces/orphan/reset")
        assert r.status_code == 400
    finally:
        app.dependency_overrides.clear()
