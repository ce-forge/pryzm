"""Tests for per-user allowed_tools cap (spec: 2026-05-19-per-user-allowed-tools.md)."""
import pytest
from fastapi import HTTPException

from core import cookie_auth
from core.tool_permissions import enforce_allowed_tools, filter_allowed_tools
from db import models


def _user(allowed: list[str], is_admin: bool = False) -> models.User:
    u = models.User(
        username="x",
        password_hash="x",
        is_admin=is_admin,
        allowed_tools=allowed,
    )
    return u


class TestEnforceAllowedTools:
    def test_empty_cap_allows_anything(self):
        enforce_allowed_tools(_user([]), ["web_search", "code_run"])

    def test_non_empty_cap_allows_subset(self):
        enforce_allowed_tools(_user(["web_search"]), ["web_search"])

    def test_non_empty_cap_allows_empty_request(self):
        enforce_allowed_tools(_user(["web_search"]), [])

    def test_disallowed_tool_raises_400(self):
        with pytest.raises(HTTPException) as exc:
            enforce_allowed_tools(_user(["web_search"]), ["code_run"])
        assert exc.value.status_code == 400
        assert "code_run" in exc.value.detail

    def test_multiple_disallowed_listed_in_message(self):
        with pytest.raises(HTTPException) as exc:
            enforce_allowed_tools(_user(["web_search"]), ["code_run", "image_gen"])
        assert "code_run" in exc.value.detail
        assert "image_gen" in exc.value.detail

    def test_admin_bypasses_non_empty_cap(self):
        enforce_allowed_tools(_user(["web_search"], is_admin=True), ["code_run"])

    def test_admin_bypasses_with_empty_cap(self):
        enforce_allowed_tools(_user([], is_admin=True), ["code_run"])


class TestFilterAllowedTools:
    def test_empty_cap_keeps_everything(self):
        kept, dropped = filter_allowed_tools(_user([]), ["web_search", "code_run"])
        assert kept == ["web_search", "code_run"]
        assert dropped == []

    def test_non_empty_cap_filters(self):
        kept, dropped = filter_allowed_tools(_user(["web_search"]), ["web_search", "code_run"])
        assert kept == ["web_search"]
        assert dropped == ["code_run"]

    def test_admin_bypasses_cap(self):
        kept, dropped = filter_allowed_tools(_user(["web_search"], is_admin=True), ["code_run"])
        assert kept == ["code_run"]
        assert dropped == []

    def test_returns_lists_not_aliases(self):
        requested = ["web_search"]
        kept, _ = filter_allowed_tools(_user([]), requested)
        kept.append("mutated")
        assert requested == ["web_search"]


# ---------------------------------------------------------------------------
# Integration tests for admin users API + allowed_tools
# ---------------------------------------------------------------------------

from fastapi.testclient import TestClient

from main import app
from db import database


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


class TestAdminUsersAllowedTools:
    def test_create_user_with_allowed_tools(self, db_session):
        try:
            c, _ = _admin_client(db_session)
            r = c.post("/api/admin/users", json={
                "username": "alice",
                "password": "alice-pw-12chars",
                "allowed_tools": ["web_search"],
            })
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["allowed_tools"] == ["web_search"]
        finally:
            app.dependency_overrides.clear()

    def test_create_user_defaults_empty_allowed_tools(self, db_session):
        try:
            c, _ = _admin_client(db_session)
            r = c.post("/api/admin/users", json={
                "username": "bob",
                "password": "bob-pw-12chars",
            })
            assert r.status_code == 200
            assert r.json()["allowed_tools"] == []
        finally:
            app.dependency_overrides.clear()

    def test_list_users_exposes_allowed_tools(self, db_session):
        try:
            c, _ = _admin_client(db_session)
            carol = models.User(
                username="carol",
                password_hash=cookie_auth.hash_password("carol-pw-12chars"),
                allowed_tools=["web_search"],
            )
            db_session.add(carol); db_session.commit()
            r = c.get("/api/admin/users")
            assert r.status_code == 200
            row = next(u for u in r.json() if u["username"] == "carol")
            assert row["allowed_tools"] == ["web_search"]
        finally:
            app.dependency_overrides.clear()

    def test_patch_user_allowed_tools(self, db_session):
        try:
            c, _ = _admin_client(db_session)
            dave = models.User(
                username="dave",
                password_hash=cookie_auth.hash_password("dave-pw-12chars"),
            )
            db_session.add(dave); db_session.commit(); db_session.refresh(dave)
            r = c.patch(f"/api/admin/users/{dave.id}",
                json={"allowed_tools": ["web_search", "execute_ping"]})
            assert r.status_code == 200, r.text
            assert sorted(r.json()["allowed_tools"]) == sorted(["web_search", "execute_ping"])
        finally:
            app.dependency_overrides.clear()

    def test_patch_user_audit_records_allowed_tools_change(self, db_session):
        try:
            c, _ = _admin_client(db_session)
            erin = models.User(
                username="erin",
                password_hash=cookie_auth.hash_password("erin-pw-12chars"),
                allowed_tools=["web_search"],
            )
            db_session.add(erin); db_session.commit(); db_session.refresh(erin)
            c.patch(f"/api/admin/users/{erin.id}",
                json={"allowed_tools": ["execute_ping"]})
            ev = (
                db_session.query(models.AuditEvent)
                .filter(models.AuditEvent.event_type == "admin.user.edited")
                .order_by(models.AuditEvent.created_at.desc())
                .first()
            )
            assert ev is not None
            assert "allowed_tools" in ev.payload.get("changed_fields", [])
        finally:
            app.dependency_overrides.clear()

    def test_create_user_rejects_unknown_tool(self, db_session):
        try:
            c, _ = _admin_client(db_session)
            r = c.post("/api/admin/users", json={
                "username": "frank",
                "password": "frank-pw-12chars",
                "allowed_tools": ["definitely_not_a_real_tool"],
            })
            assert r.status_code == 400
            assert "definitely_not_a_real_tool" in r.json()["detail"]
        finally:
            app.dependency_overrides.clear()

    def test_patch_user_rejects_unknown_tool(self, db_session):
        try:
            c, _ = _admin_client(db_session)
            grace = models.User(
                username="grace",
                password_hash=cookie_auth.hash_password("grace-pw-12chars"),
            )
            db_session.add(grace); db_session.commit(); db_session.refresh(grace)
            r = c.patch(f"/api/admin/users/{grace.id}",
                json={"allowed_tools": ["definitely_not_a_real_tool"]})
            assert r.status_code == 400
            assert "definitely_not_a_real_tool" in r.json()["detail"]
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /workspaces clamp
# ---------------------------------------------------------------------------

