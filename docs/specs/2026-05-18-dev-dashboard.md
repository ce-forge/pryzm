# Dev dashboard, bug reports, and notifications

## Status

Design ready for implementation. Depends on the auth foundation (`docs/specs/2026-05-17-user-login-and-admin.md`) and audit logging (`docs/specs/2026-05-18-audit-logging.md`) shipping first.

## Why

Once auth and audit are in place, the admin needs a single surface to operate the application: see users and what they're doing, manage workspace templates, observe the engine, triage bugs, and adjust system-level config. Today this is fragmented (the bottom-left Settings modal, manual SQL, `localhost:8080` in another tab). The dev dashboard consolidates everything operational into one place.

This spec also covers two adjacent features that live next to the dashboard: a bug-report flow (user submits, admin manages, user gets notified on resolution) and a small notification primitive that the bug flow uses.

## Goals

- One admin route (`/admin`) with six tabs covering users, workspaces, audit, the engine, system config, and bug reports.
- Bug-report flow: user submits from the chat UI; admin manages from the dashboard; user gets a notification on resolution.
- Generic notification primitive that the bug flow uses and that's reusable for future cases (admin broadcasts, system messages).
- Reverse-proxy llama-swap so its UI lives inside the dashboard under Pryzm's admin auth.
- Visual style consistent with the existing chat UI.

## Non-goals (v1)

- Real-time live updates of dashboard data. Polling on user action or simple refresh is fine.
- Admin "login as user" / impersonation. Settings-only access is enough.
- An application-log tab (FastAPI/uvicorn stdout). `docker logs` is the existing path.
- Maintenance actions tab (re-run GC, regenerate embeddings, restart models). Flag for v2 if friction surfaces.
- Per-tool denylists in audit log payloads. Add when the first sensitive tool ships.
- Push notifications (browser Notification API, WebPush). Pin in the app is enough.

## Architecture

New top-level Next.js route at `/admin`. Sub-routes per tab:
- `/admin/users`
- `/admin/workspaces` (toggles between Templates and Per-user views)
- `/admin/audit`
- `/admin/engine`
- `/admin/system`
- `/admin/bug-reports`

The whole `/admin` subtree is gated client-side by `useAuth().user.is_admin`. The real gate is server-side: every backend endpoint the dashboard calls is `require_admin`. The client check is for UX only — non-admins don't see the link or accidentally land on a 401 page.

Sidebar gains a Dashboard link visible only to admins. Non-admins see no link and no `/admin` UI.

Tabs lazy-mount (especially the Engine iframe). Inactive tabs stay unmounted to avoid memory bloat and avoid the iframe loading llama-swap at app start.

## Data model

### `bug_reports`

| column | type | notes |
|---|---|---|
| `id` | UUIDv7 PK | |
| `user_id` | UUID FK users, ON DELETE SET NULL, nullable | who reported it |
| `user_display_name` | text | snapshot at submit time for resilience after user delete |
| `workspace_id` | UUID FK workspaces, ON DELETE SET NULL, nullable | context where reported |
| `session_id` | UUID FK sessions, ON DELETE SET NULL, nullable | context where reported |
| `message` | text | user's description |
| `payload` | JSONB | browser, OS, current URL, recent console errors if captured |
| `status` | text | `'open'`, `'acknowledged'`, `'resolved'`, `'dismissed'` |
| `resolved_at` | timestamptz, nullable | set when status moves to `'resolved'` |
| `resolved_by` | UUID FK users, nullable | admin who marked it resolved |
| `created_at` | timestamptz | |

Indexes: `(status, created_at DESC)` for the default "open + acknowledged" view, `(user_id, created_at DESC)` for the per-user history.

### `notifications`

| column | type | notes |
|---|---|---|
| `id` | UUIDv7 PK | |
| `user_id` | UUID FK users, ON DELETE CASCADE | recipient |
| `message` | text | shown in the popover |
| `source` | text | `'bugreport.resolved'`, `'admin.broadcast'`, `'admin.direct'`, etc. |
| `source_id` | UUID, nullable | e.g., the `bug_report.id` that triggered the notification |
| `link_url` | text, nullable | optional clickable target |
| `created_at` | timestamptz | |
| `seen_at` | timestamptz, nullable | set when user acknowledges |

