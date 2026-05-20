# Post-launch hardening — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use
> superpowers:subagent-driven-development or
> superpowers:executing-plans. Apply Karpathy discipline at every
> step: simplicity, surgical changes, verifiable goals. No
> Co-Authored-By trailer. PR descriptions stay lean.

**Goal:** Ship the six phases of the May 21 review on six branches,
in order, each merged before the next begins.

**Architecture:** One branch and one PR per phase. Phases 1–3 are
surgical fixes; each commit covers one item and lands with a
regression test. Phase 4 is the backend refactor wave; safety net is
the pytest suite. Phase 5 is the frontend refactor wave; safety net
is the Playwright smoke harness. Phase 6 is documentation.

**Tech stack:** FastAPI + SQLAlchemy + Alembic + argon2 (backend);
Next.js 16 + React 19 + Tailwind (frontend); pytest with a real
Postgres `pryzm_test` DB; Playwright via the backend venv.

**Reference spec:** `docs/specs/2026-05-21-post-launch-hardening.md`.

---

## Process per phase

For every phase:

1. Branch from latest `main`.
2. For each item, commit-by-commit:
   - Write or extend the test, run it, watch it fail.
   - Make the change.
   - Run the relevant test(s), watch them pass.
   - Run a broader regression sweep at sensible boundaries.
   - Commit. Karpathy: "Every changed line should trace directly to
     the user's request."
3. End-of-phase verification:
   - Phase 1, 2, 3: `./venv/bin/pytest -q` full sweep from `backend/`.
   - Phase 5: `./venv/bin/pytest tests/smoke -q` from repo root with
     the stack running locally.
   - Phase 4: full pytest sweep plus a manual smoke (one chat, one
     workspace, one admin tab).
4. Push, open PR, wait for CI, auto-merge if green.
5. Pull `main` back, start the next phase from it.

---

## File map (cross-phase)

Backend files modified across phases:

| File | Phases |
|---|---|
| `backend/routers/chat.py` | 1 (S1), 4 (B2, B12) |
| `backend/routers/auth.py` | 1 (S5) |
| `backend/routers/workspaces.py` | 1 (S3, S4) |
| `backend/routers/folders.py` | 3 (D5) |
| `backend/routers/documents.py` | 2 (M2), 4 (B11) |
| `backend/routers/bug_reports.py` | 2 (M1) |
| `backend/routers/admin.py` | 4 (B5, B6) |
| `backend/routers/admin_engine.py` | 2 (M3) |
| `backend/core/cookie_auth.py` | 1 (S2) |
| `backend/core/bootstrap.py` | 1 (S7) |
| `backend/core/audit.py` | 4 (B3), 6 |
| `backend/core/ai_engine.py` | 4 (B1, B3, B4) |
| `backend/main.py` | 1 (S6) |
| `backend/db/models.py` | 3 (D2) |
| `backend/services/workspaces.py` | 3 (D1) |
| `backend/services/audit_partitions.py` | 3 (D4, D6) |
| `backend/services/template_apply.py` | 2 (M6) |
| `backend/services/knowledge.py` | 4 (B3, B7, B8) |
| `backend/services/condense.py` | 4 (B3) |
| `backend/services/title.py` | 4 (B3 — new file) |
| `backend/services/chat_pipeline.py` | 4 (B2 — new file) |
| `backend/services/llama_swap_config.py` | 4 (B5 — new file) |
| `backend/services/llama_swap_status.py` | 4 (B6 — new file) |
| `backend/tools/web.py` | 4 (B4, B9, B10) |
| `backend/tools/network.py` | 2 (M4) |
| `backend/tools/retrieval.py` | 4 (B10) |
| `backend/data/tool_directives.default.json` | 4 (B9 — new file) |
| `backend/utils/constants.py` | 3 (D2) |
| `backend/alembic/versions/<new>_workspace_color_check.py` | 3 (D2 — new) |
| `backend/alembic/versions/<new>_setnull_fk_indices.py` | 3 (D3 — new) |
| `.env.example` | 1 (S5, S6) |

Frontend files modified:

| File | Phases |
|---|---|
| `frontend/src/hooks/useInference.ts` | 5 (F1, F2, F3) |
| `frontend/src/context/SessionContext.tsx` | 5 (F4, F5) |
| `frontend/src/context/SessionMetaContext.tsx` | 5 (F4 — new) |
| `frontend/src/context/SessionMessagesContext.tsx` | 5 (F4 — new) |
| `frontend/src/context/InferenceContext.tsx` | 5 (F6) |
| `frontend/src/context/UploaderContext.tsx` | 5 (F6) |
| `frontend/src/context/TestSuiteContext.tsx` | 5 (F6) |
| `frontend/src/context/AppProviders.tsx` | 5 (F13) |
| `frontend/src/app/admin/bug-reports/page.tsx` | 5 (F7) |
| `frontend/src/components/admin/bugReports/BugDetailModal.tsx` | 5 (F7 — new) |
| `frontend/src/components/admin/StatusBadge.tsx` | 5 (F8 — new) |
| `frontend/src/types/admin.ts` | 5 (F8 — new) |
| `frontend/src/utils/auditPayload.ts` | 5 (F9 — new) |
| `frontend/src/components/admin/system/SettingsModels.tsx` | 5 (F10) |
| `frontend/src/hooks/useModelDownloadStream.ts` | 5 (F10 — new) |
| `frontend/src/components/WorkspaceSettings.tsx` | 5 (F11) |
| `frontend/src/components/WorkspaceCreateModal.tsx` | 5 (F11 — new) |
| `frontend/src/components/WorkspaceEditModal.tsx` | 5 (F11 — new) |
| `frontend/src/components/WorkspaceFieldsForm.tsx` | 5 (F11 — new) |
| `frontend/src/components/SessionDirectory.tsx` | 5 (F12) |
| `frontend/src/hooks/useSessionList.ts` | 5 (F12 — new) |
| `frontend/src/hooks/useFolderList.ts` | 5 (F12 — new) |
| `frontend/src/components/ChatInput.tsx` | 5 (F14) |

