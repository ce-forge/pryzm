"""Admin routers emit audit events at the right call sites.

Covers admin.user.*, admin.template.*, admin.workspace.*, admin.system.*.
Same shape as tests/test_audit_auth_events.py.
"""
import pytest
from fastapi.testclient import TestClient

from core import cookie_auth
from core.prompt_manager import MICRO_PROMPTS
from db import database, models
from main import app
from routers import admin as admin_router


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_admin(db_session, username="admin", password="admin-pw-12chars"):
    admin = models.User(
        username=username,
        password_hash=cookie_auth.hash_password(password),
        is_admin=True,
        is_active=True,
        can_create_workspaces=True,
    )
    db_session.add(admin); db_session.commit(); db_session.refresh(admin)
    return admin


def _seed_user(db_session, username="bob", is_admin=False, is_active=True):
    u = models.User(
        username=username,
        password_hash=cookie_auth.hash_password("user-pw-12chars"),
        is_admin=is_admin,
        is_active=is_active,
    )
    db_session.add(u); db_session.commit(); db_session.refresh(u)
    return u


def _seed_template(db_session, slug="t-test", display_name="Test Template"):
    tmpl = models.WorkspaceTemplate(
        slug=slug,
        display_name=display_name,
        system_prompt="",
        enabled_tools=[],
        engine_config={"backend": "llama_cpp"},
    )
    db_session.add(tmpl); db_session.commit(); db_session.refresh(tmpl)
    return tmpl


def _seed_workspace(db_session, user_id, slug="ws-test", template_id=None):
    ws = models.Workspace(
        slug=slug,
        display_name=slug,
        system_prompt="",
        enabled_tools=[],
        engine_config={"backend": "llama_cpp"},
        user_id=user_id,
        template_id=template_id,
        owner_can_edit=True,
    )
    db_session.add(ws); db_session.commit(); db_session.refresh(ws)
    return ws


def _admin_client(db_session):
    admin = _seed_admin(db_session)
    sid = cookie_auth.create_session(db_session, admin.id)
    app.dependency_overrides[database.get_db] = lambda: db_session
    c = TestClient(app)
    c.cookies.set(cookie_auth.COOKIE_NAME, sid)
    return c, admin


# ---------------------------------------------------------------------------
# admin.user.*
# ---------------------------------------------------------------------------

def test_admin_user_created_emits_event(db_session):
    try:
        c, admin = _admin_client(db_session)
        r = c.post("/api/admin/users", json={
            "username": "newbie",
            "password": "newbie-pw-12chars",
            "is_admin": False,
            "can_create_workspaces": False,
            "starter_templates": [],
        })
        assert r.status_code in (200, 201), r.text
        events = db_session.query(models.AuditEvent).filter_by(
            event_type="admin.user.created", user_id=admin.id,
        ).all()
        assert len(events) == 1
        payload = events[0].payload
        assert payload["created_username"] == "newbie"
        assert payload["is_admin"] is False
        assert payload["can_create_workspaces"] is False
        assert payload["starter_template_ids"] == []
    finally:
        app.dependency_overrides.clear()


def test_admin_user_edited_emits_event(db_session):
    """A PATCH that only changes non-transition fields emits ONLY the base edited event."""
    try:
        c, admin = _admin_client(db_session)
        bob = _seed_user(db_session)
        r = c.patch(f"/api/admin/users/{bob.id}", json={
            "email": "bob@example.com",
            "can_create_workspaces": True,
        })
        assert r.status_code == 200, r.text

        edited = db_session.query(models.AuditEvent).filter_by(
            event_type="admin.user.edited", user_id=admin.id,
        ).all()
        assert len(edited) == 1
        payload = edited[0].payload
        assert payload["target_user_id"] == bob.id
        assert payload["target_username"] == "bob"
        assert set(payload["changed_fields"]) == {"email", "can_create_workspaces"}

        # No transition events fired
        for et in (
            "admin.user.activated", "admin.user.deactivated",
            "admin.user.promoted_to_admin", "admin.user.demoted_from_admin",
        ):
            assert db_session.query(models.AuditEvent).filter_by(event_type=et).count() == 0
    finally:
        app.dependency_overrides.clear()


