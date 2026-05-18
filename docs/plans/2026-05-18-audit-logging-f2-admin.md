# Audit Logging F.2-admin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax. Apply Karpathy discipline.

**Goal:** Wire `log_event` into every admin-domain router, emitting the `admin.user.*`, `admin.template.*`, `admin.workspace.*`, and `admin.system.*` events from `docs/specs/2026-05-18-audit-logging.md`. Adds compliance-grade visibility into admin actions.

**Architecture:** Add `EventType` constants for the admin domain. At each admin router endpoint, after the business operation succeeds and before the response returns, call `log_event(db, EventType.X, user=current_admin, ...)`. For `admin.user.edited` (PATCH user), inspect which fields changed and emit additional events for `activated`/`deactivated`/`promoted_to_admin`/`demoted_from_admin` transitions.

**Tech Stack:** FastAPI + SQLAlchemy + `core.audit.log_event` (shipped in F.1).

**Reference spec:** `docs/specs/2026-05-18-audit-logging.md` (Event taxonomy, Payload conventions, Sensitive data policy).

**Reference precedent:** PR #85 (F.1) wired the four `auth.*` events into `routers/auth.py`. Same pattern applies here: insert via `log_event` inside the surrounding transaction, no separate commit needed (request commit covers it).

---

## Event inventory (~16 sites)

### `admin_users.py`
| Endpoint | Event | Payload |
|---|---|---|
| `POST /api/admin/users` | `admin.user.created` | `{ created_user_id, created_username, is_admin, can_create_workspaces, starter_template_ids: [str] }` |
| `PATCH /api/admin/users/{id}` (general) | `admin.user.edited` | `{ target_user_id, target_username, changed_fields: [str] }` |
| `PATCH ...` (is_active false → true) | `admin.user.activated` (additional, same payload) | `{ target_user_id, target_username }` |
| `PATCH ...` (is_active true → false) | `admin.user.deactivated` | `{ target_user_id, target_username }` |
| `PATCH ...` (is_admin false → true) | `admin.user.promoted_to_admin` | `{ target_user_id, target_username }` |
| `PATCH ...` (is_admin true → false) | `admin.user.demoted_from_admin` | `{ target_user_id, target_username }` |
| `POST /api/admin/users/{id}/password` | `auth.password_reset_by_admin` (already in `EventType`) | `{ target_user_id, target_username }` |
| `DELETE /api/admin/users/{id}` | `admin.user.deleted` | `{ deleted_user_id, deleted_username, is_hard: bool }` |

Note: multi-event emission on PATCH is intentional. The base `admin.user.edited` records the change set. Per-transition events (`activated`/`deactivated`/`promoted`/`demoted`) make those flips queryable independently — they're commonly audited.

### `admin_templates.py`
| Endpoint | Event | Payload |
|---|---|---|
| `POST /api/admin/templates` | `admin.template.created` | `{ template_id, slug, display_name }` |
| `PUT /api/admin/templates/{id}` | `admin.template.edited` | `{ template_id, slug, changed_fields: [str] }` |
| `DELETE /api/admin/templates/{id}` | `admin.template.deleted` | `{ template_id, slug, affected_instances: int }` (count of orphaned workspaces) |
| `POST /api/admin/templates/{id}/instantiate` | `admin.template.instantiated` | `{ template_id, slug, target_user_id, new_workspace_id }` |
| `POST /api/admin/templates/{id}/push` | `admin.template.pushed` | `{ template_id, affected_workspace_count, affected_user_count, had_customizations_count }` |

### `admin_workspaces.py`
| Endpoint | Event | Payload |
|---|---|---|
| `PUT /api/admin/workspaces/{id}` | `admin.workspace.edited` | `{ workspace_id, owner_user_id, slug, changed_fields: [str] }` |
| `DELETE /api/admin/workspaces/{id}` | `admin.workspace.deleted` | `{ workspace_id, owner_user_id, slug, removed_session_count, removed_folder_count, removed_document_count }` |

