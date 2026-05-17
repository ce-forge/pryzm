# User login + workspace ownership

## Status

Design ready for implementation. Replaces the May 17 draft, which assumed shared workspaces with a `workspace_members` table. The model is now per-user workspaces instantiated from admin-controlled templates ("Pattern B").

## Why

Today's auth is a single shared bearer token in `localStorage`, with a `?token=` URL fallback for `EventSource` and `<img>`. Workspaces are plumbed end-to-end through `?workspace={slug}`, but every token-holder sees every workspace.

To support multiple users with isolated chats, folders, and workspace settings — and to give one admin the ability to provision test users without those users stepping on the admin's setup — we need real per-user auth plus a per-user workspace model.

## Goals

- Per-user login with HttpOnly session cookies.
- An `admin` role that creates, edits, and removes users; manages templates; pushes workspace updates; observes activity through the dev dashboard.
- Per-user workspaces. A user's workspaces, chats, folders, and uploads are visible only to that user (and to admin via the dashboard).
- Admin-controlled provisioning. Users start with the workspaces admin gives them. Permission flags determine whether they can create more or edit what they have.
- Clean migration path. Backend runs dual-auth (bearer + cookie) during the transition; the bearer path goes away in the final phase.

## Non-goals (v1)

- OAuth / SSO / SAML. Username+password only.
- Public self-registration. Admin creates users.
- Email-based password reset. Admin resets.
- Per-user system-prompt overrides on shared workspaces (Pattern B sidesteps this by giving each user their own workspace).
- Workspace sharing between users.
- TOTP / MFA.
- Detailed audit logging. Auth lifecycle events are logged once the audit subsystem ships (separate spec); this spec only adds the auth `user_id` that the audit log will reference.

## Data model

Three new tables. Two existing tables gain columns. One existing table is repurposed as templates.

### New: `users`

| column | type | notes |
|---|---|---|
| `id` | UUIDv7 PK | |
| `username` | text, unique (case-insensitive) | stored lowercase, display can preserve case |
| `password_hash` | text | argon2id via `argon2-cffi` |
| `email` | text, nullable | admin-supplied; not used for auth or reset |
| `is_admin` | bool, default false | |
| `is_active` | bool, default true | soft-disable; `false` users can't log in |
| `can_create_workspaces` | bool, default false | admin-controlled per-user capability flag |
| `created_at`, `last_login_at` | timestamptz | |

### New: `auth_sessions`

Named to avoid colliding with the chat `sessions` table.

| column | type | notes |
|---|---|---|
| `id` | text PK | random 256-bit token, base64url; this is what goes in the cookie |
| `user_id` | UUID FK users, on delete CASCADE | |
| `created_at`, `expires_at`, `last_seen_at` | timestamptz | |

Index on `expires_at` for the cleanup sweeper.

### Modified: `workspaces`

| column | type | notes |
|---|---|---|
| `user_id` | UUID FK users, nullable, on delete CASCADE | NULL for templates |
| `is_template` | bool, default false | templates are admin-owned, instantiable |
| `template_id` | UUID FK workspaces, nullable, on delete SET NULL | which template this was instantiated from |
| `owner_can_edit` | bool, default false | gates whether the workspace's `user_id` user can edit settings |

Unique constraint changes: today `UNIQUE(slug)` globally; under Pattern B, `UNIQUE(user_id, slug)` for per-user workspaces and `UNIQUE(slug) WHERE is_template = true` for templates. Templates keep globally unique slugs so admin can refer to them unambiguously.

### Modified: `folders`

Add `user_id UUID NOT NULL` (FK users, on delete CASCADE). Folders become per-user within a workspace.

Separately: the existing client-supplied `folders.id` becomes server-generated UUIDv7 (gap C from brainstorm). Drops the `id` field from `FolderCreate`.

### Modified: `sessions` (chat)

Add `user_id UUID NOT NULL` (FK users, on delete CASCADE). Chats become per-user within a workspace.

## Permission model

Three layers:

