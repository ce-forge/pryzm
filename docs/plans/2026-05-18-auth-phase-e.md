# Auth Phase E Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Apply Karpathy discipline at every step: simplicity, surgical changes, verifiable goals.

**Goal:** Remove the provisional bearer-token plumbing entirely; cookie-based session auth becomes the only credential path. Tighten CORS from the RFC1918 wildcard to an explicit per-host allowlist.

**Architecture:** The frontend stops attaching `Authorization: Bearer` headers and `?token=` URL params. The backend's `current_user` dependency drops its bearer/token-query fallback paths and becomes cookie-only. `require_token`, `TokenGate`, the `/legacy-token` route, and the orphaned `Settings.tsx` modal are deleted. `CORS_PRIVATE_NETWORK_REGEX` (the RFC1918 wildcard) is removed from the middleware; only the explicit `CORS_ORIGINS` allowlist applies.

**Tech Stack:** FastAPI + SQLAlchemy + Pydantic settings (backend); Next.js 16 + React 19 (frontend).

**Reference spec:** `docs/specs/2026-05-17-user-login-and-admin.md` (Phase E section).

**Pre-existing on `main` from Phase C:**
- All app-facing routers use `cookie_auth.current_user` at the router level
- `apiFetch` already sends `credentials: "include"`
- `<img crossOrigin="use-credentials">`, XHR `withCredentials = true`, EventSource `{ withCredentials: true }` all in place
- `bearer-as-bootstrap-admin` resolver lives in `cookie_auth.current_user`, gated by `?token=` query OR `Authorization: Bearer`

---

## Decisions (resolved)

1. **`PRYZM_API_TOKEN` is fully removed** — the field is deleted from `config.py`, the line is removed from `.env.example`, and every test/script that currently reads it migrates to cookie auth. End state: no bearer-token surface anywhere in code.

2. **`Settings.tsx` legacy modal:** deleted. Orphaned since Phase C; sections that mattered (Models, Micro-Prompts) live at `/dashboard`.

3. **Bearer-path tests:** `tests/test_current_user_dual_mode.py` is deleted. ~30 other unit-test files currently monkeypatch `PRYZM_API_TOKEN` and send `Authorization: Bearer test-token` — these are migrated to cookie-based `TestClient` setup. The pattern is: seed a User, `cookie_auth.create_session(db_session, user.id)`, `c.cookies.set(cookie_auth.COOKIE_NAME, sid)`, then make the call.

4. **E2E + perf scripts** (`tests/e2e/conftest.py`, `tests/e2e/test_phase_b{2,3}_smoke.py`, `tests/perf/bench_llm.py`): currently read `PRYZM_API_TOKEN` from `.env`. They're migrated to programmatic login: `POST /api/auth/login` with `admin`-tier credentials sourced from env (e.g. a new `PRYZM_E2E_PASSWORD` env var, or just `admin/admin` for the local dev case), captured into a cookie jar, reused for subsequent calls. Where this is too invasive for a single script, the script is updated minimally to call the new login flow.

5. **CORS_ORIGINS after the regex drops:** the regex (`CORS_PRIVATE_NETWORK_REGEX`) was the wildcard for any RFC1918 origin. After removal, only `CORS_ORIGINS` applies — currently `["http://localhost:3000", "http://127.0.0.1:3000", "http://<your-host>.ddns.net:3000", "http://<your-host>.ddns.net:3080", "https://<your-host>.ddns.net"]` per `.env`. Anyone wanting LAN access from another device on the network needs that IP added to `CORS_ORIGINS` explicitly. This is the intended tightening. No code change beyond removing the regex.

6. **`frontend/src/data/test_suite.json`:** runs in-browser via `useTestSuite` → `useInference` → `apiFetch`. After Phase E, `apiFetch` is cookie-only and the user is logged in to use the chat UI anyway, so the data-driven runner auto-migrates with no changes to the JSON or the hook.

---

## File map