def test_admin_user_activated_emits_event(db_session):
    try:
        c, admin = _admin_client(db_session)
        bob = _seed_user(db_session, is_active=False)
        r = c.patch(f"/api/admin/users/{bob.id}", json={"is_active": True})
        assert r.status_code == 200, r.text

        edited = db_session.query(models.AuditEvent).filter_by(
            event_type="admin.user.edited", user_id=admin.id,
        ).all()
        assert len(edited) == 1
        assert "is_active" in edited[0].payload["changed_fields"]

        activated = db_session.query(models.AuditEvent).filter_by(
            event_type="admin.user.activated", user_id=admin.id,
        ).all()
        assert len(activated) == 1
        assert activated[0].payload["target_user_id"] == bob.id
        assert activated[0].payload["target_username"] == "bob"
    finally:
        app.dependency_overrides.clear()


def test_admin_user_deactivated_emits_event(db_session):
    try:
        c, admin = _admin_client(db_session)
        bob = _seed_user(db_session, is_active=True)
        r = c.patch(f"/api/admin/users/{bob.id}", json={"is_active": False})
        assert r.status_code == 200, r.text

        edited = db_session.query(models.AuditEvent).filter_by(
            event_type="admin.user.edited", user_id=admin.id,
        ).all()
        assert len(edited) == 1
        assert "is_active" in edited[0].payload["changed_fields"]

        deactivated = db_session.query(models.AuditEvent).filter_by(
            event_type="admin.user.deactivated", user_id=admin.id,
        ).all()
        assert len(deactivated) == 1
        assert deactivated[0].payload["target_user_id"] == bob.id
    finally:
        app.dependency_overrides.clear()


def test_admin_user_promoted_to_admin_emits_event(db_session):
    try:
        c, admin = _admin_client(db_session)
        bob = _seed_user(db_session, is_admin=False)
        r = c.patch(f"/api/admin/users/{bob.id}", json={"is_admin": True})
        assert r.status_code == 200, r.text

        edited = db_session.query(models.AuditEvent).filter_by(
            event_type="admin.user.edited", user_id=admin.id,
        ).all()
        assert len(edited) == 1
        assert "is_admin" in edited[0].payload["changed_fields"]

        promoted = db_session.query(models.AuditEvent).filter_by(
            event_type="admin.user.promoted_to_admin", user_id=admin.id,
        ).all()
        assert len(promoted) == 1
        assert promoted[0].payload["target_user_id"] == bob.id
    finally:
        app.dependency_overrides.clear()


def test_admin_user_demoted_from_admin_emits_event(db_session):
    try:
        c, admin = _admin_client(db_session)
        # Need a second admin so demoting doesn't trip the last-admin guard
        bob = _seed_user(db_session, is_admin=True)
        r = c.patch(f"/api/admin/users/{bob.id}", json={"is_admin": False})
        assert r.status_code == 200, r.text

        edited = db_session.query(models.AuditEvent).filter_by(
            event_type="admin.user.edited", user_id=admin.id,
        ).all()
        assert len(edited) == 1
        assert "is_admin" in edited[0].payload["changed_fields"]

        demoted = db_session.query(models.AuditEvent).filter_by(
            event_type="admin.user.demoted_from_admin", user_id=admin.id,
        ).all()
        assert len(demoted) == 1
        assert demoted[0].payload["target_user_id"] == bob.id
    finally:
        app.dependency_overrides.clear()


def test_admin_user_password_reset_by_admin_emits_event(db_session):
    try:
        c, admin = _admin_client(db_session)
        bob = _seed_user(db_session)
        r = c.post(f"/api/admin/users/{bob.id}/password", json={
            "new_password": "new-pw-12chars",
        })
        assert r.status_code == 200, r.text

        events = db_session.query(models.AuditEvent).filter_by(
            event_type="auth.password_reset_by_admin", user_id=admin.id,
        ).all()
        assert len(events) == 1
        payload = events[0].payload
        assert payload["target_user_id"] == bob.id
        assert payload["target_username"] == "bob"
    finally:
        app.dependency_overrides.clear()


def test_admin_user_deleted_soft_emits_event(db_session):
    try:
        c, admin = _admin_client(db_session)
        bob = _seed_user(db_session)
        r = c.delete(f"/api/admin/users/{bob.id}")
        assert r.status_code == 200, r.text

        events = db_session.query(models.AuditEvent).filter_by(
            event_type="admin.user.deleted", user_id=admin.id,
        ).all()
        assert len(events) == 1
        payload = events[0].payload
        assert payload["deleted_user_id"] == bob.id
        assert payload["deleted_username"] == "bob"
        assert payload["is_hard"] is False
    finally:
        app.dependency_overrides.clear()


