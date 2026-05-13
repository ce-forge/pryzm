# Phase 2 — Auth + Workspace Boundary Enforcement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Implementation agents must apply Karpathy guidelines: minimum code, no speculative abstractions, surgical changes, verifiable success criteria.

**Goal:** Close the no-auth and cross-workspace mutation gaps. Single shared bearer-token gate via env var; workspace-scoped boundary enforcement on every id-keyed route. Backend-heavy work plus a small frontend wrapper.

**Architecture:** A FastAPI dependency reads `Authorization: Bearer <token>`, constant-time compares against `settings.PRYZM_API_TOKEN`, returns 401 on mismatch. A second dependency `verify_workspace_owns` looks up id-keyed resources and 404s if they belong to another workspace (404 not 403 — no info leakage). Frontend gets a single `fetch` wrapper that injects the header automatically and an absent-token gate. No user model, no JWT, no rotation, no per-user ACL — that's a future phase.

**Tech stack:** FastAPI, SQLAlchemy (sync), `hmac.compare_digest` from stdlib for constant-time compare. No new dependencies.

**Spec reference:** [`docs/specs/2026-05-14-codebase-remediation.md`](../specs/2026-05-14-codebase-remediation.md) — read the "Phase 2 — Auth + Workspace Boundary Enforcement" section before starting.

