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
        # The cloner owns the source workspace — clone_from is now scoped
        # to the caller's own workspaces (S4). The test still asserts the
        # tool-cap clamp fires when the source carries tools the user
        # isn't allowed to have.
        try:
            capped = _seed_user(db_session, "carol", allowed_tools=["web_search"])
            source = models.Workspace(
                slug="src-clone-bad",
                display_name="Source",
                system_prompt="",
                enabled_tools=["execute_ping"],
                engine_config={"backend": "llama_cpp"},
                user_id=capped.id,
                owner_can_edit=True,
            )
            db_session.add(source); db_session.commit()

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
            capped = _seed_user(db_session, "dave", allowed_tools=["web_search"])
            source = models.Workspace(
                slug="src-clone-ok",
                display_name="Source",
                system_prompt="",
                enabled_tools=["web_search"],
                engine_config={"backend": "llama_cpp"},
                user_id=capped.id,
                owner_can_edit=True,
            )
            db_session.add(source); db_session.commit()

            c = _user_client(db_session, capped)
            r = c.post("/workspaces", json={
                "display_name": "copy ok",
                "clone_from": "src-clone-ok",
            })
            assert r.status_code in (200, 201), r.text
            assert r.json()["enabled_tools"] == ["web_search"]
        finally:
            app.dependency_overrides.clear()


class TestSlugScoping:
    """Slugs are not unique per-user — every user has their own
    `it_copilot` / `personal` / etc. PATCH and DELETE must scope their
    lookup to the caller's own workspace; without that, one user's
    request mutates whichever workspace the DB happens to return first.
    """

    def _make_ws(self, db_session, owner_id, slug, enabled_tools):
        ws = models.Workspace(
            slug=slug, display_name=slug, system_prompt="",
            enabled_tools=enabled_tools,
            engine_config={"backend": "llama_cpp"},
            user_id=owner_id, owner_can_edit=True,
        )
        db_session.add(ws); db_session.commit(); db_session.refresh(ws)
        return ws

    def test_patch_does_not_leak_across_users_with_same_slug(self, db_session):
        """Two users both own a workspace with slug 'it_copilot'.
        User A PATCHes their own; user B's record must be unchanged."""
        try:
            alice = _seed_user(db_session, "alice_slug")
            bob = _seed_user(db_session, "bob_slug")
            alice_ws = self._make_ws(db_session, alice.id, "it_copilot", ["dns_lookup"])
            bob_ws = self._make_ws(db_session, bob.id, "it_copilot", ["execute_ping"])

            c = _user_client(db_session, alice)
            r = c.patch("/workspaces/it_copilot", json={"enabled_tools": ["dns_lookup", "web_search"]})
            assert r.status_code == 200, r.text

            db_session.refresh(alice_ws)
            db_session.refresh(bob_ws)
            assert sorted(alice_ws.enabled_tools) == ["dns_lookup", "web_search"]
            assert bob_ws.enabled_tools == ["execute_ping"], (
                f"bob's workspace was mutated by alice's PATCH: {bob_ws.enabled_tools}"
            )
        finally:
            app.dependency_overrides.clear()

    def test_delete_does_not_remove_other_users_workspace_with_same_slug(self, db_session):
        """Without per-user scoping on the DELETE lookup, alice could
        delete bob's workspace by issuing DELETE /workspaces/it_copilot."""
        try:
            alice = _seed_user(db_session, "alice_del")
            bob = _seed_user(db_session, "bob_del")
            # Each user needs a second workspace so the last-workspace
            # guard doesn't intercept the delete.
            self._make_ws(db_session, alice.id, "it_copilot", [])
            self._make_ws(db_session, alice.id, "personal", [])
            bob_ws = self._make_ws(db_session, bob.id, "it_copilot", [])

            c = _user_client(db_session, alice)
            r = c.delete("/workspaces/it_copilot")
            assert r.status_code in (200, 204), r.text

            db_session.refresh(bob_ws)
            # Bob's record still exists with its original id.
            assert db_session.query(models.Workspace).filter_by(id=bob_ws.id).first() is not None
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# PATCH /workspaces/{slug} clamp + grandfathering
# ---------------------------------------------------------------------------