1. **System-level (admin only):** model management, micro-prompts, token config (transitional), the dev dashboard itself, llama-swap proxy. Gated by `require_admin`.
2. **User-level capability:** `users.can_create_workspaces` — can this user spawn new workspaces from templates? Default false.
3. **Workspace-level capability:** `workspaces.owner_can_edit` — can the workspace's owner edit its settings (system prompt, tools, color, engine_config, rename)? Default false. Admin can always edit any workspace.

Workspace delete is admin-only regardless of `owner_can_edit`. Deleting destroys all chats and folders in the workspace — too destructive to put in the user path.

## Templates

Templates are workspaces with `is_template = true` and `user_id = NULL`. Today's builtin workspaces (`it_copilot`, `personal`) become templates in the auth migration.

**Creation:** admin only. CRUD via `/api/admin/templates`.

**Instantiation:** copies the template's settings columns into a new `workspaces` row with `user_id = <target user>`, `template_id = <template>`, `is_template = false`. Slug defaults to the template's slug; admin can override at instantiation time.

**Duplicate instantiation:** blocked. If a user already has a workspace with `template_id = X`, attempting to instantiate that template again for that user returns an error: *"User already has a workspace from this template. Push update to apply the latest template, or delete the existing workspace first."*

**Push update:** admin operation. Updates the settings columns (`system_prompt`, `enabled_tools`, `color`, `engine_config`) on every workspace where `template_id = X`. Does not touch identity (`slug`, name, `user_id`, `id`) or any FK targets (chats, folders, documents stay attached). UI shows a warning before push: *"This will overwrite system prompt, enabled tools, and model settings on N user workspaces (M with customizations)."*

**Template deletion:** sets `template_id = NULL` on existing instances. Instances continue to work as standalone workspaces; admin can no longer push to them.

## Admin push behavior in detail

| Field | Pushed | Preserved |
|---|---|---|
| `system_prompt`, `enabled_tools`, `color`, `engine_config` | yes | — |
| `slug`, name (display) | — | yes |
| `user_id`, `id`, `template_id`, `owner_can_edit`, `is_template` | — | yes |
| Attached chats, folders, documents | — | yes (FK references unchanged) |

The push is always full overwrite for the settings columns. User customizations are clobbered by design; the warning dialog flags this.

## Auth flow