**Branch:** `refactor/phase-2-auth-boundaries` (cut from main after Phase 1's squash merge).

---

## File Map

### Created
- `backend/core/auth.py` — `require_token` dependency + helpers.
- `backend/core/workspace_access.py` — `verify_workspace_owns` dependency and resource-lookup helpers.
- `backend/tests/test_auth.py` — pytest unit tests for `require_token`.
- `backend/tests/test_workspace_boundary.py` — pytest tests for cross-workspace 404 behavior.
- `backend/tests/smoke/__init__.py` — empty marker.
- `backend/tests/smoke/test_auth_smoke.py` — HTTP-level smoke probes that exercise the full request path (TestClient).
- `frontend/src/utils/apiClient.ts` — single global fetch wrapper that injects `Authorization` header.
- `frontend/src/components/TokenGate.tsx` — UI shown when no token is configured.

### Modified
- `backend/config.py` — add `PRYZM_API_TOKEN` setting.
- `backend/main.py` — register `require_token` at the include_router level for chat + workspaces routers (skips /health).
- `backend/routers/chat.py` — add `verify_workspace_owns` to id-keyed routes (PATCH/DELETE messages, truncate, attachment claim).
- `backend/routers/workspaces.py` — reset endpoint rejects non-builtin with 400.
- `frontend/src/components/Settings.tsx` — add token input field, persist to localStorage.
- `frontend/src/app/page.tsx` (or root layout) — render `<TokenGate>` when no token, else children.
- All `frontend/src/hooks/*.ts` and `frontend/src/components/*.tsx` that call `fetch` directly — replace with the `apiClient` wrapper. This is mechanical search-and-replace.
- `.env` (you'll do this manually before testing) — set `PRYZM_API_TOKEN=<your-token-here>`.

### Untouched
- `backend/db/models.py` (no schema changes in Phase 2).
- `backend/alembic/` (no migrations).
- `backend/services/`, `backend/tools/`, `backend/core/ai_engine.py`, `backend/core/prompt_manager.py`.

---

## Pre-flight (do once before Task 0)

1. **Pick a token.** Generate a sufficiently random string. 32 hex chars is fine:

   ```bash
   python3 -c "import secrets; print(secrets.token_hex(32))"
   ```

   Save the value — you'll add it to `.env` after Task 0 lands.

2. **Confirm Phase 1 state.** You should be on `refactor/phase-2-auth-boundaries`, and `main` should already have Phase 1 merged.

   ```bash
   git branch --show-current   # → refactor/phase-2-auth-boundaries
   git log --oneline main -3   # → top entry "Phase 1 — schema foundations (...)"
   ```

---

## Task 0 — `PRYZM_API_TOKEN` config + `require_token` dependency

**Files:**
- Modify: `backend/config.py` (add `PRYZM_API_TOKEN` setting).
- Create: `backend/core/auth.py` (the dependency).
- Create: `backend/tests/test_auth.py` (unit tests).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_auth.py`:

```python
"""Unit tests for require_token dependency.

These tests exercise the dependency function directly (no HTTP layer) to keep
the assertions tight. The HTTP-level smoke probes in tests/smoke/ verify the
end-to-end behavior.
"""
import pytest
from fastapi import HTTPException

from core.auth import require_token


def test_require_token_accepts_correct_bearer(monkeypatch):
    monkeypatch.setattr("config.settings.PRYZM_API_TOKEN", "test-secret-token")
    # Simulate FastAPI passing the dependency the resolved header value.
    require_token(authorization="Bearer test-secret-token")  # must not raise


def test_require_token_rejects_missing_header(monkeypatch):
    monkeypatch.setattr("config.settings.PRYZM_API_TOKEN", "test-secret-token")
    with pytest.raises(HTTPException) as exc:
        require_token(authorization=None)
    assert exc.value.status_code == 401


def test_require_token_rejects_wrong_token(monkeypatch):
    monkeypatch.setattr("config.settings.PRYZM_API_TOKEN", "test-secret-token")
    with pytest.raises(HTTPException) as exc:
        require_token(authorization="Bearer wrong-token")
    assert exc.value.status_code == 401


def test_require_token_rejects_non_bearer_scheme(monkeypatch):
    monkeypatch.setattr("config.settings.PRYZM_API_TOKEN", "test-secret-token")
    with pytest.raises(HTTPException) as exc:
        require_token(authorization="Basic dGVzdDp0ZXN0")
    assert exc.value.status_code == 401


def test_require_token_uses_constant_time_compare(monkeypatch):
    """hmac.compare_digest avoids timing attacks. We don't test timing
    directly (flaky); we just verify the implementation imports hmac."""
    import core.auth
    import hmac
    assert hmac.compare_digest in core.auth.__dict__.values() or \
           any("compare_digest" in str(o) for o in core.auth.__dict__.values()) or \
           "compare_digest" in open(core.auth.__file__).read()
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /home/orbital/projects/pryzm/backend
./venv/bin/pytest tests/test_auth.py -v
```

Expected: `ModuleNotFoundError: No module named 'core.auth'`.

- [ ] **Step 3: Add the config setting**

In `backend/config.py`, add to the `Settings` class alongside the other top-level fields:

```python
class Settings(BaseSettings):
    PROJECT_NAME: str = "DaiNamik Pryzm"
    VERSION: str = "1.0.0"

    DB_USER: str
    DB_PASSWORD: str
    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 5432
    DB_NAME: str

    # ... existing fields ...

    # Shared bearer token. Reads Authorization: Bearer <PRYZM_API_TOKEN>.
    # This is the gate, not a user system. The full multi-user auth model is
    # a future phase.
    PRYZM_API_TOKEN: str

    # ... rest unchanged ...
```

Note `PRYZM_API_TOKEN` has no default — pydantic will error at import time if the env var is missing, which is the right shape for a required secret.

- [ ] **Step 4: Implement the dependency**

Create `backend/core/auth.py`:

```python
"""Bearer-token authentication dependency.

Single shared token configured via PRYZM_API_TOKEN env var. Not a user system.
"""
import hmac
from typing import Annotated, Optional

from fastapi import Header, HTTPException, status

from config import settings


_BEARER_PREFIX = "Bearer "


def require_token(
    authorization: Annotated[Optional[str], Header()] = None,
) -> None:
    """FastAPI dependency. Raises 401 if the bearer token is missing or wrong.

    Constant-time compares with hmac.compare_digest to avoid timing attacks.
    """
    if authorization is None or not authorization.startswith(_BEARER_PREFIX):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header.",
        )

    presented = authorization[len(_BEARER_PREFIX):]
    if not hmac.compare_digest(presented, settings.PRYZM_API_TOKEN):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token.",
        )
```

- [ ] **Step 5: Wire the dependency at the router level**

In `backend/main.py`, replace:

```python
app.include_router(health.router)
app.include_router(workspaces.router)
app.include_router(chat.router)
```

with:

```python
from core.auth import require_token