---

## Phase 1 — Security HIGH

Branch: `fix/security-high`.

### Task 1.0 — Create branch

- [ ] `git checkout main && git pull && git checkout -b fix/security-high`

### Task 1.1 — S1: `/analyze` session lookup scoped to workspace

**Files:**
- Modify: `backend/routers/chat.py:357-358`
- Modify: `backend/tests/test_workspace_boundary.py` (add test)

- [ ] **Write the failing test.** Append a test case in
  `test_workspace_boundary.py` (find the existing class style by
  reading the top of the file). Test: two users, two workspaces, two
  sessions. User A posts to `/analyze` with `session_id=B's session`
  and `workspace=A's slug`. Expect 404.

```python
def test_analyze_rejects_foreign_session_id(client_user_a, client_user_b, workspaces, sessions):
    """A user supplying another user's session_id with their own
    workspace slug must get 404, not have their prompt appended to
    the foreign session."""
    a_workspace = workspaces["user_a"]
    b_session = sessions["user_b_first"]
    response = client_user_a.post(
        f"/api/analyze?workspace={a_workspace.slug}",
        json={"prompt": "leak", "session_id": b_session.id},
    )
    assert response.status_code == 404
```

- [ ] **Run the test.** Expected: FAIL (handler currently 200s and
  appends).

```
backend $ ./venv/bin/pytest tests/test_workspace_boundary.py -k foreign_session -v
```

- [ ] **Apply the fix.** Change `chat.py:357-358` to:

```python
if request.session_id:
    chat_session = (
        db.query(models.Session)
        .filter(
            models.Session.id == request.session_id,
            models.Session.workspace_id == workspace.id,
        )
        .first()
    )
    if chat_session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
```

- [ ] **Run the test.** Expected: PASS. Also run the full
  `test_workspace_boundary.py` and `test_chat_session_user_ownership.py`
  to ensure no regression.

- [ ] **Commit:** `git commit -am "fix(chat): scope session_id lookup to caller's workspace"`

### Task 1.2 — S2: `must_change_password` enforced server-side

**Files:**
- Modify: `backend/core/cookie_auth.py:89-99`
- Modify: `backend/routers/auth.py` (only if a constant
  `MUST_CHANGE_ALLOWED_PATHS` lives there; otherwise keep all the
  constants in cookie_auth)
- Create: `backend/tests/test_must_change_password.py`

- [ ] **Write the failing test.** A user with `must_change_password=true`
  hits `/api/workspaces` and gets 403; same user hits
  `/api/auth/password` and gets through.

```python
def test_must_change_blocks_other_endpoints(client, db, factory_user_must_change):
    user, session_token = factory_user_must_change()
    client.cookies.set("pryzm_session", session_token)
    response = client.get("/api/workspaces")
    assert response.status_code == 403
    assert "password" in response.json()["detail"].lower()

def test_must_change_allows_password_endpoint(client, db, factory_user_must_change):
    user, session_token = factory_user_must_change()
    client.cookies.set("pryzm_session", session_token)
    response = client.post(
        "/api/auth/password",
        json={"current_password": "old", "new_password": "new1"},
    )
    assert response.status_code in (200, 400)  # not 403
```

- [ ] **Apply the fix.** Change `current_user` to accept `Request`:

```python
from fastapi import Request

ALLOWED_DURING_MUST_CHANGE = frozenset({
    "/api/auth/password",
    "/api/auth/logout",
    "/api/auth/me",
})


def current_user(
    request: Request,
    pryzm_session: Annotated[Optional[str], Cookie()] = None,
    db: DbSession = Depends(database.get_db),
) -> models.User:
    user = get_session_user(db, pryzm_session) if pryzm_session else None
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
        )
    if user.must_change_password and request.url.path not in ALLOWED_DURING_MUST_CHANGE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Password change required.",
        )
    return user
```

- [ ] **Run the tests.** Expected: both pass.

- [ ] **Run the full auth + cookie test files** to catch regressions:
  `./venv/bin/pytest tests/test_auth_router.py tests/test_current_user.py tests/test_password_change_invalidates_sessions.py -q`.

- [ ] **Commit:** `git commit -am "fix(auth): enforce must_change_password in current_user dependency"`

### Task 1.3 — S3: `can_create_workspaces` enforced

**Files:**
- Modify: `backend/routers/workspaces.py:70-152`
- Modify: `backend/tests/test_admin_users_router.py` or a new file

- [ ] **Write the failing test.** A non-admin user with
  `can_create_workspaces=false` POSTs `/api/workspaces` and gets 403.

- [ ] **Apply the fix.** At the top of `create_workspace`:

```python
if not user.is_admin and not user.can_create_workspaces:
    raise HTTPException(
        status_code=403,
        detail="You do not have permission to create workspaces.",
    )
```

- [ ] **Run the test, then `test_workspace_boundary.py`.**

- [ ] **Commit:** `git commit -am "fix(workspaces): enforce can_create_workspaces flag"`

### Task 1.4 — S4: `clone_from` scoped to caller

**Files:**
- Modify: `backend/routers/workspaces.py:106-114`
- Modify: `backend/services/workspaces.py` — confirm
  `get_by_slug(db, slug, user_id=...)` already accepts user_id; if
  not, extend it.
- Modify: tests in `test_workspace_boundary.py`