### `settings.py` (micro-prompts)
| Endpoint | Event | Payload |
|---|---|---|
| `PATCH /api/prompts` | `admin.system.micro_prompt_edited` | `{ keys_changed: [str] }` |
| `DELETE /api/prompts/{key}` | `admin.system.micro_prompt_edited` (same event type, "edited" covers delete; payload conveys the deletion) | `{ keys_changed: [key], action: "deleted" }` |

Spec lists only `micro_prompt_edited` for the prompts domain — using one event_type for both edit and delete keeps the dashboard's filter list short.

### `admin.py` (models)
| Endpoint | Event | Payload |
|---|---|---|
| `POST /api/admin/models` | `admin.system.model_added` | `{ model_id, repo, ctx_size, ngl, tags: [str], group: str?, vision: bool }` |
| `PUT /api/admin/models/{id}` | `admin.system.model_edited` | `{ model_id, changed_fields: [str] }` |
| `DELETE /api/admin/models/{id}` | `admin.system.model_removed` | `{ model_id }` |

**Deviation from spec:** the spec's `admin.system.*` list has `model_added` and `model_removed` but not `model_edited`. Adding `model_edited` because the PUT endpoint does exist; classifying every PUT as a different event_type would be over-engineering. If the dashboard later wants to merge `added/edited/removed` into a single "model_changed" filter, the data is still there.

---

## File map

| File | Action | Purpose |
|---|---|---|
| `backend/core/audit.py` | Modify | Add `ADMIN_*` and `SYSTEM_*` EventType constants |
| `backend/routers/admin_users.py` | Modify | Wire 8 event emissions |
| `backend/routers/admin_templates.py` | Modify | Wire 5 event emissions |
| `backend/routers/admin_workspaces.py` | Modify | Wire 2 event emissions |
| `backend/routers/settings.py` | Modify | Wire 2 event emissions (`/api/prompts`) |
| `backend/routers/admin.py` | Modify | Wire 3 event emissions (`/api/admin/models`) |
| `backend/tests/test_audit_admin_events.py` | Create | One test per event type; uses cookie auth |

---

## Task 0: Branch + plan commit

Branch `feat/audit-logging-f2-admin` already exists.

- [ ] **Step 1: Commit the plan**

```bash
cd /home/orbital/projects/pryzm && git add docs/plans/2026-05-18-audit-logging-f2-admin.md && \
git commit -m "docs(plan): audit logging F.2-admin (admin.user/template/workspace/system events)"
```

---

## Task 1: Add `EventType` constants

**File:** `backend/core/audit.py`

Add to the `EventType` class, alongside the existing `auth.*` constants:

```python
class EventType:
    # auth.* (already exists)
    AUTH_LOGIN_SUCCESS = "auth.login_success"
    AUTH_LOGIN_FAILURE = "auth.login_failure"
    AUTH_LOGOUT = "auth.logout"
    AUTH_PASSWORD_CHANGED = "auth.password_changed"
    AUTH_PASSWORD_RESET_BY_ADMIN = "auth.password_reset_by_admin"
    AUTH_SESSION_EXPIRED = "auth.session_expired"

    # admin.user.*
    ADMIN_USER_CREATED = "admin.user.created"
    ADMIN_USER_EDITED = "admin.user.edited"
    ADMIN_USER_ACTIVATED = "admin.user.activated"
    ADMIN_USER_DEACTIVATED = "admin.user.deactivated"
    ADMIN_USER_PROMOTED_TO_ADMIN = "admin.user.promoted_to_admin"
    ADMIN_USER_DEMOTED_FROM_ADMIN = "admin.user.demoted_from_admin"
    ADMIN_USER_DELETED = "admin.user.deleted"

    # admin.template.*
    ADMIN_TEMPLATE_CREATED = "admin.template.created"
    ADMIN_TEMPLATE_EDITED = "admin.template.edited"
    ADMIN_TEMPLATE_DELETED = "admin.template.deleted"
    ADMIN_TEMPLATE_INSTANTIATED = "admin.template.instantiated"
    ADMIN_TEMPLATE_PUSHED = "admin.template.pushed"

    # admin.workspace.*
    ADMIN_WORKSPACE_EDITED = "admin.workspace.edited"
    ADMIN_WORKSPACE_DELETED = "admin.workspace.deleted"

    # admin.system.*
    ADMIN_SYSTEM_MODEL_ADDED = "admin.system.model_added"
    ADMIN_SYSTEM_MODEL_EDITED = "admin.system.model_edited"
    ADMIN_SYSTEM_MODEL_REMOVED = "admin.system.model_removed"
    ADMIN_SYSTEM_MICRO_PROMPT_EDITED = "admin.system.micro_prompt_edited"
```

