"""Admin workspace endpoints."""
import pytest
from fastapi.testclient import TestClient

from core import cookie_auth
from db import database, models
from main import app


def _admin_client(db_session):
    admin = models.User(
        username="admin", password_hash=cookie_auth.hash_password("admin-pw-12chars"),
        is_admin=True, is_active=True,
    )
    db_session.add(admin); db_session.commit(); db_session.refresh(admin)
    sid = cookie_auth.create_session(db_session, admin.id)
    app.dependency_overrides[database.get_db] = lambda: db_session
    c = TestClient(app)
    c.cookies.set(cookie_auth.COOKIE_NAME, sid)
    return c, admin


def test_list_users_workspaces(db_session):
    try:
        c, _ = _admin_client(db_session)
        bob = models.User(username="bob", password_hash="x", is_admin=False, is_active=True)
        db_session.add(bob); db_session.commit(); db_session.refresh(bob)
        for slug in ("ws-1", "ws-2"):
            db_session.add(models.Workspace(
                slug=slug, display_name=slug, system_prompt="",
                enabled_tools=[],
                user_id=bob.id, engine_config={"backend": "llama_cpp"},
            ))
        db_session.commit()
        r = c.get(f"/api/admin/users/{bob.id}/workspaces")
        assert r.status_code == 200
        body = r.json()
        assert len(body) == 2
    finally:
        app.dependency_overrides.clear()


def test_admin_edit_any_workspace_bypasses_owner_can_edit(db_session):
    try:
        c, _ = _admin_client(db_session)
        bob = models.User(username="bob", password_hash="x", is_admin=False, is_active=True)
        db_session.add(bob); db_session.commit(); db_session.refresh(bob)
        ws = models.Workspace(
            slug="ws-x", display_name="X", system_prompt="OLD",
            enabled_tools=[],
            user_id=bob.id, owner_can_edit=False,
            engine_config={"backend": "llama_cpp"},
        )
        db_session.add(ws); db_session.commit(); db_session.refresh(ws)

        r = c.put(f"/api/admin/workspaces/{ws.id}", json={"system_prompt": "NEW"})
        assert r.status_code == 200
        db_session.expire_all()
        ws = db_session.query(models.Workspace).filter_by(id=ws.id).one()
        assert ws.system_prompt == "NEW"
    finally:
        app.dependency_overrides.clear()


def test_admin_delete_user_workspace(db_session):
    try:
        c, _ = _admin_client(db_session)
        bob = models.User(username="bob", password_hash="x", is_admin=False, is_active=True)
        db_session.add(bob); db_session.commit(); db_session.refresh(bob)
        ws = models.Workspace(
            slug="ws-del", display_name="D", system_prompt="",
            enabled_tools=[],
            user_id=bob.id, engine_config={"backend": "llama_cpp"},
        )
        db_session.add(ws); db_session.commit(); db_session.refresh(ws)
        r = c.delete(f"/api/admin/workspaces/{ws.id}")
        assert r.status_code == 200
        assert db_session.query(models.Workspace).filter_by(id=ws.id).first() is None
    finally:
        app.dependency_overrides.clear()


def test_list_all_workspaces_with_owner_and_template_names(db_session):
    try:
        c, _ = _admin_client(db_session)
        bob = models.User(username="bob", password_hash="x", is_admin=False, is_active=True)
        db_session.add(bob); db_session.commit(); db_session.refresh(bob)
        tmpl = models.WorkspaceTemplate(
            slug="tmpl", display_name="My Template",
            system_prompt="", enabled_tools=[],
            engine_config={"backend": "llama_cpp"},
        )
        db_session.add(tmpl); db_session.commit(); db_session.refresh(tmpl)

        owned = models.Workspace(
            slug="owned", display_name="Owned", system_prompt="",
            enabled_tools=[], user_id=bob.id, template_id=tmpl.id,
            engine_config={"backend": "llama_cpp"},
        )
        orphan = models.Workspace(
            slug="orphan", display_name="Orphan", system_prompt="",
            enabled_tools=[], user_id=None, template_id=None,
            engine_config={"backend": "llama_cpp"},
        )
        db_session.add_all([owned, orphan])
        db_session.commit()

        r = c.get("/api/admin/workspaces")
        assert r.status_code == 200, r.text
        rows = {w["slug"]: w for w in r.json()}
        assert "owned" in rows and "orphan" in rows
        assert rows["owned"]["owner_username"] == "bob"
        assert rows["owned"]["template_display_name"] == "My Template"
        assert rows["orphan"]["owner_username"] is None
        assert rows["orphan"]["template_display_name"] is None
    finally:
        app.dependency_overrides.clear()


def test_list_workspaces_filters_orphaned(db_session):
    try:
        c, _ = _admin_client(db_session)
        bob = models.User(username="bob", password_hash="x", is_admin=False, is_active=True)
        db_session.add(bob); db_session.commit(); db_session.refresh(bob)
        db_session.add(models.Workspace(
            slug="o", display_name="O", system_prompt="",
            enabled_tools=[], user_id=bob.id,
            engine_config={"backend": "llama_cpp"},
        ))
        db_session.add(models.Workspace(
            slug="z", display_name="Z", system_prompt="",
            enabled_tools=[], user_id=None,
            engine_config={"backend": "llama_cpp"},
        ))
        db_session.commit()
        r = c.get("/api/admin/workspaces?orphaned=true")
        assert r.status_code == 200
        slugs = [w["slug"] for w in r.json()]
        assert slugs == ["z"]
    finally:
        app.dependency_overrides.clear()


def test_list_workspaces_filters_by_user(db_session):
    try:
        c, _ = _admin_client(db_session)
        bob = models.User(username="bob", password_hash="x", is_admin=False, is_active=True)
        carol = models.User(username="carol", password_hash="x", is_admin=False, is_active=True)
        db_session.add_all([bob, carol]); db_session.commit()
        db_session.refresh(bob); db_session.refresh(carol)
        db_session.add(models.Workspace(
            slug="b1", display_name="B", system_prompt="",
            enabled_tools=[], user_id=bob.id,
            engine_config={"backend": "llama_cpp"},
        ))
        db_session.add(models.Workspace(
            slug="c1", display_name="C", system_prompt="",
            enabled_tools=[], user_id=carol.id,
            engine_config={"backend": "llama_cpp"},
        ))
        db_session.commit()
        r = c.get(f"/api/admin/workspaces?user_id={bob.id}")
        assert r.status_code == 200
        slugs = [w["slug"] for w in r.json()]
        assert slugs == ["b1"]
    finally:
        app.dependency_overrides.clear()