app.include_router(health.router)
app.include_router(workspaces.router, dependencies=[Depends(require_token)])
app.include_router(chat.router, dependencies=[Depends(require_token)])
```

Add `from fastapi import Depends` if not already imported.

**Note:** `dependencies=[...]` at the router level applies the dependency to every route in that router. `/health` stays exempt because it's on a different router with no dependency. This is cleaner than decorating every route individually.

- [ ] **Step 6: Set the env var locally so the backend can start**

Edit `.env` at the repo root:

```
PRYZM_API_TOKEN=<the-token-you-generated-in-preflight>
```

- [ ] **Step 7: Verify tests pass**

```bash
cd /home/orbital/projects/pryzm/backend
./venv/bin/pytest tests/test_auth.py tests/test_migrations_smoke.py -v
```

Expected: all auth tests pass; migration smoke tests still pass.

Also verify the backend starts and `/health` is still accessible without a token, while another endpoint demands one:

```bash
curl -i http://127.0.0.1:8000/health                # → 200
curl -i http://127.0.0.1:8000/workspaces            # → 401
curl -i -H "Authorization: Bearer <your-token>" http://127.0.0.1:8000/workspaces   # → 200
```

If the uvicorn process from earlier in the session is still running, kill and restart it so the env-var change takes effect.

- [ ] **Step 8: Commit**

```bash
git add backend/config.py backend/core/auth.py backend/main.py backend/tests/test_auth.py
git commit -m "feat(auth): bearer-token gate via PRYZM_API_TOKEN."
```

---

## Task 1 — `verify_workspace_owns` boundary verifier

**Files:**
- Create: `backend/core/workspace_access.py`
- Create: `backend/tests/test_workspace_boundary.py`

Cross-workspace access returns **404, not 403** — see spec for the info-leakage rationale.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_workspace_boundary.py`:

```python
"""Tests for verify_workspace_owns dependency."""
import pytest
from fastapi import HTTPException

from core.workspace_access import verify_workspace_owns
from db import models
from sqlalchemy.orm import Session


def _seed_two_workspaces_with_one_message(db: Session):
    """Helper: creates two workspaces, each with one session and one message.
    Returns (ws_a, ws_b, msg_in_a)."""
    ws_a = models.Workspace(id="ws-a", slug="ws-a", display_name="A",
                            system_prompt="", enabled_tools=[], is_builtin=False,
                            engine_config={"backend": "ollama", "model": "gemma4:e4b"})
    ws_b = models.Workspace(id="ws-b", slug="ws-b", display_name="B",
                            system_prompt="", enabled_tools=[], is_builtin=False,
                            engine_config={"backend": "ollama", "model": "gemma4:e4b"})
    sess_a = models.Session(id="sess-a", workspace_id="ws-a", title="t")
    msg_a = models.Message(id="msg-a", session_id="sess-a", role="user", content="x")
    db.add_all([ws_a, ws_b, sess_a, msg_a])
    db.commit()
    return ws_a, ws_b, msg_a


def test_owns_returns_resource_when_workspace_matches(db_session):
    ws_a, ws_b, msg = _seed_two_workspaces_with_one_message(db_session)
    result = verify_workspace_owns(
        resource_id="msg-a", model=models.Message, workspace_id="ws-a", db=db_session
    )
    assert result.id == "msg-a"


def test_owns_404s_when_cross_workspace(db_session):
    ws_a, ws_b, msg = _seed_two_workspaces_with_one_message(db_session)
    # msg-a belongs to ws-a; query as ws-b → 404.
    with pytest.raises(HTTPException) as exc:
        verify_workspace_owns(
            resource_id="msg-a", model=models.Message, workspace_id="ws-b", db=db_session
        )
    assert exc.value.status_code == 404


def test_owns_404s_when_resource_missing(db_session):
    ws_a, ws_b, msg = _seed_two_workspaces_with_one_message(db_session)
    with pytest.raises(HTTPException) as exc:
        verify_workspace_owns(
            resource_id="nope", model=models.Message, workspace_id="ws-a", db=db_session
        )
    assert exc.value.status_code == 404
```

This test uses a `db_session` fixture you'll need to add to `conftest.py`. See Step 3.

- [ ] **Step 2: Run to verify failure**

```bash
cd /home/orbital/projects/pryzm/backend
./venv/bin/pytest tests/test_workspace_boundary.py -v
```

Expected: `ModuleNotFoundError` (the file doesn't exist yet).

- [ ] **Step 3: Add a `db_session` fixture to conftest.py**

Append to `backend/tests/conftest.py`:

```python
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def db_session(db_at_head):
    """A SQLAlchemy Session attached to the migrated test DB."""
    engine = db_at_head
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
```

The fixture yields a Session bound to a fresh test DB at head, then closes it.

- [ ] **Step 4: Implement the verifier**

Create `backend/core/workspace_access.py`:

```python
"""Workspace boundary verification.

A reusable dependency that looks up an id-keyed resource and 404s if it
belongs to another workspace. Returning 404 rather than 403 avoids leaking
whether the resource exists in another workspace.
"""
from typing import Type, TypeVar

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from db.models import Base


T = TypeVar("T", bound=Base)


def verify_workspace_owns(
    resource_id: str,
    model: Type[T],
    workspace_id: str,
    db: Session,
) -> T:
    """Return the resource if it exists AND belongs to workspace_id.
    Raise 404 otherwise.

    The model must have a workspace_id attribute. For models that don't (e.g.,
    Message, which is scoped via session), use a model-specific verifier in
    routers/chat.py.
    """
    resource = db.query(model).filter(model.id == resource_id).first()
    if resource is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if getattr(resource, "workspace_id", None) != workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return resource
```

For `Message`, which doesn't have a direct `workspace_id` (it's scoped via `session_id` → `Session.workspace_id`), the routers will use a small helper that joins through Session. We won't add that to the generic verifier — Karpathy #2.