class TestPatchWorkspacesClamp:
    def _make_ws(self, db_session, owner_id, slug, enabled_tools):
        ws = models.Workspace(
            slug=slug,
            display_name=slug,
            system_prompt="",
            enabled_tools=enabled_tools,
            engine_config={"backend": "llama_cpp"},
            user_id=owner_id,
            owner_can_edit=True,
        )
        db_session.add(ws); db_session.commit(); db_session.refresh(ws)
        return ws

    def test_owner_can_patch_within_cap(self, db_session):
        try:
            u = _seed_user(db_session, "alice", allowed_tools=["web_search"])
            ws = self._make_ws(db_session, u.id, "alice-ws", [])
            c = _user_client(db_session, u)
            r = c.patch(f"/workspaces/{ws.slug}",
                json={"enabled_tools": ["web_search"]})
            assert r.status_code == 200, r.text
            assert r.json()["enabled_tools"] == ["web_search"]
        finally:
            app.dependency_overrides.clear()

    def test_owner_cannot_patch_to_disallowed(self, db_session):
        try:
            u = _seed_user(db_session, "bob", allowed_tools=["web_search"])
            ws = self._make_ws(db_session, u.id, "bob-ws", [])
            c = _user_client(db_session, u)
            r = c.patch(f"/workspaces/{ws.slug}",
                json={"enabled_tools": ["execute_ping"]})
            assert r.status_code == 400
            assert "execute_ping" in r.json()["detail"]
        finally:
            app.dependency_overrides.clear()

    def test_grandfathered_workspace_patch_other_field_succeeds(self, db_session):
        try:
            # Pre-existing workspace with execute_ping before the cap was set
            u = _seed_user(db_session, "carol", allowed_tools=["web_search"])
            ws = self._make_ws(db_session, u.id, "carol-ws", ["execute_ping"])
            c = _user_client(db_session, u)
            r = c.patch(f"/workspaces/{ws.slug}",
                json={"display_name": "Renamed"})
            assert r.status_code == 200, r.text
            assert r.json()["enabled_tools"] == ["execute_ping"]  # untouched
            assert r.json()["display_name"] == "Renamed"
        finally:
            app.dependency_overrides.clear()

    def test_grandfathered_workspace_patch_resending_disallowed_fails(self, db_session):
        try:
            u = _seed_user(db_session, "dave", allowed_tools=["web_search"])
            ws = self._make_ws(db_session, u.id, "dave-ws", ["execute_ping"])
            c = _user_client(db_session, u)
            # Re-sending the disallowed list — even though it's the current
            # stored value — should fail
            r = c.patch(f"/workspaces/{ws.slug}",
                json={"enabled_tools": ["execute_ping"]})
            assert r.status_code == 400
            assert "execute_ping" in r.json()["detail"]
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /admin/templates/{id}/apply — create action filter
# ---------------------------------------------------------------------------

