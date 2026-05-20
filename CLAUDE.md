# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working in this repository.

## Coding discipline

Before writing, reviewing, or refactoring code in this repo, invoke `andrej-karpathy-skills:karpathy-guidelines` via the Skill tool. The four principles (think before coding, simplicity first, surgical changes, goal-driven execution) apply to every code change, large or small. This is a project-wide requirement, not a per-task choice.

The codebase also has a number of project memories that capture local conventions and prior decisions — read those at session start.

## Stack Overview

Pryzm is a self-hosted multi-user AI copilot. Two services:
- **Backend**: FastAPI (Python 3.12) on port 8000 — agentic LLM loop, RAG over PostgreSQL/pgvector, cookie-based auth, audit logging, admin dashboard endpoints
- **Frontend**: Next.js 16 (React 19) on port 3000 — chat UI + admin dashboard, SSE streaming

Infrastructure (`docker-compose.yml`): PostgreSQL (with pgvector), Redis (upload broker + memory-condense locks), **llama-swap** (model serving over llama.cpp), SearxNG (web search).

## Development Commands

```bash
# Start infrastructure
docker compose up -d

# Backend (from /backend)
./venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --reload --reload-delay 2

# Frontend (from /frontend)
npm run dev -- -H 0.0.0.0    # port 3000
npm run build                 # production build
npm run lint                  # ESLint
```

The reload-delay flag is intentional — the default 0.25s poll causes audible coil whine on some machines.

## Tests

Real test suite — ~466 unit + integration tests. Run from `/backend`:

```bash
./venv/bin/pytest -q                    # full sweep, ~3 minutes
./venv/bin/pytest tests/test_<name>.py  # one file
```

Uses a separate `pryzm_test` PostgreSQL database created per-session by `tests/conftest.py`. Frontend has no unit-test framework — end-to-end UI smoke tests live in `tests/smoke/` (Playwright via the backend venv). Run before merging any UI-touching PR; see `tests/smoke/README.md`.

## Environment

Backend reads from `../.env` (gitignored). Key vars: `DB_USER`, `DB_PASSWORD`, `DB_NAME` (PostgreSQL); `PRYZM_BOOTSTRAP_ADMIN_PASSWORD` (first-boot admin password — when unset, bootstrap mints a random one-shot password and logs it once at WARNING level). Frontend uses `NEXT_PUBLIC_API_URL` and auto-derives `${host}:8000` when not set.

## Auth model

Cookie-based sessions, no bearer tokens. First boot creates an admin account (`admin` / `$PRYZM_BOOTSTRAP_ADMIN_PASSWORD` if set, otherwise a logged random one-shot) with `must_change_password=true` — admin is forced to set a real password on first login. `must_change_password` is enforced server-side: every endpoint except `/api/auth/{password,logout,me}` 403s while the flag is true.

Admin owns all credentials. Voluntary password change by users is closed (returns 403); the only path is **admin reset** via `/admin/users`, which sets `must_change_password=true` and signs the user out. They then change on next login via the forced-flow screen.

Per-user workspaces with FK ownership. `owner_can_edit` gates whether the recipient of an admin-instantiated template can change its settings; admin always bypasses.

## Backend architecture

### Agentic loop (`core/ai_engine.py`)

`stream_chat()` is the heart. Calls llama-swap (via `core/llm_server.py`), enters a `while` loop up to `MAXIMUM_TOOL_LOOPS=8`:

1. If the LLM returns `tool_calls`, each tool is executed and the result is fed back as a `{role:"tool"}` message.
2. If no tool calls, the response streams as `{type:"chunk"}` SSE events.
3. Auto-RAG runs upfront when the user message references an attached file.
4. Per-tool audit events emit alongside (`chat.tool_invoked`, `chat.rag_retrieved`, `chat.web_search`).

The `/analyze` endpoint wraps this in a `StreamingResponse` yielding NDJSON, persists user + assistant messages, triggers background memory condensation when message count crosses `MEMORY_CONDENSE_THRESHOLD=15`.

### Router (`core/llm_router.py`)

Stateless heuristic. `pick(prompt, history, attachments) → (model_id, tier, reason)`. Small (E2B) default; large (E4B) escalation on long prompts / code fences / complex verbs / history depth / attachments / max-loops / tool errors. Catalog driven from `infra/llama-swap-config.yaml`.

### Audit log (`core/audit.py`, `services/audit_partitions.py`, `services/audit_retention_scheduler.py`)