Smoke import:

```bash
cd /home/orbital/projects/pryzm/backend && \
./venv/bin/python -c "from core.audit import EventType; print(EventType.ADMIN_USER_CREATED, EventType.ADMIN_TEMPLATE_PUSHED, EventType.ADMIN_SYSTEM_MODEL_ADDED)"
```

Expected: prints the three strings.

- [ ] **Commit:**

```bash
cd /home/orbital/projects/pryzm && git add backend/core/audit.py && \
git commit -m "feat(audit): add EventType constants for admin.user/template/workspace/system"
```

---

## Task 2: Wire `admin_users.py` events

**File:** `backend/routers/admin_users.py`

Read the file first; identify the four endpoint handlers and how each ends (commit pattern, response shape).

For each endpoint, add `log_event` AFTER the business operation completes successfully, BEFORE the response returns. Each handler likely already has `db.commit()` — the audit row participates in that same transaction.

Add `request: Request` to handler signatures if missing. Import `Request` from `fastapi` if not present.

Add at the top of the file:
```python
from core.audit import EventType, log_event
```

### `POST /api/admin/users` — `admin.user.created`

```python
log_event(
    db, EventType.ADMIN_USER_CREATED,
    user=admin,  # the admin acting (current admin from dependency injection)
    request=request,
    payload={
        "created_user_id": new_user.id,
        "created_username": new_user.username,
        "is_admin": new_user.is_admin,
        "can_create_workspaces": new_user.can_create_workspaces,
        "starter_template_ids": [t.template_id for t in payload.starter_templates] if hasattr(payload, "starter_templates") else [],
    },
)
```

(`admin` here is whichever variable name the handler uses for the calling admin — could be `user` or `current_user`. Adapt to the existing pattern.)

### `PATCH /api/admin/users/{id}` — `admin.user.edited` + conditional transition events

Compute `changed_fields` by comparing the payload's fields to the current `u` (target user) BEFORE the update. Then apply updates. Then emit:

```python
old_is_active = u.is_active
old_is_admin = u.is_admin

# ... existing update code ...

changed_fields = []
for field in ("email", "is_admin", "is_active", "can_create_workspaces"):
    if hasattr(payload, field) and getattr(payload, field, None) is not None and getattr(u, field) != getattr(payload, field):
        changed_fields.append(field)

# Apply updates (existing code)

log_event(
    db, EventType.ADMIN_USER_EDITED,
    user=admin, request=request,
    payload={
        "target_user_id": u.id,
        "target_username": u.username,
        "changed_fields": changed_fields,
    },
)

# Transition events
if old_is_active != u.is_active:
    log_event(
        db,
        EventType.ADMIN_USER_ACTIVATED if u.is_active else EventType.ADMIN_USER_DEACTIVATED,
        user=admin, request=request,
        payload={"target_user_id": u.id, "target_username": u.username},
    )

if old_is_admin != u.is_admin:
    log_event(
        db,
        EventType.ADMIN_USER_PROMOTED_TO_ADMIN if u.is_admin else EventType.ADMIN_USER_DEMOTED_FROM_ADMIN,
        user=admin, request=request,
        payload={"target_user_id": u.id, "target_username": u.username},
    )
```

Note: the multi-event pattern means a single PATCH that flips both `is_admin` and `is_active` would emit `admin.user.edited` + one transition for active + one transition for admin = 3 rows. That's intended.

### `POST /api/admin/users/{id}/password` — `auth.password_reset_by_admin`