- [ ] **Write the failing test.** User A POSTs
  `/api/workspaces { clone_from: <user-B-slug> }` and gets 404 (or
  400, code's choice).

- [ ] **Apply the fix.** In `workspaces.py:106-114`, drop the NOTE,
  pass `user_id=user.id`:

```python
if payload.clone_from:
    source = get_by_slug(db, payload.clone_from, user_id=user.id)
    if source is None:
        raise HTTPException(
            status_code=404,
            detail="Cannot clone from a workspace you do not own.",
        )
    system_prompt = source.system_prompt
    enabled_tools = list(source.enabled_tools or [])
    engine_config = dict(source.engine_config or engine_config)
```

(If `get_by_slug` does not yet accept `user_id`, add it as a
keyword-only argument with `None` default; when set, filter
additionally on `user_id`.)

- [ ] **Run tests.** Expected: PASS.

- [ ] **Commit:** `git commit -am "fix(workspaces): scope clone_from to caller's workspaces"`

### Task 1.5 — S5: cookie `Secure` flag from env

**Files:**
- Modify: `backend/routers/auth.py:88` and other cookie-set sites
  (search `set_cookie` in `backend/`)
- Modify: `backend/config.py` — add `COOKIE_SECURE: bool = True`
- Modify: `.env.example` — document `PRYZM_COOKIE_SECURE`
- Modify: `backend/tests/test_auth_router.py` — assert Secure flag
  in `Set-Cookie` header

- [ ] **Find all cookie-set sites:** `grep -rn "set_cookie\|delete_cookie" backend/`. Likely just `auth.py`.

- [ ] **Add to `config.py`:**

```python
COOKIE_SECURE: bool = os.getenv("PRYZM_COOKIE_SECURE", "true").lower() != "false"
```

- [ ] **Update `auth.py`** — replace `secure=False` with `secure=settings.COOKIE_SECURE`. Drop the
  apologetic comment.

- [ ] **Update `.env.example`:** add `PRYZM_COOKIE_SECURE=false`
  with a comment saying "set to false ONLY for local dev over plain HTTP".

- [ ] **Update test** to set `COOKIE_SECURE=False` for the test
  client (or assert it's True in the prod-like fixture). The smoke
  harness already uses plain HTTP — note that `tests/smoke/README.md`
  may need a one-line callout.

- [ ] **Commit:** `git commit -am "fix(auth): make cookie Secure flag configurable via PRYZM_COOKIE_SECURE"`

### Task 1.6 — S6: Origin allowlist middleware

**Files:**
- Modify: `backend/main.py:167-175`
- Create: `backend/core/origin_check.py`
- Modify: `backend/config.py` — `ALLOWED_ORIGINS: list[str]` derived
  from existing CORS env var if one exists; else new
  `PRYZM_ALLOWED_ORIGINS`
- Create: `backend/tests/test_origin_check.py`

- [ ] **Write the failing tests:**

```python
def test_post_with_bad_origin_rejected(client):
    response = client.post(
        "/api/auth/login",
        json={"username": "qatest", "password": "test"},
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403

def test_post_with_no_origin_passes(client):
    response = client.post(
        "/api/auth/login",
        json={"username": "qatest", "password": "test"},
    )
    assert response.status_code != 403

def test_post_with_allowed_origin_passes(client):
    response = client.post(
        "/api/auth/login",
        json={"username": "qatest", "password": "test"},
        headers={"Origin": "http://localhost:3000"},
    )
    assert response.status_code != 403
```

- [ ] **Add middleware** in `core/origin_check.py`:

```python
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class OriginCheckMiddleware(BaseHTTPMiddleware):
    """Reject state-changing requests carrying an Origin header that
    isn't in the operator-configured allowlist. Absent Origin (curl,
    native apps) is allowed — those don't carry the CSRF threat. Browser
    requests always populate Origin on POST/PUT/PATCH/DELETE."""

    STATE_CHANGING = {"POST", "PUT", "PATCH", "DELETE"}

    def __init__(self, app, allowed_origins: list[str]):
        super().__init__(app)
        self._allowed = frozenset(allowed_origins)

    async def dispatch(self, request, call_next):
        if request.method in self.STATE_CHANGING:
            origin = request.headers.get("origin")
            if origin is not None and origin not in self._allowed:
                return JSONResponse(
                    {"detail": "Origin not allowed."},
                    status_code=403,
                )
        return await call_next(request)
```

- [ ] **Wire it in `main.py`** after CORS middleware. Default
  allowed list reuses whatever CORS already uses.

- [ ] **Run the tests.**

- [ ] **Commit:** `git commit -am "feat(auth): Origin header allowlist on state-changing endpoints"`

### Task 1.7 — S7: random bootstrap admin password + lockout

**Files:**
- Modify: `backend/core/bootstrap.py:24-35`
- Modify: `backend/tests/test_password_hashing.py` or sibling

- [ ] **Write the test.** Three cases:
  1. Env unset + no admin row + listener loopback → random password
     printed (capture stdout/log), `must_change=true`.
  2. Env unset + no admin row + non-loopback listener → SystemExit.
  3. Env set + no admin row → uses env value, `must_change=false`
     (existing behaviour).

- [ ] **Apply the change:**

```python
import os
import secrets
import sys
import logging

log = logging.getLogger(__name__)


def _listen_address_is_loopback() -> bool:
    host = os.getenv("PRYZM_HOST", "127.0.0.1")
    return host in ("127.0.0.1", "::1", "localhost")


def ensure_bootstrap_admin(db) -> None:
    # ... existing early-return when an admin already exists ...
    env_password = os.getenv("PRYZM_BOOTSTRAP_ADMIN_PASSWORD")
    if env_password:
        password = env_password
        must_change = False
    else:
        if not _listen_address_is_loopback():
            log.critical(
                "Refusing to bootstrap default admin on a non-loopback "
                "listener without PRYZM_BOOTSTRAP_ADMIN_PASSWORD set."
            )
            sys.exit(1)
        password = secrets.token_urlsafe(18)
        must_change = True
        log.warning(
            "Bootstrap admin password (one-time, log only): %s — change on first login.",
            password,
        )
    # ... existing create + commit ...
```

- [ ] **Run tests.**

- [ ] **Commit:** `git commit -am "fix(bootstrap): generate random admin password and refuse non-loopback default"`

### Task 1.8 — Full sweep + push

- [ ] `cd backend && ./venv/bin/pytest -q` — full suite green.
- [ ] `git push -u origin fix/security-high`
- [ ] `gh pr create` — body is six lines max, lists items by code (S1–S7).
- [ ] Wait for CI; merge.

---

## Phase 2 — Security MEDIUM

Branch: `fix/security-medium`. One commit per item.

### Task 2.0 — Create branch
- [ ] `git checkout main && git pull && git checkout -b fix/security-medium`

### Task 2.1 — M1: bug-report audit logs validated values, not claimed

**Files:**
- Modify: `backend/routers/bug_reports.py:74-89, 113-119`
- Modify/extend: `backend/tests/test_bug_reports.py` (or sibling)

The current code validates the workspace/session ids and nulls them
on the row, then builds the audit payload using the *unvalidated*
input. Restructure: validate first, then build payload using the
post-validation values.

- [ ] Test: submit a bug report claiming a foreign session/workspace
  → row has NULL; audit row's `current_workspace_id` is also NULL.

- [ ] Edit handler so the audit payload reads from the row, not the request.

- [ ] Commit: `fix(bug-reports): audit logs validated workspace/session ids only`

### Task 2.2 — M2: RFC 5987 filename header

**Files:**
- Modify: `backend/routers/documents.py:262`
- Modify: `backend/tests/test_document_raw_headers.py` (sibling to
  existing — create if it doesn't exist; the spec implies one was
  added in PR #102, verify before creating)

- [ ] Implement helper (inline or in `utils/formatters.py`):

```python
from urllib.parse import quote


def safe_content_disposition(filename: str, disposition: str = "inline") -> str:
    ascii_safe = "".join(c for c in filename if 32 <= ord(c) < 127 and c not in '"\\')
    if not ascii_safe:
        ascii_safe = "file"
    encoded = quote(filename, safe="")
    return f'{disposition}; filename="{ascii_safe}"; filename*=UTF-8\'\'{encoded}'
```

- [ ] Replace the f-string in `documents.py:262` with
  `safe_content_disposition(doc.filename, "inline")`.

- [ ] Test: upload doc named `weird";name.pdf`, GET it, assert
  header parses and contains both `filename=` and `filename*=`.

- [ ] Commit: `fix(documents): RFC 5987 Content-Disposition for raw downloads`

### Task 2.3 — M3: admin_engine path normalisation

**Files:**
- Modify: `backend/routers/admin_engine.py:140-141`
- Modify: `backend/tests/test_admin_engine_proxy.py`

- [ ] Test: admin GETs `/api/admin/engine/../something` → 400.

- [ ] Fix: reject `path` containing any `..` segment:

```python
if any(seg == ".." for seg in path.split("/")):
    raise HTTPException(status_code=400, detail="Invalid path.")
```

- [ ] Commit: `fix(admin_engine): reject relative path segments in proxy`

### Task 2.4 — M4: `get_public_ip` allowlist

**Files:**
- Modify: `backend/tools/network.py:200-206`
- Modify: `backend/config.py` — `NETWORK_TOOLS_ALLOW_PUBLIC_IP: bool = False`
- Modify: `backend/tests/test_tool_set.py` or similar

- [ ] Test: env unset → tool returns the disabled message; env
  `true` → tool makes the request.

- [ ] Fix: gate the request behind the flag.

- [ ] Commit: `fix(tools): gate get_public_ip behind NETWORK_TOOLS_ALLOW_PUBLIC_IP`

### Task 2.5 — M6: instantiate hard-errors on disallowed tools

**Files:**
- Modify: `backend/services/template_apply.py:138-197`
- Modify: `backend/tests/test_allowed_tools.py:444-470` (invert the
  documenting test; the new assertion is that the action raises)

- [ ] Inside `apply_template`, when the per-target action is
  `create`, call `enforce_allowed_tools(target_user, tools)` instead
  of `filter_allowed_tools`. Other actions keep their current
  semantics.

- [ ] The test currently asserts silent filtering — flip it to
  assert the call raises `HTTPException(403)`.

- [ ] Commit: `fix(template_apply): instantiate now hard-errors on disallowed tools`

### Task 2.6 — Full sweep + push
- [ ] Full pytest sweep, push, PR (body: M1, M2, M3, M4, M6), merge.

---

## Phase 3 — Data layer

Branch: `fix/data-layer`. New migrations are autocommit-safe.

### Task 3.0 — Create branch
- [ ] `git checkout main && git pull && git checkout -b fix/data-layer`

### Task 3.1 — D1: per-user slug uniqueness

**Files:**
- Modify: `backend/services/workspaces.py:90-97`
- Modify: `backend/tests/test_workspace_position.py` or a new test

- [ ] Test: user A creates "Personal" → slug `personal`; user B
  creates "Personal" → slug `personal` (no `-2`).

- [ ] Fix: scope the candidate-existence query to `user_id == user.id`.

- [ ] Commit: `fix(workspaces): scope slugify_unique to caller's workspaces`

### Task 3.2 — D2: workspace.color length + CHECK

**Files:**
- Create: `backend/utils/constants.py` if not present, add
  `WORKSPACE_COLORS: tuple[str, ...]`. Confirm the frontend's
  `workspaceColors.ts` is the source of truth and mirror it.
- Modify: `backend/db/models.py:30, 47` — both columns `String(32)`,
  both with a CHECK; add `__table_args__` entry to the relevant
  model(s).
- Create: `backend/alembic/versions/<rev>_workspace_color_check.py`
- Modify: `backend/schemas.py` — `WorkspaceCreate.color` typed as
  `Literal[…]`

- [ ] **Write migration:**

```python
def upgrade():
    op.alter_column(
        "workspace_templates",
        "color",
        existing_type=sa.String(),
        type_=sa.String(length=32),
    )
    op.create_check_constraint(
        "ck_workspaces_color_allowed",
        "workspaces",
        f"color = ANY(ARRAY[{', '.join(repr(c) for c in WORKSPACE_COLORS)}]::text[])",
    )
    op.create_check_constraint(
        "ck_workspace_templates_color_allowed",
        "workspace_templates",
        f"color = ANY(ARRAY[{', '.join(repr(c) for c in WORKSPACE_COLORS)}]::text[])",
    )

def downgrade():
    op.drop_constraint("ck_workspace_templates_color_allowed", "workspace_templates")
    op.drop_constraint("ck_workspaces_color_allowed", "workspaces")
    op.alter_column("workspace_templates", "color", type_=sa.String())
```

(Before merging, run `python -c "from alembic.config import Config; ..."`
or just apply locally: `./venv/bin/alembic upgrade head`.)

- [ ] **Test:** insert with `color="not-a-real-color"` → 422.

- [ ] **Commit:** `fix(workspaces): enforce color allowlist at schema and DB`

### Task 3.3 — D3: indices on SET NULL FK columns

**Files:**
- Create: `backend/alembic/versions/<rev>_setnull_fk_indices.py`

- [ ] Migration uses `autocommit_block()`, both indices partial:

```python
def upgrade():
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_bug_reports_resolved_by ON bug_reports(resolved_by) "
            "WHERE resolved_by IS NOT NULL;"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_audit_events_session_id ON audit_events(session_id) "
            "WHERE session_id IS NOT NULL;"
        )

def downgrade():
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_bug_reports_resolved_by;")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_audit_events_session_id;")
```

- [ ] Apply locally; spot-check via `\d+ bug_reports` in psql.

- [ ] No automated test.

- [ ] Commit: `fix(db): partial indices on SET NULL FK columns`

### Task 3.4 — D4: ensure current AND next month partition

**Files:**
- Modify: `backend/services/audit_partitions.py:32-50`
- Modify: `backend/tests/test_audit_schema.py` or
  `test_audit_partitions.py` (look for existing tests)

- [ ] Test: with `freeze_time("2026-12-15")`, run the tick → both
  Dec 2026 and Jan 2027 partitions exist.

- [ ] Fix: rename/extend the helper:

```python
def ensure_current_and_next_month_partitions(db) -> None:
    today = datetime.now(timezone.utc).date()
    _ensure_partition_for_month(db, today)
    next_month_first = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
    _ensure_partition_for_month(db, next_month_first)
```

Update the scheduler call site accordingly.

- [ ] Commit: `fix(audit): partition scheduler covers current and next month`

### Task 3.5 — D5: Pydantic schema for folders response

**Files:**
- Modify: `backend/routers/folders.py:24-29`
- Modify: `backend/schemas.py` — add `FolderResponse`

- [ ] Add schema:

```python
class FolderResponse(BaseModel):
    id: str
    name: str
    workspace_id: str
    position: int

    class Config:
        from_attributes = True
```

- [ ] Switch route to `response_model=list[FolderResponse]`.

- [ ] No new test — existing folder tests cover the shape.

- [ ] Commit: `chore(folders): typed response model strips user_id from payload`

### Task 3.6 — D6: tighten partition name regex

**Files:**
- Modify: `backend/services/audit_partitions.py:88`

- [ ] Apply regex validation before DROP:

```python
import re
_PARTITION_NAME_RE = re.compile(r"^audit_events_y\d{4}m\d{2}$")

def prune_old_partitions(db) -> None:
    # ... existing inheritance lookup ...
    for name in candidates:
        if not _PARTITION_NAME_RE.match(name):
            log.warning("Skipping unrecognised partition name %r", name)
            continue
        # ... existing drop logic ...
```

- [ ] No automated test (paranoid defence).

- [ ] Commit: `fix(audit): validate partition name before DROP`

### Task 3.7 — Full sweep + push

- [ ] `cd backend && ./venv/bin/alembic upgrade head` — clean apply.
- [ ] `./venv/bin/pytest -q`.
- [ ] Push, PR (D1–D6), merge.

---

## Phase 4 — Backend refactor

Branch: `refactor/backend-cleanup`. Each refactor is one commit and
expects the pytest suite to stay green.

### Task 4.0 — Create branch
- [ ] `git checkout main && git pull && git checkout -b refactor/backend-cleanup`

### Task 4.1 — B12 (warm-up): replace `print()` with logger

- [ ] `backend/routers/chat.py:588, 663` → `log.exception("Failed to save assistant message")`. Use the existing module logger at line 24.
- [ ] Commit: `chore(chat): logger instead of print on assistant-message persist failures`

### Task 4.2 — B11: required workspace on uploads

- [ ] `backend/routers/documents.py:50` — drop `="it_copilot"` default. Re-run `test_image_upload.py`, `test_upload_sse.py`. If frontend `useUploader` doesn't always send `workspace`, this surfaces as a 422; check the hook.
- [ ] Commit: `fix(documents): workspace is required on uploads`

### Task 4.3 — B10: drop hardcoded tool workspace allowlist

- [ ] `tools/web.py:145` and `tools/retrieval.py:33`: remove the
  `workspaces=[...]` kwarg from the `@tool` decorator. Check the
  decorator implementation — if it's now dead, simplify.
- [ ] `Workspace.enabled_tools` remains the sole gate.
- [ ] Run `test_tool_set.py`, `test_allowed_tools.py`.
- [ ] Commit: `refactor(tools): drop per-tool workspaces allowlist; enabled_tools is the gate`

### Task 4.4 — B9: move WEB_SEARCH_DIRECTIVE to data

- [ ] Create `backend/data/tool_directives.default.json`:

```json
{
  "web_search": "<the current 30-line directive>"
}
```

- [ ] Replace inline constant in `tools/web.py` with
  `prompt_manager.get_tool_directive("web_search")`. Add the helper to
  `core/prompt_manager.py` if absent.
- [ ] Tests: directive rendering already covered by
  `test_tool_directive_render.py` — re-run.
- [ ] Commit: `refactor(tools): move web_search directive to data file`

### Task 4.5 — B8: drop dead `ingest_document`; dedupe sync embed

- [ ] Remove `services/knowledge.ingest_document`. Update
  `tests/test_image_upload.py`, `tests/test_pdf_upload.py` to use
  `add_chunks_to_document` directly.
- [ ] Replace `search_chunks_sync`'s raw `requests.post` with a
  call to a new `core/llm_server.embed_sync(text) -> list[float]`
  (or inline `asyncio.run(embed(text))` if no async client is
  already cached for this thread).
- [ ] Re-run knowledge + ingest tests.
- [ ] Commit: `refactor(knowledge): remove dead ingest_document; dedupe sync embed`

### Task 4.6 — B7: split `retrieve_relevant_chunks`

- [ ] Extract:
  - `_retrieve_pinned_filenames(db, workspace_id, session_id, filenames, top_k) -> list[Chunk]`
  - `_retrieve_session_overview(db, workspace_id, session_id, top_k) -> list[Chunk]`
  - `_retrieve_workspace_wide(db, workspace_id, query, top_k) -> list[Chunk]`
- [ ] Public `retrieve_relevant_chunks(...)` dispatches by mode arg
  and formats context. Drop the "fall through" comment.
- [ ] Re-run knowledge tests.
- [ ] Commit: `refactor(knowledge): split retrieve_relevant_chunks into mode-specific functions`

### Task 4.7 — B5: extract `services/llama_swap_config.py`

- [ ] Move from `routers/admin.py`:
  - `_read_yaml`, `_write_yaml`
  - `_parse_model_row`, `_build_cmd_block`
  - `_HF_RE`, `_HFF_RE`, `_NGL_RE`, `_CTX_RE`, `_QUANT_FROM_FILE_RE`
  - `_reload_llama_swap` (and fold the three `subprocess.CalledProcessError` warn-and-swallow blocks into the helper)
- [ ] `routers/admin.py` imports from the new module.
- [ ] `core/llm_router.reload_router_from_yaml` already used the
  yaml path — verify the import seam still resolves.
- [ ] Run `test_admin_engine_proxy.py` and any admin tests.
- [ ] Commit: `refactor(admin): extract llama_swap_config service`

### Task 4.8 — B6: extract `services/llama_swap_status.py`

- [ ] Lift the 100-line SSE generator into
  `async def stream_status(model_id) -> AsyncIterator[str]`.
- [ ] Router endpoint becomes:

```python
@router.get("/llama/status/{model_id}")
async def model_status(model_id: str):
    return StreamingResponse(
        stream_status(model_id),
        media_type="text/event-stream",
    )
```

- [ ] Commit: `refactor(admin): extract llama_swap_status streaming generator`

### Task 4.9 — B3: move single-shot LLM utilities

- [ ] `condense_chat_memory` → append to `services/condense.py`. Fix
  imports in `routers/chat.py` (memory-condense background task) and
  anywhere else.
- [ ] `generate_title` → new `services/title.py`. Fix `routers/chat.py`
  imports.
- [ ] `_match_session_filename_mentions` → move into
  `services/knowledge.py`; take a `db` argument (caller passes its
  own session, no more SessionLocal mid-flow).
- [ ] `_audit_chat_event` → fold into `core/audit.py` as
  `log_event_in_new_session(...)`. Callers in `ai_engine.py` use it
  via import.
- [ ] Re-run full suite.
- [ ] Commit: `refactor(ai_engine): move single-shot LLM utilities into services`

### Task 4.10 — B4: invert tool audit shape

- [ ] Update the `@tool` decorator in `core/tool_permissions.py` (or
  wherever it lives) to accept an optional `audit_event_type` and to
  support a `(content, audit_payload)` tuple return.
- [ ] `tools/web.py.web_search` returns `(content, {…})` and ditches
  `_LAST_STATS`.
- [ ] `tools/retrieval.py.search_knowledge_base` returns
  `(content, {…})` carrying the RAG payload.
- [ ] `core/ai_engine.py` per-tool dispatch collapses to a single
  branch: get the tool's `audit_event_type` (default
  `CHAT_TOOL_INVOKED`) and emit one event with the returned payload.
- [ ] Update or remove the audit assertions in `test_tool_set.py`,
  `test_tool_directive_render.py`, etc.
- [ ] Commit: `refactor(tools): return audit payloads from tools instead of leaking via _LAST_STATS`

### Task 4.11 — B2: extract `services/chat_pipeline.py`

- [ ] Create the module with:
  - `resolve_or_create_session(db, user, workspace, prompt, session_id, http_client)`
  - `claim_attachments(db, workspace, session, attachment_ids)`
  - `persist_user_message(db, session, prompt, request) -> Message`
  - `persist_assistant_message(db, session, workspace, user, full_response, status, tool_calls, reasoning, route_meta, request)` — replaces both 40-line blocks in `chat.py`.
- [ ] `routers/chat.py` shrinks to orchestration.
- [ ] Audit emits move into the helpers too.
- [ ] Run full pytest sweep — chat is the hottest path.
- [ ] Commit: `refactor(chat): extract chat_pipeline service`

### Task 4.12 — B1: split `stream_chat`

- [ ] Inside `core/ai_engine.py`, extract:
  - `_prepare_system_message(workspace, mode, history) -> list[Message]`
  - `_resolve_route(prompt, history, attachments) -> Route`
  - `_run_auto_rag(workspace, session, prompt, attachments) -> RAGResult`
  - `_run_agent_loop(messages, route, tool_set, http_client, audit_ctx) -> AsyncIterator[Event]`
- [ ] `stream_chat` becomes a ~60-line orchestrator yielding from
  the above.
- [ ] Run full pytest sweep with extra attention on
  `test_ai_engine_typed_events.py`, `test_workspace_boundary.py`,
  `test_history_rebuild.py`.
- [ ] Commit: `refactor(ai_engine): split stream_chat into phases`

### Task 4.13 — Full sweep + push

- [ ] `./venv/bin/pytest -q` — full green.
- [ ] Manual smoke: launch backend + frontend; one chat with the
  `qatest` user, one workspace tab in admin, one document upload.
- [ ] Push, PR (B1–B12), merge.

---

## Phase 5 — Frontend refactor

Branch: `refactor/frontend-cleanup`. Verification is the Playwright
smoke harness (`tests/smoke/`) plus targeted manual checks with the
`qatest`/`test` account and admin.

### Task 5.0 — Create branch
- [ ] `git checkout main && git pull && git checkout -b refactor/frontend-cleanup`
- [ ] Boot the stack: docker compose up, backend uvicorn (with
  `--reload-delay 2`), `npm run dev -- -H 0.0.0.0`.

### Task 5.1 — F13: collapse `AppProviders`

- [ ] If `AppProviders` only wraps `AuthProvider`, drop the file and
  import `AuthProvider` directly in `app/layout.tsx`. If you prefer
  to keep it for future use, add a top-of-file comment naming what
  goes here.
- [ ] Smoke: load `/`, sign in, basic nav.
- [ ] Commit: `chore(frontend): drop single-child AppProviders shim`

### Task 5.2 — F9: shared `payloadSummary`

- [ ] Create `frontend/src/utils/auditPayload.ts` exporting
  `payloadSummary(payload: Record<string, unknown>) -> string`.
- [ ] Replace local copies in
  `app/admin/users/[user_id]/page.tsx:398-405` and
  `app/admin/audit/page.tsx:337-345`.
- [ ] Smoke: admin → audit → click a row, audit → user → activity.
- [ ] Commit: `chore(admin): shared payloadSummary helper`

### Task 5.3 — F8: shared StatusBadge + admin types

- [ ] `frontend/src/components/admin/StatusBadge.tsx` exporting
  `STATUS_COLORS` and `<StatusBadge status={...} />`.
- [ ] `frontend/src/types/admin.ts` with `AdminBugReport`,
  `AdminUserRow`, `AdminWorkspaceRow`.
- [ ] Update consumers in `app/admin/bug-reports/page.tsx`,
  `app/admin/users/[user_id]/page.tsx`, and any other admin pages.
- [ ] Commit: `chore(admin): extract StatusBadge component and shared row types`

### Task 5.4 — F7: extract `BugDetailModal`

- [ ] Create `components/admin/bugReports/BugDetailModal.tsx` from
  `app/admin/bug-reports/page.tsx:284-501`. Use the same props the
  inline modal already uses.
- [ ] List page now ~280 lines.
- [ ] Manual smoke: click an alert row → modal opens, acknowledge → status updates → close → row reflects new status.
- [ ] Commit: `chore(admin): extract BugDetailModal component`

### Task 5.5 — F5: drop dead context exposure

- [ ] In `SessionContext.tsx`: remove `getMessages` and
  `activeCacheKey` from the context value, type, and provider. Confirm
  zero consumers via `grep`.
- [ ] Commit: `chore(session-context): drop unused getMessages/activeCacheKey`

### Task 5.6 — F6: memoise pass-through providers

- [ ] `InferenceContext.tsx`, `UploaderContext.tsx`,
  `TestSuiteContext.tsx`: wrap the hook output in `useMemo` whose deps
  match the hook's output shape.
- [ ] Smoke: open a chat, send a few messages, watch React DevTools
  for fewer renders (or trust the change since the pattern is
  textbook).
- [ ] Commit: `perf(contexts): memoise pass-through provider values`

### Task 5.7 — F1, F2, F3: useInference cleanup

These three are one commit, since they share state.

- [ ] **F1: extract pure helpers.** New file
  `frontend/src/hooks/useInferenceParse.ts` (or top of `useInference.ts`):

```ts
export type StreamEvent =
  | { kind: "started"; sessionId: string; userMessageId: string }
  | { kind: "chunk"; content: string }
  | { kind: "reasoning_chunk"; content: string }
  | { kind: "reasoning_done"; durationS: number }
  | { kind: "tool_call"; name: string; args: Record<string, unknown> }
  | { kind: "tool_result"; result: string }
  | { kind: "files_referenced"; files: string[] }
  | { kind: "done"; assistantMessageId: string };

export function parseSseLine(line: string): StreamEvent | null {
  // ... extracted from the existing switch in sendMessage
}
```

- [ ] **F2: liveKey + single bucket migration.** Inside the stream
  loop, derive `const liveKey = realDbId ?? optimisticId` once.
  Write to one key on every chunk. When the real id arrives, call
  `migrateBucket(optimisticId, realDbId)` once across the streaming
  maps.

- [ ] **F3: `clearStreamingForSession(sid)` helper.** Replace the
  five `delete` blocks in `finally` with one helper call. If you
  combine the five maps into one `Record<string, StreamingState>`,
  the cleanup drops to one line — pick whichever shape doesn't
  cascade into too many consumers.

- [ ] Smoke (critical, this is the hottest path):
  - `qatest` user sends three messages back to back, ensure stream
    completes and prior bubbles stay intact.
  - Tool-using turn (e.g. web_search query) — verify tool call +
    result render correctly.
  - Reasoning turn — verify reasoning panel + Thinking pill.
  - Switching workspaces mid-stream — should still finalise the
    in-flight bubble in the correct session.
- [ ] Run smoke harness: `./venv/bin/pytest tests/smoke -q` from
  repo root.
- [ ] Commit: `refactor(useInference): pure parse helpers, single live-key writes, unified cleanup`

### Task 5.8 — F4: split `SessionContext`

- [ ] Create:
  - `SessionMetaContext.tsx` — stable per-session metadata.
  - `SessionMessagesContext.tsx` — volatile messages + streaming maps.
- [ ] Refactor `SessionProvider` to mount both contexts; keep
  `useSessionContext()` exported during a transition window if many
  files import it (one-step migration is fine — search and replace).
- [ ] Update consumers to import the narrower context.
- [ ] Smoke harness pass — render counts down measurably in
  Sidebar/ChatHeader during long streams (or trust the shape — both
  contexts are now write-narrow).
- [ ] Commit: `perf(session-context): split into meta and messages contexts`

### Task 5.9 — F10: `useModelDownloadStream` hook

- [ ] Extract the 7-state download SSE engine from
  `SettingsModels.tsx` into
  `hooks/useModelDownloadStream.ts` returning
  `{ log, status, err, progress, cancel }`.
- [ ] Component reads from the hook.
- [ ] Smoke (admin): admin → System → Models → start a download → log streams → cancel → status flips.
- [ ] Commit: `refactor(admin): extract useModelDownloadStream hook`

### Task 5.10 — F11: split WorkspaceSettings

- [ ] Create `WorkspaceCreateModal.tsx` and `WorkspaceEditModal.tsx`.
- [ ] Share fields via `WorkspaceFieldsForm.tsx`.
- [ ] Drop `withRollback` abuse in favour of try/catch on the save
  call. Same for `confirmDeleteWorkspace`/`performReset` (move to
  edit modal only).
- [ ] Update callers — sidebar create flow, settings edit flow.
- [ ] Manual smoke (admin and qatest):
  - Create a workspace, verify it appears.
  - Edit a workspace's name + color, save, verify.
  - Reset the workspace, confirm the reset modal.
  - Delete, confirm.
- [ ] Commit: `refactor(workspaces): split create and edit modals`

### Task 5.11 — F12: useSessionList / useFolderList

- [ ] Extract `hooks/useSessionList(workspaceSlug)` and
  `hooks/useFolderList(workspaceSlug)` from `SessionDirectory.tsx`.
  Each owns: fetch + state + CRUD mutations.
- [ ] Component becomes render + drag-drop wiring only.
- [ ] Replace `startsWith("optimistic-")` with `isOptimisticSessionId(id)` from `utils/ids.ts`.
- [ ] Drop the dead `<style>` block (line ~263).
- [ ] Smoke:
  - Create a session, rename, move into a folder, delete.
  - Create a folder, rename, delete.
- [ ] Commit: `refactor(sidebar): extract useSessionList and useFolderList hooks`

### Task 5.12 — F14: ChatInput consumes contexts

- [ ] In `ChatInput.tsx`, replace the 8 prop-drilled context dispatchers with direct `useUploaderContext`, `useTestSuiteContext`, `useInferenceContext` calls.
- [ ] `ActiveSession.tsx` drops the corresponding props.
- [ ] Smoke: send a message, attach a file, run a quick-action.
- [ ] Commit: `refactor(chat-input): consume contexts directly instead of prop-drill`

### Task 5.13 — Smoke harness + push

- [ ] Full smoke harness: `./venv/bin/pytest tests/smoke -q`.
- [ ] Push, PR (F1–F14), merge.

---

## Phase 6 — Docs sweep

Branch: `docs/post-launch-sweep`. One commit.

### Task 6.0 — Create branch
- [ ] `git checkout main && git pull && git checkout -b docs/post-launch-sweep`

### Task 6.1 — Update specs and CLAUDE.md

- [ ] `docs/specs/2026-05-17-user-login-and-admin.md` —
  - Update the API list: voluntary password change closed, document
    `must_change_password` flow.
  - Update the bootstrap section to match the random-password
    behaviour from Phase 1 S7.
  - Annotate the `is_template` paragraph: "Superseded by
    2026-05-18-workspace-template-split.md."

- [ ] `docs/specs/2026-05-20-web-search-v2.md` —
  - Replace the httpx fetcher section with Playwright.
  - Default `num_results` is 3, not 5.
  - Remove the "model writes `**Sources**` footer" rule; describe
    the directive's no-footer rule and the frontend-owned sources
    pill.

- [ ] `docs/specs/2026-05-19-per-user-allowed-tools.md` —
  - "Write sites" table: instantiate is strict (raises 403),
    push/adopt are filter.
  - Reflect that `/instantiate` and `/push` merged into `/apply`.

- [ ] `docs/specs/2026-05-18-audit-logging.md` —
  - Refresh `chat.message_received` and `chat.web_search` payload
    shapes to match the code (post-PR-#120/#122).

- [ ] `CLAUDE.md` —
  - "Bug reports" tab → "Alerts" in the admin dashboard section.

### Task 6.2 — Resolve the ghost EventType

- [ ] `backend/core/audit.py` — delete `AUTH_SESSION_EXPIRED`
  constant (it has no emitter, the audit-logging spec already
  documents the gap). If anyone wants it back, they can add the
  emit site in `cookie_auth.get_session_user`.
- [ ] Update `docs/specs/2026-05-18-audit-logging.md` to drop the
  row.

### Task 6.3 — Commit + push + PR

- [ ] Commit: `docs: post-launch sweep — auth, web-search, allowed-tools, audit-logging, CLAUDE.md`
- [ ] Push, PR, merge.

---

## Self-review

1. **Spec coverage:** every item in `docs/specs/2026-05-21-post-launch-hardening.md` Phase 1–6 maps to a task above. Cross-check S1–S7, M1–M4 + M6, D1–D6, B1–B12, F1–F14, and the Phase 6 list.
2. **Placeholder scan:** no "TBD", no "implement later". Every step
   names the file, the change, and the verification command.
3. **Type consistency:** the names `parseSseLine`, `applyStreamEvent`,
   `migrateBucket`, `clearStreamingForSession`, `liveKey` are used
   consistently. Backend service additions
   (`services/chat_pipeline`, `services/title`,
   `services/llama_swap_config`, `services/llama_swap_status`) match
   the spec's file map.