Append-only `audit_events` table, monthly RANGE-partitioned, composite PK `(id, created_at)`. ~30 `EventType` constants across `auth.*`, `admin.*`, `workspace.*`, `folder.*`, `document.*`, `chat.*`, `bugreport.*`, `notification.*`. DB-level trigger blocks UPDATE/DELETE except FK SET NULL cascades. Daily scheduler runs in the lifespan: ensures next month's partition + drops anything older than `AUDIT_RETENTION_DAYS=90`.

### RAG (`services/knowledge.py`)

Chunked via `RecursiveCharacterTextSplitter(1000/200)`, embedded via llama-swap's `/v1/embeddings` (`nomic-embed-text` is the default embedding model). Retrieval is hybrid: HNSW vector + tsvector keyword merged via Reciprocal Rank Fusion. Three modes: filename-restricted, overview, default workspace-wide.

### Prompts (`core/prompt_manager.py`)

System prompts live on each workspace row (per-user, may inherit from a template). Cross-workspace micro-prompts (`micro_prompts.default.json` + user override `micro_prompts.json`) for JIT injections like fallback messages and the memory-condenser system prompt. Editable via the System tab.

### Database (`db/models.py`)

ORM models: `User`, `AuthSession`, `Workspace`, `WorkspaceTemplate`, `Session`, `Message`, `Folder`, `Document`, `DocumentChunk`, `AuditEvent`, `BugReport`, `Notification`. Alembic migrations under `backend/alembic/versions/`.

### Routers (`routers/`)

User-facing: `auth`, `chat`, `workspaces`, `folders`, `documents`, `settings`, `health`. Admin-only (`require_admin` dep): `admin`, `admin_users`, `admin_templates`, `admin_workspaces`, `admin_audit`, `admin_engine` (llama-swap reverse proxy), `admin_sessions` (read-only thread reader). `bug_reports` and `notifications` each ship a user + admin sub-router.

## Frontend architecture

### Provider tree

```
AppProviders                     ← always mounted; just AuthProvider
  AuthProvider                   ← /me + login + logout + must_change_password handoff
    AppShell                     ← chooses LoginPage / force-change-pw / chat shell / admin shell
      ChatProviders              ← only mounted post-auth, for chat surface
        WorkspaceProvider        ← workspace list + active slug resolution
          SessionProvider        ← session CRUD, URL routing, message cache
            InferenceProvider    ← SSE streaming, optimistic→real id handoff
              UploaderProvider   ← upload queue
                TestSuiteProvider
```

`WorkspaceContext` falls back to the user's first workspace when the URL has no `?workspace=` (was previously hardcoded to `it_copilot`). Components consume `workspaceSlug` from the context, never from `searchParams` directly.

### Admin dashboard (`src/app/admin/`)

Six tabs under a shared layout with admin-only gate: Users, Workspaces, System, Engine, Audit, Alerts. Dynamic routes for per-user (`/admin/users/[id]`) and per-session (`/admin/sessions/[id]`) detail pages. Engine tab iframes llama-swap via the backend reverse proxy.

### Streaming (`hooks/useInference.ts`)

1. User sends → optimistic id (`optimistic-{ts}`) → cache key `${slug}:${optimisticId}`
2. POST `/analyze` → NDJSON SSE → first line `{status:"started", session_id, user_message_id}` triggers URL handoff via `router.push`
3. Cache key migrates `${slug}:optimistic-X` → `${slug}:realDbUUID`
4. Subsequent lines (`tool_call`, `tool_result`, `chunk`, `files_referenced`, `done`) feed the message cache
5. `streamingSessionIdsRef` tracks mid-stream sessions so post-stream UI doesn't overwrite optimistic bubbles

### Key components

- `ActiveSession.tsx` — main chat area; renders empty-state when user has zero workspaces
- `Sidebar.tsx` — workspace switcher, session/folder list, bug-report icon, NotificationPin (bell), admin Dashboard link (admins only), sign-out
- `BugReportModal.tsx`, `NotificationPin.tsx` — user-facing parts of the bug-report flow
- `ChatBubble.tsx` → `AssistantMessage.tsx` (markdown + Prism via `CodeBlock`) / `UserMessage.tsx`

### Next.js 16 note

Breaking API changes from earlier versions. Read `node_modules/next/dist/docs/` before writing framework-specific code; outdated guides on the web steer wrong.

### Cursor convention

All clickable elements (buttons, anchors, native `<select>`, checkboxes, radios) get `cursor: pointer` via a global rule in `globals.css`. Disabled controls get `cursor: not-allowed`. Web-app norm — browsers don't default to this.