```python
log_event(
    db, EventType.AUTH_PASSWORD_RESET_BY_ADMIN,
    user=admin,  # actor; admin is the actor, target is in payload
    request=request,
    payload={"target_user_id": u.id, "target_username": u.username},
)
```

Note: the actor on `log_event` is the **admin**, not the target — the audit answers "who reset this password" not "whose password was reset". The target is in the payload.

### `DELETE /api/admin/users/{id}` — `admin.user.deleted`

The endpoint supports soft (default) and hard (`?hard=true`) delete. Capture which:

```python
log_event(
    db, EventType.ADMIN_USER_DELETED,
    user=admin, request=request,
    payload={
        "deleted_user_id": u.id,
        "deleted_username": u.username,
        "is_hard": is_hard,  # the query param value, however the handler exposes it
    },
)
```

- [ ] Smoke against the running backend (login as admin via cookie, hit each endpoint, verify rows appear in `audit_events`).

- [ ] **Commit:**

```bash
cd /home/orbital/projects/pryzm && git add backend/routers/admin_users.py && \
git commit -m "feat(audit): emit admin.user.* + auth.password_reset_by_admin events"
```

---

## Task 3: Wire `admin_templates.py` events

**File:** `backend/routers/admin_templates.py`

Same pattern. Add imports, add `request: Request` to signatures that need it, emit one `log_event` per endpoint:

### `POST` (create) — `admin.template.created`
```python
log_event(
    db, EventType.ADMIN_TEMPLATE_CREATED,
    user=admin, request=request,
    payload={
        "template_id": tmpl.id,
        "slug": tmpl.slug,
        "display_name": tmpl.display_name,
    },
)
```

### `PUT` (edit) — `admin.template.edited`
Compute `changed_fields` before applying updates. Then:
```python
log_event(
    db, EventType.ADMIN_TEMPLATE_EDITED,
    user=admin, request=request,
    payload={
        "template_id": tmpl.id,
        "slug": tmpl.slug,
        "changed_fields": changed_fields,
    },
)
```

### `DELETE` — `admin.template.deleted`
Capture the count of affected workspaces BEFORE the delete (since ON DELETE SET NULL will null out their `template_id`):
```python
affected = db.query(models.Workspace).filter(models.Workspace.template_id == tmpl.id).count()

# ... existing delete code ...

log_event(
    db, EventType.ADMIN_TEMPLATE_DELETED,
    user=admin, request=request,
    payload={
        "template_id": tmpl.id,
        "slug": tmpl.slug,
        "affected_instances": affected,
    },
)
```

### `POST /{id}/instantiate` — `admin.template.instantiated`
```python
log_event(
    db, EventType.ADMIN_TEMPLATE_INSTANTIATED,
    user=admin, request=request,
    payload={
        "template_id": tmpl.id,
        "slug": tmpl.slug,
        "target_user_id": target_user.id,
        "new_workspace_id": new_ws.id,
    },
)
```

### `POST /{id}/push` — `admin.template.pushed`
The push spec calls for affected counts. Compute before/during:
```python
affected = db.query(models.Workspace).filter(models.Workspace.template_id == tmpl.id).all()
affected_count = len(affected)
affected_user_ids = {w.user_id for w in affected}
# Count "had customizations" however the existing push code measures it; if it doesn't,
# leave this as 0 and add it as a follow-up. Don't over-engineer.

# ... existing push code ...

log_event(
    db, EventType.ADMIN_TEMPLATE_PUSHED,
    user=admin, request=request,
    payload={
        "template_id": tmpl.id,
        "affected_workspace_count": affected_count,
        "affected_user_count": len(affected_user_ids),
        "had_customizations_count": 0,  # placeholder; refine if existing push logic tracks it
    },
)
```

- [ ] **Commit:**

```bash
cd /home/orbital/projects/pryzm && git add backend/routers/admin_templates.py && \
git commit -m "feat(audit): emit admin.template.* events (created/edited/deleted/instantiated/pushed)"
```

---

## Task 4: Wire `admin_workspaces.py`, `settings.py`, `admin.py` (models)

