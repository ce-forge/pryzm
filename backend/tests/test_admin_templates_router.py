"""Admin templates CRUD + push + instantiate."""
import pytest
from fastapi.testclient import TestClient

from core import cookie_auth
from db import database, models
from main import app


def _admin_client(db_session, monkeypatch):
    admin = models.User(
        username="admin", password_hash=cookie_auth.hash_password("admin-pw-12chars"),
        is_admin=True, is_active=True,
    )
    db_session.add(admin); db_session.commit(); db_session.refresh(admin)
    sid = cookie_auth.create_session(db_session, admin.id)
    monkeypatch.setattr("config.settings.PRYZM_API_TOKEN", "test-token")
    app.dependency_overrides[database.get_db] = lambda: db_session
    c = TestClient(app)
    c.cookies.set(cookie_auth.COOKIE_NAME, sid)
    return c, admin


def test_list_templates(db_session, monkeypatch):
    try:
        c, _ = _admin_client(db_session, monkeypatch)
        t = models.WorkspaceTemplate(
            id="t-1", slug="t-1", display_name="T1", system_prompt="",
            enabled_tools=[], engine_config={"backend": "llama_cpp"},
        )
        db_session.add(t); db_session.commit()
        r = c.get("/api/admin/templates")
        assert r.status_code == 200
        body = r.json()
        slugs = [b["slug"] for b in body]
        assert "t-1" in slugs
        # Non-templates do NOT show up
        admin = db_session.query(models.User).filter_by(username="admin").one()
        ws = models.Workspace(
            id="ws-1", slug="ws-1", display_name="W1", system_prompt="",
            enabled_tools=[], user_id=admin.id, engine_config={"backend": "llama_cpp"},
        )
        db_session.add(ws); db_session.commit()
        r = c.get("/api/admin/templates")
        slugs = [b["slug"] for b in r.json()]
        assert "ws-1" not in slugs
    finally:
        app.dependency_overrides.clear()


def test_create_template(db_session, monkeypatch):
    try:
        c, _ = _admin_client(db_session, monkeypatch)
        r = c.post("/api/admin/templates", json={
            "slug": "new-tmpl",
            "display_name": "New Template",
            "system_prompt": "You are helpful.",
            "enabled_tools": ["get_local_time"],
            "engine_config": {"backend": "llama_cpp"},
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["slug"] == "new-tmpl"
        t = db_session.query(models.WorkspaceTemplate).filter_by(slug="new-tmpl").one()
        assert t.display_name == "New Template"
    finally:
        app.dependency_overrides.clear()


def test_instantiate_template_for_user(db_session, monkeypatch):
    try:
        c, _ = _admin_client(db_session, monkeypatch)
        t = models.WorkspaceTemplate(
            id="t-instn", slug="t-instn", display_name="T", system_prompt="",
            enabled_tools=[], engine_config={"backend": "llama_cpp"},
        )
        bob = models.User(username="bob", password_hash="x", is_admin=False, is_active=True)
        db_session.add_all([t, bob]); db_session.commit(); db_session.refresh(bob)

        r = c.post(f"/api/admin/templates/t-instn/instantiate", json={
            "user_id": bob.id, "owner_can_edit": True,
        })
        assert r.status_code == 200, r.text
        instance = db_session.query(models.Workspace).filter_by(
            user_id=bob.id, template_id="t-instn",
        ).first()
        assert instance is not None
        assert instance.owner_can_edit is True
    finally:
        app.dependency_overrides.clear()


def test_instantiate_duplicate_blocks(db_session, monkeypatch):
    try:
        c, _ = _admin_client(db_session, monkeypatch)
        t = models.WorkspaceTemplate(
            id="t-dup", slug="t-dup", display_name="T", system_prompt="",
            enabled_tools=[], engine_config={"backend": "llama_cpp"},
        )
        bob = models.User(username="bob", password_hash="x", is_admin=False, is_active=True)
        db_session.add_all([t, bob]); db_session.commit(); db_session.refresh(bob)
        c.post("/api/admin/templates/t-dup/instantiate", json={"user_id": bob.id})
        r = c.post("/api/admin/templates/t-dup/instantiate", json={"user_id": bob.id})
        assert r.status_code in (400, 409)
    finally:
        app.dependency_overrides.clear()


def test_push_updates_all_instances(db_session, monkeypatch):
    try:
        c, _ = _admin_client(db_session, monkeypatch)
        t = models.WorkspaceTemplate(
            id="t-push", slug="t-push", display_name="T", system_prompt="OLD",
            enabled_tools=["get_local_time"], engine_config={"backend": "llama_cpp"},
        )
        bob = models.User(username="bob", password_hash="x", is_admin=False, is_active=True)
        db_session.add_all([t, bob]); db_session.commit(); db_session.refresh(bob)
        instance = models.Workspace(
            slug="t-push", display_name="T", system_prompt="OLD",
            enabled_tools=["get_local_time"],
            template_id="t-push", user_id=bob.id, owner_can_edit=False,
            engine_config={"backend": "llama_cpp"},
        )
        db_session.add(instance); db_session.commit()

        c.put("/api/admin/templates/t-push", json={
            "system_prompt": "NEW", "enabled_tools": ["check_port"],
        })
        r = c.post("/api/admin/templates/t-push/push")
        assert r.status_code == 200
        db_session.expire_all()
        instance = db_session.query(models.Workspace).filter_by(
            user_id=bob.id, template_id="t-push",
        ).one()
        assert instance.system_prompt == "NEW"
        assert instance.enabled_tools == ["check_port"]
    finally:
        app.dependency_overrides.clear()


def test_delete_template_nulls_template_id_on_instances(db_session, monkeypatch):
    try:
        c, _ = _admin_client(db_session, monkeypatch)
        t = models.WorkspaceTemplate(
            id="t-del", slug="t-del", display_name="T", system_prompt="",
            enabled_tools=[], engine_config={"backend": "llama_cpp"},
        )
        bob = models.User(username="bob", password_hash="x", is_admin=False, is_active=True)
        db_session.add_all([t, bob]); db_session.commit(); db_session.refresh(bob)
        instance = models.Workspace(
            slug="t-del", display_name="T", system_prompt="",
            enabled_tools=[],
            template_id="t-del", user_id=bob.id,
            engine_config={"backend": "llama_cpp"},
        )
        db_session.add(instance); db_session.commit(); db_session.refresh(instance)

        r = c.delete("/api/admin/templates/t-del")
        assert r.status_code == 200
        assert db_session.query(models.WorkspaceTemplate).filter_by(id="t-del").first() is None
        db_session.expire_all()
        instance = db_session.query(models.Workspace).filter_by(id=instance.id).one()
        assert instance.template_id is None
    finally:
        app.dependency_overrides.clear()