class TestApplyCreateClamp:
    """The create action via /apply silently drops tools the target user
    isn't allowed to have, mirroring the push/update path. The modal
    surfaces this via the `dropped_tools` field on each outcome so admin
    sees what was filtered."""
    def _make_template(self, db_session, slug, enabled_tools):
        t = models.WorkspaceTemplate(
            slug=slug,
            display_name=slug,
            system_prompt="",
            enabled_tools=enabled_tools,
            engine_config={"backend": "llama_cpp"},
        )
        db_session.add(t); db_session.commit(); db_session.refresh(t)
        return t

    def _create(self, c, template_id, user_id):
        return c.post(f"/api/admin/templates/{template_id}/apply", json={
            "targets": [{"user_id": user_id, "action": "create", "owner_can_edit": False}],
        })

    def test_create_succeeds_with_no_drops_when_within_cap(self, db_session):
        try:
            c, _ = _admin_client(db_session)
            target = _seed_user(db_session, "alice", allowed_tools=["web_search"])
            t = self._make_template(db_session, "t1", ["web_search"])
            r = self._create(c, t.id, target.id)
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["outcomes"][0]["action"] == "create"
            assert body["outcomes"][0]["dropped_tools"] == []
        finally:
            app.dependency_overrides.clear()

    def test_create_drops_tools_when_template_exceeds_cap(self, db_session):
        try:
            c, _ = _admin_client(db_session)
            target = _seed_user(db_session, "bob", allowed_tools=["web_search"])
            t = self._make_template(db_session, "t2", ["web_search", "execute_ping"])
            r = self._create(c, t.id, target.id)
            assert r.status_code == 200, r.text
            outcome = r.json()["outcomes"][0]
            assert outcome["dropped_tools"] == ["execute_ping"]
            ws = db_session.query(models.Workspace).filter_by(id=outcome["workspace_id"]).one()
            assert ws.enabled_tools == ["web_search"]
        finally:
            app.dependency_overrides.clear()

    def test_create_for_admin_user_keeps_all_tools(self, db_session):
        try:
            c, _ = _admin_client(db_session)
            # Target user is also an admin → no cap applies
            target = models.User(
                username="carol",
                password_hash=cookie_auth.hash_password("carol-pw-12chars"),
                is_admin=True,
                is_active=True,
                allowed_tools=["web_search"],
            )
            db_session.add(target); db_session.commit(); db_session.refresh(target)
            t = self._make_template(db_session, "t3", ["web_search", "execute_ping"])
            r = self._create(c, t.id, target.id)
            assert r.status_code == 200, r.text
            outcome = r.json()["outcomes"][0]
            assert outcome["dropped_tools"] == []
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# PUT /admin/workspaces/{id} clamp
# ---------------------------------------------------------------------------

class TestAdminDirectEditClamp:
    def _make_ws(self, db_session, owner_id, slug, enabled_tools):
        ws = models.Workspace(
            slug=slug,
            display_name=slug,
            system_prompt="",
            enabled_tools=enabled_tools,
            engine_config={"backend": "llama_cpp"},
            user_id=owner_id,
            owner_can_edit=False,
        )
        db_session.add(ws); db_session.commit(); db_session.refresh(ws)
        return ws

    def test_admin_can_edit_within_recipient_cap(self, db_session):
        try:
            c, _ = _admin_client(db_session)
            target = _seed_user(db_session, "alice", allowed_tools=["web_search"])
            ws = self._make_ws(db_session, target.id, "alice-ws-1", [])
            r = c.put(f"/api/admin/workspaces/{ws.id}",
                json={"enabled_tools": ["web_search"]})
            assert r.status_code == 200, r.text
        finally:
            app.dependency_overrides.clear()

    def test_admin_cannot_edit_beyond_recipient_cap(self, db_session):
        try:
            c, _ = _admin_client(db_session)
            target = _seed_user(db_session, "bob", allowed_tools=["web_search"])
            ws = self._make_ws(db_session, target.id, "bob-ws-1", [])
            r = c.put(f"/api/admin/workspaces/{ws.id}",
                json={"enabled_tools": ["execute_ping"]})
            assert r.status_code == 400
            assert "execute_ping" in r.json()["detail"]
        finally:
            app.dependency_overrides.clear()

    def test_admin_can_edit_non_tool_fields_on_grandfathered(self, db_session):
        try:
            c, _ = _admin_client(db_session)
            target = _seed_user(db_session, "carol", allowed_tools=["web_search"])
            ws = self._make_ws(db_session, target.id, "carol-ws-1", ["execute_ping"])
            r = c.put(f"/api/admin/workspaces/{ws.id}",
                json={"owner_can_edit": True})
            assert r.status_code == 200, r.text
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /workspaces/{slug}/reset filter + new response shape
# ---------------------------------------------------------------------------