def test_admin_user_deleted_hard_emits_event(db_session):
    try:
        c, admin = _admin_client(db_session)
        bob = _seed_user(db_session)
        r = c.delete(f"/api/admin/users/{bob.id}?hard=true")
        assert r.status_code == 200, r.text

        events = db_session.query(models.AuditEvent).filter_by(
            event_type="admin.user.deleted", user_id=admin.id,
        ).all()
        assert len(events) == 1
        payload = events[0].payload
        assert payload["deleted_username"] == "bob"
        assert payload["is_hard"] is True
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# admin.template.*
# ---------------------------------------------------------------------------

def test_admin_template_created_emits_event(db_session):
    try:
        c, admin = _admin_client(db_session)
        r = c.post("/api/admin/templates", json={
            "slug": "new-tmpl",
            "display_name": "New Template",
            "system_prompt": "You are helpful.",
            "enabled_tools": [],
            "engine_config": {"backend": "llama_cpp"},
        })
        assert r.status_code == 200, r.text

        events = db_session.query(models.AuditEvent).filter_by(
            event_type="admin.template.created", user_id=admin.id,
        ).all()
        assert len(events) == 1
        payload = events[0].payload
        assert payload["slug"] == "new-tmpl"
        assert payload["display_name"] == "New Template"
        assert payload["template_id"]  # non-empty
    finally:
        app.dependency_overrides.clear()


def test_admin_template_edited_emits_event(db_session):
    try:
        c, admin = _admin_client(db_session)
        tmpl = _seed_template(db_session, slug="t-edit")
        r = c.put(f"/api/admin/templates/{tmpl.id}", json={
            "system_prompt": "NEW PROMPT",
            "display_name": "Renamed",
        })
        assert r.status_code == 200, r.text

        events = db_session.query(models.AuditEvent).filter_by(
            event_type="admin.template.edited", user_id=admin.id,
        ).all()
        assert len(events) == 1
        payload = events[0].payload
        assert payload["template_id"] == tmpl.id
        assert payload["slug"] == "t-edit"
        assert set(payload["changed_fields"]) == {"system_prompt", "display_name"}
    finally:
        app.dependency_overrides.clear()


def test_admin_template_deleted_emits_event(db_session):
    try:
        c, admin = _admin_client(db_session)
        bob = _seed_user(db_session)
        tmpl = _seed_template(db_session, slug="t-del")
        # Seed 2 instances of the template
        _seed_workspace(db_session, bob.id, slug="ws-del-1", template_id=tmpl.id)
        _seed_workspace(db_session, bob.id, slug="ws-del-2", template_id=tmpl.id)

        r = c.delete(f"/api/admin/templates/{tmpl.id}")
        assert r.status_code == 200, r.text

        events = db_session.query(models.AuditEvent).filter_by(
            event_type="admin.template.deleted", user_id=admin.id,
        ).all()
        assert len(events) == 1
        payload = events[0].payload
        assert payload["template_id"] == tmpl.id
        assert payload["slug"] == "t-del"
        assert payload["affected_instances"] == 2
    finally:
        app.dependency_overrides.clear()


def test_admin_template_instantiated_emits_event(db_session):
    """A `create` action via /apply emits one ADMIN_TEMPLATE_INSTANTIATED
    event per created workspace, matching the legacy /instantiate
    semantics so existing audit queries still work."""
    try:
        c, admin = _admin_client(db_session)
        bob = _seed_user(db_session)
        tmpl = _seed_template(db_session, slug="t-instn")

        r = c.post(f"/api/admin/templates/{tmpl.id}/apply", json={
            "targets": [{"user_id": bob.id, "action": "create", "owner_can_edit": True}],
        })
        assert r.status_code == 200, r.text

        events = db_session.query(models.AuditEvent).filter_by(
            event_type="admin.template.instantiated", user_id=admin.id,
        ).all()
        assert len(events) == 1
        payload = events[0].payload
        assert payload["template_id"] == tmpl.id
        assert payload["slug"] == "t-instn"
        assert payload["target_user_id"] == bob.id
        instance = db_session.query(models.Workspace).filter_by(
            user_id=bob.id, template_id=tmpl.id,
        ).one()
        assert payload["new_workspace_id"] == instance.id
    finally:
        app.dependency_overrides.clear()


