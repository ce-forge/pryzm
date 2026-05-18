"""Workspace, folder, and document routers emit audit events at the right call sites.

Covers workspace.*, folder.*, and document.*.
Same shape as tests/test_audit_admin_events.py.
"""
from fastapi.testclient import TestClient

from core import cookie_auth
from db import database, models
from main import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_user(db_session, username="alice", can_create=True):
    u = models.User(
        username=username,
        password_hash=cookie_auth.hash_password("alice-pw-12chars"),
        is_admin=False,
        is_active=True,
        can_create_workspaces=can_create,
    )
    db_session.add(u); db_session.commit(); db_session.refresh(u)
    return u


def _seed_workspace(db_session, user_id, slug="ws-test"):
    ws = models.Workspace(
        slug=slug,
        display_name=slug,
        system_prompt="initial prompt",
        enabled_tools=[],
        engine_config={"backend": "llama_cpp"},
        color="blue",
        user_id=user_id,
        owner_can_edit=True,
    )
    db_session.add(ws); db_session.commit(); db_session.refresh(ws)
    return ws


def _user_client(db_session, user=None):
    u = user or _seed_user(db_session)
    sid = cookie_auth.create_session(db_session, u.id)
    app.dependency_overrides[database.get_db] = lambda: db_session
    c = TestClient(app)
    c.cookies.set(cookie_auth.COOKIE_NAME, sid)
    return c, u


# ---------------------------------------------------------------------------
# workspace.*
# ---------------------------------------------------------------------------

def test_workspace_created_emits_event(db_session):
    try:
        c, user = _user_client(db_session)
        r = c.post("/workspaces", json={
            "display_name": "Test WS",
            "color": "orange",
        })
        assert r.status_code in (200, 201), r.text
        events = db_session.query(models.AuditEvent).filter_by(
            event_type="workspace.created", user_id=user.id,
        ).all()
        assert len(events) == 1
        payload = events[0].payload
        assert payload["display_name"] == "Test WS"
        assert payload["color"] == "orange"
        assert payload["cloned_from_slug"] is None
        assert events[0].workspace_id is not None

        # Sanity: created workspace is tied to the creator and is therefore
        # visible to them via GET /workspaces.
        created = db_session.query(models.Workspace).filter_by(
            id=events[0].workspace_id
        ).first()
        assert created.user_id == user.id

        list_r = c.get("/workspaces")
        assert list_r.status_code == 200, list_r.text
        slugs = [w["slug"] for w in list_r.json()]
        assert created.slug in slugs
    finally:
        app.dependency_overrides.clear()


def test_create_workspace_rejects_duplicate_display_name_per_user(db_session):
    try:
        c, user = _user_client(db_session)
        first = c.post("/workspaces", json={"display_name": "Project X"})
        assert first.status_code in (200, 201), first.text

        dup = c.post("/workspaces", json={"display_name": "Project X"})
        assert dup.status_code == 409, dup.text
        assert "already" in dup.json()["detail"].lower()

        # No second audit event for the rejected create.
        events = db_session.query(models.AuditEvent).filter_by(
            event_type="workspace.created", user_id=user.id,
        ).all()
        assert len(events) == 1
    finally:
        app.dependency_overrides.clear()


def test_workspace_edited_emits_event_only_for_changes(db_session):
    try:
        c, user = _user_client(db_session)
        ws = _seed_workspace(db_session, user.id)
        r = c.patch(f"/workspaces/{ws.slug}", json={
            "display_name": "Renamed",
            "color": "blue",  # same as initial — should NOT appear in changed_fields
        })
        assert r.status_code == 200, r.text

        events = db_session.query(models.AuditEvent).filter_by(
            event_type="workspace.edited", user_id=user.id,
        ).all()
        assert len(events) == 1
        payload = events[0].payload
        assert payload["changed_fields"] == ["display_name"]
        assert payload["previous_values"]["display_name"] == "ws-test"
        assert payload["new_values"]["display_name"] == "Renamed"
    finally:
        app.dependency_overrides.clear()


def test_workspace_edited_no_event_when_nothing_changed(db_session):
    try:
        c, user = _user_client(db_session)
        ws = _seed_workspace(db_session, user.id)
        r = c.patch(f"/workspaces/{ws.slug}", json={
            "display_name": "ws-test",  # same as current
        })
        assert r.status_code == 200, r.text
        assert db_session.query(models.AuditEvent).filter_by(
            event_type="workspace.edited",
        ).count() == 0
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# folder.*
# ---------------------------------------------------------------------------

def test_folder_created_emits_event(db_session):
    try:
        c, user = _user_client(db_session)
        ws = _seed_workspace(db_session, user.id)
        r = c.post("/folders", json={"name": "Reports", "workspace": ws.slug})
        assert r.status_code == 200, r.text

        events = db_session.query(models.AuditEvent).filter_by(
            event_type="folder.created", user_id=user.id,
        ).all()
        assert len(events) == 1
        payload = events[0].payload
        assert payload["name"] == "Reports"
        assert events[0].workspace_id == ws.id
        assert events[0].resource_type == "folder"
    finally:
        app.dependency_overrides.clear()