class TestResetFilter:
    def _make_template(self, db_session, slug, enabled_tools, system_prompt="prompt-x"):
        t = models.WorkspaceTemplate(
            slug=slug,
            display_name=slug,
            system_prompt=system_prompt,
            enabled_tools=enabled_tools,
            engine_config={"backend": "llama_cpp"},
        )
        db_session.add(t); db_session.commit(); db_session.refresh(t)
        return t

    def _make_instance(self, db_session, owner_id, slug, template_id, enabled_tools):
        ws = models.Workspace(
            slug=slug,
            display_name=slug,
            system_prompt="",
            enabled_tools=enabled_tools,
            engine_config={"backend": "llama_cpp"},
            user_id=owner_id,
            template_id=template_id,
            owner_can_edit=True,
        )
        db_session.add(ws); db_session.commit(); db_session.refresh(ws)
        return ws

    def test_reset_within_cap_no_dropped(self, db_session):
        try:
            u = _seed_user(db_session, "alice", allowed_tools=["web_search"])
            t = self._make_template(db_session, "t1", ["web_search"])
            ws = self._make_instance(db_session, u.id, "alice-ws", t.id, [])
            c = _user_client(db_session, u)
            r = c.post(f"/workspaces/{ws.slug}/reset")
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["dropped_tools"] == []
            assert body["workspace"]["enabled_tools"] == ["web_search"]
        finally:
            app.dependency_overrides.clear()

    def test_reset_filters_disallowed(self, db_session):
        try:
            u = _seed_user(db_session, "bob", allowed_tools=["web_search"])
            t = self._make_template(db_session, "t2", ["web_search", "execute_ping"])
            ws = self._make_instance(db_session, u.id, "bob-ws", t.id, [])
            c = _user_client(db_session, u)
            r = c.post(f"/workspaces/{ws.slug}/reset")
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["dropped_tools"] == ["execute_ping"]
            assert body["workspace"]["enabled_tools"] == ["web_search"]
            # other fields still propagated
            assert body["workspace"]["system_prompt"] == "prompt-x"
        finally:
            app.dependency_overrides.clear()

    def test_reset_admin_bypasses_filter(self, db_session):
        try:
            admin_user = models.User(
                username="adminish",
                password_hash=cookie_auth.hash_password("adminish-pw-12chars"),
                is_admin=True,
                is_active=True,
                allowed_tools=["web_search"],
            )
            db_session.add(admin_user); db_session.commit(); db_session.refresh(admin_user)
            t = self._make_template(db_session, "t3", ["web_search", "execute_ping"])
            ws = self._make_instance(db_session, admin_user.id, "adm-ws", t.id, [])
            c = _user_client(db_session, admin_user)
            r = c.post(f"/workspaces/{ws.slug}/reset")
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["dropped_tools"] == []
            assert sorted(body["workspace"]["enabled_tools"]) == sorted(["web_search", "execute_ping"])
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /admin/templates/{id}/apply — update action filter + audit
# ---------------------------------------------------------------------------