def test_admin_template_pushed_emits_event(db_session):
    """`update` (and `adopt`) actions roll up into one
    ADMIN_TEMPLATE_PUSHED event per /apply call so the audit feed isn't
    flooded when admin pushes to many users at once."""
    try:
        c, admin = _admin_client(db_session)
        bob = _seed_user(db_session, username="bob")
        carol = _seed_user(db_session, username="carol")
        tmpl = _seed_template(db_session, slug="t-push")
        _seed_workspace(db_session, bob.id, slug="ws-push-bob", template_id=tmpl.id)
        _seed_workspace(db_session, carol.id, slug="ws-push-carol", template_id=tmpl.id)

        r = c.post(f"/api/admin/templates/{tmpl.id}/apply", json={
            "targets": [
                {"user_id": bob.id, "action": "update"},
                {"user_id": carol.id, "action": "update"},
            ],
        })
        assert r.status_code == 200, r.text

        events = db_session.query(models.AuditEvent).filter_by(
            event_type="admin.template.pushed", user_id=admin.id,
        ).all()
        assert len(events) == 1
        payload = events[0].payload
        assert payload["template_id"] == tmpl.id
        assert payload["affected_workspace_count"] == 2
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# admin.workspace.*
# ---------------------------------------------------------------------------

def test_admin_workspace_edited_emits_event(db_session):
    try:
        c, admin = _admin_client(db_session)
        bob = _seed_user(db_session)
        ws = _seed_workspace(db_session, bob.id, slug="ws-edit")

        r = c.put(f"/api/admin/workspaces/{ws.id}", json={
            "system_prompt": "NEW", "display_name": "Renamed",
        })
        assert r.status_code == 200, r.text

        events = db_session.query(models.AuditEvent).filter_by(
            event_type="admin.workspace.edited", user_id=admin.id,
        ).all()
        assert len(events) == 1
        payload = events[0].payload
        assert payload["workspace_id"] == ws.id
        assert payload["owner_user_id"] == bob.id
        assert payload["slug"] == "ws-edit"
        assert set(payload["changed_fields"]) == {"system_prompt", "display_name"}
    finally:
        app.dependency_overrides.clear()


def test_admin_workspace_deleted_emits_event(db_session):
    try:
        c, admin = _admin_client(db_session)
        bob = _seed_user(db_session)
        ws = _seed_workspace(db_session, bob.id, slug="ws-del")

        # Seed children: 2 sessions, 1 folder, 3 documents
        for i in range(2):
            db_session.add(models.Session(
                title=f"s{i}", workspace_id=ws.id, user_id=bob.id,
            ))
        db_session.add(models.Folder(name="f1", workspace_id=ws.id, user_id=bob.id))
        for i in range(3):
            db_session.add(models.Document(
                filename=f"d{i}.txt", workspace_id=ws.id,
            ))
        db_session.commit()

        r = c.delete(f"/api/admin/workspaces/{ws.id}")
        assert r.status_code == 200, r.text

        events = db_session.query(models.AuditEvent).filter_by(
            event_type="admin.workspace.deleted", user_id=admin.id,
        ).all()
        assert len(events) == 1
        payload = events[0].payload
        assert payload["workspace_id"] == ws.id
        assert payload["owner_user_id"] == bob.id
        assert payload["slug"] == "ws-del"
        assert payload["removed_session_count"] == 2
        assert payload["removed_folder_count"] == 1
        assert payload["removed_document_count"] == 3
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# admin.system.* — micro-prompts
# ---------------------------------------------------------------------------

def test_admin_system_micro_prompt_edited_via_patch_emits_event(db_session, monkeypatch):
    # Stub the file-write side effect; we only care the audit row appears.
    monkeypatch.setattr(MICRO_PROMPTS, "save_prompts", lambda payload: None)
    try:
        c, admin = _admin_client(db_session)
        r = c.patch("/api/prompts", json={"some_key": "some value"})
        assert r.status_code == 200, r.text

        events = db_session.query(models.AuditEvent).filter_by(
            event_type="admin.system.micro_prompt_edited", user_id=admin.id,
        ).all()
        assert len(events) == 1
        payload = events[0].payload
        assert payload["action"] == "edited"
        assert payload["keys_changed"] == ["some_key"]
    finally:
        app.dependency_overrides.clear()


def test_admin_system_micro_prompt_edited_via_delete_emits_event(db_session, monkeypatch):
    monkeypatch.setattr(MICRO_PROMPTS, "delete_prompt", lambda key: True)
    try:
        c, admin = _admin_client(db_session)
        r = c.delete("/api/prompts/some_key")
        assert r.status_code == 200, r.text

        events = db_session.query(models.AuditEvent).filter_by(
            event_type="admin.system.micro_prompt_edited", user_id=admin.id,
        ).all()
        assert len(events) == 1
        payload = events[0].payload
        assert payload["action"] == "deleted"
        assert payload["keys_changed"] == ["some_key"]
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# admin.system.* — models (write to llama-swap-config.yaml; isolate via tmp file)
# ---------------------------------------------------------------------------

