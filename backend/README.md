# Pryzm backend

FastAPI service hosting the agentic chat loop, RAG ingestion + retrieval, multi-user auth, audit logging, and the admin dashboard endpoints. Talks to **llama-swap** over HTTP for inference + embeddings, PostgreSQL for persistence, Redis for the upload status broker + memory-condense locks.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Required env (read from `../.env`, gitignored — see root README):

- `DB_USER`, `DB_PASSWORD`, `DB_NAME` — PostgreSQL credentials. Schema is owned by Alembic; the test suite uses a separate `pryzm_test` database in the same container.

Optional env (defaults in `config.py`):

- `PRYZM_BOOTSTRAP_ADMIN_PASSWORD` — password set on the auto-created `admin` account at first boot. Defaults to `admin` if unset; `must_change_password=true` is set either way so admin is forced to pick a real password on first login.
- `LLM_SERVER_URL` (default `http://127.0.0.1:8080`) — llama-swap's OpenAI-compatible endpoint.
- `SEARXNG_URL` (default `http://127.0.0.1:8888`) — local SearxNG for `web_search`.
- `REDIS_URL` (default `redis://127.0.0.1:6379`).
- `CORS_ORIGINS` — JSON list of allowed dev/deploy origins beyond loopback + LAN.
- `NETWORK_TOOLS_ALLOW_PRIVATE` (default `False`) — flip to `True` to let the network tools probe RFC1918 / loopback / link-local addresses for LAN diagnostics.
- `AUDIT_RETENTION_DAYS` (default `90`) — partitions older than this are dropped daily by the retention scheduler.

### Run

```bash
./venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --reload --reload-delay 2
```

`--host 0.0.0.0` enables LAN access. `--reload-delay 2` slows uvicorn's file-watch poll so the dev box doesn't chirp.

### Database migrations

```bash
./venv/bin/alembic upgrade head        # apply pending
./venv/bin/alembic revision -m "..."   # new migration scaffold
./venv/bin/alembic downgrade -1        # roll back one
```

If you've applied a migration on a feature branch and then switch to a branch without that migration's `.py` file, Alembic crashes on startup. Run `alembic downgrade -1` WHILE STILL on the feature branch, then switch.

## Auth model

Cookie-based sessions (`pryzm_session`, `HttpOnly`, `SameSite=Lax`), Argon2id password hashing. Bootstrap admin created on first boot. Per-user FK ownership on `workspaces`, `sessions`, `folders`, `documents`.

Admin owns all credentials. Voluntary password change is closed — `POST /api/auth/password` returns 403 unless the caller has `must_change_password=true`, which only happens during the forced-flow window after admin reset or first-login. The path is:

1. Admin creates user with temp password → `must_change_password=true`
2. User logs in → forced change-password screen → picks real password → flag flips to `false`
3. Later: admin resets via `/admin/users` → flag flips back to `true`, user signed out
4. User logs in with new temp password → forced change screen again

## Core architecture

### `core/ai_engine.py` — `stream_chat()`

The heart of the system. Per-turn flow:

1. Load the workspace's stored system prompt; apply any per-turn `modes` (`core/modes.py`) — modes can force-include tools, append directives, or override the router tier.
2. Build the recent-message window from history (caps at `MEMORY_CONTEXT_WINDOW=5` plus an optional condensed-memory summary message).
3. Run auto-RAG if the last user message has an `[Attached_File:]` marker or a filename mention; emits `chat.rag_retrieved` audit event.
4. Pick a model via `HeuristicRouter.pick()` — small (E2B) by default, large (E4B) on long prompts / code fences / complex verbs / history depth / attachments.
5. Loop up to `MAXIMUM_TOOL_LOOPS=8` iterations: call llama-swap, handle any `tool_calls`, emit `chat.tool_invoked` / `chat.rag_retrieved` / `chat.web_search` per call, feed results back as `{role:"tool"}` messages.
6. On loop exhaustion or any tool error, escalate from small→large once (`escalated=True` prevents re-escalation).
7. Yields typed SSE events: `{type:"started"}` → `{type:"tool_call"}` / `{type:"tool_result"}` → `{type:"chunk"}` → `{type:"done"}`.

