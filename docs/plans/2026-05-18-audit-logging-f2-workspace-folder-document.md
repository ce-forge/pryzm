# Audit Logging F.2 — workspace, folder, document events

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire `workspace.*`, `folder.*`, and `document.*` audit events into their existing routers per `docs/specs/2026-05-18-audit-logging.md`. No schema changes; only `core/audit.py` constants, `log_event(...)` calls in three routers + one service, and tests.

**Architecture:** Sync inline `log_event(db, ..., user=..., workspace=..., ...)` calls after the business operation succeeds, before the response returns. Mirrors the F.2-admin shape (PR #87). Background-task event (`document.processing_failed`) emits from `services/ingest_pipeline._finalize_error` after the error-state commit.

**Tech Stack:** FastAPI, SQLAlchemy, pytest, existing `core/audit.py` helper.

---

## Scope

Events covered in this slice (8 new EventType constants):

| event_type | call site | payload |
|---|---|---|
| `workspace.created` | `routers/workspaces.py::create_workspace` | `{slug, display_name, color, cloned_from_slug}` |
| `workspace.edited` | `routers/workspaces.py::update_workspace` | `{changed_fields, previous_values, new_values}` |
| `folder.created` | `routers/folders.py::create_folder` | `{folder_id, name}` |
| `folder.edited` | `routers/folders.py::update_folder` | `{folder_id, previous_name, new_name}` |
| `folder.deleted` | `routers/folders.py::delete_folder` | `{folder_id, name, orphaned_session_count}` |
| `document.uploaded` | `routers/documents.py::upload_document` | `{filename, mime, size_bytes, document_id, session_id, is_global}` |
| `document.deleted` | `routers/documents.py::delete_document` | `{document_id, filename}` |
| `document.processing_failed` | `services/ingest_pipeline.py::_finalize_error` | `{document_id, filename, error}` |

**Out of scope (deferred):**
- `workspace.deleted` (user deleting their own workspace) — not in spec v1 surface; `admin.workspace.deleted` covers admin-initiated deletes.
- `/workspaces/{slug}/reset` and `/workspaces/{slug}/position` — not in spec taxonomy.
- `chat.*` events — separate slice (next PR).

**Adjacent change required:** `routers/workspaces.py` POST/PATCH currently have no `user: Depends(cookie_auth.current_user)` parameter. Auth IS enforced at router-include level, but the user object isn't available inside the handler. Add the dep to those two endpoints (smallest surgical change for audit attribution). Same for `routers/folders.py::update_folder`/`delete_folder` and `routers/documents.py::delete_document`, which currently use only the `workspace_query_dep`.

---

## Task 1: Add 8 EventType constants

**Files:**
- Modify: `backend/core/audit.py`

- [ ] **Step 1: Append three new prefix groups to the EventType class.**

After `ADMIN_SYSTEM_MICRO_PROMPT_EDITED`, append:

```python
    # workspace.*
    WORKSPACE_CREATED = "workspace.created"
    WORKSPACE_EDITED = "workspace.edited"

    # folder.*
    FOLDER_CREATED = "folder.created"
    FOLDER_EDITED = "folder.edited"
    FOLDER_DELETED = "folder.deleted"

    # document.*
    DOCUMENT_UPLOADED = "document.uploaded"
    DOCUMENT_DELETED = "document.deleted"
    DOCUMENT_PROCESSING_FAILED = "document.processing_failed"
```

- [ ] **Step 2: Run the existing test sweep.**

```bash
cd backend && ./venv/bin/pytest -q
```

Expected: 393 passed, 1 skipped (same baseline as on main).

- [ ] **Step 3: Commit.**

```bash
git add backend/core/audit.py
git commit -m "audit: add workspace/folder/document EventType constants"
```

---

## Task 2: Wire workspace.* events

**Files:**
- Modify: `backend/routers/workspaces.py`

### Step 1: Add user + request deps to POST /workspaces

- [ ] In `routers/workspaces.py`, locate `create_workspace`. Change the signature from:

```python
@router.post("/workspaces", response_model=WorkspaceResponse)
def create_workspace(
    payload: WorkspaceCreate,
    db: Session = Depends(database.get_db),
):
```

to:

```python
@router.post("/workspaces", response_model=WorkspaceResponse)
def create_workspace(
    payload: WorkspaceCreate,
    request: Request,
    db: Session = Depends(database.get_db),
    user: models.User = Depends(cookie_auth.current_user),
):
```

Add to imports at top of file (alongside existing imports):

```python
from fastapi import APIRouter, Depends, HTTPException, Request
from core import cookie_auth
from core.audit import EventType, log_event
```

(Keep existing imports; add `Request` to the fastapi import, add `cookie_auth` if missing, add the `audit` import.)

### Step 2: Emit workspace.created

- [ ] After `db.refresh(ws)` and before `return _to_response(ws)`, add:

```python
    log_event(
        db,
        EventType.WORKSPACE_CREATED,
        user=user,
        workspace=ws,
        resource_type="workspace",
        resource_id=ws.id,
        payload={
            "slug": ws.slug,
            "display_name": ws.display_name,
            "color": ws.color,
            "cloned_from_slug": payload.clone_from,
        },
        request=request,
    )
    db.commit()
```

(The audit write needs its own commit because the helper only `db.add`s — the surrounding endpoint already committed the workspace insert.)

### Step 3: Add user + request deps to PATCH /workspaces/{slug}

- [ ] Change `update_workspace` signature from:

```python
@router.patch("/workspaces/{slug}", response_model=WorkspaceResponse)
def update_workspace(
    slug: str,
    payload: WorkspaceUpdate,
    db: Session = Depends(database.get_db),
):
```

to:

```python
@router.patch("/workspaces/{slug}", response_model=WorkspaceResponse)
def update_workspace(
    slug: str,
    payload: WorkspaceUpdate,
    request: Request,
    db: Session = Depends(database.get_db),
    user: models.User = Depends(cookie_auth.current_user),
):
```

### Step 4: Track previous/new values and emit workspace.edited

- [ ] Inside `update_workspace`, before mutating, capture previous values for the fields being changed:

```python
    ws = get_by_slug(db, slug)
    data = payload.model_dump(exclude_unset=True)

    changed_fields: list[str] = []
    previous_values: dict = {}
    new_values: dict = {}

    if "display_name" in data:
        stripped = data["display_name"].strip()
        if not stripped:
            raise HTTPException(
                status_code=400,
                detail="display_name must contain non-whitespace characters",
            )
        if stripped != ws.display_name:
            previous_values["display_name"] = ws.display_name
            new_values["display_name"] = stripped
            changed_fields.append("display_name")
        ws.display_name = stripped

    if "system_prompt" in data:
        if data["system_prompt"] != ws.system_prompt:
            previous_values["system_prompt"] = ws.system_prompt
            new_values["system_prompt"] = data["system_prompt"]
            changed_fields.append("system_prompt")
        ws.system_prompt = data["system_prompt"]

    if "enabled_tools" in data:
        _validate_enabled_tools(data["enabled_tools"])
        if list(ws.enabled_tools or []) != list(data["enabled_tools"]):
            previous_values["enabled_tools"] = list(ws.enabled_tools or [])
            new_values["enabled_tools"] = list(data["enabled_tools"])
            changed_fields.append("enabled_tools")
        ws.enabled_tools = data["enabled_tools"]

    if "color" in data:
        if data["color"] != ws.color:
            previous_values["color"] = ws.color
            new_values["color"] = data["color"]
            changed_fields.append("color")
        ws.color = data["color"]

    db.commit()
    db.refresh(ws)

    if changed_fields:
        log_event(
            db,
            EventType.WORKSPACE_EDITED,
            user=user,
            workspace=ws,
            resource_type="workspace",
            resource_id=ws.id,
            payload={
                "changed_fields": changed_fields,
                "previous_values": previous_values,
                "new_values": new_values,
            },
            request=request,
        )
        db.commit()

    return _to_response(ws)
```

(No event when nothing actually changed — keeps the audit log signal-rich.)

### Step 5: Run the sweep

- [ ] ```bash
cd backend && ./venv/bin/pytest -q
```

Expected: 393 passed, 1 skipped. (No new tests yet; just verifying no regressions.)

### Step 6: Commit

- [ ] ```bash
git add backend/routers/workspaces.py
git commit -m "audit: emit workspace.created/edited events"
```

---

## Task 3: Wire folder.* events

**Files:**
- Modify: `backend/routers/folders.py`

### Step 1: Add audit + Request imports

- [ ] Top of file, add:

```python
from fastapi import APIRouter, Depends, HTTPException, Request
from core.audit import EventType, log_event
```

(`cookie_auth` is already imported.)

### Step 2: Emit folder.created

- [ ] In `create_folder`, add `request: Request` to the signature (between `folder: FolderCreate` and `db: Session = ...`). After `db.commit()` and before `return`:

```python
    log_event(
        db,
        EventType.FOLDER_CREATED,
        user=user,
        workspace=ws,
        resource_type="folder",
        resource_id=new_folder.id,
        payload={
            "folder_id": new_folder.id,
            "name": new_folder.name,
        },
        request=request,
    )
    db.commit()
```

### Step 3: Add user dep + emit folder.edited

- [ ] Change `update_folder` signature from:

```python
@router.patch("/folders/{folder_id}")
def update_folder(
    folder_id: str,
    payload: FolderUpdate,
    workspace: models.Workspace = Depends(workspace_query_dep),
    db: Session = Depends(database.get_db),
):
```

to:

```python
@router.patch("/folders/{folder_id}")
def update_folder(
    folder_id: str,
    payload: FolderUpdate,
    request: Request,
    workspace: models.Workspace = Depends(workspace_query_dep),
    db: Session = Depends(database.get_db),
    user: models.User = Depends(cookie_auth.current_user),
):
```

Then inside the function, capture previous name before mutating:

```python
    db_folder = verify_workspace_owns(folder_id, models.Folder, workspace.id, db)
    previous_name = db_folder.name
    db_folder.name = payload.name
    db.commit()

    if previous_name != payload.name:
        log_event(
            db,
            EventType.FOLDER_EDITED,
            user=user,
            workspace=workspace,
            resource_type="folder",
            resource_id=folder_id,
            payload={
                "folder_id": folder_id,
                "previous_name": previous_name,
                "new_name": payload.name,
            },
            request=request,
        )
        db.commit()

    return {"status": "success"}
```

### Step 4: Add user dep + emit folder.deleted

- [ ] Change `delete_folder` signature similarly to add `request: Request` and `user: models.User = Depends(cookie_auth.current_user)`. Then:

```python
    db_folder = verify_workspace_owns(folder_id, models.Folder, workspace.id, db)
    deleted_name = db_folder.name

    orphaned_session_count = db.query(models.Session).filter(
        models.Session.folder_id == folder_id
    ).count()

    db.query(models.Session).filter(models.Session.folder_id == folder_id).update(
        {"folder_id": None}, synchronize_session=False,
    )
    db.query(models.Folder).filter(models.Folder.id == folder_id).delete()

    log_event(
        db,
        EventType.FOLDER_DELETED,
        user=user,
        workspace=workspace,
        resource_type="folder",
        resource_id=folder_id,
        payload={
            "folder_id": folder_id,
            "name": deleted_name,
            "orphaned_session_count": orphaned_session_count,
        },
        request=request,
    )
    db.commit()
    return {"status": "success"}
```

(Note the audit `log_event` happens *before* the final `db.commit()` so deletion + audit row commit atomically. The `verify_workspace_owns` lookup returns a fresh row whose `.name` is safe to read.)

### Step 5: Run the sweep

- [ ] ```bash
cd backend && ./venv/bin/pytest -q
```

Expected: 393 passed, 1 skipped.

### Step 6: Commit

- [ ] ```bash
git add backend/routers/folders.py
git commit -m "audit: emit folder.created/edited/deleted events"
```

---

## Task 4: Wire document.* events

**Files:**
- Modify: `backend/routers/documents.py`
- Modify: `backend/services/ingest_pipeline.py`

### Step 1: Emit document.uploaded

- [ ] In `routers/documents.py`, add to imports at top:

```python
from core.audit import EventType, log_event
```

In `upload_document`, after `db.refresh(doc)` and before scheduling the ingest task:

```python
    log_event(
        db,
        EventType.DOCUMENT_UPLOADED,
        user=user,
        workspace=ws,
        resource_type="document",
        resource_id=doc.id,
        payload={
            "document_id": doc.id,
            "filename": file.filename,
            "mime": content_type,
            "size_bytes": len(content),
            "session_id": active_session_id,
            "is_global": is_global,
        },
        request=request,
    )
    db.commit()
```

### Step 2: Add user dep + emit document.deleted

- [ ] Change `delete_document` signature from:

```python
@router.delete("/documents/{document_id}")
def delete_document(
    document_id: str,
    workspace: models.Workspace = Depends(workspace_query_dep),
    db: Session = Depends(database.get_db),
):
```

to:

```python
@router.delete("/documents/{document_id}")
def delete_document(
    document_id: str,
    request: Request,
    workspace: models.Workspace = Depends(workspace_query_dep),
    db: Session = Depends(database.get_db),
    user: models.User = Depends(cookie_auth.current_user),
):
```

(`Request` is already imported in this file.) Then change the body to capture the filename/mime *before* deleting:

```python
    doc = verify_workspace_owns(document_id, models.Document, workspace.id, db)
    deleted_filename = doc.filename
    deleted_session_id = doc.session_id

    db.delete(doc)

    log_event(
        db,
        EventType.DOCUMENT_DELETED,
        user=user,
        workspace=workspace,
        session=db.query(models.Session).filter_by(id=deleted_session_id).first() if deleted_session_id else None,
        resource_type="document",
        resource_id=document_id,
        payload={
            "document_id": document_id,
            "filename": deleted_filename,
        },
        request=request,
    )
    db.commit()
    return {"status": "deleted"}
```

(Note: `models.Document` has no `mime_type` column — original MIME isn't stored after ingest. Don't add one in this slice; just capture filename.)

### Step 3: Emit document.processing_failed from ingest pipeline

- [ ] In `services/ingest_pipeline.py`, add to imports at top:

```python
from core.audit import EventType, log_event
```

Modify `_finalize_error`. After `db.commit()` (line ~180), before the broker publish:

```python
    try:
        db.rollback()
        fresh = db.query(models.Document).filter(models.Document.id == doc.id).first()
        if fresh is not None:
            fresh.status = "error"
            fresh.error_message = message
            db.commit()

            # Audit the failure with the workspace owner as the actor.
            ws = db.query(models.Workspace).filter_by(id=fresh.workspace_id).first()
            user_obj = (
                db.query(models.User).filter_by(id=ws.user_id).first()
                if ws and ws.user_id else None
            )
            session_obj = (
                db.query(models.Session).filter_by(id=fresh.session_id).first()
                if fresh.session_id else None
            )
            log_event(
                db,
                EventType.DOCUMENT_PROCESSING_FAILED,
                user=user_obj,
                workspace=ws,
                session=session_obj,
                resource_type="document",
                resource_id=fresh.id,
                payload={
                    "document_id": fresh.id,
                    "filename": fresh.filename,
                    "error": message,
                },
                request=None,  # background task; no Request available
            )
            db.commit()
    except Exception:
        _logger.exception("ingest_doc: could not persist error state for %s", doc.id)
        db.rollback()
    await broker.publish(doc.id, {"status": "error", "error": message})
```

(The audit write is inside the `try` so an audit-write failure also rolls back; the broker publish still fires unconditionally, matching the existing best-effort behavior.)

### Step 4: Run the sweep

- [ ] ```bash
cd backend && ./venv/bin/pytest -q
```

Expected: 393 passed, 1 skipped.

### Step 5: Commit

- [ ] ```bash
git add backend/routers/documents.py backend/services/ingest_pipeline.py
git commit -m "audit: emit document.uploaded/deleted/processing_failed events"
```

---

## Task 5: Tests

**Files:**
- Create: `backend/tests/test_audit_workspace_folder_document_events.py`

### Step 1: Write the test file

- [ ] Use the same helpers pattern as `test_audit_admin_events.py` (a `_user_client` that seeds a non-admin user with `can_create_workspaces=True` and sets the session cookie).

```python
"""Workspace, folder, and document routers emit audit events at the right call sites.

Covers workspace.*, folder.*, and document.*.
Same shape as tests/test_audit_admin_events.py.
"""
import pytest
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
        r = c.post("/api/workspaces", json={
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
    finally:
        app.dependency_overrides.clear()


def test_workspace_edited_emits_event_only_for_changes(db_session):
    try:
        c, user = _user_client(db_session)
        ws = _seed_workspace(db_session, user.id)
        r = c.patch(f"/api/workspaces/{ws.slug}", json={
            "display_name": "Renamed",
            "color": "blue",   # same as initial — should NOT appear in changed_fields
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
        r = c.patch(f"/api/workspaces/{ws.slug}", json={
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
        r = c.post("/api/folders", json={"name": "Reports", "workspace": ws.slug})
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

        r = c.patch(f"/api/folders/{folder.id}?workspace={ws.slug}", json={"name": "New"})
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

        r = c.patch(f"/api/folders/{folder.id}?workspace={ws.slug}", json={"name": "Same"})
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

        r = c.delete(f"/api/folders/{folder_id}?workspace={ws.slug}")
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
    handler emits the audit event before scheduling.
    """
    from services import ingest_broker
    monkeypatch.setattr(ingest_broker, "add_task", lambda _coro: None)

    try:
        c, user = _user_client(db_session)
        ws = _seed_workspace(db_session, user.id)

        files = {"file": ("notes.txt", b"hello world", "text/plain")}
        data = {"workspace": ws.slug, "is_global": "false"}
        r = c.post("/api/upload", files=files, data=data)
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

        r = c.delete(f"/api/documents/{doc_id}?workspace={ws.slug}")
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


@pytest.mark.asyncio
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
```

### Step 2: Run the new tests

- [ ] ```bash
cd backend && ./venv/bin/pytest tests/test_audit_workspace_folder_document_events.py -v
```

Expected: 9 passed.

### Step 3: Run the full sweep

- [ ] ```bash
cd backend && ./venv/bin/pytest -q
```

Expected: 402 passed, 1 skipped (393 baseline + 9 new).

### Step 4: Commit

- [ ] ```bash
git add backend/tests/test_audit_workspace_folder_document_events.py
git commit -m "audit: cover workspace/folder/document events with tests"
```

---

## Task 6: PR

- [ ] Pre-push audit: confirm no `dainamik`, real email, or secret strings appear in the diff.

```bash
git diff main...HEAD | grep -iE "dainamik|@gmail|@dainamik|PRYZM_API_TOKEN=[A-Za-z0-9]" | head -5
```

Expected: no output.

- [ ] Push the branch and open the PR:

```bash
git push -u origin feat/audit-logging-f2-workspace-folder-document
gh pr create --title "audit(F.2): workspace/folder/document events" --body "$(cat <<'EOF'
## Summary
- Wires `workspace.created`, `workspace.edited`, `folder.created`, `folder.edited`, `folder.deleted`, `document.uploaded`, `document.deleted`, `document.processing_failed` into the existing routers + ingest pipeline.
- Adds 8 EventType constants; no schema changes.
- 9 new tests; full sweep green.

## Test plan
- [x] `pytest -q` — full sweep
- [x] Pre-push audit clean (no leaks)
EOF
)"
```

- [ ] Report the PR URL back to the controller for review.

---

## Self-review

- Spec coverage: every event_type in this slice maps to a task. ✓
- Placeholder scan: no TODOs, no "implement later". ✓
- Type consistency: `workspace.created` payload uses `cloned_from_slug` consistently; `previous_name`/`new_name` consistent across folder edited; `document_id` consistent across document events. ✓
- Adjacent change isolated: user dep additions are the minimum required for audit attribution. ✓