Index: `(user_id, seen_at)` so the unseen-count query (`WHERE user_id = ? AND seen_at IS NULL`) is fast.

## Tab-by-tab design

### Users tab

**Default view:** paginated table of users — username, email, is_admin, is_active, last_login, workspace_count.

**Filters:** active/inactive toggle, admin-only filter, search by username.

**Create user (modal):**
- username, password (with strength meter), email (optional), is_admin checkbox, can_create_workspaces checkbox
- Starter-templates multi-select: pick which templates to instantiate for the new user, with per-template `owner_can_edit` toggle
- Submit → atomically creates the user, instantiates the chosen templates as the user's workspaces

**Per-row actions:**
- Edit (modal) — change username, email, is_admin, can_create_workspaces, is_active
- Reset password (modal) — admin types new password; submission invalidates all the user's sessions
- Deactivate / reactivate
- Delete (with confirm) — soft by default; checkbox in the dialog for hard delete (with second confirmation since cascade is destructive)

**Click user row → user detail page** at `/admin/users/{id}`:
- User's workspaces (with same edit/delete affordances as the Workspaces tab)
- Recent activity (last N audit_events for this user — pre-filtered audit view)
- Open bug reports filed by this user

### Workspaces tab

**Two sub-views via a toggle:**

**Templates view:**
- Table of admin-owned templates (is_template=true)
- Per-template actions: edit settings (system_prompt, enabled_tools, color, engine_config, slug), push to all instances, instantiate for a user, delete
- "Push" action shows a confirmation: *"This will overwrite system prompt, enabled tools, and model settings on N user workspaces (M with customizations). Continue?"*
- Create new template (full form)

**Per-user workspaces view:**
- Filterable by user (dropdown) and by template (dropdown)
- Table: workspace name, owner (user), template-of-origin, owner_can_edit flag, created_at
- Per-row actions: edit settings, delete, toggle owner_can_edit
- Click row → workspace detail page showing settings, attached chats, attached folders, attached documents

### Audit tab

**Default view:** paginated table of recent audit_events.

**Filters:** user (dropdown of all users), event_type (dropdown of known prefixes plus exact match), workspace (dropdown), time range (presets: last hour, last day, last week, last month, custom).

**Pagination:** cursor-based (created_at + id) — stable scrolling even as new events append.

**Per-row click → event detail modal:** full payload, links to related entities (user, workspace, session). Includes a "show full chat message" link if the event is `chat.message_sent` or `chat.message_received` and the session is still around.

### Engine tab

**Single iframe** pointing at `/api/admin/engine/` (the llama-swap reverse-proxy path). Llama-swap's own UI handles its tabs (Playground, Models, Activity, Logs, Performance).

Lazy-mounted: the iframe element only exists in the DOM while the tab is active. Switching away unmounts.

The iframe path is gated by `require_admin` on the backend, so direct navigation to `/api/admin/engine/` without admin auth returns 401.

### System tab

**Three sub-sections:**

**Model management** — ported from the existing `SettingsModels.tsx`. Same data and same controls (add/remove models, download status, configuration), wrapped in the dashboard chrome rather than a standalone modal.

**Micro-prompts** — ported from the existing `Settings.tsx` micro-prompt editor. Global config, applies to all workspaces.

**Token configuration (transitional)** — only shown during Phase D while the bearer-token fallback is still wired. Removed entirely in Phase E.

### Bug Reports tab

**Default view:** table of bug reports filtered to `status IN ('open', 'acknowledged')`.

**Filters:** status (all/open/acknowledged/resolved/dismissed), user (dropdown).

**Table columns:** created_at, user, status, message preview (first 100 chars), context (workspace/session shortcut).

**Per-row click → bug detail modal:**
- Full message
- Payload context (browser, OS, URL, recent console errors if captured)
- Linked workspace/session (clickable to admin views)
- Audit timeline for this bug (queries audit_events filtered by `source_id = bug_report.id`)
- Action buttons: Acknowledge, Resolve, Dismiss, Delete

