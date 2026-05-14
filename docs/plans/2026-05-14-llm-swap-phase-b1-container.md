# LLM Swap — Phase B1 — llama-swap Container + OpenAI-Compatible Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking. Apply Karpathy guidelines: minimum code, no speculative abstractions, surgical changes, verifiable success criteria.

**Goal:** Replace the Ollama Docker service with `llama-swap` (orchestrating `llama.cpp`'s `llama-server`). Refactor `backend/core/ollama.py` into `backend/core/llm_server.py` calling OpenAI-compatible endpoints. Drop the per-workspace `engine_config.model` field — the backend uses a hardcoded default model end-to-end in this phase (Phase B2 replaces the constant with the router). Frontend drops the model picker UI. Phase A's perf benchmark continues to work; the bench script needs no changes.

**Architecture:** The inference container changes from `ollama/ollama` to `ghcr.io/mostlygeek/llama-swap:cuda`, mounted with `infra/llama-swap-config.yaml` that defines three models: `gemma-4-E2B-it` (small, future tier-1), `gemma-4-E4B-it` (large, future tier-2 — also the hardcoded default for this phase), and `nomic-embed-text-v1.5` (embedding, pinned always-on). Backend speaks `/v1/chat/completions`, `/v1/embeddings`, `/v1/models` instead of Ollama's `/api/chat`, `/api/embeddings`, `/api/tags`. The `EngineConfig` Pydantic model loses the `model` field; the JSONB column keeps the `backend` field as `"llama_cpp"`. Workspaces no longer expose a model picker.

**Tech stack:** `llama-swap` (Go proxy), `llama.cpp`'s `llama-server`, GGUF model files pulled from HuggingFace on first request. Backend is unchanged Python/FastAPI/httpx. Frontend is unchanged React/Next.js. Alembic migration for the JSONB schema change.

**Spec reference:** [`docs/specs/2026-05-14-llm-server-swap.md`](../specs/2026-05-14-llm-server-swap.md) — Phase B1 section.

**Branch:** `refactor/llm-swap-phase-b1-container` (cut from `main` after Phase A merged).

---

## Operational Notes (Read Before Starting)

This phase is **invasive at runtime**:

- The Ollama container goes away. The first time `llama-swap` starts after this PR merges, the first request hits a model that hasn't been downloaded yet — `llama-server` will pull ~3.5 GB (E2B) or ~5.4 GB (E4B) from HuggingFace, which can take 1–10 minutes depending on bandwidth. After download, the GGUF is cached in the `llama_models` named volume and subsequent loads are instant.
- The dev backend is currently running with `--reload` against `core/ollama.py`. During implementation the reloader will reload on each commit. That's fine — the backend will be in a partially-migrated state until B1 finishes, but no production users are hitting it. Stop and restart the backend manually before running the final smoke test.
- Existing chat sessions/messages in the DB stay valid. Only the `workspaces.engine_config` JSONB shape changes; messages reference workspace by id only.

If you must roll back mid-implementation, revert the branch and run `docker compose up -d ollama` to restore Ollama (the `pgdata` volume and chat history are untouched). The Alembic down-migration restores `engine_config.model` for builtin workspaces.

---

## File Map

### Created
- `infra/llama-swap-config.yaml` — three model definitions + group config, mounted into the llama-swap container.
- `backend/core/llm_server.py` — OpenAI-compatible HTTP wrapper (replaces `core/ollama.py`). Exports `chat`, `generate`, `embed`, `list_models`, plus module-level `DEFAULT_CHAT_MODEL` and `DEFAULT_EMBED_MODEL` constants.
- `backend/alembic/versions/<new>_drop_engine_config_model.py` — Alembic revision that strips `model` from each row's `engine_config` JSONB and updates the column server-default.
- `backend/tests/test_llm_server.py` — unit tests for the new module's wire-format parsing (chat response shape, embeddings response shape, error mapping).

### Modified
- `docker-compose.yml` — replace `ollama` service with `llama-swap`; add `llama_models` named volume.
- `backend/.env.example` — `OLLAMA_URL` removed; add `LLM_SERVER_URL` (default `http://127.0.0.1:8080`).
- `backend/config.py` — `OLLAMA_URL` → `LLM_SERVER_URL`. Comment in timeouts section adjusts the file reference from `core/ollama.py` to `core/llm_server.py`.
- `backend/main.py` — no code change but the comment referencing `OLLAMA_CONNECT_TIMEOUT_SECONDS` stays unchanged (the env var name in `config.py` is what's renamed).
- `backend/core/ai_engine.py` — `from core import ollama` → `from core import llm_server`. Three call sites swapped (chat, generate, generate again). Response shape adapter: `response["message"]` → `response["choices"][0]["message"]`; tool_calls path identical. Hardcoded `model=llm_server.DEFAULT_CHAT_MODEL` everywhere `engine_config.model` was used.
- `backend/core/engine_config.py` — `EngineConfig` becomes `backend: Literal["llama_cpp"]` only; `model: str` field dropped. Docstring updated.
- `backend/services/knowledge.py` — `from core import ollama` → `from core import llm_server`. `ollama.embed` → `llm_server.embed`. Response shape adapter: Ollama returned `{"embedding": [...]}`; OpenAI returns `{"data": [{"embedding": [...]}]}`. The function-level extraction handles that.
- `backend/services/builtins.py` — `engine_config={"backend": "llama_cpp"}` (no `model` key). Both builtin entries.
- `backend/services/workspaces.py` — no functional change but verify the `BUILTIN_WORKSPACES` import path still works; any place that reads `engine_config.model` is now reading a missing key (defaults handled by `engine_config_for`).
- `backend/routers/chat.py` — `from core import ollama` → `from core import llm_server`. Error envelope codes rename: `ollama_unreachable` → `llm_unreachable`, `ollama_timeout` → `llm_timeout`. `get_ollama_models` route at `GET /api/models` becomes `get_chat_models`, returns `llm_server.list_models()` result.
- `backend/routers/workspaces.py` — `_validate_model` removed. The `if "model_name" in data:` block in `update_workspace` removed. Fresh-workspace creation uses `engine_config={"backend": "llama_cpp"}`. `_to_response` no longer reads `model_name`.
- `backend/routers/health.py` — `database.ping_ollama` → `database.ping_llm_server`. Response field `inference_engine` keeps its name.
- `backend/db/database.py` — `ping_ollama` → `ping_llm_server`. Probes `LLM_SERVER_URL/health` instead of Ollama root.
- `backend/db/models.py` — `Workspace.engine_config.server_default` from `'{"backend": "ollama", "model": "gemma4:e4b"}'` to `'{"backend": "llama_cpp"}'`.
- `backend/schemas.py` — `WorkspaceResponse.model_name` field removed; `WorkspaceUpdate.model_name` field removed.
- `backend/tests/test_engine_config.py` — fixture data updated to new shape (no `model` field).
- `backend/tests/test_phase4_smoke.py` (if it references `model_name`) — adjust.
- `backend/tests/e2e/test_phase4_smoke.py` — no changes expected; e2e tests don't reference model names directly.
- `frontend/src/hooks/useWorkspaces.ts` — `Workspace.model_name` and `UpdatePayload.model_name` fields removed.
- `frontend/src/components/WorkspaceSettings.tsx` — entire "Preferred model" `<div>` block + the `preferredModel` / `installedModels` state + the `apiFetch("/api/models")` call removed.
- `frontend/src/components/ChatHeader.tsx` — `wsModel` reference and the `· {wsModel}` display element removed.

### Removed
- `backend/core/ollama.py` — replaced by `core/llm_server.py`.

### Untouched
- `backend/core/llm_metrics.py` — Phase A's metric helpers continue to work; `emit_chat_metric` extracts `prompt_eval_count` / `eval_count` from the response, and llama-server's OpenAI-compatible response carries equivalent fields under `usage.prompt_tokens` / `usage.completion_tokens`. The Phase A function will receive a slightly different dict shape; we update the extractor in this phase as part of `core/llm_server.py`.
- `backend/tests/perf/bench_llm.py` — already reads `usage` from the final SSE chunk; the chunk shape doesn't change.
- Any session/message/folder/document data — schema for those tables is untouched.

---

## Pre-flight

```bash
cd /home/orbital/projects/pryzm
git checkout main
git pull --ff-only
git checkout -b refactor/llm-swap-phase-b1-container

# Confirm Phase A baseline.
./backend/venv/bin/pytest backend/tests/ --quiet --ignore=backend/tests/e2e 2>&1 | tail -3
# Expected: 79 passed

# Confirm dev backend reachable.
curl -sf http://127.0.0.1:8000/health && echo "backend up" || echo "backend NOT ok — start it first"

# Note the current ollama-baseline file so we don't accidentally re-generate it.
ls backend/tests/perf/results/
# Expected: .gitkeep, ollama-baseline-2026-05-14.md
```

---

## Task 1 — `infra/llama-swap-config.yaml`

**Files:**
- Create: `infra/llama-swap-config.yaml`

### Step 1: Create the directory and config file

```bash
mkdir -p /home/orbital/projects/pryzm/infra
```

Write `/home/orbital/projects/pryzm/infra/llama-swap-config.yaml`:

```yaml
# llama-swap configuration for Pryzm.
#
# Three model groups:
#   - chat: chat-capable models, swapped on-demand (one in VRAM at a time)
#   - always-on: embedding model, pinned in memory so RAG never pays swap cost
#
# Adding a new model: append to `models:` with the same shape, optionally
# attach a `groups` list. Reload without restart: docker compose kill -s HUP llama-swap

healthCheckTimeout: 3600   # allow first-request HuggingFace downloads to finish
startPort: 9000            # llama-server instances bind 9000+

groups:
  "chat":
    swap: true             # one chat model loaded at a time
    exclusive: false       # don't unload always-on
  "always-on":
    swap: false
    exclusive: false
    persistent: true

models:
  # Tier-1 default (small).
  "gemma-4-E2B-it":
    cmd: >
      /app/llama-server --port ${PORT}
      -hf bartowski/google_gemma-4-E2B-it-GGUF:Q4_K_M
      -ngl 99 --ctx-size 8192 --jinja --flash-attn
      --cache-type-k q8_0 --cache-type-v q8_0
    groups: ["chat"]
    # Capability tags consumed by the future Router in Phase B2.
    # `vision` is reserved for the day image input ships.
    tags: []

  # Tier-2 default (larger). HARDCODED DEFAULT for Phase B1 — every chat call
  # uses this until the router lands in B2.
  "gemma-4-E4B-it":
    cmd: >
      /app/llama-server --port ${PORT}
      -hf bartowski/google_gemma-4-E4B-it-GGUF:Q4_K_M
      -ngl 99 --ctx-size 8192 --jinja --flash-attn
      --cache-type-k q8_0 --cache-type-v q8_0
    groups: ["chat"]
    tags: []

  # Embedding model — pinned always-on so RAG queries don't pay swap cost.
  "nomic-embed-text-v1.5":
    cmd: >
      /app/llama-server --port ${PORT}
      -hf nomic-ai/nomic-embed-text-v1.5-GGUF:Q8_0
      -ngl 99 --embeddings --batch-size 8192
      --rope-scaling yarn --rope-freq-scale 0.75
    groups: ["always-on"]
    tags: ["embedding"]
```

### Step 2: Commit

```bash
cd /home/orbital/projects/pryzm
git add infra/llama-swap-config.yaml
git commit -m "feat(infra): llama-swap config — two Gemma 4 + nomic-embed"
```

---

## Task 2 — Swap the Docker compose service

**Files:**
- Modify: `docker-compose.yml`

### Step 1: Replace the `ollama` service block

Open `/home/orbital/projects/pryzm/docker-compose.yml`. Replace the entire `ollama:` service block with:

```yaml
  llama-swap:
    image: ghcr.io/mostlygeek/llama-swap:cuda
    container_name: pryzm_llama_swap
    ports:
      - "127.0.0.1:8080:8080"
    volumes:
      - ./infra/llama-swap-config.yaml:/app/config.yaml:ro
      - llama_models:/root/.cache/llama.cpp
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    restart: always
```

At the end of the file, add a top-level `volumes:` section (or append to it if one already exists):

```yaml
volumes:
  llama_models:
```

### Step 2: Verify the compose file parses

```bash
cd /home/orbital/projects/pryzm
docker compose config --quiet && echo "ok"
```

Expected: `ok`. If parsing fails, the YAML structure is off — fix the indentation and re-run.

### Step 3: Commit

```bash
git add docker-compose.yml
git commit -m "feat(infra): docker-compose — replace ollama service with llama-swap

Adds named volume llama_models so downloaded GGUFs persist across container
restarts. NVIDIA GPU is reserved the same way Ollama claimed it. Host port
moves from 11434 (Ollama) to 8080 (llama-swap default)."
```

---

## Task 3 — Settings rename: `OLLAMA_URL` → `LLM_SERVER_URL`

**Files:**
- Modify: `backend/.env.example`
- Modify: `backend/config.py`

### Step 1: Update `.env.example`

If `backend/.env.example` exists, open it. Otherwise the rename only needs to land in `config.py`. Check:

```bash
ls /home/orbital/projects/pryzm/backend/.env.example 2>/dev/null && echo "exists" || echo "absent"
```

If it exists, replace the `OLLAMA_URL=...` line with:

```
LLM_SERVER_URL=http://127.0.0.1:8080
```

(If it doesn't exist, skip — `config.py` has the default.)

### Step 2: Update `backend/config.py`

Open `backend/config.py`. Replace the line:

```python
OLLAMA_URL: str = "http://127.0.0.1:11434"
```

with:

```python
LLM_SERVER_URL: str = "http://127.0.0.1:8080"
```

Find the comment block immediately above the timeout settings:

```python
    # Async HTTP timeouts for the Ollama client (see core/ollama.py).
    # LLM_TIMEOUT_SECONDS replaces the hardcoded timeout=120 that bit us in Phase 2
    # when cold-loading 35B models took >120s. Bumping to 180 gives headroom.
    OLLAMA_CONNECT_TIMEOUT_SECONDS: float = 5.0
```

Update the comment + the variable name:

```python
    # Async HTTP timeouts for the LLM server (see core/llm_server.py).
    # LLM_TIMEOUT_SECONDS replaces the hardcoded timeout=120 that bit us in Phase 2
    # when cold-loading 35B models took >120s. Bumping to 180 gives headroom.
    LLM_CONNECT_TIMEOUT_SECONDS: float = 5.0
```

### Step 3: Update the lifespan handler's reference

Open `/home/orbital/projects/pryzm/backend/main.py`. Find the line:

```python
            connect=settings.OLLAMA_CONNECT_TIMEOUT_SECONDS,
```

Change to:

```python
            connect=settings.LLM_CONNECT_TIMEOUT_SECONDS,
```

### Step 4: Run the test suite

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest --quiet --ignore=tests/e2e tests/ 2>&1 | tail -3
```

Expected: still **79 passed**. (Tests don't depend on the rename yet.)

### Step 5: Commit

```bash
cd /home/orbital/projects/pryzm
git add backend/config.py backend/main.py backend/.env.example 2>/dev/null || git add backend/config.py backend/main.py
git commit -m "refactor(config): OLLAMA_URL → LLM_SERVER_URL, OLLAMA_CONNECT_* → LLM_CONNECT_*"
```

---

## Task 4 — Write `core/llm_server.py` (OpenAI-compatible client)

**Files:**
- Create: `backend/core/llm_server.py`
- Create: `backend/tests/test_llm_server.py`

This task introduces the new module. It does NOT delete `core/ollama.py` yet — that happens after all callers have been migrated (Task 11). The two modules briefly coexist, but nothing imports `llm_server` until Task 5.

### Step 1: Write the failing tests

`backend/tests/test_llm_server.py`:

```python
"""Unit tests for the OpenAI-compatible LLM server wrapper.

These tests mock httpx responses rather than hitting a real llama-server —
they cover the wire-format adapter, not the actual inference. End-to-end
exercise lives in the e2e suite and the bench_llm harness."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from core import llm_server


def _make_mock_client(post_response: dict):
    """Builds an httpx.AsyncClient stand-in whose .post returns a
    Response-shaped object carrying the given JSON body."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value=post_response)
    client = MagicMock()
    client.post = AsyncMock(return_value=mock_resp)
    return client, mock_resp


@pytest.mark.asyncio
async def test_chat_returns_openai_message_dict():
    """chat() returns the inner message dict (with role + content + optional
    tool_calls) — same shape ai_engine expects after Ollama's adapter."""
    openai_response = {
        "id": "chatcmpl-xxx",
        "object": "chat.completion",
        "model": "gemma-4-E4B-it",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Hello!",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 12,
            "completion_tokens": 3,
            "total_tokens": 15,
        },
    }
    client, _ = _make_mock_client(openai_response)
    out = await llm_server.chat(client, messages=[{"role": "user", "content": "hi"}], tools=None, model="m")
    assert out["message"]["role"] == "assistant"
    assert out["message"]["content"] == "Hello!"
    # Ollama-shape fields still expected by core/llm_metrics: re-mapped from usage.
    assert out["prompt_eval_count"] == 12
    assert out["eval_count"] == 3


@pytest.mark.asyncio
async def test_chat_passes_tool_calls_through():
    """When the model emits tool_calls, they flow through unchanged."""
    openai_response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "check_port", "arguments": '{"port": 22}'},
                        }
                    ],
                }
            }
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 8, "total_tokens": 13},
    }
    client, _ = _make_mock_client(openai_response)
    out = await llm_server.chat(client, messages=[], tools=[{"type": "function"}], model="m")
    assert out["message"]["tool_calls"][0]["function"]["name"] == "check_port"


