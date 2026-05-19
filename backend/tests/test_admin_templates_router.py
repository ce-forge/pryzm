"""Admin templates: CRUD, preview, apply (the unified push flow)."""
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


def test_list_templates(db_session):
    try:
        c, _ = _admin_client(db_session)
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


def test_create_template(db_session):
    try:
        c, _ = _admin_client(db_session)
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


def test_delete_template_nulls_template_id_on_instances(db_session):
    try:
        c, _ = _admin_client(db_session)
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


def test_preview_returns_three_row_states(db_session):
    """One user with a linked workspace, one with a slug-match unlinked
    workspace, one with no workspace at all → preview reports each state."""
    try:
        c, _ = _admin_client(db_session)
        t = models.WorkspaceTemplate(
            id="t-prev", slug="prev", display_name="Prev", system_prompt="TEMPLATE",
            enabled_tools=["get_local_time"], engine_config={"backend": "llama_cpp"},
            color="orange",
        )
        alice = models.User(username="alice", password_hash="x", is_admin=False, is_active=True)
        bob = models.User(username="bob", password_hash="x", is_admin=False, is_active=True)
        carol = models.User(username="carol", password_hash="x", is_admin=False, is_active=True)
        db_session.add_all([t, alice, bob, carol]); db_session.commit()
        db_session.refresh(alice); db_session.refresh(bob); db_session.refresh(carol)

        # Alice: linked + diverged (different system_prompt)
        db_session.add(models.Workspace(
            slug="prev", display_name="Prev", system_prompt="LOCAL",
            enabled_tools=["get_local_time"], template_id=t.id, user_id=alice.id,
            engine_config={"backend": "llama_cpp"}, color="orange",
        ))
        # Bob: slug-match unlinked
        db_session.add(models.Workspace(
            slug="prev", display_name="Prev", system_prompt="LEGACY",
            enabled_tools=[], template_id=None, user_id=bob.id,
            engine_config={"backend": "llama_cpp"},
        ))
        # Carol: no workspace
        db_session.commit()

        r = c.get("/api/admin/templates/t-prev/preview")
        assert r.status_code == 200, r.text
        by_user = {row["username"]: row for row in r.json()["rows"]}
        assert by_user["alice"]["state"] == "linked"
        assert "system_prompt" in by_user["alice"]["diff_fields"]
        assert by_user["bob"]["state"] == "slug_match_unlinked"
        assert by_user["carol"]["state"] == "none"
        assert by_user["carol"]["diff_fields"] == []
    finally:
        app.dependency_overrides.clear()