**Resolve action:**
- Updates `bug_reports.status='resolved'`, `resolved_at=now()`, `resolved_by=current_admin.id`
- Inserts an `audit_events` row with `event_type='bugreport.resolved'`
- **Inserts a `notifications` row** for the bug's `user_id` with `source='bugreport.resolved'`, `source_id=<bug_report.id>`, `message="Your bug report has been resolved: <first 60 chars of bug message>"`

**Dismiss action:** same as resolve but no notification fires (used for invalid/spam reports). Status moves to `'dismissed'`, audit event written.

**Delete action:** removes the row entirely (the audit event for the original submission stays). Requires confirmation.

## Bug-report submission (user-facing)

A small UI element in the user's chat surface lets them submit bug reports.

**Placement:** sidebar footer, next to the avatar / logout area. A small icon button labeled "Report a bug" or similar.

**Submit modal:**
- Text area for the bug description
- Optional checkbox: "Include current chat session" (captures session_id so admin can see the conversation)
- Submit button

**On submit:**
- `POST /api/bug-reports` with `{message, include_session: bool}`
- Backend inserts the `bug_reports` row (with current workspace_id, session_id if opted-in, current URL, user-agent in payload)
- Inserts an `audit_events` row with `event_type='bugreport.submitted'`
- Returns 200; UI shows a brief "Thanks — we'll look into it" toast

No notification fires on submission (the user is the one submitting; they know).

## Notification system

**Polling cadence:** every 30 seconds while the app is focused, plus once on window focus event (so switching back to a stale tab refreshes). Skip when window is blurred or app is backgrounded.

**Frontend component (`NotificationPin`):** lives in the sidebar header.
- Shows a bell icon
- Red badge with count when `unseen_count > 0`
- Click → popover with the unseen messages, newest first
- Each message has a small dismiss "x"
- Clicking the message body marks it `seen` and (if `link_url` is set) navigates there
- "Mark all as seen" button at the bottom of the popover
- Popover auto-closes after 5 seconds of no interaction

**Auto-dismiss-after-seen behavior:** when a notification is marked seen, the popover removes it from the visible list. The DB row stays (seen_at set) — the popover is a transient view.

**Admin broadcast UI:** small form in the Users tab (or as a sub-page) where admin types a message and submits to all users at once. Less common surface; can ship in a follow-up if needed.

## Endpoints

All admin endpoints `require_admin`. User-facing endpoints require auth.

### Dashboard meta
- (None — the dashboard uses existing user/workspace/audit endpoints plus the bug-report + notification routes below.)

### Bug reports
- `POST /api/bug-reports` — user submission; body `{message, include_session: bool}`
- `GET /api/admin/bug-reports` — paginated, filter by status, user
- `GET /api/admin/bug-reports/{id}` — detail with payload + audit timeline
- `POST /api/admin/bug-reports/{id}/acknowledge` — status → 'acknowledged'
- `POST /api/admin/bug-reports/{id}/resolve` — status → 'resolved', notification fires
- `POST /api/admin/bug-reports/{id}/dismiss` — status → 'dismissed', no notification
- `DELETE /api/admin/bug-reports/{id}` — hard delete row

### Notifications
- `GET /api/notifications/unseen` — current user's unseen notifications
- `POST /api/notifications/{id}/seen` — mark single notification seen
- `POST /api/notifications/seen-all` — mark all current user's notifications seen
- `POST /api/admin/notifications` — admin sends to specific user; body `{user_id, message, link_url?}`
- `POST /api/admin/notifications/broadcast` — admin sends to all active users; body `{message, link_url?}`

### Engine reverse-proxy
- `* /api/admin/engine/{path:path}` — proxies to `http://llama_swap:8080/{path}`. Streams responses. Handles WebSocket upgrade if llama-swap uses websockets for live data.

## llama-swap proxy: implementation wrinkles

Worth flagging upfront because they're easy to underestimate:

**Base-path rewriting.** Llama-swap's UI likely emits absolute URLs (e.g., `/api/models`, `/static/...`). When iframed at `/api/admin/engine/`, those absolute paths break unless either:
- Llama-swap supports a configurable base path (check the binary's flags or env vars first — this is the cleanest fix)
- The proxy rewrites HTML/JS responses to inject the prefix (complex, fragile)
- The proxy returns a 302 to the bare path on root (fails because we want it under our auth)

Check llama-swap's documentation for base-path support first. If absent, file an upstream feature request and consider running it on a dedicated subdomain (`engine.localhost`) instead of a sub-path.

**WebSocket support.** If llama-swap streams live updates over WebSocket, the proxy needs to handle the WS upgrade. FastAPI/Starlette supports this via `WebSocketRoute` and `httpx-ws` or similar. Plan for this; don't discover it during implementation.

**Auth posture.** Llama-swap has no auth of its own. After the proxy lands, port 8080 should be firewalled from external access; only admin-gated proxy access exposes the UI. Operational note for deployment docs.

## Migration / phasing

Phase D of the broader work. Sequence assumes auth Phase B + audit Phase F.2 have shipped.

- **D.1** — `/admin` route scaffolding, tab navigation, lazy-mount infrastructure.
- **D.2** — `bug_reports` + `notifications` tables (alembic migration). Endpoints stubbed.
- **D.3** — Bug Reports tab + bug-report submission UI in the chat surface. Bug-resolve → notification insert wiring.
- **D.4** — NotificationPin component + polling endpoints. The pin works end-to-end for bug-report resolutions.
- **D.5** — Audit tab (needs audit F.3 endpoints).
- **D.6** — Engine tab + llama-swap reverse-proxy.
- **D.7** — System tab (port `SettingsModels.tsx` + micro-prompt editor + transitional token config).
- **D.8** — Users tab (the largest single sub-phase: create-user modal with starter templates, edit, delete, password reset, per-user detail page).
- **D.9** — Workspaces tab (templates view + per-user workspaces view).

Each is its own PR. D.1 lands first; D.5/6/7/8/9 can land in any order once their dependencies are in place.

## Decisions

All resolved during brainstorm:

1. **Six tabs:** Users, Workspaces, Audit, Engine, System, Bug Reports.
2. **Bug reports separate from audit_events:** `bug_reports` is its own mutable table; lifecycle events recorded in `audit_events`.
3. **Notifications as a generic primitive:** `notifications` table, used by the bug-resolve hook in v1, reusable for admin broadcasts and system messages later.
4. **Notification delivery:** polling, not push. 30-second interval while window is focused.
5. **Notification auto-dismiss:** popover closes after 5 seconds of no interaction; DB row stays with `seen_at` set.
6. **Bug resolve always notifies the user.** No admin opt-out at resolve time. Dismiss exists for cases where notification isn't appropriate.
7. **Engine tab uses iframe**, not native re-render. Lazy-mounted.
8. **System tab absorbs the old bottom-left Settings content.** No bottom-left Settings button in the chat UI.
9. **Bug report submission lives in the sidebar footer** of the chat UI. Small icon, modal on click.
10. **Admin can't impersonate users.** Settings-only access. Audit log gives observation.
11. **No application-log tab.** `docker logs` covers it.

## Testing

Backend tests:
- Bug-report lifecycle: submit → acknowledge → resolve → notification row exists. Verify `audit_events` rows at each step.
- Notification polling: unseen count, mark-seen, mark-all-seen.
- Engine proxy: basic forwarding, auth gate (401 for non-admin), WebSocket upgrade if applicable.
- Admin endpoints: 401 for unauthenticated, 403 for non-admin, 200 for admin.

Frontend tests aren't currently configured. The dashboard frontend would benefit from a Playwright smoke harness covering: admin navigates to `/admin`, sees the six tabs, can submit a test action in each. This is the right project to cut the planned UI smoke harness from the future-features list.

## What this unblocks

- Multi-user support is operationally usable end-to-end.
- The bug-report flow gives users a sanctioned way to report issues — better than them dropping bugs into chat or DMs.
- Future tabs slot in naturally (Maintenance, Analytics, Integrations) without re-architecting.
- The Playwright smoke harness (long-planned) gets its first real consumer.