@pytest.mark.asyncio
async def test_chat_payload_uses_openai_endpoint():
    """The POST hits /v1/chat/completions, not /api/chat."""
    client, _ = _make_mock_client({
        "choices": [{"message": {"role": "assistant", "content": ""}}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    })
    await llm_server.chat(client, messages=[], tools=None, model="m")
    args, kwargs = client.post.call_args
    assert args[0].endswith("/v1/chat/completions")


@pytest.mark.asyncio
async def test_generate_uses_chat_completions_with_user_role():
    """generate() is a thin shim around /v1/chat/completions with a single
    user message — llama-server has no /api/generate equivalent."""
    openai_response = {
        "choices": [{"message": {"role": "assistant", "content": "answer text"}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
    }
    client, _ = _make_mock_client(openai_response)
    out = await llm_server.generate(client, prompt="hello", model="m")
    assert out == "answer text"


@pytest.mark.asyncio
async def test_embed_returns_vector():
    """embed() unwraps OpenAI's nested `data[0].embedding` and returns the float
    list directly — same shape Ollama's adapter returned."""
    openai_response = {
        "object": "list",
        "data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}],
        "model": "nomic-embed-text-v1.5",
        "usage": {"prompt_tokens": 4, "total_tokens": 4},
    }
    client, _ = _make_mock_client(openai_response)
    out = await llm_server.embed(client, text="hello", model="nomic-embed-text-v1.5")
    assert out == [0.1, 0.2, 0.3]


@pytest.mark.asyncio
async def test_list_models_returns_ids():
    """list_models() returns the `id` strings from /v1/models."""
    openai_response = {
        "object": "list",
        "data": [
            {"id": "gemma-4-E2B-it", "object": "model"},
            {"id": "gemma-4-E4B-it", "object": "model"},
            {"id": "nomic-embed-text-v1.5", "object": "model"},
        ],
    }
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value=openai_response)
    client = MagicMock()
    client.get = AsyncMock(return_value=mock_resp)
    out = await llm_server.list_models(client)
    assert out == ["gemma-4-E2B-it", "gemma-4-E4B-it", "nomic-embed-text-v1.5"]
```

Run:
```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest tests/test_llm_server.py -v 2>&1 | tail -10
```

Expected: collection error — `core.llm_server` doesn't exist yet.

### Step 2: Write `core/llm_server.py`

`backend/core/llm_server.py`:

```python
"""OpenAI-compatible LLM server wrapper.

Speaks /v1/chat/completions, /v1/embeddings, /v1/models — the de facto
standard wire format adopted by llama-server (via llama-swap), vLLM,
LM Studio, etc. This is NOT a multi-backend abstraction; it's one module
talking to one server (llama-swap in front of llama.cpp). The wire format
just happens to be the standard one because so many tools already speak it.

The module exposes the same function signatures the previous Ollama wrapper
had — chat / generate / embed / list_models — so ai_engine and friends
keep their existing call shapes. Response payloads are adapted in here so
callers continue to see the Ollama-shaped `{message, prompt_eval_count,
eval_count, ...}` dict on chat/generate.

Phase B1 hardcodes DEFAULT_CHAT_MODEL everywhere a model id is needed.
Phase B2's router will replace those references with dynamic picks.
"""
from __future__ import annotations

import time
from typing import Any, AsyncIterator

import httpx

from config import settings
from core.llm_metrics import emit_chat_metric, emit_embed_metric

BASE_URL = settings.LLM_SERVER_URL.strip().rstrip("/")

# Hardcoded defaults used while Phase B1 has no router. Phase B2 will read
# from the Workspace/Router context instead of importing these constants.
DEFAULT_CHAT_MODEL = "gemma-4-E4B-it"
DEFAULT_EMBED_MODEL = "nomic-embed-text-v1.5"


def _adapt_chat_response(data: dict) -> dict:
    """Translate OpenAI chat-completion response shape into the legacy
    Ollama shape ai_engine consumes.

    OpenAI:  {choices: [{message: {role, content, tool_calls?}}], usage: {prompt_tokens, completion_tokens, ...}}
    Ollama:  {message: {role, content, tool_calls?}, prompt_eval_count, eval_count, ...}

    Returns the Ollama-shaped dict. Drops fields ai_engine never reads."""
    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message", {})
    usage = data.get("usage", {}) or {}
    return {
        "message": message,
        "prompt_eval_count": int(usage.get("prompt_tokens", 0)),
        "eval_count": int(usage.get("completion_tokens", 0)),
        # OpenAI doesn't expose nanosecond timings the way Ollama did; the
        # metric emitter's fallback path uses caller-measured wall clock.
        "prompt_eval_duration": 0,
        "eval_duration": 0,
        "total_duration": 0,
    }


async def chat(
    client: httpx.AsyncClient,
    messages: list,
    tools: list | None,
    model: str,
    options: dict | None = None,
) -> dict:
    """POST /v1/chat/completions (non-streaming). Returns an Ollama-shaped dict
    for compatibility with ai_engine. Emits an 'llm.metric' line per call."""
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
    }
    if tools is not None:
        payload["tools"] = tools
    if options:
        # llama-server accepts options as top-level fields (temperature, top_p,
        # num_ctx → max_tokens-ish), not nested. Forward verbatim; unknown keys
        # are ignored by the server.
        for k, v in options.items():
            if k == "num_ctx":
                payload["max_tokens"] = v   # rough analog; llama-server's own
                                            # --ctx-size flag is the actual ceiling
            else:
                payload[k] = v

    url = f"{BASE_URL}/v1/chat/completions"
    t0 = time.perf_counter()
    resp = await client.post(url, json=payload, timeout=settings.LLM_TIMEOUT_SECONDS)
    resp.raise_for_status()
    duration_s = time.perf_counter() - t0
    adapted = _adapt_chat_response(resp.json())
    emit_chat_metric(model=model, response=adapted, fallback_duration_s=duration_s)
    return adapted


async def generate(
    client: httpx.AsyncClient,
    prompt: str,
    model: str,
    options: dict | None = None,
) -> str:
    """Single-shot text completion. llama-server has no /api/generate analog;
    we wrap /v1/chat/completions with a single user message. Returns the
    response text only. Emits an 'llm.metric' line per call."""
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }
    if options:
        for k, v in options.items():
            if k == "num_ctx":
                payload["max_tokens"] = v
            else:
                payload[k] = v

    url = f"{BASE_URL}/v1/chat/completions"
    t0 = time.perf_counter()
    resp = await client.post(url, json=payload, timeout=settings.LLM_TIMEOUT_SECONDS)
    resp.raise_for_status()
    duration_s = time.perf_counter() - t0
    data = resp.json()
    adapted = _adapt_chat_response(data)
    emit_chat_metric(model=model, response=adapted, fallback_duration_s=duration_s)
    return adapted["message"].get("content", "")