def test_apply_create_action_makes_workspace(db_session):
    try:
        c, _ = _admin_client(db_session)
        t = models.WorkspaceTemplate(
            id="t-cr", slug="cr", display_name="Cr", system_prompt="SP",
            enabled_tools=[], engine_config={"backend": "llama_cpp"}, color="orange",
        )
        bob = models.User(username="bob", password_hash="x", is_admin=False, is_active=True)
        db_session.add_all([t, bob]); db_session.commit(); db_session.refresh(bob)

        r = c.post("/api/admin/templates/t-cr/apply", json={
            "targets": [{"user_id": bob.id, "action": "create", "owner_can_edit": True}],
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body["outcomes"]) == 1
        assert body["outcomes"][0]["action"] == "create"
        ws = db_session.query(models.Workspace).filter_by(
            user_id=bob.id, template_id="t-cr",
        ).one()
        assert ws.system_prompt == "SP"
        assert ws.owner_can_edit is True
        assert ws.color == "orange"
    finally:
        app.dependency_overrides.clear()


def test_apply_create_rejects_when_workspace_with_slug_exists(db_session):
    """Create action is rejected (not crashed) when the user already has a
    workspace with the template's slug — the admin should adopt instead."""
    try:
        c, _ = _admin_client(db_session)
        t = models.WorkspaceTemplate(
            id="t-cr2", slug="cr2", display_name="Cr2", system_prompt="",
            enabled_tools=[], engine_config={"backend": "llama_cpp"},
        )
        bob = models.User(username="bob", password_hash="x", is_admin=False, is_active=True)
        db_session.add_all([t, bob]); db_session.commit(); db_session.refresh(bob)
        db_session.add(models.Workspace(
            slug="cr2", display_name="Cr2", system_prompt="LEGACY",
            enabled_tools=[], template_id=None, user_id=bob.id,
            engine_config={"backend": "llama_cpp"},
        ))
        db_session.commit()

        r = c.post("/api/admin/templates/t-cr2/apply", json={
            "targets": [{"user_id": bob.id, "action": "create"}],
        })
        assert r.status_code == 200
        body = r.json()
        assert body["outcomes"] == []
        assert body["rejections"][0]["reason"] == "workspace_with_slug_exists"
    finally:
        app.dependency_overrides.clear()


def test_apply_update_action_overwrites_linked_workspace(db_session):
    try:
        c, _ = _admin_client(db_session)
        t = models.WorkspaceTemplate(
            id="t-up", slug="up", display_name="Up", system_prompt="OLD",
            enabled_tools=["get_local_time"], engine_config={"backend": "llama_cpp"},
        )
        bob = models.User(username="bob", password_hash="x", is_admin=False, is_active=True)
        db_session.add_all([t, bob]); db_session.commit(); db_session.refresh(bob)
        db_session.add(models.Workspace(
            slug="up", display_name="Up", system_prompt="OLD",
            enabled_tools=["get_local_time"],
            template_id="t-up", user_id=bob.id, owner_can_edit=False,
            engine_config={"backend": "llama_cpp"},
        ))
        db_session.commit()

        c.put("/api/admin/templates/t-up", json={
            "system_prompt": "NEW", "enabled_tools": ["check_port"],
        })
        r = c.post("/api/admin/templates/t-up/apply", json={
            "targets": [{"user_id": bob.id, "action": "update"}],
        })
        assert r.status_code == 200, r.text
        db_session.expire_all()
        ws = db_session.query(models.Workspace).filter_by(
            user_id=bob.id, template_id="t-up",
        ).one()
        assert ws.system_prompt == "NEW"
        assert ws.enabled_tools == ["check_port"]
    finally:
        app.dependency_overrides.clear()


def test_apply_adopt_action_links_unlinked_workspace(db_session):
    """Adopt: take a slug-matched but unlinked workspace, set template_id,
    overwrite settings. This is the path the historical `it_copilot`
    workspaces will take once the admin pushes the template."""
    try:
        c, _ = _admin_client(db_session)
        t = models.WorkspaceTemplate(
            id="t-ad", slug="ad", display_name="Ad", system_prompt="TEMPLATE",
            enabled_tools=[], engine_config={"backend": "llama_cpp"}, color="orange",
        )
        bob = models.User(username="bob", password_hash="x", is_admin=False, is_active=True)
        db_session.add_all([t, bob]); db_session.commit(); db_session.refresh(bob)
        legacy = models.Workspace(
            slug="ad", display_name="Ad", system_prompt="LEGACY",
            enabled_tools=[], template_id=None, user_id=bob.id,
            engine_config={"backend": "llama_cpp"},
        )
        db_session.add(legacy); db_session.commit(); db_session.refresh(legacy)

        r = c.post("/api/admin/templates/t-ad/apply", json={
            "targets": [{"user_id": bob.id, "action": "adopt"}],
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["outcomes"][0]["action"] == "adopt"
        db_session.expire_all()
        ws = db_session.query(models.Workspace).filter_by(id=legacy.id).one()
        assert ws.template_id == "t-ad"
        assert ws.system_prompt == "TEMPLATE"
        assert ws.color == "orange"
    finally:
        app.dependency_overrides.clear()


def test_apply_adopt_rejects_when_already_linked(db_session):
    """Server re-checks state — if the preview the admin saw is stale and
    the workspace is now linked, the adopt action is rejected rather than
    silently overwriting an unrelated template's link."""
    try:
        c, _ = _admin_client(db_session)
        t = models.WorkspaceTemplate(
            id="t-ad2", slug="ad2", display_name="Ad2", system_prompt="",
            enabled_tools=[], engine_config={"backend": "llama_cpp"},
        )
        bob = models.User(username="bob", password_hash="x", is_admin=False, is_active=True)
        db_session.add_all([t, bob]); db_session.commit(); db_session.refresh(bob)
        # Already linked — adopt should refuse.
        db_session.add(models.Workspace(
            slug="ad2", display_name="Ad2", system_prompt="",
            enabled_tools=[], template_id="t-ad2", user_id=bob.id,
            engine_config={"backend": "llama_cpp"},
        ))
        db_session.commit()

        r = c.post("/api/admin/templates/t-ad2/apply", json={
            "targets": [{"user_id": bob.id, "action": "adopt"}],
        })
        assert r.status_code == 200
        body = r.json()
        assert body["outcomes"] == []
        assert body["rejections"][0]["reason"] == "no_slug_match_or_already_linked"
    finally:
        app.dependency_overrides.clear()


def test_apply_mixed_targets_in_one_call(db_session):
    """Single /apply with three distinct actions across three users."""
    try:
        c, _ = _admin_client(db_session)
        t = models.WorkspaceTemplate(
            id="t-mix", slug="mix", display_name="Mix", system_prompt="TPL",
            enabled_tools=[], engine_config={"backend": "llama_cpp"},
        )
        u_upd = models.User(username="u_upd", password_hash="x", is_admin=False, is_active=True)
        u_ado = models.User(username="u_ado", password_hash="x", is_admin=False, is_active=True)
        u_cre = models.User(username="u_cre", password_hash="x", is_admin=False, is_active=True)
        db_session.add_all([t, u_upd, u_ado, u_cre]); db_session.commit()
        db_session.refresh(u_upd); db_session.refresh(u_ado); db_session.refresh(u_cre)
        db_session.add(models.Workspace(
            slug="mix", display_name="Mix", system_prompt="OLD",
            enabled_tools=[], template_id="t-mix", user_id=u_upd.id,
            engine_config={"backend": "llama_cpp"},
        ))
        db_session.add(models.Workspace(
            slug="mix", display_name="Mix", system_prompt="LEGACY",
            enabled_tools=[], template_id=None, user_id=u_ado.id,
            engine_config={"backend": "llama_cpp"},
        ))
        db_session.commit()

        r = c.post("/api/admin/templates/t-mix/apply", json={
            "targets": [
                {"user_id": u_upd.id, "action": "update"},
                {"user_id": u_ado.id, "action": "adopt"},
                {"user_id": u_cre.id, "action": "create", "owner_can_edit": True},
            ],
        })
        assert r.status_code == 200, r.text
        body = r.json()
        actions = sorted(o["action"] for o in body["outcomes"])
        assert actions == ["adopt", "create", "update"]
        assert body["rejections"] == []
    finally:
        app.dependency_overrides.clear()
