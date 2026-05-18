"""Admin users CRUD."""
import pytest
from fastapi.testclient import TestClient

from core import cookie_auth
from db import database, models
from main import app


def _setup_admin(db_session):
    admin = models.User(
        username="admin",
        password_hash=cookie_auth.hash_password("admin-pw-12chars"),
        is_admin=True,
        is_active=True,
        can_create_workspaces=True,
    )
    db_session.add(admin); db_session.commit(); db_session.refresh(admin)
    return admin


def _admin_client(db_session):
    admin = _setup_admin(db_session)
    sid = cookie_auth.create_session(db_session, admin.id)
    app.dependency_overrides[database.get_db] = lambda: db_session
    c = TestClient(app)
    c.cookies.set(cookie_auth.COOKIE_NAME, sid)
    return c, admin


def test_admin_list_users_returns_existing(db_session):
    try:
        c, admin = _admin_client(db_session)
        r = c.get("/api/admin/users")
        assert r.status_code == 200
        body = r.json()
        usernames = [u["username"] for u in body]
        assert "admin" in usernames
    finally:
        app.dependency_overrides.clear()


def test_admin_create_user_with_no_templates(db_session):
    try:
        c, _ = _admin_client(db_session)
        r = c.post("/api/admin/users", json={
            "username": "alice",
            "password": "alice-pw-12chars",
            "email": "alice@example.com",
            "is_admin": False,
            "can_create_workspaces": True,
            "starter_templates": [],
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["username"] == "alice"
        alice = db_session.query(models.User).filter_by(username="alice").one()
        assert alice.email == "alice@example.com"
        assert alice.can_create_workspaces is True
        # Admin chose the password, so user must change on first login.
        assert alice.must_change_password is True
    finally:
        app.dependency_overrides.clear()


def test_admin_password_reset_forces_change_on_next_login(db_session):
    try:
        c, _ = _admin_client(db_session)
        # Make a user with the flag already cleared (post-first-login state).
        u = models.User(
            username="bob",
            password_hash=cookie_auth.hash_password("bob-pw-12chars"),
            is_active=True,
            must_change_password=False,
        )
        db_session.add(u); db_session.commit(); db_session.refresh(u)

        r = c.post(
            f"/api/admin/users/{u.id}/password",
            json={"new_password": "fresh-pw-12chars"},
        )
        assert r.status_code == 200, r.text
        db_session.refresh(u)
        assert u.must_change_password is True
    finally:
        app.dependency_overrides.clear()


def test_admin_create_user_instantiates_starter_templates(db_session):
    try:
        c, _ = _admin_client(db_session)
        tmpl = models.WorkspaceTemplate(
            id="tmpl-x", slug="tmpl-x", display_name="X", system_prompt="x",
            enabled_tools=[],
            engine_config={"backend": "llama_cpp"},
        )
        db_session.add(tmpl); db_session.commit()

        r = c.post("/api/admin/users", json={
            "username": "bob",
            "password": "bob-pw-12chars",
            "starter_templates": [{"template_id": "tmpl-x", "owner_can_edit": True}],
        })
        assert r.status_code == 200, r.text
        bob = db_session.query(models.User).filter_by(username="bob").one()
        instances = db_session.query(models.Workspace).filter_by(
            user_id=bob.id, template_id="tmpl-x",
        ).all()
        assert len(instances) == 1
        assert instances[0].owner_can_edit is True
    finally:
        app.dependency_overrides.clear()


def test_admin_patch_user_changes_fields(db_session):
    try:
        c, _ = _admin_client(db_session)
        bob = models.User(username="bob", password_hash="x", is_admin=False, is_active=True)
        db_session.add(bob); db_session.commit(); db_session.refresh(bob)
        r = c.patch(f"/api/admin/users/{bob.id}", json={
            "email": "bob@example.com",
            "can_create_workspaces": True,
        })
        assert r.status_code == 200, r.text
        db_session.expire_all()
        bob = db_session.query(models.User).filter_by(id=bob.id).one()
        assert bob.email == "bob@example.com"
        assert bob.can_create_workspaces is True
    finally:
        app.dependency_overrides.clear()


def test_admin_password_reset_invalidates_sessions(db_session):
    try:
        c, _ = _admin_client(db_session)
        bob = models.User(
            username="bob",
            password_hash=cookie_auth.hash_password("old-pw-12chars"),
            is_admin=False, is_active=True,
        )
        db_session.add(bob); db_session.commit(); db_session.refresh(bob)
        bob_sid = cookie_auth.create_session(db_session, bob.id)
        assert db_session.query(models.AuthSession).filter_by(user_id=bob.id).count() == 1

        r = c.post(f"/api/admin/users/{bob.id}/password", json={"new_password": "new-pw-12chars"})
        assert r.status_code == 200

        db_session.expire_all()
        assert db_session.query(models.AuthSession).filter_by(user_id=bob.id).count() == 0
        from core.cookie_auth import verify_password
        bob = db_session.query(models.User).filter_by(id=bob.id).one()
        assert verify_password("new-pw-12chars", bob.password_hash)
    finally:
        app.dependency_overrides.clear()


def test_admin_cannot_demote_last_admin(db_session):
    try:
        c, admin = _admin_client(db_session)
        r = c.patch(f"/api/admin/users/{admin.id}", json={"is_admin": False})
        assert r.status_code == 400
        db_session.expire_all()
        admin = db_session.query(models.User).filter_by(id=admin.id).one()
        assert admin.is_admin is True
    finally:
        app.dependency_overrides.clear()


def test_admin_delete_soft_by_default(db_session):
    try:
        c, _ = _admin_client(db_session)
        bob = models.User(username="bob", password_hash="x", is_admin=False, is_active=True)
        db_session.add(bob); db_session.commit(); db_session.refresh(bob)
        r = c.delete(f"/api/admin/users/{bob.id}")
        assert r.status_code == 200
        db_session.expire_all()
        bob = db_session.query(models.User).filter_by(id=bob.id).one()
        assert bob.is_active is False
    finally:
        app.dependency_overrides.clear()


def test_admin_delete_hard_cascades(db_session):
    try:
        c, _ = _admin_client(db_session)
        bob = models.User(username="bob", password_hash="x", is_admin=False, is_active=True)
        db_session.add(bob); db_session.commit(); db_session.refresh(bob)
        r = c.delete(f"/api/admin/users/{bob.id}?hard=true")
        assert r.status_code == 200
        assert db_session.query(models.User).filter_by(id=bob.id).first() is None
    finally:
        app.dependency_overrides.clear()


def test_non_admin_cannot_call_admin_endpoints(db_session):
    try:
        non_admin = models.User(username="bob", password_hash="x", is_admin=False, is_active=True)
        db_session.add(non_admin); db_session.commit(); db_session.refresh(non_admin)
        sid = cookie_auth.create_session(db_session, non_admin.id)
        app.dependency_overrides[database.get_db] = lambda: db_session
        c = TestClient(app)
        c.cookies.set(cookie_auth.COOKIE_NAME, sid)
        r = c.get("/api/admin/users")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.clear()