_FIXTURE_YAML = """\
healthCheckTimeout: 3600
startPort: 9000

groups:
  "on-demand":
    swap: false
    exclusive: false
  "always-on":
    swap: false
    exclusive: false
    persistent: true

models:
  "gemma-4-E2B-it":
    cmd: >
      /app/llama-server --port ${PORT}
      -hf bartowski/google_gemma-4-E2B-it-GGUF:Q4_K_M
      -ngl 99 --ctx-size 8192 --jinja --flash-attn on
      --cache-type-k q8_0 --cache-type-v q8_0
    groups: ["on-demand"]
    tags: []

  "gemma-4-E4B-it":
    cmd: >
      /app/llama-server --port ${PORT}
      -hf bartowski/google_gemma-4-E4B-it-GGUF:Q4_K_M
      -ngl 99 --ctx-size 8192 --jinja --flash-attn on
      --cache-type-k q8_0 --cache-type-v q8_0
    groups: ["on-demand"]
    tags: []

  "nomic-embed-text-v1.5":
    cmd: >
      /app/llama-server --port ${PORT}
      -hf nomic-ai/nomic-embed-text-v1.5-GGUF:Q8_0
      -ngl 99 --embeddings --batch-size 8192
    groups: ["always-on"]
    tags: ["embedding"]
"""


@pytest.fixture
def model_admin_client(db_session, tmp_path, monkeypatch):
    """Mirrors tests/test_admin_models.py: temp yaml + stubbed sighup/warmup."""
    yaml_path = tmp_path / "llama-swap-config.yaml"
    yaml_path.write_text(_FIXTURE_YAML)
    monkeypatch.setattr(admin_router, "_YAML_PATH", yaml_path)
    monkeypatch.setattr(admin_router, "_reload_llama_swap", lambda: None)

    async def _stub_warmup(model_id: str) -> None:
        return None
    monkeypatch.setattr(admin_router, "_warmup_model", _stub_warmup)

    async def _stub_running() -> set[str]:
        return set()
    monkeypatch.setattr(admin_router, "_fetch_running_model_ids", _stub_running)

    admin = _seed_admin(db_session)
    sid = cookie_auth.create_session(db_session, admin.id)
    app.dependency_overrides[database.get_db] = lambda: db_session
    with TestClient(app) as c:
        c.cookies.set(cookie_auth.COOKIE_NAME, sid)
        yield c, admin
    app.dependency_overrides.clear()


def test_admin_system_model_added_emits_event(db_session, model_admin_client):
    c, admin = model_admin_client
    r = c.post("/api/admin/models", json={
        "id": "new-model-7b",
        "repo": "org/repo:Q4_K_M",
        "ngl": 50,
        "ctx_size": 4096,
        "group": "on-demand",
        "tags": ["code"],
    })
    assert r.status_code == 201, r.text

    events = db_session.query(models.AuditEvent).filter_by(
        event_type="admin.system.model_added", user_id=admin.id,
    ).all()
    assert len(events) == 1
    payload = events[0].payload
    assert payload["model_id"] == "new-model-7b"
    assert payload["repo"] == "org/repo:Q4_K_M"
    assert payload["ctx_size"] == 4096
    assert payload["ngl"] == 50
    assert payload["group"] == "on-demand"
    assert payload["tags"] == ["code"]
    assert payload["vision"] is False


def test_admin_system_model_edited_emits_event(db_session, model_admin_client):
    c, admin = model_admin_client
    r = c.put("/api/admin/models/gemma-4-E2B-it", json={
        "ngl": 50, "ctx_size": 4096,
    })
    assert r.status_code == 200, r.text

    events = db_session.query(models.AuditEvent).filter_by(
        event_type="admin.system.model_edited", user_id=admin.id,
    ).all()
    assert len(events) == 1
    payload = events[0].payload
    assert payload["model_id"] == "gemma-4-E2B-it"
    assert set(payload["changed_fields"]) == {"ngl", "ctx_size"}


def test_admin_system_model_removed_emits_event(db_session, model_admin_client):
    c, admin = model_admin_client
    # Add first so we have something deletable that won't trip the embedding guard.
    # The id needs a size hint (e.g. "3b") so the router's catalog rebuild accepts it.
    add = c.post("/api/admin/models", json={"id": "deletable-3b", "repo": "a/b:Q4"})
    assert add.status_code == 201, add.text

    r = c.delete("/api/admin/models/deletable-3b")
    assert r.status_code == 200, r.text

    events = db_session.query(models.AuditEvent).filter_by(
        event_type="admin.system.model_removed", user_id=admin.id,
    ).all()
    assert len(events) == 1
    assert events[0].payload["model_id"] == "deletable-3b"