def test_folder_edited_emits_event(db_session):
    try:
        c, user = _user_client(db_session)
        ws = _seed_workspace(db_session, user.id)
        folder = models.Folder(name="Old", workspace_id=ws.id, user_id=user.id)
        db_session.add(folder); db_session.commit(); db_session.refresh(folder)

        r = c.patch(f"/folders/{folder.id}?workspace={ws.slug}", json={"name": "New"})
        assert r.status_code == 200, r.text

        events = db_session.query(models.AuditEvent).filter_by(
            event_type="folder.edited", user_id=user.id,
        ).all()
        assert len(events) == 1
        payload = events[0].payload
        assert payload["previous_name"] == "Old"
        assert payload["new_name"] == "New"
    finally:
        app.dependency_overrides.clear()


def test_folder_edited_no_event_when_name_unchanged(db_session):
    try:
        c, user = _user_client(db_session)
        ws = _seed_workspace(db_session, user.id)
        folder = models.Folder(name="Same", workspace_id=ws.id, user_id=user.id)
        db_session.add(folder); db_session.commit(); db_session.refresh(folder)

        r = c.patch(f"/folders/{folder.id}?workspace={ws.slug}", json={"name": "Same"})
        assert r.status_code == 200, r.text

        assert db_session.query(models.AuditEvent).filter_by(
            event_type="folder.edited",
        ).count() == 0
    finally:
        app.dependency_overrides.clear()


def test_folder_deleted_emits_event(db_session):
    try:
        c, user = _user_client(db_session)
        ws = _seed_workspace(db_session, user.id)
        folder = models.Folder(name="ToDelete", workspace_id=ws.id, user_id=user.id)
        db_session.add(folder); db_session.commit(); db_session.refresh(folder)
        folder_id = folder.id

        r = c.delete(f"/folders/{folder_id}?workspace={ws.slug}")
        assert r.status_code == 200, r.text

        events = db_session.query(models.AuditEvent).filter_by(
            event_type="folder.deleted", user_id=user.id,
        ).all()
        assert len(events) == 1
        payload = events[0].payload
        assert payload["folder_id"] == folder_id
        assert payload["name"] == "ToDelete"
        assert payload["orphaned_session_count"] == 0
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# document.*
# ---------------------------------------------------------------------------

def test_document_uploaded_emits_event(db_session, monkeypatch):
    """Upload a tiny text doc and verify the event row.

    Stubs the ingest broker's add_task so the background pipeline never
    runs in the test process — we only care that the synchronous upload
    handler emits the audit event before scheduling. Also overrides
    `get_http_client` since TestClient skips lifespan startup by default
    (so `app.state.http_client` isn't set), and the upload handler still
    declares it as a dependency.
    """
    from core.deps import get_http_client
    from services import ingest_broker
    monkeypatch.setattr(ingest_broker, "add_task", lambda _coro: None)

    try:
        c, user = _user_client(db_session)
        app.dependency_overrides[get_http_client] = lambda: None
        ws = _seed_workspace(db_session, user.id)

        files = {"file": ("notes.txt", b"hello world", "text/plain")}
        data = {"workspace": ws.slug, "is_global": "false"}
        r = c.post("/upload", files=files, data=data)
        assert r.status_code == 202, r.text

        events = db_session.query(models.AuditEvent).filter_by(
            event_type="document.uploaded", user_id=user.id,
        ).all()
        assert len(events) == 1
        payload = events[0].payload
        assert payload["filename"] == "notes.txt"
        assert payload["mime"] == "text/plain"
        assert payload["size_bytes"] == 11
        assert payload["is_global"] is False
        assert events[0].workspace_id == ws.id
    finally:
        app.dependency_overrides.clear()


def test_document_deleted_emits_event(db_session):
    try:
        c, user = _user_client(db_session)
        ws = _seed_workspace(db_session, user.id)
        doc = models.Document(
            filename="goodbye.txt",
            workspace_id=ws.id,
            is_global=False,
            status="ready",
        )
        db_session.add(doc); db_session.commit(); db_session.refresh(doc)
        doc_id = doc.id

        r = c.delete(f"/documents/{doc_id}?workspace={ws.slug}")
        assert r.status_code == 200, r.text

        events = db_session.query(models.AuditEvent).filter_by(
            event_type="document.deleted", user_id=user.id,
        ).all()
        assert len(events) == 1
        payload = events[0].payload
        assert payload["document_id"] == doc_id
        assert payload["filename"] == "goodbye.txt"
        assert events[0].workspace_id == ws.id
    finally:
        app.dependency_overrides.clear()


async def test_document_processing_failed_emits_event(db_session):
    """Call _finalize_error directly with a stubbed broker; verify the audit row."""
    from services import ingest_pipeline

    user = _seed_user(db_session)
    ws = _seed_workspace(db_session, user.id)
    doc = models.Document(
        filename="bad.pdf",
        workspace_id=ws.id,
        is_global=False,
        status="processing",
    )
    db_session.add(doc); db_session.commit(); db_session.refresh(doc)

    class _StubBroker:
        async def publish(self, _doc_id, _event):
            return None

    await ingest_pipeline._finalize_error(
        db_session, _StubBroker(), doc, "embed call failed"
    )

    events = db_session.query(models.AuditEvent).filter_by(
        event_type="document.processing_failed",
    ).all()
    assert len(events) == 1
    assert events[0].user_id == user.id
    assert events[0].workspace_id == ws.id
    assert events[0].resource_id == doc.id
    payload = events[0].payload
    assert payload["filename"] == "bad.pdf"
    assert payload["error"] == "embed call failed"
