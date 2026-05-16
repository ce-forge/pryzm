# Pryzm backend

FastAPI service that hosts the agentic chat loop, RAG ingestion + retrieval, and the tool registry. Talks to llama-swap over HTTP for inference + embeddings, PostgreSQL for persistence, Redis for the upload status broker and memory-condense locks.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Required env (read from `../.env`, gitignored — see root README for the full shape):

- `DB_USER`, `DB_PASSWORD`, `DB_NAME` — PostgreSQL credentials. Schema is created by Alembic; the test suite uses a separate `pryzm_test` database in the same container.
- `PRYZM_API_TOKEN` — shared bearer token used by every API client. No default; missing => startup error.

Optional env (with sensible defaults in `config.py`):

- `LLM_SERVER_URL` (default `http://127.0.0.1:8080`) — llama-swap's OpenAI-compatible endpoint.
- `SEARXNG_URL` (default `http://127.0.0.1:8888`) — local SearxNG for `web_search`.
- `REDIS_URL` (default `redis://127.0.0.1:6379`).
- `NETWORK_TOOLS_ALLOW_PRIVATE` (default `False`) — flip to `True` to let the network tools probe RFC1918 / loopback / link-local addresses for LAN diagnostics.

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

## Core architecture

### `core/ai_engine.py` — `stream_chat()`

The heart of the system. Per-turn flow:

1. Load the workspace's stored system prompt; apply any per-turn `modes` (`core/modes.py`) — modes can force-include tools, append directives, or override the router tier.
2. Build the recent-message window from history (caps at `MEMORY_CONTEXT_WINDOW=5` plus an optional condensed-memory summary message).
3. Run auto-RAG if the last user message has an `[Attached_File:]` marker or a filename mention that matches a known doc; the retrieved chunks get prepended to the user message as a context block.
4. Pick a model via `HeuristicRouter.pick()` — small (E2B) by default, large (E4B) on long prompts / code fences / complex verbs / history depth / attachments. Mode `tier_override` short-circuits this.
5. Loop up to `MAXIMUM_TOOL_LOOPS=8` iterations: call llama-swap, handle any `tool_calls`, feed results back as `{role:"tool"}` messages, repeat. Stream tokens out as they arrive.
6. On loop exhaustion or any tool error, escalate from small→large once (`escalated=True` prevents re-escalation).
7. Yields typed SSE events: `{type:"started"}` → `{type:"tool_call"}` / `{type:"tool_result"}` → `{type:"chunk"}` → `{type:"finalize"}`.

### `core/llm_router.py` — `HeuristicRouter`

Stateless. `pick(prompt, history, attachments) → (model_id, tier, reason)`. Catalog-driven from `infra/llama-swap-config.yaml` — small = smallest non-embedding model, large = a `code`-tagged model. No DB, no caching.

### `core/llm_server.py` — OpenAI-compatible adapter

Wraps llama-swap's `/v1/chat/completions`, `/v1/embeddings`, `/v1/models`. Translates OpenAI's response shape back to the Ollama-shaped dict the engine expects (legacy compat from the pre-llama-swap days). Surfaces upstream `error.message` bodies on HTTP errors so context-overflow / model-not-loaded errors show their real cause.

### `core/modes.py` — per-turn override registry

```python
@dataclass(frozen=True)
class Mode:
    name: str
    force_tools: list[str] = []
    directive: str = ""
    tier_override: Optional[str] = None

MODES: dict[str, Mode] = {}
def register_mode(mode: Mode): ...
def apply_modes(tool_set, system_prompt, requested_modes): ...
```

`web_search` is mode #1 — registered next to the tool. Adding `deep_research` / `strict_rag` / `code_mode` etc. is a `register_mode(...)` at module load.

### `services/knowledge.py` — RAG ingestion + retrieval

- **Ingestion:** `add_chunks_to_document()` chunks text via `RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)` and embeds each chunk via `/v1/embeddings`. New chunks get UUIDv7 ids so `ORDER BY id` recovers insertion order.
- **Retrieval (three modes):**
  - `restrict_to_filenames` (attached file present) — returns ALL chunks of the scoped doc(s) in insertion order, with chunk-overlap deduped at the seam. Bypasses relevance ranking entirely; "transcribe / summarise this file" needs completeness, not top-K.
  - `overview_mode` (file attached, no user text) — top-K from the most recent doc in the session.
  - Default — workspace-wide hybrid: HNSW vector search + `content_tsv` keyword search merged via Reciprocal Rank Fusion (K=60). Permissive cosine threshold (0.65 for auto-RAG, 0.45 for the explicit tool).

### Tool registry — `tools/`

`@tool(properties, required, workspaces, system_prompt_directive)` decorator registers a callable. Three required pieces:

1. **JSON-schema parameter definition** in `properties` + `required` — what the LLM sees.
2. **Workspace allowlist** — which workspaces can enable the tool (filters the Admin-UI toggle list).
3. **Optional `system_prompt_directive`** — a short "when to call this" line that gets injected into the workspace prompt under `== AVAILABLE TOOLS ==` only when the tool is enabled.

Module-level `MODULE_DIRECTIVE` constants apply to every tool in the same file (e.g. the network-tools shared validation rule).

Adding a new tool: drop it in `tools/<name>.py`, register it in `tools/__init__.py`, restart the backend. The Admin UI picks it up from `/api/tools` automatically.

## Tests

```bash
./venv/bin/pytest                          # full unit + integration suite (~35s)
./venv/bin/pytest tests/e2e/               # Playwright smoke harness (separate; uses session-scoped browser)
./venv/bin/pytest tests/test_<name>.py     # one file
```

Integration tests run against a separate `pryzm_test` Postgres database in the same docker container; the fixture in `tests/conftest.py` drops + recreates it per session.

## Notable conventions

- Every primary key is UUIDv7 (`db/models.py:generate_uuid`). Better B-tree insert locality than v4; lexicographic sort = insertion order for chunks created back-to-back.
- Workspaces are seeded by `services/builtins.py`. The Alembic seed migration reads from there; the Admin UI's "Reset to defaults" endpoint does too.
- Memory condensation runs in the background when a session crosses `MEMORY_CONDENSE_THRESHOLD=15` messages; condensed summaries are stored as `{role:"memory"}` rows.
- llama-swap config tags drive capability lookup — e.g. captioning routes to whatever model carries the `vision` tag in `infra/llama-swap-config.yaml`. The captioning model is on-demand with `ttl: 60`.