class TestApplyUpdateFilter:
    """Update action via /apply filters tools per-user and reports drops
    in each outcome. Aggregate audit event lists the filtered users."""
    def _make_template(self, db_session, slug, enabled_tools):
        t = models.WorkspaceTemplate(
            slug=slug,
            display_name=slug,
            system_prompt="",
            enabled_tools=enabled_tools,
            engine_config={"backend": "llama_cpp"},
        )
        db_session.add(t); db_session.commit(); db_session.refresh(t)
        return t

    def _make_instance(self, db_session, owner_id, slug, template_id, enabled_tools=None):
        ws = models.Workspace(
            slug=slug,
            display_name=slug,
            system_prompt="",
            enabled_tools=enabled_tools or [],
            engine_config={"backend": "llama_cpp"},
            user_id=owner_id,
            template_id=template_id,
            owner_can_edit=True,
        )
        db_session.add(ws); db_session.commit(); db_session.refresh(ws)
        return ws

    def _apply_update(self, c, template_id, user_ids):
        return c.post(f"/api/admin/templates/{template_id}/apply", json={
            "targets": [{"user_id": uid, "action": "update"} for uid in user_ids],
        })

    def test_apply_update_no_drops_when_users_uncapped(self, db_session):
        try:
            c, _ = _admin_client(db_session)
            t = self._make_template(db_session, "tp1", ["web_search", "execute_ping"])
            u = _seed_user(db_session, "alice")  # no cap
            self._make_instance(db_session, u.id, "alice-tp1", t.id)
            r = self._apply_update(c, t.id, [u.id])
            assert r.status_code == 200, r.text
            body = r.json()
            assert len(body["outcomes"]) == 1
            assert body["outcomes"][0]["dropped_tools"] == []
        finally:
            app.dependency_overrides.clear()

    def test_apply_update_drops_per_capped_user(self, db_session):
        try:
            c, _ = _admin_client(db_session)
            t = self._make_template(db_session, "tp2", ["web_search", "execute_ping"])
            u1 = _seed_user(db_session, "alice2")  # uncapped
            u2 = _seed_user(db_session, "bob2", allowed_tools=["web_search"])  # capped
            self._make_instance(db_session, u1.id, "a2-tp2", t.id)
            self._make_instance(db_session, u2.id, "b2-tp2", t.id)
            r = self._apply_update(c, t.id, [u1.id, u2.id])
            assert r.status_code == 200, r.text
            outcomes = r.json()["outcomes"]
            assert len(outcomes) == 2
            by_user = {o["user_id"]: o for o in outcomes}
            assert by_user[u1.id]["dropped_tools"] == []
            assert by_user[u2.id]["dropped_tools"] == ["execute_ping"]
        finally:
            app.dependency_overrides.clear()

    def test_apply_update_drops_persisted_to_workspace(self, db_session):
        try:
            c, _ = _admin_client(db_session)
            t = self._make_template(db_session, "tp3", ["web_search", "execute_ping"])
            u = _seed_user(db_session, "carol2", allowed_tools=["web_search"])
            ws = self._make_instance(db_session, u.id, "c2-tp3", t.id)
            self._apply_update(c, t.id, [u.id])
            db_session.refresh(ws)
            assert ws.enabled_tools == ["web_search"]
        finally:
            app.dependency_overrides.clear()

    def test_apply_update_audit_records_filtered(self, db_session):
        try:
            c, _ = _admin_client(db_session)
            t = self._make_template(db_session, "tp4", ["web_search", "execute_ping"])
            u = _seed_user(db_session, "dave2", allowed_tools=["web_search"])
            self._make_instance(db_session, u.id, "d2-tp4", t.id)
            self._apply_update(c, t.id, [u.id])
            ev = (
                db_session.query(models.AuditEvent)
                .filter(models.AuditEvent.event_type == "admin.template.pushed")
                .order_by(models.AuditEvent.created_at.desc())
                .first()
            )
            assert ev is not None
            payload = ev.payload
            assert payload["filtered"] == [
                {"user_id": u.id, "dropped_tools": ["execute_ping"]}
            ]
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# /api/tools is reachable by non-admin users
# Regression: settings_router was mounted with require_admin, breaking the
# user-facing workspace settings tool picker.
# ---------------------------------------------------------------------------

class TestToolsEndpointAccess:
    def test_non_admin_user_can_list_tools(self, db_session):
        try:
            u = _seed_user(db_session, "tools_reader")
            c = _user_client(db_session, u)
            r = c.get("/api/tools")
            assert r.status_code == 200, r.text
            body = r.json()
            assert isinstance(body, list)
            assert len(body) > 0
            assert all("name" in t and "description" in t for t in body)
        finally:
            app.dependency_overrides.clear()
