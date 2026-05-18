"""Workspace position column + reorder endpoint + listing order."""
from fastapi.testclient import TestClient

from core import cookie_auth
from db import database, models
from main import app


def _seed_three(db_session):
    admin = models.User(
        username="admin", password_hash=cookie_auth.hash_password("admin-pw-12chars"),
        is_admin=True, is_active=True,
    )
    db_session.add(admin); db_session.commit(); db_session.refresh(admin)
    for i, slug in enumerate(["a", "b", "c"]):
        db_session.add(models.Workspace(
            slug=slug, display_name=slug.upper(), system_prompt="",
            enabled_tools=[], engine_config={"backend": "llama_cpp"},
            user_id=admin.id, position=i,
        ))
    db_session.commit()
    return admin


def test_list_workspaces_orders_by_position(db_session):
    admin = _seed_three(db_session)
    sid = cookie_auth.create_session(db_session, admin.id)
    app.dependency_overrides[database.get_db] = lambda: db_session
    try:
        c = TestClient(app)
        c.cookies.set(cookie_auth.COOKIE_NAME, sid)
        r = c.get("/workspaces")
        assert r.status_code == 200
        slugs = [w["slug"] for w in r.json()]
        assert slugs == ["a", "b", "c"]
    finally:
        app.dependency_overrides.clear()


def test_patch_position_moves_workspace_up(db_session):
    admin = _seed_three(db_session)
    sid = cookie_auth.create_session(db_session, admin.id)
    app.dependency_overrides[database.get_db] = lambda: db_session
    try:
        c = TestClient(app)
        c.cookies.set(cookie_auth.COOKIE_NAME, sid)
        # Move 'c' (position=2) to position=0
        r = c.patch("/workspaces/c/position", json={"position": 0})
        assert r.status_code == 200, r.text
        r = c.get("/workspaces")
        slugs = [w["slug"] for w in r.json()]
        assert slugs == ["c", "a", "b"]
    finally:
        app.dependency_overrides.clear()


def test_patch_position_moves_workspace_down(db_session):
    admin = _seed_three(db_session)
    sid = cookie_auth.create_session(db_session, admin.id)
    app.dependency_overrides[database.get_db] = lambda: db_session
    try:
        c = TestClient(app)
        c.cookies.set(cookie_auth.COOKIE_NAME, sid)
        # Move 'a' (position=0) to position=2
        r = c.patch("/workspaces/a/position", json={"position": 2})
        assert r.status_code == 200, r.text
        r = c.get("/workspaces")
        slugs = [w["slug"] for w in r.json()]
        assert slugs == ["b", "c", "a"]
    finally:
        app.dependency_overrides.clear()