Cookie-based sessions backed by the `auth_sessions` Postgres table. No JWTs (rotation, revocation complexity, payload size don't pay off at this scale).

**`POST /api/auth/login`** — body `{username, password}`. On success: insert `auth_sessions` row, set cookie `pryzm_session=<sid>; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=<idle window>`. Return `{id, username, is_admin, can_create_workspaces, workspaces: [...]}`. On failure: 401, no cookie, generic "Invalid credentials" (same for wrong password and disabled account). 200-300ms artificial delay on failure to slow enumeration without enabling timing oracles. Login attempts rate-limited per username (gap M): after 10 failures in a 15-minute window, the username is locked for 15 minutes; admin can reset.

**`POST /api/auth/logout`** — delete the `auth_sessions` row matching the cookie; clear the cookie via `Max-Age=0`. Idempotent.

**`GET /api/auth/me`** — return the current user (or 401). Frontend hits this on app boot to choose login-page vs main-app.

**Session sliding:** every authenticated request bumps `last_seen_at`. If `last_seen_at + idle_window < now()` the session is invalidated. Hard cap on `expires_at` regardless of activity.

**Session lengths:** 7-day idle window, 30-day hard cap.

**Cookie parameters:**
- `HttpOnly` — JS can't read it.
- `Secure` — set when the request was over TLS (dev over plain HTTP omits).
- `SameSite=Lax` — blocks cross-site state-changing requests without breaking normal navigation.
- `Path=/` — covers all routes.

**Session invalidation on password change / deactivation (gap A):** when admin resets a user's password, or the user changes their own, or the admin deactivates the user, `DELETE FROM auth_sessions WHERE user_id = ?` runs in the same transaction. Forces re-login on all the user's devices.

## CSRF defense

- `SameSite=Lax` covers cross-site POST/PUT/DELETE for normal navigation.
- `Origin` header check on every state-changing endpoint (POST/PUT/DELETE/PATCH) as defense-in-depth: reject if `Origin` is not in the configured allowlist. Reuses the CORS allowlist.
- Login endpoint itself gets the same `Origin` check (login CSRF prevention — attacker shouldn't be able to force a user to log in as the attacker).

**CORS posture changes in Phase E (gap D):** today's `allow_origins` regex permits any RFC1918/loopback origin with `allow_credentials=True`. Once cookies are the auth path, this becomes a real CSRF surface: any page served by any device on the LAN can issue credentialed cross-origin requests. When the bearer fallback is removed in Phase E, replace the private-network regex with an explicit per-host allowlist (the actual frontend origins, configurable via env).

## Replacing `?token=` for SSE and `<img>`

Today's `EventSource` and `<img>` calls put the bearer token in the URL because neither can set custom headers. With cookies that becomes automatic — cookies are sent on same-origin requests by default for both. The `getToken()` / `?token=` plumbing gets deleted in Phase E once cookies are the only auth.

During the transition, the backend accepts either form (see "Migration" below).

Frontend and backend run on different ports today (`:3000` and `:8000`), which are different *origins* but the same *site* for cookie purposes (site is registrable domain, not port). So cookies will be sent on cross-port same-site requests as expected.

## Workspace ownership gating

The existing `workspace_query_dep` becomes:

```python
def workspace_query_dep(
    workspace: str = Query(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Workspace:
    ws = db.query(Workspace).filter(
        Workspace.slug == workspace,
        Workspace.user_id == user.id,
        Workspace.is_template == False,
    ).first()
    if ws is None:
        raise HTTPException(404)
    return ws
```

Admin bypass: admin can query any workspace via the admin endpoints (which take an explicit workspace_id), not via the per-user `?workspace=<slug>` flow.

The 404-not-403 convention matches the rest of the codebase (no info leak about workspace existence).

## Endpoints

**Auth (any authenticated user)**
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/auth/me`
- `POST /api/auth/password` — change own password; invalidates sessions other than the current one

**User workspaces (the workspace's owner)**
- `GET /api/workspaces` — list current user's workspaces
- `POST /api/workspaces` — create from template; gated by `can_create_workspaces`
- `GET /api/workspaces/{slug}`
- `PUT /api/workspaces/{slug}` — gated by `owner_can_edit` (admin always allowed via the admin route)
- Workspace delete is not available on this route; admin-only via `/api/admin/workspaces/{id}`

**Admin: users (`require_admin`)**
- `GET /api/admin/users` — paginate, filter active/inactive
- `POST /api/admin/users` — `{username, password, email?, is_admin?, can_create_workspaces?, starter_templates: [{template_id, owner_can_edit}]}`. Creates user and instantiates the specified templates atomically.
- `GET /api/admin/users/{id}`
- `PUT /api/admin/users/{id}` — update fields except password
- `POST /api/admin/users/{id}/password` — admin reset; invalidates all sessions for that user
- `DELETE /api/admin/users/{id}` — soft-delete by default. `?hard=true` cascades; see "Audit log integration" for how that interacts with audit history.

**Admin: templates (`require_admin`)**
- `GET /api/admin/templates`
- `POST /api/admin/templates` — create
- `GET /api/admin/templates/{id}`
- `PUT /api/admin/templates/{id}` — edit template settings
- `DELETE /api/admin/templates/{id}` — sets `template_id = NULL` on instances
- `POST /api/admin/templates/{id}/instantiate` — `{user_id, slug?, owner_can_edit?}` — create a workspace instance for a target user
- `POST /api/admin/templates/{id}/push` — overwrite settings on all instances

**Admin: workspaces (`require_admin`)**
- `GET /api/admin/users/{user_id}/workspaces` — list a user's workspaces
- `GET /api/admin/workspaces/{id}` — admin view of any workspace
- `PUT /api/admin/workspaces/{id}` — admin edit of any workspace (bypasses `owner_can_edit`)
- `DELETE /api/admin/workspaces/{id}` — admin can delete any workspace

**Admin: last-admin guard (gap B):** every endpoint that could lead to "zero active admins" (`PUT /api/admin/users/{id}` setting `is_admin=false` or `is_active=false`, `DELETE /api/admin/users/{id}` on the only admin) checks the count first. Refuses with a clear error message naming the constraint.

**Existing admin routes** (`/api/admin/models`, `/api/prompts/*`) — keep `require_admin` (they need it today via `require_token`, the gate just becomes user-level).

## Bootstrap

First-boot admin user is a chicken-and-egg problem ("you need an admin to create users").

**Approach: env vars on backend startup.**
- `PRYZM_BOOTSTRAP_ADMIN_USERNAME` (default `admin`)
- `PRYZM_BOOTSTRAP_ADMIN_PASSWORD` — if set AND `users` table is empty, create an admin with this password.

If the env is unset and the `users` table is empty, the backend refuses to start with a clear error pointing at the env var.

After first boot the env is ignored (table is no longer empty). Bootstrap admin should rotate the password from the UI immediately. The bootstrap admin is also auto-granted instances of all current builtin templates (`it_copilot`, `personal`) so their first-launch UX matches today's behavior.

## Migration from bearer token

Five phases on the backend, two on the frontend.

### Phase A (backend) — auth model
Create `users`, `auth_sessions`. Add `user_id` columns to `workspaces`, `folders`, `sessions`. Add `is_template`, `template_id`, `owner_can_edit` to `workspaces`. Add `can_create_workspaces` to `users`.

Backfill existing data:
- Builtin workspaces (`it_copilot`, `personal`) marked `is_template = true`, `user_id = NULL`.
- Bootstrap admin created from env vars on first boot.
- Existing chats/folders/documents (if any) backfilled to the bootstrap admin's `user_id`.
- Bootstrap admin auto-instantiated with both builtins.

Implement `POST /api/auth/login`, `/logout`, `/me`. Bearer auth (`require_token`) stays in place; new login flow is additive.

Folder ID generation moves to server-side (UUIDv7) — drop `id` from `FolderCreate` schema.

### Phase B (backend) — workspace ownership + admin endpoints
Switch `workspace_query_dep` to require `current_user` and match on `(slug, user_id)`. Bearer auth holders still pass (they resolve to the bootstrap admin per the dual-auth bridge). Add admin endpoints for users, templates, workspaces. Add `require_admin` to model/micro-prompt routes.

Last-admin guard and session-invalidation-on-password-change land here.

### Phase C (frontend) — login page replaces token gate
App boot flow: `GET /api/auth/me`; if 401, show login page; else show main app. Existing `getToken()` and `?token=` URL fallback stay in place during this phase (still needed by callers that haven't moved over).

Wire `useAuth()` context (`user`, `is_admin`, `can_create_workspaces`) into the frontend. Audit UI surfaces for permission gating (gap H):
- Bottom-left Settings button removed entirely.
- Workspace switcher "create workspace" hidden unless `can_create_workspaces`.
- Workspace settings UI read-only when `owner_can_edit` is false.
- Workspace delete UI hidden from non-admin.
- Sidebar gains a Dashboard link visible only to admins.
- Logout flow lands in the sidebar header.

### Phase D (frontend + backend) — dev dashboard
The dev dashboard is its own spec (see `docs/specs/2026-05-DD-dev-dashboard.md` once written). Phase D is reserved for that work and depends on Phase B + Phase C plus the audit logging subsystem (because the Audit tab needs `audit_events`).

### Phase E (backend + frontend) — remove bearer-token fallback
Replace `require_token` with `require_user` (cookie-only). Delete `?token=` URL fallback. CORS regex tightens to an explicit per-host allowlist. `EventSource` and `<img>` rely on the cookie being sent automatically.

Each phase is independently shippable. Bearer token keeps working through Phase D.

## Audit log integration

Audit logging has its own spec (next). What this spec needs to commit to:

**Auth lifecycle events (gap L):** login success, login failure (with attempted username and source IP), logout, password change (by user or admin), session expiry, account deactivation, account activation, admin promotion/demotion. All written to `audit_events` once the audit subsystem ships.

**Hard delete vs audit integrity (gap K):** when admin hard-deletes a user (`?hard=true`):
- `users` row goes
- `auth_sessions` cascades
- `workspaces` cascades (and their chats, folders, documents cascade through)
- `audit_events.user_id` is set NULL via `ON DELETE SET NULL`; a `user_display_name_at_event` column on `audit_events` (populated at event write time) keeps the event readable in the dashboard

This means `audit_events` cannot use a hard FK with cascade to users — it uses `ON DELETE SET NULL`. The audit spec will codify this. Mentioned here so the auth migration knows not to add CASCADE on a future `audit_events.user_id` FK.

## Decisions (all resolved)

1. **Session backing store:** Postgres `auth_sessions` table. Move to Redis if profiling shows lookup latency on the hot path.
2. **Session lengths:** 7-day idle window, 30-day hard cap.
3. **Password policy:** 12-character minimum, no other rules (NIST 800-63B). No rotation. Common-password reject is a v2 polish.
4. **Username case-sensitivity:** case-insensitive unique (store lowercased, compare lowercased, display can preserve case).
5. **Active-only login enforcement:** `is_active=false` returns generic "Invalid credentials" same as wrong password.
6. **Hard vs soft delete default:** soft default; hard via `?hard=true`.
7. **Bootstrap admin password source:** env var on first boot; backend refuses to start if env unset and `users` is empty.
8. **Cookie name:** `pryzm_session`.
9. **Chat-session ownership:** chats are per-user. Backfill existing chats to the bootstrap admin during Phase A.

Additional decisions resolved in the May 18 brainstorm:

10. **Workspace model:** per-user workspaces instantiated from admin-controlled templates (Pattern B).
11. **`workspace_members` table:** dropped. Workspaces have a single owner via `workspaces.user_id`.
12. **Permission flags:** `users.can_create_workspaces` and `workspaces.owner_can_edit`, both default false.
13. **Workspace delete:** admin-only.
14. **Duplicate template instantiation:** blocked with a clear error.
15. **Template deletion:** sets `template_id = NULL` on instances.
16. **Admin push:** overwrites all settings (including `engine_config`), preserves identity and FK targets. Warning dialog flags affected workspaces with customizations.
17. **Soft-deleted users:** invisible to the user, visible to admin in the dashboard.
18. **Slug behavior:** unchanged from today, except uniqueness scope (`UNIQUE(user_id, slug)` for per-user workspaces, `UNIQUE(slug) WHERE is_template = true` for templates).
19. **Folder ID generation:** server-side UUIDv7 (was client-supplied).
20. **Login rate limiting:** 10 failures per username per 15-minute window triggers a 15-minute lockout. Admin can reset.

## Phased plan (sizing only — implementation plan is a separate doc)

- **Phase A** — auth model, login/logout/me, folder-id server generation, Phase A backfill. ~3 days.
- **Phase B** — workspace ownership migration, admin endpoints, last-admin guard, session invalidation on password change. ~3-4 days.
- **Phase C** — frontend login page, permission-flag UI audit, logout home. ~2 days.
- **Phase D** — dev dashboard (separate spec).
- **Phase E** — bearer-token removal, CORS tightening. ~half day.

Auth foundation (Phases A-C + E) is roughly 1.5 weeks. Phase D depends on the audit subsystem landing first.

## What this unblocks

- Multi-user deployments where each user has isolated chats and workspaces.
- The audit logging subsystem (needs `user_id`).
- The dev dashboard subsystem (needs auth, audit, and admin endpoints).
- Bug-report flow (rides on audit and the dashboard).
- Per-user IT-platform credentials (future-features item) and other identity-bound integrations.