async def embed(client: httpx.AsyncClient, text: str, model: str) -> list[float]:
    """POST /v1/embeddings. Returns the embedding vector. Emits an
    'llm.embed_metric' line per call."""
    url = f"{BASE_URL}/v1/embeddings"
    payload = {"model": model, "input": text}
    t0 = time.perf_counter()
    resp = await client.post(url, json=payload, timeout=30.0)
    resp.raise_for_status()
    duration_s = time.perf_counter() - t0
    emit_embed_metric(model=model, char_count=len(text), duration_s=duration_s)
    data = resp.json()
    return data["data"][0]["embedding"]


async def list_models(client: httpx.AsyncClient) -> list[str]:
    """GET /v1/models. Returns the list of model ids. llama-swap reports its
    configured models here; the order matches infra/llama-swap-config.yaml."""
    url = f"{BASE_URL}/v1/models"
    resp = await client.get(url, timeout=5.0)
    resp.raise_for_status()
    return [m["id"] for m in resp.json().get("data", [])]
```

### Step 3: Run the tests

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest tests/test_llm_server.py -v 2>&1 | tail -15
```

Expected: 6 passed.

### Step 4: Run the full backend suite

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest --quiet --ignore=tests/e2e tests/ 2>&1 | tail -3
```

Expected: **85 passed** (79 prior + 6 new). Existing tests still using `core.ollama` keep passing because we haven't deleted that module yet.

### Step 5: Commit

```bash
cd /home/orbital/projects/pryzm
git add backend/core/llm_server.py backend/tests/test_llm_server.py
git commit -m "feat(llm-server): OpenAI-compatible wrapper module + unit tests

