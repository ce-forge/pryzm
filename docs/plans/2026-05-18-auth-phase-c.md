# Auth Phase C Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Apply Karpathy discipline at every step: simplicity, surgical changes, verifiable goals.

**Goal:** Replace the bearer-token gate with a cookie-based login page; expose user identity and permission flags via a `useAuth()` context; gate UI surfaces per the auth spec; add a logout flow.

**Architecture:** A new `AuthContext` fetches `GET /api/auth/me` on app boot and exposes `{ user, isLoading, refresh, logout }`. On 401, the app renders `LoginPage` (username/password form). On success, the existing app shell renders. Permission gating reads flags from the context — no behavior change to backend. Bearer-token plumbing (`getToken`/`setToken`/`?token=`) stays in place during this phase as a fallback for non-migrated callers; full removal is Phase E.

**Tech stack:** Next.js 16 (App Router, client components), React 19, Tailwind, existing FastAPI auth endpoints (`/api/auth/login`, `/api/auth/logout`, `/api/auth/me`, `/api/auth/password`).

**Reference spec:** `docs/specs/2026-05-17-user-login-and-admin.md` (Phase C section).

---

## File map

| File | Action | Purpose |
|---|---|---|
| `frontend/src/utils/apiClient.ts` | Modify | Add `credentials: "include"` to fetch so cookies flow |
| `frontend/src/context/AuthContext.tsx` | Create | `useAuth()` hook: `{ user, isLoading, refresh, logout }`; fetches `/api/auth/me` on mount |
| `frontend/src/context/AppProviders.tsx` | Modify | Wrap children with `AuthProvider` at the top of the provider stack |
| `frontend/src/components/LoginPage.tsx` | Create | Username/password form; POST `/api/auth/login`; on success calls `refresh()` |
| `frontend/src/components/Sidebar.tsx` | Modify | Drop bottom Settings button; add logout + admin Dashboard link in header |
| `frontend/src/components/TokenGate.tsx` | Modify | Demote to optional fallback at `/legacy-token` route; not auto-shown |
| `frontend/src/app/page.tsx` | Modify | Boot flow: read `useAuth()`; show `LoginPage` on no user, app on user |
| `frontend/src/app/dashboard/page.tsx` | Create | Admin-only placeholder route; embeds existing models/prompts sections for now |
| `frontend/src/components/WorkspaceSwitcher.tsx` | Modify | Hide "create workspace" affordance unless `user.can_create_workspaces` |
| `frontend/src/components/Settings.tsx` | Modify | Sections that touch admin-only endpoints render only if `user.is_admin`; workspace settings switches to read-only when `!workspace.owner_can_edit && !user.is_admin` |
| `backend/routers/auth.py` | Modify | `/api/auth/me` adds `workspaces: [...]` to the response (frontend boot needs the workspace list without a second round-trip) |
| `backend/tests/test_auth_router.py` | Modify | Update `/me` test to assert the new `workspaces` field |

**Out of scope (Phase E or later):**
- Removing `getToken()` / `?token=` URL fallback (Phase E)
- Tightening CORS regex from RFC1918 wildcard to explicit per-host allowlist (Phase E)
- The real dev dashboard (Phase D — separate spec)
- TOTP / MFA / OAuth / password reset email
- Self-registration

---

## Task 0: Branch setup

- [ ] **Step 1: Create a new branch off main**

```bash
cd /home/orbital/projects/pryzm
git checkout main && git pull origin main
git checkout -b feat/auth-phase-c
git status --short
```

Expected: clean tree, `feat/auth-phase-c` branch created.

---

## Task 1: `apiFetch` sends cookies

**Files:**
- Modify: `frontend/src/utils/apiClient.ts`

**Why:** Cookie-based auth requires `credentials: "include"` on fetch (cross-origin between `:3000` and `:8000` makes the browser strip cookies by default). The bearer-token fallback continues to work alongside.

- [ ] **Step 1: Edit `apiFetch` to include credentials**

Change the return line in `apiFetch`:

```typescript
return fetch(`${APP_CONFIG.API_URL}${path}`, {
  ...init,
  headers,
  credentials: "include",
});
```

- [ ] **Step 2: Same change in `useUploader.ts` XHR call**

Find the `xhr.open(...)` block. After `xhr.open(...)` and before `xhr.send(...)`, add:

```typescript
xhr.withCredentials = true;
```

- [ ] **Step 3: Verify backend tests still pass**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest tests/test_auth_router.py tests/test_current_user_dual_mode.py -v
```

Expected: green. No backend changes; this is a sanity check.

- [ ] **Step 4: Commit**

```bash
cd /home/orbital/projects/pryzm && \
git add frontend/src/utils/apiClient.ts frontend/src/hooks/useUploader.ts && \
git commit -m "feat(auth): send cookies on apiFetch and XHR uploads"
```

---

## Task 2: `/api/auth/me` returns workspaces

**Files:**
- Modify: `backend/routers/auth.py`
- Modify: `backend/tests/test_auth_router.py`

**Why:** Frontend boot needs both user identity AND the workspace list to render the sidebar. Doing this in one round-trip (instead of `/me` then `/workspaces`) eliminates a flash of empty state on every reload.

- [ ] **Step 1: Update `/me` handler**

In `backend/routers/auth.py`, locate `def me(...)`. Replace its body with:

```python
@router.get("/me")
def me(
    user: models.User = Depends(cookie_auth.current_user),
    db: Session = Depends(database.get_db),
):
    workspaces = (
        db.query(models.Workspace)
        .filter(models.Workspace.user_id == user.id)
        .order_by(models.Workspace.position.asc(), models.Workspace.created_at.asc())
        .all()
    )
    return {
        "id": user.id,
        "username": user.username,
        "is_admin": user.is_admin,
        "can_create_workspaces": user.can_create_workspaces,
        "email": user.email,
        "workspaces": [
            {
                "id": w.id,
                "slug": w.slug,
                "display_name": w.display_name,
                "color": w.color,
                "owner_can_edit": w.owner_can_edit,
                "template_id": w.template_id,
                "position": w.position,
            }
            for w in workspaces
        ],
    }
```

Add the `Session` import at the top of the file if it's not already there:

```python
from sqlalchemy.orm import Session
from db import database, models
```

- [ ] **Step 2: Add a workspace-list assertion to the `/me` test**

In `backend/tests/test_auth_router.py`, find the `test_me_returns_user_when_session_valid` test (or equivalent). Add seed data and an assertion:

```python
def test_me_returns_user_and_workspaces(db_session, monkeypatch):
    admin = models.User(
        username="admin",
        password_hash=cookie_auth.hash_password("admin-pw-12chars"),
        is_admin=True,
        is_active=True,
        can_create_workspaces=True,
    )
    db_session.add(admin); db_session.commit(); db_session.refresh(admin)

    ws = models.Workspace(
        slug="my-ws", display_name="My WS", system_prompt="",
        enabled_tools=[], engine_config={"backend": "llama_cpp"},
        user_id=admin.id, owner_can_edit=True, position=0,
    )
    db_session.add(ws); db_session.commit()

    sid = cookie_auth.create_session(db_session, admin.id)
    monkeypatch.setattr("config.settings.PRYZM_API_TOKEN", "test-token")
    app.dependency_overrides[database.get_db] = lambda: db_session
    try:
        c = TestClient(app)
        c.cookies.set(cookie_auth.COOKIE_NAME, sid)
        r = c.get("/api/auth/me")
        assert r.status_code == 200
        body = r.json()
        assert body["username"] == "admin"
        assert body["is_admin"] is True
        assert body["can_create_workspaces"] is True
        assert len(body["workspaces"]) == 1
        assert body["workspaces"][0]["slug"] == "my-ws"
        assert body["workspaces"][0]["owner_can_edit"] is True
    finally:
        app.dependency_overrides.clear()
```

If the existing `test_me_returns_user_when_session_valid` already covers the bare-user shape, keep it but ALSO add this new test. Don't delete the old one.

- [ ] **Step 3: Run the affected tests**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest tests/test_auth_router.py -v
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
cd /home/orbital/projects/pryzm && \
git add backend/routers/auth.py backend/tests/test_auth_router.py && \
git commit -m "feat(auth): /me returns user's workspaces in the same response"
```

---

## Task 3: AuthContext and AuthProvider

**Files:**
- Create: `frontend/src/context/AuthContext.tsx`
- Modify: `frontend/src/context/AppProviders.tsx`