| File | Action | Purpose |
|---|---|---|
| `backend/core/cookie_auth.py` | Modify | Drop `?token=` param and bearer fallback from `current_user`; cookie-only |
| `backend/core/auth.py` | Delete | Only contained `require_token`, now unused |
| `backend/main.py` | Modify | Drop `require_token` import; drop `allow_origin_regex=...` from CORS middleware |
| `backend/config.py` | Modify | Drop `CORS_PRIVATE_NETWORK_REGEX` setting; make `PRYZM_API_TOKEN` optional (`str \| None = None`) |
| `backend/routers/documents.py` | Modify | Drop the now-unused `require_token` import |
| `backend/tests/test_current_user_dual_mode.py` | Modify | Delete the bearer-path tests; keep cookie-only assertions |
| `backend/tests/test_auth_smoke.py` (and any others using bearer) | Modify | Switch test API calls from `Authorization: Bearer` to cookie auth |
| `frontend/src/utils/apiClient.ts` | Modify | Delete `getToken`/`setToken`/`clearToken`; simplify `apiFetch` to just credentials |
| `frontend/src/hooks/useUploader.ts` | Modify | Drop `getToken()` calls and bearer-related header attachment; XHR `withCredentials` stays |
| `frontend/src/components/ReferencedFilesPreview.tsx` | Modify | Drop the `?token=` URL param; `crossOrigin="use-credentials"` stays |
| `frontend/src/components/TokenGate.tsx` | Delete | Bearer-only entry UI, no longer reachable |
| `frontend/src/app/legacy-token/` | Delete | Route that hosted TokenGate |
| `frontend/src/components/Settings.tsx` | Delete | Orphaned legacy modal (per decision 2) |

---

## Execution order

Tests migrate **before** the bearer removal, not after. Reason: every test in `backend/tests/` that uses `Authorization: Bearer test-token` would silently break the moment Task 2 deletes `cookie_auth.current_user`'s bearer fallback. Keeping the bearer fallback alive while we mass-convert the tests to cookie pattern means every intermediate commit stays green. Once tests are on cookies, the bearer code can be deleted without collateral damage.

Order:
- Task 0: Branch + plan commit
- Task 1 (was Task 6): Test migration — all unit tests, e2e, perf
- Task 2 (was Task 1): `current_user` cookie-only
- Task 3 (was Task 2): Backend cleanup — delete `auth.py`, `require_token`, CORS regex, `PRYZM_API_TOKEN`
- Task 4 (was Task 3): Frontend `apiClient.ts` cookie-only
- Task 5 (was Task 4): Frontend consumers — `useUploader`, `ReferencedFilesPreview`
- Task 6 (was Task 5): Frontend deletions — `TokenGate`, `/legacy-token`, `Settings.tsx`
- Task 7: Full sweep + manual smoke
- Task 8: Push + PR

The task content stays the same; only the order changes. Below, the existing task definitions are preserved — read them in the new order above.

---

## Task 0: Branch setup

The branch `feat/auth-phase-e` is already checked out.

- [ ] **Step 1: Verify clean state**

```bash
cd /home/orbital/projects/pryzm && git status --short && git branch --show-current
```