Same five exports as core/ollama.py (chat / generate / embed / list_models)
plus DEFAULT_CHAT_MODEL / DEFAULT_EMBED_MODEL constants. Chat responses
adapt to the Ollama-shaped dict ai_engine expects so callers can swap
imports without touching downstream consumers."
```

---

## Task 5 — Migrate `ai_engine.py` to `llm_server`

**Files:**
- Modify: `backend/core/ai_engine.py`

### Step 1: Update imports

Open `backend/core/ai_engine.py`. Find:

```python
from core import ollama
```

Replace with:

```python
from core import llm_server
```

### Step 2: Replace the three call sites

There are exactly three `ollama.` calls (verified via grep). For each, change `ollama.` → `llm_server.` AND replace `engine_config.model` with `llm_server.DEFAULT_CHAT_MODEL`.

**Site 1** — `condense_chat_memory` around line 54:

```python
        response = await ollama.generate(client, prompt=prompt, model=engine_config.model, options={"num_ctx": 8192})
```

becomes:

```python
        response = await llm_server.generate(client, prompt=prompt, model=llm_server.DEFAULT_CHAT_MODEL, options={"num_ctx": 8192})
```

**Site 2** — `stream_chat` around line 175:

```python
            data = await ollama.chat(
                client,
                messages=...,                      # whatever was there
                tools=...,
                model=engine_config.model,
                ...
            )
```

becomes:

```python
            data = await llm_server.chat(
                client,
                messages=...,
                tools=...,
                model=llm_server.DEFAULT_CHAT_MODEL,
                ...
            )
```

(Leave every other arg in place — only the function reference and the `model=` argument change.)

**Site 3** — `generate_title` around line 291:

```python
        text = await ollama.generate(client, prompt=system_prompt, model=engine_config.model, options={"num_ctx": 4096})
```

becomes:

```python
        text = await llm_server.generate(client, prompt=system_prompt, model=llm_server.DEFAULT_CHAT_MODEL, options={"num_ctx": 4096})
```

### Step 3: Run the test suite

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest --quiet --ignore=tests/e2e tests/ 2>&1 | tail -3
```

Expected: 85 passed. Engine-level tests (if any) should still pass because we mocked `core/ollama` previously and ai_engine now imports `core/llm_server`; both modules expose the same chat-response shape, so test mocks of either still work.

If anything fails because a test was patching `core.ollama.chat`, that test now needs `core.llm_server.chat`. Update the test.

### Step 4: Commit

```bash
cd /home/orbital/projects/pryzm
git add backend/core/ai_engine.py
git commit -m "refactor(engine): ai_engine consumes llm_server (was ollama)

Hardcodes llm_server.DEFAULT_CHAT_MODEL at every former engine_config.model
call site. Phase B2 replaces those references with the router's pick."
```

---

## Task 6 — Migrate `services/knowledge.py` to `llm_server`

**Files:**
- Modify: `backend/services/knowledge.py`

### Step 1: Find and update the embed call site

Open `backend/services/knowledge.py`. Find the line that calls `ollama.embed`:

```bash
grep -n "ollama\." backend/services/knowledge.py
```

There should be one site (in `get_embedding` or similar). It looks like:

```python
return await ollama.embed(client, text, model=EMBED_MODEL)
```

Update the import at the top of the file:

```python
from core import ollama
```

becomes:

```python
from core import llm_server
```

And the call site:

```python
return await llm_server.embed(client, text, model=llm_server.DEFAULT_EMBED_MODEL)
```

If the file had a module-level `EMBED_MODEL = "nomic-embed-text"` constant, delete that constant (the embed model id now lives in `core/llm_server.py` as `DEFAULT_EMBED_MODEL`).

### Step 2: Update `search_chunks_sync` (legacy sync path)

The same file has a `search_chunks_sync` function around line 145 that bypasses `ollama` and does a raw `requests.post` to Ollama's `/api/embeddings`. This sync path is reached from tools running inside the agentic loop. Update it to hit the new URL:

```python
def search_chunks_sync(
    db: Session,
    query: str,
    workspace_id: str,
    session_id: str = None,
    threshold: float = 0.65,
    top_k: int = 3,
):
    """Sync chunk-search for use from tool functions (which are called
    synchronously by ai_engine). Embeds via a direct HTTP POST to the LLM
    server and delegates to _query_chunks_by_vector for the DB work."""
    import requests
    url = f"{settings.LLM_SERVER_URL.strip().rstrip('/')}/v1/embeddings"
    try:
        resp = requests.post(url, json={"model": "nomic-embed-text-v1.5", "input": query}, timeout=30)
        resp.raise_for_status()
        query_vector = resp.json()["data"][0]["embedding"]
    except Exception:
        query_vector = []
    if not query_vector:
        return []
    return _query_chunks_by_vector(db, query_vector, query, workspace_id, session_id, threshold, top_k)
```

(Compare against the existing function in `backend/services/knowledge.py:145-175` — change `OLLAMA_URL` → `LLM_SERVER_URL`, `"/api/embeddings"` → `"/v1/embeddings"`, `"prompt": query` → `"input": query`, response extraction `.get("embedding", [])` → `["data"][0]["embedding"]`, and the model name to `"nomic-embed-text-v1.5"`.)

### Step 3: Run the test suite

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest --quiet --ignore=tests/e2e tests/ 2>&1 | tail -3
```

Expected: 85 passed.

### Step 4: Commit

```bash
cd /home/orbital/projects/pryzm
git add backend/services/knowledge.py
git commit -m "refactor(knowledge): embed via llm_server; sync path hits /v1/embeddings"
```

---

## Task 7 — Migrate routers to `llm_server` + update error codes

**Files:**
- Modify: `backend/routers/chat.py`
- Modify: `backend/routers/workspaces.py`

### Step 1: Update `routers/chat.py`

Open `backend/routers/chat.py`.

Find:
```python
from core import ollama
```
Replace with:
```python
from core import llm_server
```

Find the `_error_envelope` function (around line 29). The error codes and messages reference Ollama. Replace:

```python
def _error_envelope(exc: Exception) -> dict:
    """Map an exception to a {error, code} envelope for the SSE stream.

    Codes:
      ollama_unreachable — connection refused, DNS fail, etc.
      ollama_timeout     — read timeout (LLM hung)
      tool_timeout       — a tool exceeded TOOL_TIMEOUT_SECONDS
      engine_error       — anything else (generic catch-all)
    """
    if isinstance(exc, httpx.ConnectError):
        return {"error": "Ollama is not reachable.", "code": "ollama_unreachable"}
    if isinstance(exc, (httpx.ReadTimeout, httpx.PoolTimeout)):
        return {"error": "Ollama took too long to respond.", "code": "ollama_timeout"}
    if isinstance(exc, asyncio.TimeoutError):
        return {"error": "Tool execution timed out.", "code": "tool_timeout"}
    return {"error": str(exc) or "Engine error.", "code": "engine_error"}
```

with:

```python
def _error_envelope(exc: Exception) -> dict:
    """Map an exception to a {error, code} envelope for the SSE stream.

    Codes:
      llm_unreachable — connection refused, DNS fail, etc.
      llm_timeout     — read timeout (model hung)
      tool_timeout    — a tool exceeded TOOL_TIMEOUT_SECONDS
      engine_error    — anything else (generic catch-all)
    """
    if isinstance(exc, httpx.ConnectError):
        return {"error": "LLM server is not reachable.", "code": "llm_unreachable"}
    if isinstance(exc, (httpx.ReadTimeout, httpx.PoolTimeout)):
        return {"error": "LLM server took too long to respond.", "code": "llm_timeout"}
    if isinstance(exc, asyncio.TimeoutError):
        return {"error": "Tool execution timed out.", "code": "tool_timeout"}
    return {"error": str(exc) or "Engine error.", "code": "engine_error"}
```

Find the `/api/models` endpoint (around line 448):

```python
@router.get("/api/models")
async def get_ollama_models(http_client: httpx.AsyncClient = Depends(get_http_client)):
    try:
        all_models = await ollama.list_models(http_client)
        chat_models = [m for m in all_models if "embed" not in m.lower()]
        return chat_models if chat_models else ["gemma4:e4b"]
    except Exception:
        return ["gemma4:e4b"]
```

Replace with:

```python
@router.get("/api/models")
async def get_chat_models(http_client: httpx.AsyncClient = Depends(get_http_client)):
    """List the chat-capable models llama-swap has configured. The list is
    derived from infra/llama-swap-config.yaml at server start; embedding-tagged
    models are filtered out."""
    try:
        all_models = await llm_server.list_models(http_client)
        return [m for m in all_models if "embed" not in m.lower()]
    except Exception:
        return [llm_server.DEFAULT_CHAT_MODEL]
```

### Step 2: Update `routers/workspaces.py` — drop the model picker path

Open `backend/routers/workspaces.py`.

Find:
```python
from core import ollama
```
Replace with:
```python
from core import llm_server
```

Find `_validate_model` (around line 54). Delete the entire function (it's no longer called from anywhere after we strip the `model_name` PATCH path).

Find the `update_workspace` handler (around line 140). Locate the block:

```python
    if "model_name" in data:
        new_model = data["model_name"]
        if new_model:
            await _validate_model(http_client, new_model)
        else:
            # null → reset to default for this workspace
            builtin = get_builtin(ws.slug)
            new_model = builtin.engine_config["model"] if builtin else "gemma4:e4b"
        # JSONB partial update: copy + mutate + reassign so SQLAlchemy detects the change.
        ws.engine_config = {**(ws.engine_config or {}), "model": new_model, "backend": "ollama"}
```

Delete it entirely. The new `update_workspace` no longer handles `model_name` at all (the field was removed from `WorkspaceUpdate` in Task 10 — coming up).

Find `create_workspace` around line 117. Replace:

```python
    engine_config = {"backend": "ollama", "model": "gemma4:e4b"}
```

with:

```python
    engine_config = {"backend": "llama_cpp"}
```

Find `_to_response` around line 79. Remove the `model_name` field:

```python
def _to_response(workspace) -> WorkspaceResponse:
    """Build a WorkspaceResponse from a Workspace row."""
    return WorkspaceResponse(
        id=workspace.id,
        slug=workspace.slug,
        display_name=workspace.display_name,
        system_prompt=workspace.system_prompt,
        enabled_tools=workspace.enabled_tools or [],
        is_builtin=workspace.is_builtin,
        color=workspace.color,
        created_at=workspace.created_at,
    )
```

Also remove `http_client` parameter from `update_workspace` if it's only there for `_validate_model`:

```python
@router.patch("/workspaces/{slug}", response_model=WorkspaceResponse)
def update_workspace(
    slug: str,
    payload: WorkspaceUpdate,
    db: Session = Depends(database.get_db),
):
```

(Drop `async` and the http_client dep; nothing inside is awaited any more after dropping `_validate_model`.)

### Step 3: Run the test suite

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest --quiet --ignore=tests/e2e tests/ 2>&1 | tail -3
```

Expected: probably some failures from tests that reference `model_name` in the response shape. Read the failures and update each test minimally:

- Tests that PATCH `model_name` should now skip that field (it's no longer accepted).
- Tests that assert `WorkspaceResponse.model_name == ...` should drop that assertion.

If failures only come from those expected places, fix them in the test file. Re-run.

If the test count after fix is **less than** 85, that's OK — we expect some test count drop as model-picker tests get pared down. As long as no UNEXPECTED test regresses.

### Step 4: Commit

```bash
cd /home/orbital/projects/pryzm
git add backend/routers/chat.py backend/routers/workspaces.py backend/tests/  # if tests touched
git commit -m "refactor(routers): chat + workspaces consume llm_server; drop model picker

- /api/models proxies llm-swap's /v1/models, filters embedding-tagged models.
- /workspaces PATCH no longer accepts model_name; _validate_model removed.
- Error codes rename: ollama_* → llm_*.
- Fresh-workspace engine_config = {'backend': 'llama_cpp'} only."
```

---

## Task 8 — `EngineConfig` Pydantic model + Alembic migration

**Files:**
- Modify: `backend/core/engine_config.py`
- Create: `backend/alembic/versions/<new>_drop_engine_config_model.py`
- Modify: `backend/db/models.py`
- Modify: `backend/services/builtins.py`
- Modify: `backend/tests/test_engine_config.py`

### Step 1: Update `EngineConfig`

Open `backend/core/engine_config.py`. Replace the `EngineConfig` class and the docstring at the top:

```python
"""Typed view over workspaces.engine_config JSONB.

The schema lives in db.models.Workspace.engine_config as JSONB. This module
gives the rest of the codebase a typed handle on those values without each
caller re-parsing the dict.

Phase B1 dropped the `model` field — the backend hardcodes its model id in
`core/llm_server.py`. The column stays as JSONB so future per-workspace
overrides (e.g. council members forcing a specific model) can plug in
without a migration.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from db import models


class EngineConfig(BaseModel):
    """Inference backend choice for a workspace. Today the only value is
    'llama_cpp'; Phase B2 may add backend-specific overrides here."""
    backend: Literal["llama_cpp"]


def engine_config_for(workspace: models.Workspace) -> EngineConfig:
    """Read the JSONB column on a Workspace row and return the typed model.

    Raises pydantic ValidationError if the stored JSON doesn't match the
    schema — that would mean someone wrote a malformed engine_config (defensive
    check against direct SQL surgery; the migration server-defaults to a valid
    shape)."""
    return EngineConfig.model_validate(workspace.engine_config)
```

### Step 2: Update `db/models.py`

Open `backend/db/models.py`. Find the `Workspace.engine_config` column (around line 23):

```python
    engine_config = Column(
        JSONB,
        nullable=False,
        server_default='{"backend": "ollama", "model": "gemma4:e4b"}',
    )
```

Change the server default:

```python
    engine_config = Column(
        JSONB,
        nullable=False,
        server_default='{"backend": "llama_cpp"}',
    )
```

### Step 3: Update `services/builtins.py`

Open `backend/services/builtins.py`. Find the two `engine_config={"backend": "ollama", "model": "gemma4:e4b"}` lines and update both to:

```python
        engine_config={"backend": "llama_cpp"},
```

### Step 4: Generate the Alembic revision

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/alembic revision -m "drop engine_config model and rebrand backend"
```

This creates a new file under `backend/alembic/versions/`. Note the generated filename (it has a hex prefix). Open it and replace the `upgrade()` and `downgrade()` stubs:

```python
"""drop engine_config model and rebrand backend

Revision ID: <generated>
Revises: <prior head>
Create Date: <generated>

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "<generated>"
down_revision = "<prior head>"
branch_labels = None
depends_on = None


NEW_DEFAULT = """{"backend": "llama_cpp"}"""
OLD_DEFAULT = """{"backend": "ollama", "model": "gemma4:e4b"}"""


def upgrade() -> None:
    # Strip the 'model' key and rebrand the 'backend' value on every row.
    op.execute(
        "UPDATE workspaces SET engine_config = "
        "(engine_config - 'model') || jsonb_build_object('backend', 'llama_cpp')"
    )
    # Update the column's server default to match.
    op.alter_column(
        "workspaces",
        "engine_config",
        server_default=sa.text(f"'{NEW_DEFAULT}'::jsonb"),
    )


def downgrade() -> None:
    # Restore the model key on every row, defaulting to gemma4:e4b. (We don't
    # remember per-workspace model picks here — the original was a user-
    # editable field, but the only path that wrote it was the model picker,
    # which gets reinstated by the surrounding code revert.)
    op.execute(
        "UPDATE workspaces SET engine_config = "
        "jsonb_build_object('backend', 'ollama', 'model', 'gemma4:e4b')"
    )
    op.alter_column(
        "workspaces",
        "engine_config",
        server_default=sa.text(f"'{OLD_DEFAULT}'::jsonb"),
    )
```

> Replace `<generated>` and `<prior head>` with the actual values Alembic populated. The `down_revision` should already match the prior migration's revision id — verify by running `./backend/venv/bin/alembic history | head` if needed.

### Step 5: Update `tests/test_engine_config.py`

Open `backend/tests/test_engine_config.py`. Find every fixture that constructs an engine_config dict with `{"backend": "ollama", "model": ...}` and update to `{"backend": "llama_cpp"}` (no `model` field).

Find every assertion that reads `engine_cfg.model` or `engine_config["model"]` and either drop the assertion (if model was the subject) or delete the test (if the entire test was about model resolution — that's no longer a thing).

### Step 6: Run the migration + tests

```bash
cd /home/orbital/projects/pryzm/backend
./venv/bin/alembic upgrade head 2>&1 | tail -5
./venv/bin/pytest --quiet --ignore=tests/e2e tests/ 2>&1 | tail -3
```

Expected:
- Alembic prints `Running upgrade <prior> -> <new>, drop engine_config model and rebrand backend`.
- pytest: passes (count may be slightly lower than 85 due to deleted model-resolution tests; that's expected).

Then test the down-migration to verify reversibility:

```bash
./venv/bin/alembic downgrade -1 2>&1 | tail -3
./venv/bin/alembic upgrade head 2>&1 | tail -3
```

Expected: both succeed. (Skip if your dev DB has rows you don't want re-defaulted — but in normal dev there's nothing destructive going on.)

### Step 7: Commit

```bash
cd /home/orbital/projects/pryzm
git add backend/core/engine_config.py backend/db/models.py backend/services/builtins.py backend/alembic/versions/ backend/tests/test_engine_config.py
git commit -m "feat(schema): drop engine_config.model, rebrand backend to llama_cpp

- Alembic migration strips 'model' key from every row and updates the
  server default to {'backend': 'llama_cpp'}.
- Pydantic EngineConfig loses the model field; only backend remains.
- BUILTIN_WORKSPACES entries match the new shape.
- Tests updated; model-resolution tests removed (the concept no longer exists)."
```

---

## Task 9 — Health check rename: `ping_ollama` → `ping_llm_server`

**Files:**
- Modify: `backend/db/database.py`
- Modify: `backend/routers/health.py`

### Step 1: Update `db/database.py`

Open `backend/db/database.py`. Find:

```python
def ping_ollama():
    try:
        response = requests.get(f"{settings.OLLAMA_URL.strip().rstrip('/')}/", timeout=2)
        if response.status_code == 200:
            return "connected"
        return "disconnected"
    except Exception:
        return "disconnected"
```

Replace with:

```python
def ping_llm_server():
    """Ping the LLM server's health endpoint. llama-swap responds 200 to GET /
    once at least one upstream llama-server has loaded."""
    try:
        response = requests.get(f"{settings.LLM_SERVER_URL.strip().rstrip('/')}/", timeout=2)
        if response.status_code == 200:
            return "connected"
        return "disconnected"
    except Exception:
        return "disconnected"
```

### Step 2: Update `routers/health.py`

Open `backend/routers/health.py`. Find:

```python
    ollama_status = database.ping_ollama()
```

Replace with:

```python
    ollama_status = database.ping_llm_server()
```

> The variable name stays `ollama_status` to minimize churn; the `inference_engine` response field already uses that variable. Rename can come in a future hygiene pass.

### Step 3: Run tests

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest --quiet --ignore=tests/e2e tests/ 2>&1 | tail -3
```

Expected: same pass count as Task 8.

### Step 4: Commit

```bash
cd /home/orbital/projects/pryzm
git add backend/db/database.py backend/routers/health.py
git commit -m "refactor(health): ping_ollama → ping_llm_server"
```

---

## Task 10 — Schema cleanup: drop `model_name` from `WorkspaceResponse` / `WorkspaceUpdate`

**Files:**
- Modify: `backend/schemas.py`

### Step 1: Locate the Pydantic models

```bash
grep -n "model_name" /home/orbital/projects/pryzm/backend/schemas.py
```

Expect two lines: one in `WorkspaceResponse`, one in `WorkspaceUpdate`. Delete both lines.

The shapes should now be (with these fields ABSENT):

```python
class WorkspaceResponse(BaseModel):
    id: str
    slug: str
    display_name: str
    system_prompt: str
    enabled_tools: list[str]
    # model_name removed in Phase B1
    is_builtin: bool
    color: str | None
    created_at: datetime
```

(Same removal in `WorkspaceUpdate`; that one is partial-update so the field was Optional.)

### Step 2: Run tests

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest --quiet --ignore=tests/e2e tests/ 2>&1 | tail -3
```

Expected: passing. (Tests that constructed WorkspaceResponse with `model_name=...` should already be updated from Task 7's test fixes; any leftover failure is a missed test — update it now.)

### Step 3: Commit

```bash
cd /home/orbital/projects/pryzm
git add backend/schemas.py backend/tests/ 2>/dev/null || git add backend/schemas.py
git commit -m "schema(workspace): drop model_name from request/response shapes"
```

---

## Task 11 — Delete `core/ollama.py`

**Files:**
- Remove: `backend/core/ollama.py`

### Step 1: Confirm no remaining importers

```bash
grep -rn "from core import ollama\|from core.ollama\|core\.ollama" /home/orbital/projects/pryzm/backend/ --include="*.py" 2>/dev/null | grep -v venv | grep -v __pycache__
```

Expected: empty output. If anything matches, fix that file first (replace `ollama` → `llm_server` per Tasks 5/6/7's pattern), then re-run the grep.

### Step 2: Remove the file

```bash
cd /home/orbital/projects/pryzm
git rm backend/core/ollama.py
```

### Step 3: Run tests

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest --quiet --ignore=tests/e2e tests/ 2>&1 | tail -3
```

Expected: passing. If any test failed because it imported `core.ollama` for a mock target, update the mock target to `core.llm_server`.

### Step 4: Commit

```bash
cd /home/orbital/projects/pryzm
git commit -m "chore(core): remove core/ollama.py — all callers on llm_server now"
```

---

## Task 12 — Frontend: drop the model picker

**Files:**
- Modify: `frontend/src/hooks/useWorkspaces.ts`
- Modify: `frontend/src/components/WorkspaceSettings.tsx`
- Modify: `frontend/src/components/ChatHeader.tsx`

### Step 1: Update `useWorkspaces.ts`

Open `frontend/src/hooks/useWorkspaces.ts`. Find the `Workspace` interface (around line 6). Remove the `model_name` field:

```ts
export interface Workspace {
  id: string;
  slug: string;
  display_name: string;
  system_prompt: string;
  enabled_tools: string[];
  // model_name removed in Phase B1 — backend no longer per-workspace pins a model
  is_builtin: boolean;
  color: string | null;
  created_at: string;
}
```

Find the `UpdatePayload` interface (around line 24). Remove the `model_name` field:

```ts
export interface UpdatePayload {
  display_name?: string;
  system_prompt?: string;
  enabled_tools?: string[];
  // model_name removed in Phase B1
  color?: string | null;
}
```

### Step 2: Update `WorkspaceSettings.tsx`

Open `frontend/src/components/WorkspaceSettings.tsx`. Find the "Preferred model" block (around line 257-275) and delete the entire block:

```tsx
          {/* Preferred model */}
          <div>
            <label className="block text-sm font-semibold text-[#e3e3e3] mb-2">Preferred model</label>
            <select
              value={preferredModel ?? ""}
              onChange={(e) => {
                const v = e.target.value || null;
                setPreferredModel(v);
                dirtyRef.current = true;
                if (mode === "edit") save({ model_name: v });
              }}
              className="w-full bg-[#131314] border border-[#333537] text-[#e3e3e3] rounded-lg px-4 py-2.5 outline-none focus:border-blue-500"
            >
              <option value="">Use default model (current global picker)</option>
              {installedModels.map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          </div>
```

Delete the related state and effect:

- `const [preferredModel, setPreferredModel] = useState<string | null>(workspace?.model_name ?? null);` (around line 37)
- `const [installedModels, setInstalledModels] = useState<string[]>([]);` (around line 44)
- The `apiFetch("/api/models")` block inside the `useEffect` (around line 62-65) — remove the `.then(...)` chain for models.
- In `handleStartFromChange` (around line 75), remove `setPreferredModel(source.model_name);` (just delete that one line).

In create-mode submit (`handleCreate`), remove `model_name: ...` from the payload if present.

### Step 3: Update `ChatHeader.tsx`

Open `frontend/src/components/ChatHeader.tsx`. Find:

```tsx
  const wsModel = activeWorkspace?.model_name;
```

Delete that line. Find the JSX block that renders `wsModel`:

```tsx
              {wsModel && (
                <span className="shrink-0 text-[10px] text-gray-500 font-mono truncate">
                  · {wsModel}
                </span>
              )}
```

Delete the block.

### Step 4: Build the frontend

```bash
cd /home/orbital/projects/pryzm/frontend && npm run build 2>&1 | tail -10
```

Expected: `Compiled successfully` with no TypeScript errors. If TS complains about anywhere else reading `.model_name`, grep and fix:

```bash
grep -rn "model_name" /home/orbital/projects/pryzm/frontend/src/ --include="*.ts" --include="*.tsx" 2>/dev/null
```

### Step 5: Commit

```bash
cd /home/orbital/projects/pryzm
git add frontend/src/hooks/useWorkspaces.ts frontend/src/components/WorkspaceSettings.tsx frontend/src/components/ChatHeader.tsx
git commit -m "feat(frontend): drop per-workspace model picker

WorkspaceSettings no longer renders Preferred model select. ChatHeader no
longer shows the model name. Workspace.model_name and UpdatePayload.model_name
removed from the typed hook surface — backend stopped accepting/returning
model_name in Phase B1."
```

---

## Task 13 — Integration smoke + capture llama-swap baseline

This is the moment the new stack lights up. Bring up llama-swap, send a chat, run the bench harness end-to-end, save the result for Phase C.

### Step 1: Stop Ollama, start llama-swap

```bash
cd /home/orbital/projects/pryzm
docker compose stop ollama || true
docker compose rm -f ollama || true
docker compose up -d llama-swap
docker compose logs --tail 50 llama-swap
```

Expected: `llama-swap` container starts. The log shows "Listening on :8080" (or similar). No models are loaded yet — they'll be pulled on the first request.

### Step 2: Restart the backend

The dev backend was running with the old (Ollama-importing) code. Restart it so the new `core/llm_server.py` import path takes effect:

```bash
# Find the dev uvicorn process and kill it cleanly
pkill -f "uvicorn main:app" || true
sleep 2

# Restart in the background per the user's stack convention
cd /home/orbital/projects/pryzm/backend
nohup ./venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --reload --reload-delay 2.0 > /tmp/pryzm-backend.log 2>&1 &

# Wait for it
until curl -sf http://127.0.0.1:8000/health -o /dev/null; do sleep 1; done
echo "backend ready"
```

### Step 3: Smoke a single chat

```bash
TOKEN=$(grep PRYZM_API_TOKEN /home/orbital/projects/pryzm/.env | cut -d= -f2)
curl -s -N -X POST "http://127.0.0.1:8000/analyze?workspace=personal" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "say one word", "session_id": null, "attachments": []}' \
  | tail -3
```

Expected (after a longer-than-usual wait on first run because llama-swap is downloading gemma-4-E4B-it from HuggingFace):
- One JSON line containing `"status": "started"`.
- One or more chunks containing assistant text.
- A final `{"done": true, "usage": {...}}` chunk where `usage.model` is `gemma-4-E4B-it`.

If the request times out, the most likely cause is the HuggingFace download. Tail the llama-swap container log (`docker compose logs -f llama-swap`) and look for the download progress. Bump the `LLM_TIMEOUT_SECONDS` in `backend/config.py` temporarily if the first request exceeds 180s.

### Step 4: Run the Phase A benchmark on the new stack

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/python tests/perf/bench_llm.py \
  --backend http://127.0.0.1:8000 \
  --token "$(grep PRYZM_API_TOKEN ../.env | cut -d= -f2)" \
  --repeats 3 \
  --label llama-swap-2026-05-14 2>&1 | tail -20
```

Expected: 45 successful runs, markdown table printed, file written to `backend/tests/perf/results/llama-swap-2026-05-14.md`. Some early prompts may be slow due to the still-cooling cache; the comparison number is the median.

### Step 5: Run the full pytest + e2e suite against the new stack

```bash
cd /home/orbital/projects/pryzm/backend
./venv/bin/pytest --quiet --ignore=tests/e2e tests/ 2>&1 | tail -3
./venv/bin/pytest tests/e2e/ -v 2>&1 | tail -25
```

Expected:
- pytest: passing (count whatever Tasks 1–11 ended up at; no regressions vs after Task 11).
- e2e: 16/16 passing. If any phase test (especially Phase 4 model-name tests) fails because it asserted on `model_name`, update that test.

### Step 6: Commit the llama-swap baseline

```bash
cd /home/orbital/projects/pryzm
git add backend/tests/perf/results/llama-swap-2026-05-14.md
git commit -m "perf(baseline): llama-swap run captured post-container-swap

Phase C reads both ollama-baseline-* and llama-swap-* result files and
diffs them in the comparison doc."
```

---

## Task 14 — Open + merge Phase B1 PR

### Step 1: Push the branch

```bash
cd /home/orbital/projects/pryzm
git push -u origin refactor/llm-swap-phase-b1-container
```

### Step 2: Open the PR

```bash
gh pr create --title "LLM Swap Phase B1 — llama-swap container + OpenAI-compatible backend" --body "$(cat <<'EOF'
## Summary

- Docker compose: \`ollama\` service replaced with \`ghcr.io/mostlygeek/llama-swap:cuda\`. Named volume \`llama_models\` persists downloaded GGUFs across restarts.
- \`infra/llama-swap-config.yaml\` ships with three models: \`gemma-4-E2B-it\` (small), \`gemma-4-E4B-it\` (large, hardcoded default), \`nomic-embed-text-v1.5\` (embedding, pinned always-on).
- Backend: \`core/ollama.py\` removed; \`core/llm_server.py\` is the OpenAI-compatible wrapper. Same function shape, different wire format.
- Per-workspace model selection dropped end-to-end: Alembic migration strips \`model\` from \`engine_config\` JSONB; \`EngineConfig\` Pydantic model loses the field; \`/workspaces\` PATCH no longer accepts \`model_name\`; frontend Preferred-model UI removed; ChatHeader no longer displays a model.
- Settings renamed: \`OLLAMA_URL\` → \`LLM_SERVER_URL\`, \`OLLAMA_CONNECT_TIMEOUT_SECONDS\` → \`LLM_CONNECT_TIMEOUT_SECONDS\`. Error codes: \`ollama_*\` → \`llm_*\`. Health probe: \`ping_ollama\` → \`ping_llm_server\`.
- Captured \`backend/tests/perf/results/llama-swap-2026-05-14.md\` for the Phase C comparison.

## Test plan

- backend pytest: passing (count depends on test fixture cleanup).
- e2e: 16 passing.
- benchmark: 45 successful runs against the new stack.
- manual smoke: chat round-trip end-to-end against llama-swap, first-request GGUF download succeeded, follow-up requests use cached model.

## Operational notes for reviewers

- After merging, run \`docker compose up -d llama-swap\` and \`docker compose stop ollama\` to switch the stack. First request downloads gemma-4-E4B-it (~5.4 GB) from HuggingFace — subsequent ones are instant.
- The named \`llama_models\` volume is new; the old \`./ollama_models\` bind mount is no longer referenced (you can delete it on your machine if you want the disk back).

EOF
)"
```

### Step 3: Auto-merge

```bash
gh pr merge --squash --auto
```

### Step 4: Sync local main after merge

```bash
git checkout main && git pull --ff-only origin main && git log --oneline -3
```

---

## Self-Review Checklist

After completing all tasks, verify spec coverage from `docs/specs/2026-05-14-llm-server-swap.md` (Phase B1 section):

- [x] **`ollama` Docker service replaced with `llama-swap`** — Task 2.
- [x] **`infra/llama-swap-config.yaml` defining model groups** — Task 1.
- [x] **`core/ollama.py` → `core/llm_server.py` (OpenAI wire format)** — Tasks 4 + 11.
- [x] **Alembic migration drops `engine_config.model`** — Task 8.
- [x] **Hardcoded default model used everywhere (no router yet)** — Task 4 (DEFAULT_CHAT_MODEL constant), Task 5 (call sites).
- [x] **Three model defaults shipping in YAML: E2B / E4B / nomic-embed-text-v1.5** — Task 1.
- [x] **Frontend `WorkspaceSettings.tsx` drops the Preferred-model select** — Task 12.
- [x] **`/api/models` proxy returns llama-swap's `/v1/models` list, embedding-tagged filtered out** — Task 7.
- [x] **`OLLAMA_URL` removed; `LLM_SERVER_URL` added; no compat shim** — Task 3.
- [x] **Unit tests update Ollama mocks to OpenAI-compatible response shapes** — Task 4 (test_llm_server.py), Tasks 7/8/10 (existing tests).
- [x] **Phase 2/3/4/5/6 e2e suite passes unchanged against new stack** — Task 13 Step 5.
- [x] **New unit test in `backend/tests/test_llm_server.py`** — Task 4.

Out of scope (explicit non-goals per spec):

- No router yet (Phase B2).
- No Web UI for model management (Phase B3).
- No comparison doc (Phase C).
- No image-input support (separate future spec).

---

## Plan Self-Review

1. **Spec coverage:** Every Phase B1 line item in the spec maps to a task above. ✓
2. **Placeholder scan:**
   - `<generated>` and `<prior head>` in Task 8 Step 4 are literal placeholders to be filled in at Alembic-revision time (Alembic generates the values). Marked explicitly as such; not a content gap.
   - Three result-filename references use today's date (`2026-05-14`); these are literals matching the existing baseline file's convention.
   - No "TBD", "TODO", "fill in details" anywhere.
3. **Type consistency:** `DEFAULT_CHAT_MODEL` / `DEFAULT_EMBED_MODEL` used consistently across Tasks 4/5/6/7. `EngineConfig` shape change touched in Task 8 only; downstream files no longer read `engine_config.model`. ✓