**Why:** Single source of truth for `who am I, what can I do, what workspaces are mine`. UI components read from this; refresh/logout mutate it.

- [ ] **Step 1: Create the context**

Create `frontend/src/context/AuthContext.tsx`:

```typescript
"use client";

import React, { createContext, useCallback, useContext, useEffect, useState } from "react";
import { apiFetch } from "@/utils/apiClient";

export interface AuthWorkspace {
  id: string;
  slug: string;
  display_name: string;
  color: string | null;
  owner_can_edit: boolean;
  template_id: string | null;
  position: number;
}

export interface AuthUser {
  id: string;
  username: string;
  is_admin: boolean;
  can_create_workspaces: boolean;
  email: string | null;
  workspaces: AuthWorkspace[];
}

interface AuthContextValue {
  user: AuthUser | null;
  isLoading: boolean;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const refresh = useCallback(async () => {
    setIsLoading(true);
    try {
      const r = await apiFetch("/api/auth/me");
      if (r.ok) {
        const body = (await r.json()) as AuthUser;
        setUser(body);
      } else {
        setUser(null);
      }
    } catch {
      setUser(null);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const logout = useCallback(async () => {
    try {
      await apiFetch("/api/auth/logout", { method: "POST" });
    } catch {
      // Network error on logout — still clear local state.
    }
    setUser(null);
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return (
    <AuthContext.Provider value={{ user, isLoading, refresh, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
```

- [ ] **Step 2: Wrap AppProviders**

Edit `frontend/src/context/AppProviders.tsx` to wrap the existing tree:

```typescript
"use client";

import React from "react";
import { AuthProvider } from "@/context/AuthContext";
import { WorkspaceProvider } from "@/context/WorkspaceContext";
import { SessionProvider } from "@/context/SessionContext";
import { InferenceProvider } from "@/context/InferenceContext";
import { UploaderProvider } from "@/context/UploaderContext";
import { TestSuiteProvider } from "@/context/TestSuiteContext";

export function AppProviders({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <WorkspaceProvider>
        <SessionProvider>
          <InferenceProvider>
            <UploaderProvider>
              <TestSuiteProvider>{children}</TestSuiteProvider>
            </UploaderProvider>
          </InferenceProvider>
        </SessionProvider>
      </WorkspaceProvider>
    </AuthProvider>
  );
}
```

- [ ] **Step 3: Smoke test the import**

```bash
cd /home/orbital/projects/pryzm/frontend && npx tsc --noEmit 2>&1 | head -20
```

Expected: zero errors related to the new file. Pre-existing errors elsewhere (if any) ignore.

- [ ] **Step 4: Commit**

```bash
cd /home/orbital/projects/pryzm && \
git add frontend/src/context/AuthContext.tsx frontend/src/context/AppProviders.tsx && \
git commit -m "feat(auth): AuthContext + useAuth hook"
```

---

## Task 4: LoginPage component

**Files:**
- Create: `frontend/src/components/LoginPage.tsx`

**Why:** Username/password entry, POST to `/api/auth/login`, on success calls `refresh()`. Replaces `TokenGate` as the boot-time blocker.

- [ ] **Step 1: Create LoginPage**

Create `frontend/src/components/LoginPage.tsx`:

```typescript
"use client";

import { useState } from "react";
import { useAuth } from "@/context/AuthContext";
import { apiFetch } from "@/utils/apiClient";

export function LoginPage() {
  const { refresh } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password) return;
    setIsSubmitting(true);
    setError(null);
    try {
      const r = await apiFetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: username.trim(), password }),
      });
      if (r.ok) {
        await refresh();
        return;
      }
      // Backend returns 401 with a generic message on bad credentials and on
      // disabled accounts (intentional, per the auth spec).
      setError("Invalid credentials.");
    } catch {
      setError("Couldn't reach the server. Try again.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="flex h-dvh w-full items-center justify-center bg-[#131314] text-[#e3e3e3]">
      <form onSubmit={handleSubmit} className="w-full max-w-sm space-y-4 p-8">
        <h1 className="text-xl font-semibold">Sign in</h1>
        <div>
          <label htmlFor="username" className="block text-xs text-slate-400 mb-1">Username</label>
          <input
            id="username"
            type="text"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
            autoFocus
          />
        </div>
        <div>
          <label htmlFor="password" className="block text-xs text-slate-400 mb-1">Password</label>
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
          />
        </div>
        {error && <p className="text-sm text-red-400">{error}</p>}
        <button
          type="submit"
          disabled={isSubmitting || !username.trim() || !password}
          className="w-full rounded bg-blue-600 px-4 py-2 text-sm font-medium hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isSubmitting ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
```