Three small files; one commit covers all of them.

### `admin_workspaces.py`

**`PUT /api/admin/workspaces/{id}`** — `admin.workspace.edited`:
```python
# Before applying updates, compute changed_fields by comparing payload to ws
log_event(
    db, EventType.ADMIN_WORKSPACE_EDITED,
    user=admin, request=request,
    workspace=ws,
    payload={
        "workspace_id": ws.id,
        "owner_user_id": ws.user_id,
        "slug": ws.slug,
        "changed_fields": changed_fields,
    },
)
```

**`DELETE /api/admin/workspaces/{id}`** — `admin.workspace.deleted`:

Capture cascaded counts before the delete:
```python
session_count = db.query(models.Session).filter(models.Session.workspace_id == ws.id).count()
folder_count = db.query(models.Folder).filter(models.Folder.workspace_id == ws.id).count()
document_count = db.query(models.Document).filter(models.Document.workspace_id == ws.id).count()

# ... existing delete code ...

log_event(
    db, EventType.ADMIN_WORKSPACE_DELETED,
    user=admin, request=request,
    payload={
        "workspace_id": ws.id,
        "owner_user_id": ws.user_id,
        "slug": ws.slug,
        "removed_session_count": session_count,
        "removed_folder_count": folder_count,
        "removed_document_count": document_count,
    },
)
```

### `settings.py` (micro-prompts)

**`PATCH /api/prompts`** — `admin.system.micro_prompt_edited`:
```python
log_event(
    db, EventType.ADMIN_SYSTEM_MICRO_PROMPT_EDITED,
    user=admin, request=request,
    payload={"keys_changed": list(payload.keys()), "action": "edited"},
)
```

**`DELETE /api/prompts/{key}`** — same `admin.system.micro_prompt_edited`:
```python
log_event(
    db, EventType.ADMIN_SYSTEM_MICRO_PROMPT_EDITED,
    user=admin, request=request,
    payload={"keys_changed": [key], "action": "deleted"},
)
```

Per spec, prompts uses one event type for both edit and delete; `action` in payload differentiates.

### `admin.py` (models)

**`POST /api/admin/models`** — `admin.system.model_added`:
```python
log_event(
    db, EventType.ADMIN_SYSTEM_MODEL_ADDED,
    user=admin, request=request,
    payload={
        "model_id": m.id,
        "repo": m.repo,
        "ctx_size": m.ctx_size,
        "ngl": m.ngl,
        "tags": list(m.tags or []),
        "group": m.group,
        "vision": "vision" in (m.tags or []),
    },
)
```

**`PUT /api/admin/models/{model_id}`** — `admin.system.model_edited`:
```python
log_event(
    db, EventType.ADMIN_SYSTEM_MODEL_EDITED,
    user=admin, request=request,
    payload={"model_id": m.id, "changed_fields": changed_fields},
)
```

**`DELETE /api/admin/models/{model_id}`** — `admin.system.model_removed`:
```python
log_event(
    db, EventType.ADMIN_SYSTEM_MODEL_REMOVED,
    user=admin, request=request,
    payload={"model_id": model_id},
)
```

- [ ] **Commit:**

```bash
cd /home/orbital/projects/pryzm && git add backend/routers/admin_workspaces.py backend/routers/settings.py backend/routers/admin.py && \
git commit -m "feat(audit): emit admin.workspace.*, admin.system.micro_prompt_edited, admin.system.model_* events"
```

---

## Task 5: Tests

**File:** `backend/tests/test_audit_admin_events.py`

One test per event type. Each test:
1. Seeds admin (and any target user/template/workspace/etc.)
2. Logs in admin (cookie-based via `cookie_auth.create_session`)
3. Calls the endpoint
4. Asserts the event row exists with the right `event_type`, `user_id` (the admin), and key payload fields

Reuse the pattern from `tests/test_audit_auth_events.py` (already in F.1).

Required tests (~17):