def _seed_user(db_session, username, allowed_tools=None, can_create=True):
    u = models.User(
        username=username,
        password_hash=cookie_auth.hash_password(f"{username}-pw-12chars"),
        is_admin=False,
        is_active=True,
        can_create_workspaces=can_create,
        allowed_tools=allowed_tools or [],
    )
    db_session.add(u); db_session.commit(); db_session.refresh(u)
    return u


def _user_client(db_session, user):
    sid = cookie_auth.create_session(db_session, user.id)
    app.dependency_overrides[database.get_db] = lambda: db_session
    c = TestClient(app)
    c.cookies.set(cookie_auth.COOKIE_NAME, sid)
    return c


class TestPostWorkspacesClamp:
    def test_user_with_no_cap_creates_blank(self, db_session):
        try:
            u = _seed_user(db_session, "alice")
            c = _user_client(db_session, u)
            r = c.post("/workspaces", json={"display_name": "blank"})
            assert r.status_code in (200, 201), r.text
            assert r.json()["enabled_tools"] == []
        finally:
            app.dependency_overrides.clear()

    def test_capped_user_creates_blank(self, db_session):
        try:
            u = _seed_user(db_session, "bob", allowed_tools=["web_search"])
            c = _user_client(db_session, u)
            r = c.post("/workspaces", json={"display_name": "blank"})
            assert r.status_code in (200, 201)
            assert r.json()["enabled_tools"] == []
        finally:
            app.dependency_overrides.clear()

    def test_cloning_blocked_when_source_exceeds_cap(self, db_session):
        try:
            # Source workspace owned by someone else, has execute_ping
            owner = _seed_user(db_session, "owner")
            source = models.Workspace(
                slug="src-clone-bad",
                display_name="Source",
                system_prompt="",
                enabled_tools=["execute_ping"],
                engine_config={"backend": "llama_cpp"},
                user_id=owner.id,
                owner_can_edit=True,
            )
            db_session.add(source); db_session.commit()

            # Capped user clones it
            capped = _seed_user(db_session, "carol", allowed_tools=["web_search"])
            c = _user_client(db_session, capped)
            r = c.post("/workspaces", json={
                "display_name": "copy",
                "clone_from": "src-clone-bad",
            })
            assert r.status_code == 400
            assert "execute_ping" in r.json()["detail"]
        finally:
            app.dependency_overrides.clear()

    def test_cloning_succeeds_when_source_within_cap(self, db_session):
        try:
            owner = _seed_user(db_session, "owner2")
            source = models.Workspace(
                slug="src-clone-ok",
                display_name="Source",
                system_prompt="",
                enabled_tools=["web_search"],
                engine_config={"backend": "llama_cpp"},
                user_id=owner.id,
                owner_can_edit=True,
            )
            db_session.add(source); db_session.commit()

            capped = _seed_user(db_session, "dave", allowed_tools=["web_search"])
            c = _user_client(db_session, capped)
            r = c.post("/workspaces", json={
                "display_name": "copy ok",
                "clone_from": "src-clone-ok",
            })
            assert r.status_code in (200, 201), r.text
            assert r.json()["enabled_tools"] == ["web_search"]
        finally:
            app.dependency_overrides.clear()