- [ ] **Step 2: Smoke test**

```bash
cd /home/orbital/projects/pryzm/frontend && npx tsc --noEmit 2>&1 | grep -i "LoginPage\|AuthContext" | head -10
```

Expected: zero errors for these files.

- [ ] **Step 3: Commit**

```bash
cd /home/orbital/projects/pryzm && \
git add frontend/src/components/LoginPage.tsx && \
git commit -m "feat(auth): LoginPage component for cookie-based sign-in"
```

---

## Task 5: Boot flow — replace TokenGate with LoginPage

**Files:**
- Modify: `frontend/src/app/page.tsx`

**Why:** App boot now reads `useAuth()`. On no user (after the initial load completes), show `LoginPage`. On user, show the app shell. The previous bearer-token-based gate is bypassed.

- [ ] **Step 1: Rewrite the page**

Replace the body of `frontend/src/app/page.tsx`:

```typescript
"use client";

import { useEffect, useState } from "react";
import Sidebar from "@/components/Sidebar";
import ActiveSession from "@/components/ActiveSession";
import { AppProviders } from "@/context/AppProviders";
import { LoginPage } from "@/components/LoginPage";
import { useAuth } from "@/context/AuthContext";

function AppShell() {
  const { user, isLoading } = useAuth();
  const [isMounted, setIsMounted] = useState(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);

  useEffect(() => {
    setIsMounted(true);
    if (typeof window !== "undefined" && window.innerWidth < 768) setIsSidebarOpen(false);
  }, []);

  if (!isMounted || isLoading) {
    return <div className="h-dvh w-full bg-[#131314]" />;
  }

  if (!user) {
    return <LoginPage />;
  }

  return (
    <div className="flex h-dvh w-full bg-[#131314] text-[#e3e3e3] overflow-hidden font-sans">
      <Sidebar isOpen={isSidebarOpen} setIsOpen={setIsSidebarOpen} />
      <ActiveSession isSidebarOpen={isSidebarOpen} setIsSidebarOpen={setIsSidebarOpen} />
    </div>
  );
}

export default function Home() {
  return (
    <AppProviders>
      <AppShell />
    </AppProviders>
  );
}
```

The `getToken()` import is removed — the bearer-token boot path is gone. Bearer tokens still work for callers that explicitly set them (e.g., via the legacy `/legacy-token` route in Task 10).

- [ ] **Step 2: Smoke test compile**

```bash
cd /home/orbital/projects/pryzm/frontend && npx tsc --noEmit 2>&1 | head -10
```

Expected: zero new errors.

- [ ] **Step 3: Commit**

```bash
cd /home/orbital/projects/pryzm && \
git add frontend/src/app/page.tsx && \
git commit -m "feat(auth): boot flow uses /me + LoginPage instead of TokenGate"
```

---

## Task 6: Sidebar — drop Settings button, add logout, add admin Dashboard link

**Files:**
- Modify: `frontend/src/components/Sidebar.tsx`

**Why:** Per spec gap H — bottom-left Settings button is removed entirely. Logout goes in the header. Admins get a Dashboard link.

- [ ] **Step 1: Edit Sidebar**

Open `frontend/src/components/Sidebar.tsx` and apply these changes:

1. Remove the `import SettingsModal from "./Settings"` line.
2. Remove the `import { SettingsIcon } from "./Icons"` (keep `MenuIcon`).
3. Remove the `useState` for `isSettingsOpen`.
4. Remove the `{isSettingsOpen && <SettingsModal ... />}` line at the bottom.
5. Replace the entire `<div className="mt-auto p-4 border-t border-[#333537]">` block (the bottom Settings area) with `null` — i.e., delete that block.
6. In the header area (the `<div className="p-4 flex items-center gap-4">` near the top of the sidebar), add a right-aligned region with the logout button and (if admin) the Dashboard link.

The header section becomes:

```tsx
import { useAuth } from "@/context/AuthContext";
// ...existing imports, minus SettingsModal and SettingsIcon

export default function Sidebar({ isOpen, setIsOpen }: SidebarProps) {
  const { user, logout } = useAuth();
  // ...rest of existing component logic, minus isSettingsOpen state

  return (
    <>
      {/* existing overlay div */}
      <div className={`fixed md:relative h-full ...`}>
        <div className="w-sidebar h-full bg-[#1e1f20] flex flex-col border-r border-[#333537] shadow-2xl md:shadow-none">
          {/* HEADER: menu toggle on left, user/logout on right */}
          <div className="p-4 flex items-center justify-between gap-4">
            <button onClick={() => setIsOpen(!isOpen)} className="text-gray-400 hover:text-[#e3e3e3]">
              <MenuIcon className="w-5 h-5" />
            </button>
            <div className="flex items-center gap-3">
              {user?.is_admin && (
                <a
                  href="/dashboard"
                  className="text-xs text-gray-400 hover:text-[#e3e3e3] transition-colors"
                  title="Admin dashboard"
                >
                  Dashboard
                </a>
              )}
              <button
                onClick={() => { void logout(); }}
                className="text-xs text-gray-400 hover:text-[#e3e3e3] transition-colors"
                title={user ? `Sign out ${user.username}` : "Sign out"}
              >
                Sign out
              </button>
            </div>
          </div>

          {/* existing workspace switcher area */}
          <div className="px-4 mb-4">
            {/* ...unchanged */}
          </div>

          {/* existing session list */}
          <div className="flex-1 overflow-y-auto custom-scrollbar px-3 space-y-2 pb-12" onScroll={markSidebarScrolling}>
            {/* ...unchanged */}
          </div>

          {/* The old "bottom-left Settings" block is DELETED entirely. */}
        </div>
      </div>
    </>
  );
}
```

**Important:** the menu toggle button might already be elsewhere — preserve whatever the existing component does for that, just augment the header with the new right-aligned region.

- [ ] **Step 2: Verify Settings.tsx is no longer the entry point for users**

`Settings.tsx` continues to exist as a component (used by `/dashboard` in Task 7) but is no longer rendered by `Sidebar`. The component itself doesn't need to change yet.

- [ ] **Step 3: Smoke compile**

```bash
cd /home/orbital/projects/pryzm/frontend && npx tsc --noEmit 2>&1 | head -10
```

Expected: zero new errors.

- [ ] **Step 4: Commit**

```bash
cd /home/orbital/projects/pryzm && \
git add frontend/src/components/Sidebar.tsx && \
git commit -m "feat(auth): sidebar header gets sign-out + admin Dashboard link; remove bottom Settings button"
```

---

## Task 7: `/dashboard` route — admin-only stub holding the existing models/prompts UI

**Files:**
- Create: `frontend/src/app/dashboard/page.tsx`

**Why:** The Settings button is gone, but the model/micro-prompt admin UI shouldn't vanish from the running app. A minimal `/dashboard` page renders the existing `Settings` modal contents as a page for admins. Phase D will replace this with a real dashboard.

- [ ] **Step 1: Create the route**

Create `frontend/src/app/dashboard/page.tsx`:

```typescript
"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/context/AuthContext";
import { AppProviders } from "@/context/AppProviders";
import ModelsSection from "@/components/SettingsModels";

function DashboardPageBody() {
  const { user, isLoading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && (!user || !user.is_admin)) {
      router.replace("/");
    }
  }, [user, isLoading, router]);

  if (isLoading || !user || !user.is_admin) {
    return <div className="h-dvh w-full bg-[#131314]" />;
  }

  return (
    <div className="min-h-dvh w-full bg-[#131314] text-[#e3e3e3] p-8">
      <div className="mx-auto max-w-3xl space-y-8">
        <header className="flex items-center justify-between">
          <h1 className="text-2xl font-semibold">Admin dashboard</h1>
          <a href="/" className="text-xs text-gray-400 hover:text-[#e3e3e3]">Back to chat</a>
        </header>
        <section>
          <h2 className="text-sm font-medium text-gray-300 mb-3">Models</h2>
          <ModelsSection />
        </section>
        {/* Future sections (audit, users, etc.) will land here in Phase D. */}
      </div>
    </div>
  );
}

export default function DashboardPage() {
  return (
    <AppProviders>
      <DashboardPageBody />
    </AppProviders>
  );
}
```