- `test_admin_user_created_emits_event`
- `test_admin_user_edited_emits_event`
- `test_admin_user_activated_emits_event`
- `test_admin_user_deactivated_emits_event`
- `test_admin_user_promoted_to_admin_emits_event`
- `test_admin_user_demoted_from_admin_emits_event`
- `test_admin_user_password_reset_emits_event`
- `test_admin_user_deleted_emits_event` (both soft and hard variants)
- `test_admin_template_created_emits_event`
- `test_admin_template_edited_emits_event`
- `test_admin_template_deleted_emits_event` (assert `affected_instances` is computed)
- `test_admin_template_instantiated_emits_event`
- `test_admin_template_pushed_emits_event` (assert counts)
- `test_admin_workspace_edited_emits_event`
- `test_admin_workspace_deleted_emits_event` (assert cascaded counts)
- `test_admin_system_micro_prompt_edited_emits_event` (PATCH path)
- `test_admin_system_micro_prompt_deleted_emits_event` (DELETE path; same event type but action="deleted")
- `test_admin_system_model_added_emits_event`
- `test_admin_system_model_edited_emits_event`
- `test_admin_system_model_removed_emits_event`

That's ~20 tests. Mechanical to write; reuse helper `_seed_admin` from existing audit tests if available.

Run after each batch:

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest tests/test_audit_admin_events.py -v
```

All pass.

- [ ] **Commit:**

```bash
cd /home/orbital/projects/pryzm && git add backend/tests/test_audit_admin_events.py && \
git commit -m "test(audit): coverage for admin.* event emission"
```

---

## Task 6: Full sweep + PR

- [ ] **Step 1: Backend full sweep**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest -q
```

Baseline 372 + ~20 new = ~392 passing.

- [ ] **Step 2: Frontend typecheck (sanity — no frontend changes expected)**

```bash
cd /home/orbital/projects/pryzm/frontend && npx tsc --noEmit
```

- [ ] **Step 3: Push + open PR**

```bash
cd /home/orbital/projects/pryzm && git push -u origin feat/audit-logging-f2-admin
gh pr create --base main --head feat/audit-logging-f2-admin \
  --title "feat(audit): F.2-admin — emit admin.user/template/workspace/system events" \
  --body "$(cat <<'EOF'
Second slice of audit logging. Wires log_event into every admin-domain router, emitting the 16+ admin.* events from docs/specs/2026-05-18-audit-logging.md.

## Changes
- New EventType constants: ADMIN_USER_*, ADMIN_TEMPLATE_*, ADMIN_WORKSPACE_*, ADMIN_SYSTEM_*
- admin_users.py: emits admin.user.created/edited/activated/deactivated/promoted_to_admin/demoted_from_admin/deleted + auth.password_reset_by_admin
- admin_templates.py: emits admin.template.created/edited/deleted/instantiated/pushed (with affected_instances + push counts)
- admin_workspaces.py: emits admin.workspace.edited/deleted (with cascaded counts)
- settings.py: emits admin.system.micro_prompt_edited for PATCH and DELETE
- admin.py: emits admin.system.model_added/edited/removed
- ~20 new tests, one per event type, cookie-auth pattern from F.1

After this PR, every admin action against users, templates, workspaces, prompts, and models is recorded with actor + target + payload. F.3 (admin read endpoints) is next.

Spec: docs/specs/2026-05-18-audit-logging.md. Plan: docs/plans/2026-05-18-audit-logging-f2-admin.md.
EOF
)"
```

- [ ] **Step 4: No auto-merge** — operator reviews.

---

## Self-review

Spec coverage for F.2-admin:

- [x] `admin.user.*` — 7 events
- [x] `auth.password_reset_by_admin` — emitted from `POST /users/{id}/password`
- [x] `admin.template.*` — 5 events
- [x] `admin.workspace.*` — 2 events
- [x] `admin.system.*` — 4 events (model_added/edited/removed + micro_prompt_edited)

Out of scope (subsequent PRs):
- F.2-workspace (workspace.created, workspace.edited — for user-initiated workspace edits, not admin)
- F.2-folder, F.2-document
- F.2-chat (largest chunk)
- F.3 — admin read endpoints