### `core/llm_router.py` — `HeuristicRouter`

Stateless. Catalog-driven from `infra/llama-swap-config.yaml` — small = smallest non-embedding model, large = a `code`-tagged model. No DB, no caching.

### `core/llm_server.py` — OpenAI-compatible adapter

Wraps llama-swap's `/v1/chat/completions`, `/v1/embeddings`, `/v1/models`. Surfaces upstream `error.message` bodies on HTTP errors so context-overflow / model-not-loaded errors show their real cause.

### `core/audit.py` + `services/audit_*`

Append-only `audit_events` table, monthly RANGE partitions, composite PK `(id, created_at)`. ~30 `EventType` constants. Daily retention scheduler in the lifespan ensures next month's partition + drops anything older than `AUDIT_RETENTION_DAYS`. DB-level trigger blocks UPDATE/DELETE except FK SET NULL cascades.

### `services/knowledge.py` — RAG ingestion + retrieval

- **Ingestion:** `add_chunks_to_document()` chunks text via `RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)` and embeds each chunk via `/v1/embeddings`. New chunks get UUIDv7 ids so `ORDER BY id` recovers insertion order.
- **Retrieval (three modes):**
  - `restrict_to_filenames` (attached file present) — returns ALL chunks of the scoped doc(s) in insertion order. "Summarise this file" needs completeness, not top-K.
  - `overview_mode` (file attached, no user text) — top-K from the most recent doc in the session.
  - Default — workspace-wide hybrid: HNSW vector search + `content_tsv` keyword search merged via Reciprocal Rank Fusion (K=60). Permissive cosine threshold (0.65 for auto-RAG, 0.45 for the explicit tool).

### Tool registry — `tools/`

`@tool(properties, required, workspaces, system_prompt_directive)` decorator. Three required pieces:

1. **JSON-schema parameter definition** in `properties` + `required` — what the LLM sees.
2. **Workspace allowlist** — which workspaces can enable the tool (filters the Admin-UI toggle list).
3. **Optional `system_prompt_directive`** — a short "when to call this" line injected into the workspace prompt under `== AVAILABLE TOOLS ==` only when the tool is enabled.

Adding a new tool: drop it in `tools/<name>.py`, register it in `tools/__init__.py`, restart the backend.

### Routers (`routers/`)

- User-facing (auth-required, cookie-gated): `auth`, `chat`, `workspaces`, `folders`, `documents`, `settings`, `health`.
- Admin-only (`require_admin`): `admin`, `admin_users`, `admin_templates`, `admin_workspaces`, `admin_audit`, `admin_engine` (llama-swap reverse proxy), `admin_sessions` (read-only thread reader for any session).
- Bug reports + notifications each ship user-facing + admin sub-routers.

## Tests

```bash
./venv/bin/pytest -q                       # full sweep (~3 minutes)
./venv/bin/pytest tests/e2e/               # Playwright smoke harness
./venv/bin/pytest tests/test_<name>.py     # one file
```

`tests/conftest.py` drops + recreates `pryzm_test` per session.

## Notable conventions

- Every primary key is UUIDv7 (`db/models.py:generate_uuid`). Better B-tree insert locality than v4; lexicographic sort = insertion order.
- Workspaces vs workspace_templates are separate tables. Templates are admin-owned blueprints; workspaces are per-user instances with FK back to the template (SET NULL on template delete).
- Memory condensation runs in the background when a session crosses `MEMORY_CONDENSE_THRESHOLD=15` messages; condensed summaries are `{role:"memory"}` rows.
- llama-swap config tags drive capability lookup — captioning routes to whatever model carries the `vision` tag in `infra/llama-swap-config.yaml`. The captioning model is on-demand with `ttl: 60`.
- Audit history survives hard-deletes via FK SET NULL + display-name snapshots. `user_display_name_at_event` outlives a hard-deleted user.