If `SettingsModels` doesn't export as default, adjust the import. Verify with:

```bash
grep -E "^export" /home/orbital/projects/pryzm/frontend/src/components/SettingsModels.tsx | head -5
```

- [ ] **Step 2: Smoke compile**

```bash
cd /home/orbital/projects/pryzm/frontend && npx tsc --noEmit 2>&1 | head -10
```

- [ ] **Step 3: Commit**

```bash
cd /home/orbital/projects/pryzm && \
git add frontend/src/app/dashboard/page.tsx && \
git commit -m "feat(auth): admin /dashboard route with models section (Phase D placeholder)"
```

---

## Task 8: Permission gating in the existing UI surfaces

**Files:**
- Modify: `frontend/src/components/WorkspaceSwitcher.tsx` (or wherever "create workspace" lives — `grep` first)
- Modify: `frontend/src/components/Settings.tsx` (workspace settings read-only mode)
- Modify: `frontend/src/components/SessionDirectory.tsx` or wherever workspace-delete lives — gate by `user.is_admin`

**Why:** Spec gap H — frontend should hide / disable affordances the user can't act on. Backend still enforces; this is just UX.

- [ ] **Step 1: Locate "create workspace" affordance**

```bash
cd /home/orbital/projects/pryzm && grep -rn -i "create workspace\|new workspace\|onClick.*createWorkspace\|POST.*\/workspaces" frontend/src --include="*.tsx" --include="*.ts" | head -10
```

Find the button or menu item that triggers workspace creation. Wrap its render with:

```tsx
{user.can_create_workspaces && (
  <button onClick={handleCreateWorkspace} className="...">
    New workspace
  </button>
)}
```

`user` from `const { user } = useAuth();` — add the import if missing.

- [ ] **Step 2: Workspace settings read-only when `!owner_can_edit && !is_admin`**

In `frontend/src/components/Settings.tsx`, the workspace-settings section currently allows editing the system prompt, enabled tools, color, and engine config. Wrap the inputs:

```tsx
const { user } = useAuth();
const canEdit = user?.is_admin || workspace.owner_can_edit;

// In the JSX where the inputs render, set:
<input ... disabled={!canEdit} />
<textarea ... disabled={!canEdit} readOnly={!canEdit} />
{/* Tools toggle disabled when !canEdit */}
{/* Color picker disabled when !canEdit */}
```

Add a thin banner at the top of the section when `!canEdit`:

```tsx
{!canEdit && (
  <p className="text-xs text-gray-500 mb-3">
    This workspace is read-only. Contact your admin to enable editing.
  </p>
)}
```

If the workspace shape passed to Settings doesn't already include `owner_can_edit`, plumb it through from `useAuth().user.workspaces` (which DOES have it as of Task 2).

- [ ] **Step 3: Workspace delete affordance gated by `is_admin`**

```bash
cd /home/orbital/projects/pryzm && grep -rn -i "delete.*workspace\|DELETE.*workspaces" frontend/src --include="*.tsx" --include="*.ts" | head -10
```

Find the workspace-delete UI. Wrap with:

```tsx
{user?.is_admin && (
  <button onClick={handleDeleteWorkspace} className="...">
    Delete workspace
  </button>
)}
```

- [ ] **Step 4: Smoke compile**

```bash
cd /home/orbital/projects/pryzm/frontend && npx tsc --noEmit 2>&1 | head -15
```

- [ ] **Step 5: Commit**

```bash
cd /home/orbital/projects/pryzm && \
git add frontend/src && \
git commit -m "feat(auth): gate UI surfaces by useAuth() permission flags"
```

---

## Task 9: Logout flow verification

**Files:** none new — wires together Tasks 3 and 6.

- [ ] **Step 1: End-to-end probe via curl**

With the dev backend running, capture an authenticated session and then logout:

```bash
PRYZM_API_URL=http://127.0.0.1:8000
BOOTSTRAP_USER=$(grep '^PRYZM_BOOTSTRAP_ADMIN_USERNAME' /home/orbital/projects/pryzm/.env | cut -d= -f2- || echo "admin")
# If you have a known admin password handy, use it here; otherwise log in
# via the running UI once and reuse the cookie.

# 1. Login
curl -s -i -c /tmp/pryzm_cookies.txt -X POST "$PRYZM_API_URL/api/auth/login" \
  -H "Content-Type: application/json" -H "Origin: http://localhost:3000" \
  -d "{\"username\":\"$BOOTSTRAP_USER\",\"password\":\"<your-admin-password>\"}" | head -10

# 2. Verify /me works with the cookie
curl -s -b /tmp/pryzm_cookies.txt "$PRYZM_API_URL/api/auth/me" | python3 -m json.tool | head -20

# 3. Logout
curl -s -i -b /tmp/pryzm_cookies.txt -X POST "$PRYZM_API_URL/api/auth/logout" \
  -H "Origin: http://localhost:3000" | head -5

# 4. Verify /me now 401s
curl -s -i -b /tmp/pryzm_cookies.txt "$PRYZM_API_URL/api/auth/me" | head -5
```

Expected: login returns 200 with Set-Cookie; /me returns 200 with the user JSON; logout clears the cookie; subsequent /me returns 401.

- [ ] **Step 2: Update the autotest script**

If `/tmp/pryzm_autotest.py` exists, add a Phase C section that probes the four steps above. If it doesn't exist, skip.

---

## Task 10: Legacy bearer token fallback at `/legacy-token`

**Files:**
- Modify: `frontend/src/components/TokenGate.tsx`
- Create: `frontend/src/app/legacy-token/page.tsx`

**Why:** The auth spec says `getToken()` and `?token=` URL fallback stay in place during Phase C. Some external callers (mobile bookmark, the existing test_suite.json runs) still rely on it. Move the bearer-token entry UI to an out-of-the-way route so it stays usable without dominating the boot flow.

- [ ] **Step 1: Create the legacy-token route**

Create `frontend/src/app/legacy-token/page.tsx`:

```typescript
"use client";

import { useRouter } from "next/navigation";
import { TokenGate } from "@/components/TokenGate";

export default function LegacyTokenPage() {
  const router = useRouter();
  return <TokenGate onConfigured={() => router.replace("/")} />;
}
```

- [ ] **Step 2: Smoke compile**

```bash
cd /home/orbital/projects/pryzm/frontend && npx tsc --noEmit 2>&1 | head -10
```

- [ ] **Step 3: Commit**

```bash
cd /home/orbital/projects/pryzm && \
git add frontend/src/app/legacy-token/page.tsx && \
git commit -m "feat(auth): move bearer-token entry UI to /legacy-token route"
```

---

## Task 11: Full test sweep + manual smoke

- [ ] **Step 1: Backend full sweep**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest -q --ignore=tests/test_image_upload.py --ignore=tests/test_upload_sse.py
```

Expected: all pass (currently 365; new test in Task 2 adds one, expect 366).

- [ ] **Step 2: Frontend typecheck**

```bash
cd /home/orbital/projects/pryzm/frontend && npx tsc --noEmit
```

Expected: zero new errors. Pre-existing errors (if any) ignore.

- [ ] **Step 3: Frontend ESLint**

```bash
cd /home/orbital/projects/pryzm/frontend && npm run lint 2>&1 | tail -20
```

Expected: no new errors. Pre-existing warnings ignore.

- [ ] **Step 4: Restart services**

```bash
# Backend
lsof -ti tcp:8000 | xargs -r kill && sleep 2 && \
cd /home/orbital/projects/pryzm/backend && \
nohup ./venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --reload --reload-delay 2 > /tmp/pryzm_backend.log 2>&1 &
for i in 1 2 3 4 5; do curl -sf -o /dev/null http://127.0.0.1:8000/health && break; sleep 1; done