- [ ] **Step 5: Run tests**

```bash
cd /home/orbital/projects/pryzm/backend
./venv/bin/pytest tests/test_workspace_boundary.py -v
```

Expected: 3 pass.

- [ ] **Step 6: Commit**

```bash
git add backend/core/workspace_access.py backend/tests/conftest.py backend/tests/test_workspace_boundary.py
git commit -m "feat(auth): verify_workspace_owns dependency with 404-on-mismatch."
```

---

## Task 2 — Apply workspace scoping to id-keyed routes

**Files:**
- Modify: `backend/routers/chat.py`

The routes that today take an id without checking workspace ownership:

| Route | Today | After this task |
|---|---|---|
| `PATCH /messages/{id}` | unscoped | 404 if message's session isn't in caller's workspace |
| `DELETE /messages/{id}` | unscoped | same |
| `DELETE /sessions/{id}/truncate/{message_id}` | unscoped | same |
| Attachment claim inside `POST /analyze` | unscoped | document must belong to caller's workspace |

These all need a small helper because Message doesn't have a direct workspace_id — it goes via `session.workspace_id`.

- [ ] **Step 1: Write the failing smoke test**

The full HTTP-level test goes in `tests/smoke/test_auth_smoke.py` (Task 5). For this task, extend `test_workspace_boundary.py` with a router-level integration check:

```python
def test_message_lookup_via_session_workspace(db_session):
    """Verify the message-scope helper resolves through session.workspace_id."""
    from routers.chat import _message_in_workspace_or_404
    ws_a, ws_b, msg = _seed_two_workspaces_with_one_message(db_session)
    # Caller is ws-a → msg-a found.
    result = _message_in_workspace_or_404("msg-a", "ws-a", db_session)
    assert result.id == "msg-a"
    # Caller is ws-b → 404 (info-leak protection).
    with pytest.raises(HTTPException) as exc:
        _message_in_workspace_or_404("msg-a", "ws-b", db_session)
    assert exc.value.status_code == 404
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /home/orbital/projects/pryzm/backend
./venv/bin/pytest tests/test_workspace_boundary.py::test_message_lookup_via_session_workspace -v
```

Expected: ImportError on `_message_in_workspace_or_404`.

- [ ] **Step 3: Add the message helper to `routers/chat.py`**

Near the top of `routers/chat.py`, add:

```python
def _message_in_workspace_or_404(message_id: str, workspace_id: str, db: Session):
    """Return the message if it belongs to a session in workspace_id, else 404.
    Message has no direct workspace_id; we join through Session.

    Returning 404 (not 403) avoids leaking whether the message exists in
    another workspace.
    """
    msg = (
        db.query(models.Message)
        .join(models.Session, models.Message.session_id == models.Session.id)
        .filter(
            models.Message.id == message_id,
            models.Session.workspace_id == workspace_id,
        )
        .first()
    )
    if msg is None:
        raise HTTPException(status_code=404)
    return msg
```

- [ ] **Step 4: Apply the helper to the four routes**

In `routers/chat.py:421` (`PATCH /messages/{message_id}`), at the top of the body:

```python
@router.patch("/messages/{message_id}")
def edit_message(message_id: str, body: MessageEditPayload,
                 workspace: str = Query(...), db: Session = Depends(get_db)):
    workspace_obj = _resolve_workspace_or_404(workspace, db)
    msg = _message_in_workspace_or_404(message_id, workspace_obj.id, db)
    # ... rest of the existing implementation, using `msg` instead of re-querying ...
```

Same shape for `DELETE /messages/{message_id}` (line 442), `DELETE /sessions/{session_id}/truncate/{message_id}` (line 507).

For the **attachment claim** inside `POST /analyze`: the existing code does `Document.id.in_(request.attachments)` unscoped (per the spec audit, `routers/chat.py:151-158`). Update to filter by workspace_id:

```python
# Before:
db.query(models.Document).filter(models.Document.id.in_(request.attachments)).update(
    {"session_id": chat_session.id}, synchronize_session=False
)

# After:
db.query(models.Document).filter(
    models.Document.id.in_(request.attachments),
    models.Document.workspace_id == workspace_obj.id,
).update({"session_id": chat_session.id}, synchronize_session=False)
```

