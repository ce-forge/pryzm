# Pryzm frontend

Next.js 16 / React 19 / Tailwind 4 chat UI. Streams via the backend's NDJSON-over-SSE protocol; persists session + message state in React Context; renders markdown with custom code-block and tool-output components.

## Setup

```bash
npm install
npm run dev -- -H 0.0.0.0
```

`-H 0.0.0.0` binds to all interfaces so any LAN device can hit `http://<host-ip>:3000`. The frontend auto-derives the API URL from `window.location.hostname:8000` (see `src/utils/constants.ts`), so LAN access works without extra config.

To expose the UI off-LAN (Cloudflare tunnel, etc.), set `NEXT_PUBLIC_API_URL` in `.env.local` to the backend's public URL and restart the dev server. `NEXT_PUBLIC_*` vars are read at process start, not hot-reloaded.

## State architecture

State is **not** Redux. Each concern is a custom hook composed under a thin Context wrapper:

| Context | Hook | What it owns |
|---|---|---|
| `WorkspaceContext` | `useWorkspaces` | Workspace list, active workspace slug from `?workspace=` query, `enabled_tools` for the current workspace |
| `SessionContext` | `useSession` | Session list, current session id, per-workspace message cache (keyed `${slug}:${session_id}`), folder list, navigation, streaming-session set |
| `InferenceContext` | `useInference` | SSE streaming state, `sendMessage()`, abort controllers, optimistic→real session id handoff |
| `UploaderContext` | `useUploader` | File upload queue, XHR progress, image preview URLs |
| `TestSuiteContext` | `useTestSuite` | Multi-step automated test runner driven by `src/data/test_suite.json` |

Top-level page (`src/app/page.tsx`) wraps everything in the providers; `ActiveSession.tsx` consumes them.

## Key components

- **`ActiveSession.tsx`** — main chat area. Composes `ChatHeader`, the scrollable message list, `ChatInput`, and the search overlay. Owns the per-session `webSearchEnabled` toggle state.
- **`ChatInput.tsx`** — textarea + attach button + test-suite menu + globe-icon (per-turn `web_search` toggle, gated by workspace's `enabled_tools`) + send button. Handles drag-and-drop file upload.
- **`ChatBubble.tsx`** — picks between `UserMessage` and `AssistantMessage` for the body, threads `ToolCallsBlock` and `ReferencedFilesPreview` in alongside.
- **`AssistantMessage.tsx`** — `react-markdown` + `remark-gfm` with custom component map: fenced code → `CodeBlock` (Prism + Copy button), inline code → styled pill, blockquote → tool-call indicator. Search highlights propagate via `highlightChildren` for prose and an invisible scan-layer for fenced code so the counter and Enter-navigation work without disturbing syntax highlighting.
- **`Sidebar.tsx` + `SessionDirectory.tsx`** — session list with folders, search, drag-and-drop reorg, workspace switcher.
- **`ToolCallsBlock.tsx`** — renders the typed `tool_call` / `tool_result` events from the SSE stream as a styled blockquote with a TerminalIcon + code pills.
- **`WorkspaceSettings.tsx`** — per-workspace system-prompt editor + tool toggle list + builtins reset.

## Streaming model

`useInference.sendMessage(text, sessionId, attachments, skipUserAdd, modes)` POSTs to `/analyze`, then line-reads the NDJSON stream:

1. First line: `{status:"started", session_id, user_message_id}` — if `session_id` differs from the optimistic id, fire the URL handoff (`navigateToSession(realId)`) and migrate cache keys.
2. Each subsequent line: a typed event (`tool_call`, `tool_result`, `chunk`, `files_referenced`, `finalize`, etc.). Append to the in-memory cache for that session.
3. The session id is tracked in `streamingSessionIdsRef` so the post-stream UI knows not to overwrite optimistic bubbles with a stale DB fetch.

## Common dev tasks

```bash
npm run lint             # ESLint
npx tsc --noEmit         # type-check
npm run build            # production build
npm start                # serve the production build (snappier than `dev` for demos)
```

## Notes for working in this codebase

- Next.js 16 introduced breaking API changes from earlier versions. Reach into `node_modules/next/dist/docs/` for current syntax before writing framework-specific code; outdated guides on the web will steer you wrong.
- `NEXT_PUBLIC_*` env vars are baked into the JS bundle at dev-server start. After editing `.env.local`, restart `npm run dev`.
- The bearer token is provisional. It's entered once via `WorkspaceSettings` and stored in `localStorage` — never bound to a DOM `value` attribute (a regression rule exists for this). Eventual end-state is an HttpOnly cookie session.