# Frontend
pkill -9 -f "next-server" ; pkill -9 -f "next dev" ; sleep 3
cd /home/orbital/projects/pryzm/frontend && \
nohup npm run dev -- -H 0.0.0.0 > /tmp/pryzm_frontend.log 2>&1 &
for i in 1 2 3 4 5 6 7 8 9 10; do curl -sf -o /dev/null http://127.0.0.1:3000/ && break; sleep 1; done
```

- [ ] **Step 5: Manual UI smoke (browser checklist)**

Phase C is a phase boundary — manual verification required per project convention.

1. Visit `http://localhost:3000` in a private/incognito window → LoginPage appears (not TokenGate, not the chat UI)
2. Submit bad credentials → "Invalid credentials." error shown
3. Submit correct credentials → chat UI loads, sidebar populated
4. Reload the page → no flash of LoginPage, app loads directly
5. As admin: sidebar header shows "Dashboard" link; click → `/dashboard` opens with the Models section
6. As admin: click "Sign out" in sidebar header → redirected to LoginPage; reload confirms session is gone
7. Log back in. As non-admin (create a regular user via `/api/admin/users` first if needed): sidebar shows no Dashboard link; "Create workspace" hidden if `can_create_workspaces=false`; workspace settings read-only when `owner_can_edit=false`; workspace delete button absent
8. Visit `http://localhost:3000/legacy-token` → bearer-token entry form still works (paste the `PRYZM_API_TOKEN` value); after configuring, redirect to `/` and app loads

Note any deviations.

---

## Task 12: Push branch + open PR

- [ ] **Step 1: Push**

```bash
cd /home/orbital/projects/pryzm && git push -u origin feat/auth-phase-c
```

- [ ] **Step 2: Open PR**

```bash
gh pr create --base main --head feat/auth-phase-c \
  --title "feat(auth): Phase C — frontend login page + permission gating" \
  --body "$(cat <<'EOF'
Replaces the bearer-token gate with a cookie-based login page; surfaces user identity and permission flags via `useAuth()`; gates UI per the auth spec; adds a logout flow.

## Changes
- `useAuth()` context: `{ user, isLoading, refresh, logout }`; fetches `/api/auth/me` on boot
- New `LoginPage` (replaces `TokenGate` in the boot flow); `TokenGate` itself moves to `/legacy-token` as a fallback for non-migrated callers
- `/api/auth/me` returns the user's workspaces inline (saves one round-trip on boot)
- Sidebar: bottom Settings button removed; sign-out + admin Dashboard link in header
- `/dashboard` route holds the existing models/prompts UI for admins (Phase D will replace)
- Permission gating: "create workspace" hidden unless `can_create_workspaces`; workspace settings read-only unless `owner_can_edit || is_admin`; workspace delete admin-only

Spec: `docs/specs/2026-05-17-user-login-and-admin.md`. Plan: `docs/plans/2026-05-18-auth-phase-c.md`.

Bearer token (`getToken()` / `?token=` URL fallback) stays functional during this phase per spec. Removal is Phase E.
EOF
)"
```

- [ ] **Step 3: No auto-merge** — Phase C is a phase boundary; user reviews and merges manually.

---

## Self-review

Spec coverage check:

- [x] App boot uses `GET /api/auth/me` (Task 3/5)
- [x] 401 → LoginPage (Task 5)
- [x] `getToken()` / `?token=` URL fallback retained (Task 10, plus no removal in Task 1)
- [x] `useAuth()` exposes `user`, `is_admin`, `can_create_workspaces` (Task 3)
- [x] Bottom-left Settings button removed entirely (Task 6)
- [x] Workspace switcher "create workspace" hidden unless `can_create_workspaces` (Task 8)
- [x] Workspace settings UI read-only when `owner_can_edit` is false (Task 8)
- [x] Workspace delete UI hidden from non-admin (Task 8)
- [x] Sidebar gains Dashboard link visible only to admins (Task 6)
- [x] Logout flow in sidebar header (Task 6 + 9)

Under-specified spots (judgment calls left to implementer, flagged here):

- Task 6's exact JSX rewrite depends on the current Sidebar structure; the implementer should preserve unrelated behavior (workspace switcher, session list, scroll handler) verbatim.
- Task 8 Step 1's "locate create-workspace affordance" depends on the actual component layout. The grep finds it; the wrap pattern is consistent.
- Task 8 Step 2's plumbing of `owner_can_edit` from auth context depends on how Settings currently receives its `workspace` prop. If Settings already reads from `WorkspaceContext`, the auth context's `workspaces` array might need to merge in there — implementer applies judgment.

Known fallbacks intentionally kept (out of scope for Phase C, planned for Phase E):

- Bearer-token plumbing (`getToken`/`setToken`/`?token=`)
- RFC1918 CORS regex wildcard
- `PRYZM_API_TOKEN` env requirement at startup