The `workspace_obj` variable should already be in scope from the slug resolution earlier in the function. If not, resolve it via the same `_resolve_workspace_or_404` helper.

- [ ] **Step 5: Verify tests pass**

```bash
cd /home/orbital/projects/pryzm/backend
./venv/bin/pytest tests/ -v
```

Expected: all tests pass (including the new boundary test).

- [ ] **Step 6: Commit**

```bash
git add backend/routers/chat.py backend/tests/test_workspace_boundary.py
git commit -m "feat(auth): scope id-keyed routes to workspace (404 on cross-workspace)."
```

---

## Task 3 — Reset endpoint hardening

**Files:**
- Modify: `backend/routers/workspaces.py`

`POST /workspaces/{slug}/reset` already requires the bearer token (via Task 0's router-level dependency). Now also reject the reset if the workspace is not a builtin (`is_builtin = false`).

- [ ] **Step 1: Add a smoke test (or extend test_workspace_boundary.py)**

Append to `backend/tests/test_workspace_boundary.py`:

```python
def test_reset_rejects_non_builtin(db_session):
    """Reset endpoint must reject non-builtin workspaces with 400."""
    from routers.workspaces import _validate_resettable
    ws_a, ws_b, _ = _seed_two_workspaces_with_one_message(db_session)
    # ws-a is is_builtin=False per the seed → reject.
    with pytest.raises(HTTPException) as exc:
        _validate_resettable(ws_a)
    assert exc.value.status_code == 400


def test_reset_accepts_builtin(db_session):
    from routers.workspaces import _validate_resettable
    ws_builtin = models.Workspace(
        id="ws-builtin", slug="builtin", display_name="X", system_prompt="",
        enabled_tools=[], is_builtin=True,
        engine_config={"backend": "ollama", "model": "gemma4:e4b"},
    )
    db_session.add(ws_builtin)
    db_session.commit()
    _validate_resettable(ws_builtin)  # must not raise
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /home/orbital/projects/pryzm/backend
./venv/bin/pytest tests/test_workspace_boundary.py::test_reset_rejects_non_builtin -v
```

Expected: ImportError on `_validate_resettable`.

- [ ] **Step 3: Implement the guard**

At the top of `backend/routers/workspaces.py`, add:

```python
def _validate_resettable(workspace: models.Workspace) -> None:
    """Raise 400 if the workspace is not a builtin."""
    if not workspace.is_builtin:
        raise HTTPException(
            status_code=400,
            detail="Reset is only allowed for builtin workspaces.",
        )
```

In the existing reset route (`POST /workspaces/{slug}/reset`, line 188), call it after resolving the workspace:

```python
@router.post("/workspaces/{slug}/reset", response_model=WorkspaceResponse)
def reset_workspace(slug: str, db: Session = Depends(get_db)):
    workspace = db.query(models.Workspace).filter(models.Workspace.slug == slug).first()
    if workspace is None:
        raise HTTPException(status_code=404)
    _validate_resettable(workspace)
    # ... rest of the existing reset logic ...
```

- [ ] **Step 4: Verify tests pass**

```bash
cd /home/orbital/projects/pryzm/backend
./venv/bin/pytest tests/ -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/routers/workspaces.py backend/tests/test_workspace_boundary.py
git commit -m "feat(auth): reset endpoint rejects non-builtin workspaces."
```

---

## Task 4 — Frontend token UX + global fetch wrapper

**Files:**
- Create: `frontend/src/utils/apiClient.ts`
- Create: `frontend/src/components/TokenGate.tsx`
- Modify: `frontend/src/components/Settings.tsx`
- Modify: `frontend/src/app/page.tsx` (or root layout) — render TokenGate when no token
- Modify: every file that calls `fetch(...)` directly — replace with `apiClient`

This task is mostly mechanical. The wrapper has one job: inject the Authorization header.

- [ ] **Step 1: Create the wrapper**

Create `frontend/src/utils/apiClient.ts`:

```typescript
import { APP_CONFIG } from "./constants";

const TOKEN_STORAGE_KEY = "pryzm_api_token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_STORAGE_KEY);
}

export function setToken(token: string): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(TOKEN_STORAGE_KEY, token);
}

export function clearToken(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(TOKEN_STORAGE_KEY);
}

/**
 * Wraps fetch with the Authorization header. Pass a path (e.g. "/sessions")
 * — the wrapper prepends APP_CONFIG.API_URL.
 *
 * On 401, the wrapper does NOT auto-redirect; callers decide how to handle.
 */
export async function apiFetch(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const token = getToken();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return fetch(`${APP_CONFIG.API_URL}${path}`, { ...init, headers });
}
```

- [ ] **Step 2: Create the TokenGate component**

Create `frontend/src/components/TokenGate.tsx`:

```tsx
import { useState } from "react";
import { setToken } from "@/utils/apiClient";

export function TokenGate({ onConfigured }: { onConfigured: () => void }) {
  const [value, setValue] = useState("");

  return (
    <div className="flex h-screen items-center justify-center bg-zinc-950 text-zinc-100">
      <div className="w-full max-w-md space-y-4 p-8">
        <h1 className="text-xl font-semibold">Configure API token</h1>
        <p className="text-sm text-zinc-400">
          Pryzm requires a shared bearer token. Get the value from{" "}
          <code className="rounded bg-zinc-800 px-1 py-0.5">PRYZM_API_TOKEN</code>{" "}
          in the backend&apos;s <code>.env</code> file.
        </p>
        <input
          type="password"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="Paste token"
          className="w-full rounded border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm"
        />
        <button
          onClick={() => {
            if (value.trim()) {
              setToken(value.trim());
              onConfigured();
            }
          }}
          disabled={!value.trim()}
          className="w-full rounded bg-blue-600 px-4 py-2 text-sm font-medium hover:bg-blue-500 disabled:opacity-50"
        >
          Save and continue
        </button>
      </div>
    </div>
  );
}
```

(Match the styling conventions used elsewhere in the codebase — adjust class names if Tailwind isn't the chosen styling.)

- [ ] **Step 3: Render TokenGate at the app root**

Modify `frontend/src/app/page.tsx` to render TokenGate when no token is set. The exact integration depends on the existing structure; a minimal pattern:

```tsx
"use client";
import { useState, useEffect } from "react";
import { getToken } from "@/utils/apiClient";
import { TokenGate } from "@/components/TokenGate";
// ... other imports ...

export default function Home() {
  const [hasToken, setHasToken] = useState<boolean | null>(null);

  useEffect(() => {
    setHasToken(!!getToken());
  }, []);

  if (hasToken === null) return null; // SSR/hydration
  if (!hasToken) return <TokenGate onConfigured={() => setHasToken(true)} />;

  // existing app render
  return (
    <ChatProvider>
      {/* ... */}
    </ChatProvider>
  );
}
```

- [ ] **Step 4: Add the token field to Settings.tsx**

In `frontend/src/components/Settings.tsx`, add a section for the API token. Use the same `getToken`/`setToken` helpers from `apiClient`. Mask the value (`type="password"`) and provide a "regenerate" hint linking to the backend's `.env` file.

- [ ] **Step 5: Replace direct fetch calls with apiFetch**

Grep all frontend files for `fetch(`:

```bash
cd /home/orbital/projects/pryzm/frontend
grep -rn "fetch(" src/ --include="*.ts" --include="*.tsx" | grep -v "apiFetch\|apiClient" | head -40
```

Replace each call:

```typescript
// Before
fetch(`${API_URL}/sessions`, { method: "GET" })

// After
import { apiFetch } from "@/utils/apiClient";
apiFetch("/sessions", { method: "GET" })
```

Notes:
- The wrapper prepends `APP_CONFIG.API_URL`, so don't pass the URL — just the path.
- Don't change the response-handling code; it's still a normal `Response`.
- For multipart uploads (`/upload`), let the browser set the Content-Type boundary automatically — don't set it manually.

This is the most mechanical step. Use search-and-replace carefully; one file at a time is fine.

- [ ] **Step 6: Verify in the browser**

```bash
# Backend restart to pick up the auth change
cd backend && ./venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Frontend (in another terminal)
cd frontend && npm run dev -- -H 0.0.0.0
```

1. Open `http://localhost:3000` — TokenGate should appear.
2. Paste your token, click Save.
3. App loads as normal — every API call carries the Authorization header (verify in Network tab).
4. Open Settings, confirm the token field shows the masked value.
5. Click "Clear token" (or delete localStorage) and reload — TokenGate appears again.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/utils/apiClient.ts \
        frontend/src/components/TokenGate.tsx \
        frontend/src/components/Settings.tsx \
        frontend/src/app/page.tsx \
        frontend/src/hooks/ \
        frontend/src/components/
git commit -m "feat(auth): frontend token gate + apiFetch wrapper."
```

---

## Task 5 — HTTP smoke probes

**Files:**
- Create: `backend/tests/smoke/__init__.py` (empty).
- Create: `backend/tests/smoke/test_auth_smoke.py`.

These run against the real FastAPI app via TestClient. They exercise the wire protocol — what an actual misbehaving client would see — not the helper functions directly.

- [ ] **Step 1: Write the smoke probes**

Create `backend/tests/smoke/__init__.py` (empty).

Create `backend/tests/smoke/test_auth_smoke.py`:

```python
"""HTTP-level smoke probes for Phase 2 auth + workspace boundary.

These exercise the full request path via FastAPI's TestClient. Use them as a
last line of defense — the unit tests in tests/test_auth.py and
tests/test_workspace_boundary.py are tighter; this file confirms the wire
protocol matches.
"""
import pytest
from fastapi.testclient import TestClient

from main import app
from config import settings


@pytest.fixture
def client(db_at_head, monkeypatch):
    """TestClient with a known token and a migrated DB."""
    monkeypatch.setattr(settings, "PRYZM_API_TOKEN", "smoke-test-token")
    return TestClient(app)


def _auth_headers(token: str = "smoke-test-token") -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_health_exempt_from_auth(client):
    """/health is the only route that doesn't require a token."""
    resp = client.get("/health")
    assert resp.status_code == 200


def test_destructive_route_without_token_401(client):
    resp = client.delete("/workspaces/it_copilot")  # no auth header
    assert resp.status_code == 401


def test_destructive_route_with_wrong_token_401(client):
    resp = client.delete("/workspaces/it_copilot", headers=_auth_headers("wrong"))
    assert resp.status_code == 401


def test_destructive_route_with_correct_token_does_not_401(client):
    # We expect *not* a 401. The route may still 404/400/etc. for other
    # reasons, but the auth gate is satisfied.
    resp = client.get("/workspaces", headers=_auth_headers())
    assert resp.status_code != 401


def test_reset_rejects_non_builtin(client, db_session):
    """Per Task 3, reset of a non-builtin workspace returns 400."""
    from db import models
    ws = models.Workspace(
        id="non-builtin", slug="non-builtin", display_name="x",
        system_prompt="", enabled_tools=[], is_builtin=False,
        engine_config={"backend": "ollama", "model": "gemma4:e4b"},
    )
    db_session.add(ws)
    db_session.commit()
    resp = client.post("/workspaces/non-builtin/reset", headers=_auth_headers())
    assert resp.status_code == 400


def test_message_edit_cross_workspace_404(client, db_session):
    """Per Task 2: editing a message via a workspace that doesn't own it → 404."""
    from db import models
    ws_a = models.Workspace(id="ws-a", slug="ws-a", display_name="A",
                            system_prompt="", enabled_tools=[], is_builtin=False,
                            engine_config={"backend": "ollama", "model": "gemma4:e4b"})
    ws_b = models.Workspace(id="ws-b", slug="ws-b", display_name="B",
                            system_prompt="", enabled_tools=[], is_builtin=False,
                            engine_config={"backend": "ollama", "model": "gemma4:e4b"})
    sess_a = models.Session(id="sess-a", workspace_id="ws-a", title="t")
    msg_a = models.Message(id="msg-a", session_id="sess-a", role="user", content="x")
    db_session.add_all([ws_a, ws_b, sess_a, msg_a])
    db_session.commit()

    # Edit msg-a while claiming workspace=ws-b → 404.
    resp = client.patch(
        f"/messages/msg-a?workspace=ws-b",
        json={"content": "tampered"},
        headers=_auth_headers(),
    )
    assert resp.status_code == 404
```

- [ ] **Step 2: Verify they pass**

```bash
cd /home/orbital/projects/pryzm/backend
./venv/bin/pytest tests/smoke/ -v
```

Expected: all smoke probes pass.

- [ ] **Step 3: Run the full suite**

```bash
cd /home/orbital/projects/pryzm/backend
./venv/bin/pytest tests/ -v
```

Expected: all tests pass (Phase 1 migration tests + Phase 2 unit tests + Phase 2 smoke probes).

- [ ] **Step 4: Commit**

```bash
git add backend/tests/smoke/
git commit -m "test(auth): HTTP-level smoke probes for token + workspace boundary."
```

---

## Task 6 — Final review and PR

- [ ] **Step 1: Full sweep**

Walk the whole branch:

```bash
git log main..HEAD --oneline    # → 6 commits (T0-T5)
git diff main..HEAD --stat       # → overview of changed files
```

Expected:
- Exactly the files listed in the File Map at the top of this plan.
- No spurious changes (no formatting churn in adjacent code, no dead imports).
- Each commit has a Conventional Commit message with trailing period, no `Co-Authored-By` trailer.

- [ ] **Step 2: Run the full test suite one more time**

```bash
cd /home/orbital/projects/pryzm/backend
./venv/bin/pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 3: Manual smoke against the running app**

With backend + frontend running:

1. Reload the browser at `http://localhost:3000`.
2. TokenGate appears (assuming you cleared localStorage during testing).
3. Paste the token, click Save.
4. App loads. Sessions/folders/workspaces list correctly. Chat in `personal` and `it_copilot` works.
5. File upload still works.
6. Open Settings, confirm the token field shows the masked token. (Don't accidentally screenshot the actual value.)
7. Try to call the backend directly without a token:
   ```bash
   curl -i http://127.0.0.1:8000/workspaces   # → 401
   ```
8. Try to call with a wrong token:
   ```bash
   curl -i -H "Authorization: Bearer wrong" http://127.0.0.1:8000/workspaces   # → 401
   ```
9. Try cross-workspace message edit (curl, replace ids with real ones from your DB):
   ```bash
   curl -i -X PATCH "http://127.0.0.1:8000/messages/<msg-in-personal>?workspace=it_copilot" \
     -H "Authorization: Bearer <your-token>" \
     -H "Content-Type: application/json" \
     -d '{"content": "tampered"}'
   # → 404
   ```

- [ ] **Step 4: Push the branch and open the PR**

```bash
git push -u origin refactor/phase-2-auth-boundaries
```

**Title:** `Phase 2 — auth gate + workspace boundary enforcement`

**Body (draft):**

```markdown
## Summary

Phase 2 of the codebase remediation: closes the no-auth and cross-workspace mutation gaps.

### Changes
- Bearer-token gate via `PRYZM_API_TOKEN` env var. `/health` exempt; everything else requires the header.
- `verify_workspace_owns` and `_message_in_workspace_or_404` helpers — id-keyed routes return **404** (not 403) on cross-workspace access to avoid info leakage.
- Reset endpoint (`POST /workspaces/{slug}/reset`) rejects non-builtin workspaces with 400.
- Frontend `apiFetch` wrapper injects the Authorization header automatically; `TokenGate` UI when no token is configured; Settings panel exposes the token field.

### Explicitly NOT in this PR
- Multi-user / per-user ACL / admin roles — future phase.
- JWT or session-based auth — future.
- Token rotation, audit log — future.
- UI permission model — future.

### Test plan
- [x] `pytest backend/tests/` — all unit + smoke probes pass.
- [x] Manual: `/health` reachable without token; other endpoints 401 without; correct token works; wrong token gets 401.
- [x] Manual: cross-workspace message edit returns 404.
- [x] Manual: TokenGate appears when localStorage is cleared; app loads after pasting token; Settings shows masked field.
- [x] Reset on `personal` (builtin) works; reset on a user-created workspace returns 400.

### Spec
[`docs/specs/2026-05-14-codebase-remediation.md`](docs/specs/2026-05-14-codebase-remediation.md) — Phase 2 section.

### Plan
[`docs/plans/2026-05-14-phase-2-auth-boundaries.md`](docs/plans/2026-05-14-phase-2-auth-boundaries.md).
```

Open at `https://github.com/ce-forge/pryzm/pull/new/refactor/phase-2-auth-boundaries`.

- [ ] **Step 5: Squash and merge**

Same as Phase 1 — squash merge keeps Phase 2 as a single commit on main.

---

## Risks and rollback

- **Forgotten token in `.env`:** the backend won't start (Pydantic raises). The error message names `PRYZM_API_TOKEN`. Easy fix: add it.
- **Stale token in browser localStorage:** the frontend will get 401s on every request. Resolution: clear `pryzm_api_token` from localStorage, reload, paste the current token.
- **`apiFetch` migration left a few stray `fetch()` calls:** those calls will 401. Each is a one-line replacement.
- **`/upload` regression risk:** the multipart Content-Type handling is delicate. If uploads break after the wrapper migration, check that `apiFetch` doesn't override Content-Type on FormData bodies.
- **CORS still permissive:** out of scope here. Hardcoded LAN IP removed in Phase 6.
- **Rollback:** the whole phase reverts via `git revert <merge-commit>` and restart. No data shape changes.

---

## Related memory

- [[project-workspace-roadmap]] — the multi-user / admin work this auth gate precedes.
- [[reference-stack-commands]] — uvicorn + npm commands for the verification steps.
- [[feedback-karpathy-for-subagents]] — implementation agents executing this plan get Karpathy guidelines in their brief.
- [[feedback-schema-forces-consumer-updates]] — analogous lesson for Phase 2: every route addition forces frontend `apiFetch` adoption; do the mechanical sweep, don't leave stragglers.