Expected: branch `feat/auth-phase-e`, working tree clean (or only the in-progress plan file if it hasn't been committed yet).

- [ ] **Step 2: Commit this plan**

```bash
cd /home/orbital/projects/pryzm && git add docs/plans/2026-05-18-auth-phase-e.md && \
git commit -m "docs(plan): add auth Phase E implementation plan"
```

---

## Task 1: Backend — `current_user` becomes cookie-only

**Files:**
- Modify: `backend/core/cookie_auth.py`

- [ ] **Step 1: Drop the bearer-token fallback path**

In `cookie_auth.current_user`:
- Remove the `authorization: Annotated[Optional[str], Header()] = None` parameter
- Remove the `token: Annotated[Optional[str], Query()] = None` parameter
- Remove the `_bearer_resolves_to_bootstrap_admin(authorization, token, db)` fallback call
- Delete the helper function `_bearer_resolves_to_bootstrap_admin` (and any imports only it used)

New shape:

```python
def current_user(
    pryzm_session: Annotated[Optional[str], Cookie()] = None,
    db: DbSession = Depends(database.get_db),
) -> models.User:
    user = get_session_user(db, pryzm_session) if pryzm_session else None
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
        )
    return user
```

Keep `require_admin` as-is (it wraps `current_user`; the signature change doesn't propagate visibly).

- [ ] **Step 2: Run the affected tests**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest tests/test_current_user_dual_mode.py -v 2>&1 | tail -20
```

Expect failures on the bearer-path tests — that's expected and fixed in Task 5.

- [ ] **Step 3: Commit**

```bash
cd /home/orbital/projects/pryzm && git add backend/core/cookie_auth.py && \
git commit -m "feat(auth): current_user becomes cookie-only (drop bearer fallback)"
```

---

## Task 2: Backend — delete `require_token`, tighten CORS

**Files:**
- Delete: `backend/core/auth.py`
- Modify: `backend/main.py`
- Modify: `backend/config.py`
- Modify: `backend/routers/documents.py`

- [ ] **Step 1: Drop the dead import from documents.py**

```bash
sed -i '/^from core.auth import require_token$/d' /home/orbital/projects/pryzm/backend/routers/documents.py
```

- [ ] **Step 2: Drop the dead import + CORS regex from main.py**

In `backend/main.py`:
- Delete the line `from core.auth import require_token`
- In the `CORSMiddleware` initialization, delete the `allow_origin_regex=settings.CORS_PRIVATE_NETWORK_REGEX,` line (and the surrounding comment block describing the private-network wildcard)

After the change, the middleware should look like:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

- [ ] **Step 3: Drop `CORS_PRIVATE_NETWORK_REGEX` from config.py**

In `backend/config.py`:
- Delete the `CORS_PRIVATE_NETWORK_REGEX: str = (...)` declaration entirely (including the multi-line regex string)
- Delete the related comment block

- [ ] **Step 4: Delete `PRYZM_API_TOKEN` from config.py + .env.example**

In `backend/config.py`:
- Delete the `PRYZM_API_TOKEN: str` declaration entirely (Option A: full removal, not just optional)
- Delete the surrounding comment block

In `.env.example`:
- Delete the `PRYZM_API_TOKEN=` line
- (Existing local `.env` files can keep the line; it'll just be ignored by `extra="ignore"` in `SettingsConfigDict`.)

Note: any code still importing `settings.PRYZM_API_TOKEN` will now fail at import time. The next steps (3, 6) clean those up; Task 5 (frontend cleanup) and Task 6 (test migration) finish the chain.

- [ ] **Step 5: Delete `backend/core/auth.py`**

```bash
rm /home/orbital/projects/pryzm/backend/core/auth.py
```

- [ ] **Step 6: Verify nothing else imports from `core.auth`**

```bash
cd /home/orbital/projects/pryzm && grep -rn "from core.auth\|import core.auth" backend --include="*.py"
```

Expected: zero matches. If anything remains, fix it.

- [ ] **Step 7: Smoke test backend startup**

```bash
cd /home/orbital/projects/pryzm/backend && timeout 10 ./venv/bin/python -c "from main import app; print('imports ok')"
```

Expected: `imports ok`. If startup fails with `KeyError: 'PRYZM_API_TOKEN'` or similar, fix.

- [ ] **Step 8: Commit**

```bash
cd /home/orbital/projects/pryzm && git add -A backend/ && \
git commit -m "feat(auth): remove require_token, RFC1918 CORS wildcard, mandatory PRYZM_API_TOKEN"
```

---

## Task 3: Frontend — `apiClient.ts` becomes cookie-only

**Files:**
- Modify: `frontend/src/utils/apiClient.ts`

- [ ] **Step 1: Delete bearer-token helpers; simplify `apiFetch`**

Replace the entire file with:

```typescript
import { APP_CONFIG } from "./constants";

/**
 * Wraps fetch with same-origin / cross-origin credentials. The session
 * cookie carries auth; the wrapper sets no Authorization header.
 *
 * IMPORTANT: this wrapper does NOT touch Content-Type. Callers that pass a
 * FormData body MUST leave Content-Type unset so the browser sets the
 * multipart boundary automatically. Callers that send JSON must set
 * Content-Type: application/json themselves.
 *
 * For SSE/streaming responses, this returns the raw Response so callers can
 * use response.body.getReader() as before.
 */
export async function apiFetch(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  return fetch(`${APP_CONFIG.API_URL}${path}`, {
    ...init,
    credentials: "include",
  });
}
```

The `TOKEN_STORAGE_KEY` constant and `getToken`/`setToken`/`clearToken` exports are gone.

- [ ] **Step 2: Smoke compile**

```bash
cd /home/orbital/projects/pryzm/frontend && npx tsc --noEmit 2>&1 | head -10
```

There will be type errors in callers that import the deleted functions. That's expected; the next tasks fix them.

- [ ] **Step 3: Commit**

```bash
cd /home/orbital/projects/pryzm && git add frontend/src/utils/apiClient.ts && \
git commit -m "feat(auth): apiClient drops getToken/setToken/clearToken; apiFetch is cookie-only"
```

---

## Task 4: Frontend — drop bearer plumbing from consumers

**Files:**
- Modify: `frontend/src/hooks/useUploader.ts`
- Modify: `frontend/src/components/ReferencedFilesPreview.tsx`

- [ ] **Step 1: `useUploader.ts`**

- Delete the `import { getToken } from "@/utils/apiClient"` line.
- In `uploadWithProgress`: delete `const token = getToken();` and `if (token) xhr.setRequestHeader("Authorization", \`Bearer ${token}\`);`. The `xhr.withCredentials = true` line stays.
- In `subscribeToIngestionStatus`: delete `const token = getToken();` and `if (token) url.searchParams.set("token", token);`. The `EventSource(url.toString(), { withCredentials: true })` line stays.

- [ ] **Step 2: `ReferencedFilesPreview.tsx`**

- Delete the `import { getToken } from "@/utils/apiClient"` line.
- Delete `const token = getToken();`.
- Delete `if (token) qs.set("token", token);`.

The `<img crossOrigin="use-credentials">` attribute stays.

- [ ] **Step 3: Smoke compile**

```bash
cd /home/orbital/projects/pryzm/frontend && npx tsc --noEmit 2>&1 | head -10
```

Expected: errors related to apiClient should be gone for these two files. Errors may remain for files in the next task.

- [ ] **Step 4: Commit**

```bash
cd /home/orbital/projects/pryzm && git add frontend/src/hooks/useUploader.ts frontend/src/components/ReferencedFilesPreview.tsx && \
git commit -m "feat(auth): useUploader + ReferencedFilesPreview drop bearer/?token= plumbing"
```

---

## Task 5: Frontend — delete TokenGate, legacy-token route, Settings modal

**Files (delete):**
- `frontend/src/components/TokenGate.tsx`
- `frontend/src/app/legacy-token/` (entire directory)
- `frontend/src/components/Settings.tsx`

- [ ] **Step 1: Delete the files**

```bash
rm /home/orbital/projects/pryzm/frontend/src/components/TokenGate.tsx
rm -rf /home/orbital/projects/pryzm/frontend/src/app/legacy-token
rm /home/orbital/projects/pryzm/frontend/src/components/Settings.tsx
```

- [ ] **Step 2: Verify no imports remain**

```bash
cd /home/orbital/projects/pryzm && grep -rn "TokenGate\|@/components/Settings\b" frontend/src --include="*.tsx" --include="*.ts"
```

Expected: zero matches. If any remain, fix the importer (most likely the import is dead and can just be removed).

- [ ] **Step 3: Smoke compile + lint**

```bash
cd /home/orbital/projects/pryzm/frontend && npx tsc --noEmit 2>&1 | head -10
cd /home/orbital/projects/pryzm/frontend && npm run lint -- --no-fix 2>&1 | tail -5
```

Both clean.

- [ ] **Step 4: Commit**

```bash
cd /home/orbital/projects/pryzm && git add -A frontend/src/ && \
git commit -m "feat(auth): delete TokenGate, /legacy-token route, orphaned Settings modal"
```

---

## Task 6: Tests — full bearer migration (Option A scope)

The inventory: ~30 unit-test files monkeypatch `PRYZM_API_TOKEN` and use `Authorization: Bearer test-token` headers, plus the e2e and perf CLI tools read the real `.env` token. ALL of these migrate to cookie auth.

**Migration pattern for unit tests (mechanical, one-shot):**

Before:

```python
def test_something(db_session, monkeypatch):
    monkeypatch.setattr("config.settings.PRYZM_API_TOKEN", "test-token")
    c = TestClient(app)
    r = c.get("/workspaces", headers={"Authorization": "Bearer test-token"})
    assert r.status_code == 200
```

After:

```python
def test_something(db_session, monkeypatch):
    admin = models.User(
        username="admin",
        password_hash=cookie_auth.hash_password("admin-pw"),
        is_admin=True,
        is_active=True,
    )
    db_session.add(admin); db_session.commit(); db_session.refresh(admin)
    sid = cookie_auth.create_session(db_session, admin.id)
    app.dependency_overrides[database.get_db] = lambda: db_session
    try:
        c = TestClient(app)
        c.cookies.set(cookie_auth.COOKIE_NAME, sid)
        r = c.get("/workspaces")
        assert r.status_code == 200
    finally:
        app.dependency_overrides.clear()
```

If the test already has a user/session fixture (many do, post-Phase B), reuse it — just drop the `monkeypatch` line and the `Authorization` header. The cookie path is already in place.

A reusable conftest fixture would be ideal but is not in scope for this PR — keep edits per-test, mechanical.

- [ ] **Step 1: Inventory**

```bash
cd /home/orbital/projects/pryzm && \
grep -rln "Authorization.*Bearer\|PRYZM_API_TOKEN" backend/tests > /tmp/phaseE_bearer_files.txt
wc -l /tmp/phaseE_bearer_files.txt
cat /tmp/phaseE_bearer_files.txt
```

Expected: ~30 files. Migrate one at a time, in the order they appear.

- [ ] **Step 2: Delete `test_current_user_dual_mode.py`**

The whole file's purpose was to validate the dual-mode bridge. Cookie path is exercised by every other test post-migration.

```bash
rm /home/orbital/projects/pryzm/backend/tests/test_current_user_dual_mode.py
```

- [ ] **Step 3: Migrate each unit-test file**

For each file in the inventory (other than the deleted one), apply the pattern above. Some files have multiple test functions; convert each. Some files use a `_setup` helper — update the helper once.

Run after each file to catch breakage early:

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest tests/<file>.py -q
```

- [ ] **Step 4: Migrate the e2e + perf scripts**

`backend/tests/e2e/conftest.py`, `tests/e2e/test_phase_b2_smoke.py`, `tests/e2e/test_phase_b3_smoke.py`:

Currently they read `PRYZM_API_TOKEN` from `.env` for outgoing requests. Migrate to programmatic login:

1. Read admin credentials from env: introduce `PRYZM_E2E_USERNAME` (default `"admin"`) and `PRYZM_E2E_PASSWORD` (default `"admin"`). Document in `.env.example`.
2. On test setup, POST to `/api/auth/login` with those creds; capture the `pryzm_session` cookie from the response.
3. For all subsequent requests, attach the cookie instead of the bearer header.

`backend/tests/perf/bench_llm.py`:

Currently has `--token` CLI arg. Replace with `--username` and `--password` (defaults `admin` / `admin`). On startup, log in and capture cookie; reuse for the load loop.

- [ ] **Step 5: Run the full backend suite**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest -q --ignore=tests/test_image_upload.py --ignore=tests/test_upload_sse.py
```

All pass. Note: this is the canonical sweep — if any test still references `PRYZM_API_TOKEN` after the migration, this will fail because Task 2 removed the field from `config.py`.

- [ ] **Step 6: Commit (one commit or split by domain — judgment call)**

```bash
cd /home/orbital/projects/pryzm && git add -A backend/tests/ && \
git commit -m "test(auth): migrate all bearer-using tests + e2e/perf scripts to cookie auth"
```

If the scope feels too coarse for one commit, split into two: "unit tests" and "e2e + perf scripts". Either is fine.

---

## Task 7: Full sweep + manual smoke

- [ ] **Step 1: Backend sweep**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest -q --ignore=tests/test_image_upload.py --ignore=tests/test_upload_sse.py
```

- [ ] **Step 2: Frontend typecheck + lint**

```bash
cd /home/orbital/projects/pryzm/frontend && npx tsc --noEmit
cd /home/orbital/projects/pryzm/frontend && npm run lint -- --no-fix
```

- [ ] **Step 3: Restart services**

```bash
lsof -ti tcp:8000 | xargs -r kill && sleep 2
cd /home/orbital/projects/pryzm/backend && \
nohup ./venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --reload --reload-delay 2 > /tmp/pryzm_backend.log 2>&1 &
for i in 1 2 3 4 5; do curl -sf -o /dev/null http://127.0.0.1:8000/health && break; sleep 1; done

pkill -9 -f "next-server" 2>/dev/null; sleep 3
cd /home/orbital/projects/pryzm/frontend && \
nohup npm run dev -- -H 0.0.0.0 > /tmp/pryzm_frontend.log 2>&1 &
for i in 1 2 3 4 5 6 7 8 9 10; do curl -sf -o /dev/null http://127.0.0.1:3000/ && break; sleep 1; done
```

- [ ] **Step 4: Manual smoke (phase boundary — operator verifies)**

In a private/incognito window:

1. Visit `http://localhost:3000` → login page appears
2. Enter wrong creds → "Invalid credentials"
3. Enter correct creds → app loads with workspaces and sessions populated
4. Open a chat → previously-uploaded images render inline (not as filename cards)
5. Upload a new image → ingestion-progress pill updates and resolves
6. Open `/dashboard` → Models, Micro-Prompts, and Change password sections visible
7. Sign out from sidebar → returned to login page
8. Visit `/legacy-token` → 404 (route deleted)
9. From cellular (external), repeat step 1-7 against `http://<your-host>.ddns.net:3000`

---

## Task 8: Push + open PR

- [ ] **Step 1: Push**

```bash
cd /home/orbital/projects/pryzm && git push -u origin feat/auth-phase-e
```

- [ ] **Step 2: Open PR**

```bash
gh pr create --base main --head feat/auth-phase-e \
  --title "feat(auth): Phase E — remove bearer-token plumbing + tighten CORS" \
  --body "$(cat <<'EOF'
Removes the provisional bearer-token plumbing. Cookie-based session auth is now the only credential path. CORS tightens from the RFC1918 wildcard to the explicit `CORS_ORIGINS` allowlist only.

## Changes
- Backend `current_user` is cookie-only (no `Authorization: Bearer`, no `?token=` URL param)
- `core/auth.py` deleted (`require_token` is gone)
- `CORS_PRIVATE_NETWORK_REGEX` removed from `config.py` and middleware
- `PRYZM_API_TOKEN` env var is optional (was required at startup)
- Frontend `getToken`/`setToken`/`clearToken` deleted; `apiFetch` is cookie-only
- `TokenGate`, `/legacy-token` route, orphaned `Settings.tsx` deleted
- Bearer-path tests migrated to cookie auth; `test_current_user_dual_mode.py` deleted

Spec: `docs/specs/2026-05-17-user-login-and-admin.md`. Plan: `docs/plans/2026-05-18-auth-phase-e.md`.

After this PR, the auth surface is: cookie in / cookie out, with the login page as the only entry point.
EOF
)"
```

- [ ] **Step 3: No auto-merge.** Phase boundary; operator reviews and merges.

---

## Self-review

Spec coverage:

- [x] Cookie-only `current_user` (Task 1)
- [x] `require_token` deleted (Task 2)
- [x] `?token=` URL fallback gone from backend (Task 1) and frontend (Task 4)
- [x] CORS regex tightened to explicit allowlist (Task 2)
- [x] `getToken()` and consumers deleted (Tasks 3, 4)
- [x] TokenGate and `/legacy-token` deleted (Task 5)
- [x] Tests migrated (Task 6)

Known follow-ups deferred:
- `Settings.tsx` admin-only sections (Models, Micro-Prompts) live on `/dashboard` already; the modal goes away cleanly.
- The `test_suite.json` data-driven runner historically used `PRYZM_API_TOKEN`. If that runner still exists and is exercised, it will need to switch to cookie auth — separate from this PR.
