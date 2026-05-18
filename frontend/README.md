# Pryzm frontend

Next.js 16 / React 19 / Tailwind 4. Two surfaces:

- **Chat UI** at `/` — streams via the backend's NDJSON-over-SSE protocol; persists session + message state in React Context; renders markdown with custom code-block and tool-output components.
- **Admin dashboard** at `/admin` — six tabs (Users, Workspaces, System, Engine, Audit, Bug reports) for the operator. Gated by `is_admin`.

## Setup

```bash
npm install
npm run dev -- -H 0.0.0.0
```

`-H 0.0.0.0` binds to all interfaces so any LAN device can hit `http://<host-ip>:3000`. The API URL auto-derives from `window.location.hostname:8000` (`src/utils/constants.ts`), so LAN access works without extra config.

To expose the UI off-LAN (Cloudflare tunnel, DDNS, reverse proxy), set `NEXT_PUBLIC_API_URL` in `.env.local` to the backend's public URL and restart the dev server. `NEXT_PUBLIC_*` vars are read at process start, not hot-reloaded.

## Auth + provider tree

Cookie-based sessions, no bearer tokens. The provider tree splits along an auth boundary so data-fetching providers don't fire requests before login:

```
AppProviders                     ← always mounted
  AuthProvider                   ← /me, login, logout, must_change_password
    AppShell                     ← chooses LoginPage / force-change / chat shell
      ChatProviders              ← only mounted post-auth
        WorkspaceProvider        ← workspace list + active slug
          SessionProvider        ← session CRUD, message cache
            InferenceProvider    ← SSE streaming
              UploaderProvider   ← upload queue
                TestSuiteProvider
```

`WorkspaceContext` resolves the slug as: `?workspace=` query → first owned workspace → empty string when the user has none (triggers the empty-state on `ActiveSession`). Components consume `workspaceSlug` from the context, not from `searchParams`.

Voluntary password changes are gated server-side — the user-side change-password form only exists inside the forced first-login flow. Admin reset is the only way to rotate a password mid-life.

## Chat-surface contexts

| Context | Hook | Owns |
|---|---|---|
| `WorkspaceContext` | `useWorkspaces` | List, active slug, `activeWorkspace`, `hasNoWorkspaces` |
| `SessionContext` | `useSession` | Session list, current id, per-workspace message cache (`${slug}:${sessionId}`), folders, navigation |
| `InferenceContext` | `useInference` | SSE streaming state, `sendMessage()`, abort controllers, optimistic→real id handoff |
| `UploaderContext` | `useUploader` | File upload queue, XHR progress, image preview URLs |
| `TestSuiteContext` | `useTestSuite` | Multi-step automated test runner from `src/data/test_suite.json` |

## Admin surface (`src/app/admin/`)

- `layout.tsx` — shared header + tab nav + admin-only auth gate
- `users/` — roster + inline create form (with starter-template multi-select), edit modal, deactivate / reactivate toggle, password reset, soft+hard delete
- `users/[user_id]/` — per-user detail (workspaces, recent activity, open bug reports)
- `workspaces/` — all-workspaces view + templates view (create / edit / push / instantiate / delete)
- `system/` — Models + Micro-prompts
- `engine/` — iframe of llama-swap UI via the backend reverse proxy
- `audit/` — filterable table, cursor pagination, detail modal with resolved workspace/session names
- `bug-reports/` — triage table + detail modal (Acknowledge / Resolve+notify / Dismiss / Delete)
- `sessions/[session_id]/` — read-only chat-thread reader linked from audit + bug-report modals

## Key chat components

- **`ActiveSession.tsx`** — main chat area. Composes `ChatHeader`, scrollable message list, `ChatInput`, search overlay. Renders an empty-state when `hasNoWorkspaces`.
- **`ChatInput.tsx`** — textarea + attach button + test-suite menu + globe icon (per-turn `web_search` toggle) + send button. Drag-and-drop file upload.
- **`ChatBubble.tsx`** — picks between `UserMessage` and `AssistantMessage`; threads in `ToolCallsBlock` and `ReferencedFilesPreview`.
- **`AssistantMessage.tsx`** — `react-markdown` + `remark-gfm` with custom component map; fenced code → `CodeBlock` (Prism + Copy button); search highlights propagate via `highlightChildren`.
- **`Sidebar.tsx` + `SessionDirectory.tsx`** — workspace switcher, session list with folders, drag-and-drop reorg, bug-report icon, `NotificationPin`, admin Dashboard link (admin only), sign-out.
- **`BugReportModal.tsx`** — user-facing submit form (category + description + include-session toggle).
- **`NotificationPin.tsx`** — bell icon with badge; polls `/api/notifications/unseen` every 30s + on window focus; popover via React portal (escapes the sidebar's translate transform).
- **`WorkspaceSettings.tsx`** — per-workspace system-prompt editor + tool toggle list + builtins reset.

## Streaming model

`useInference.sendMessage(text, sessionId, attachments, skipUserAdd, modes)` POSTs to `/analyze`, then line-reads the NDJSON stream:

1. First line: `{status:"started", session_id, user_message_id}` — if `session_id` differs from the optimistic id, fire the URL handoff (`navigateToSession(realId)`) and migrate cache keys.
2. Subsequent lines: typed events (`tool_call`, `tool_result`, `chunk`, `files_referenced`, `done`). Append to the message cache for that session.
3. `streamingSessionIdsRef` tracks mid-stream sessions so post-stream UI doesn't overwrite optimistic bubbles with a stale DB fetch.

## Common dev tasks

```bash
npm run lint             # ESLint
npx tsc --noEmit         # type-check
npm run build            # production build
npm start                # serve the production build (snappier than `dev` for demos)
```

## Conventions

- **Cursor:** global rule in `globals.css` sets `cursor: pointer` on `button`, anchor, `select`, checkbox, radio. Disabled controls get `cursor: not-allowed`. Web-app norm — browsers don't default to this.
- **Pop-overs from inside the sidebar** must render via React portal — the sidebar uses a `translate-x` transform for its slide animation, which makes it the containing block for `position: fixed` descendants. The `NotificationPin` does this; pattern as needed.
- **Next.js 16** has breaking API changes from earlier versions. Reach into `node_modules/next/dist/docs/` for current syntax before writing framework-specific code; outdated guides on the web steer you wrong.
- **`NEXT_PUBLIC_*` env vars** are baked into the JS bundle at dev-server start. After editing `.env.local`, restart `npm run dev`.
