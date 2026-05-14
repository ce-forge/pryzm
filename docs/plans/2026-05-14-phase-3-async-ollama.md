# Phase 3 — Async I/O + Ollama Colocation + Background Condensation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Implementation agents must apply Karpathy guidelines: minimum code, no speculative abstractions, surgical changes, verifiable success criteria.

**Goal:** Make the SSE chat path actually asynchronous. Replace blocking `requests` with `httpx.AsyncClient` everywhere. Co-locate all Ollama-specific HTTP shape into one module (no abstraction — just hygiene). Add real client-disconnect propagation. Move memory condensation out of the response path into a background task with proper race protection. Make the SSE error envelope distinguishable from a normal chunk.

**Architecture:** A single `httpx.AsyncClient` is created in the FastAPI lifespan handler and stored on `app.state.http_client`. All HTTP shape that talks to Ollama lives in `backend/core/ollama.py` (one module, no `LLMClient` base class). Consumers (`ai_engine`, `services/knowledge`, `routers/chat`, `routers/workspaces`) import from `core.ollama` instead of doing their own `requests.post` calls. `/analyze` becomes `async def`; the agentic loop checks `await request.is_disconnected()` between iterations and propagates `asyncio.CancelledError`. Sync tools run via `asyncio.to_thread`. Memory condensation moves to `BackgroundTasks` with a Postgres advisory lock keyed on `session_id`. SSE errors emit `{"error", "code"}` envelopes that the frontend parses cleanly.

**Tech stack:** `httpx` 0.28 (already in `requirements.txt`), FastAPI's `BackgroundTasks` (no new infra), `asyncio.wait_for` + `asyncio.to_thread`, Postgres `pg_try_advisory_lock`. No new runtime dependencies.

**Spec reference:** [`docs/specs/2026-05-14-codebase-remediation.md`](../specs/2026-05-14-codebase-remediation.md) — Phase 3 section.

**Branch:** `refactor/phase-3-async-ollama` (cut from main after Phase 2 + the smoke harness chore merged).

---

## File Map

### Created
- `backend/core/ollama.py` — all Ollama HTTP shape; async.
- `backend/core/__init__.py` if not present (probably is).
- `backend/tests/test_ollama_client.py` — unit tests with mocked `httpx`.
- `backend/tests/test_async_analyze.py` — async-path tests for `/analyze` (concurrency, disconnect, error envelope) via `TestClient`.
- `backend/tests/e2e/test_phase3_smoke.py` — Playwright e2e covering: concurrent chats don't serialize, disconnect mid-stream cancels, error envelope shows error UI.

### Modified
- `backend/main.py` — lifespan handler creates / disposes `httpx.AsyncClient`, stored on `app.state.http_client`.
- `backend/core/ai_engine.py` — `stream_chat`, `condense_chat_memory`, `generate_title` become async; all `requests.post` → `core.ollama` calls; agentic loop adds disconnect check + `asyncio.wait_for` tool wrapping + `asyncio.to_thread` for sync tools.
- `backend/services/knowledge.py` — `ingest_document` becomes async; `get_embedding` becomes async (or stays sync but called via `to_thread`).
- `backend/routers/chat.py` — `/analyze` becomes `async def`; SSE generator becomes `async`; condensation moves out of the `finally` block into `BackgroundTasks`; error chunks emit the new envelope; `/api/models` becomes async; the upload route's `ingest_document` call becomes `await ingest_document(...)`.
- `backend/routers/workspaces.py` — `_validate_preferred_model` becomes async (it hits Ollama for tag list).
- `backend/config.py` — add `LLM_TIMEOUT_SECONDS`, `TOOL_TIMEOUT_SECONDS`, `OLLAMA_CONNECT_TIMEOUT_SECONDS` config with sensible defaults; remove the hardcoded `timeout=120` magic numbers.
- `frontend/src/hooks/useInference.ts` — SSE parser detects `error` envelope and surfaces a clean error message in the message bubble; doesn't crash on it.

### Untouched
- `backend/db/`, `backend/alembic/` — no schema changes in Phase 3.
- `backend/tools/` — tools stay sync; they're wrapped in `asyncio.to_thread` from the engine. (We are NOT making every tool individually async.)
- Frontend except for `useInference.ts`.

---

## Pre-flight

Confirm Phase 2 baseline is solid:

```bash
cd /home/orbital/projects/pryzm
git checkout refactor/phase-3-async-ollama  # already on it
git log main..HEAD --oneline                # should be empty initially
./backend/venv/bin/pytest backend/tests/ --ignore=backend/tests/e2e -v | tail -5
```

Expected: 40 tests pass (we run e2e separately because it needs the dev servers up).

Backend + frontend should be running (`curl :8000/health` returns 200; `curl :3000/` returns 200). If not, start them per `reference-stack-commands` memory.

---

## Task 0 — `httpx.AsyncClient` lifecycle + empty `core/ollama.py` shell

Set up infrastructure WITHOUT touching consumers yet. After T0, the app behaves identically — we've just added a shared client that nothing uses, and an empty module.

**Files:**
- Modify: `backend/main.py` (lifespan)
- Create: `backend/core/ollama.py` (with function signatures only, no implementations yet)

### Step 1: Write the failing test

Create `backend/tests/test_ollama_client.py`:

```python
"""Unit tests for the Ollama HTTP client wrapper (core.ollama)."""
import pytest

from core import ollama


def test_module_exports_chat_stream():
    """The module must export an async chat_stream function."""
    assert hasattr(ollama, "chat_stream")


def test_module_exports_embed():
    assert hasattr(ollama, "embed")


def test_module_exports_list_models():
    assert hasattr(ollama, "list_models")


def test_module_exports_generate():
    """Used by condense_chat_memory + generate_title (the /api/generate path)."""
    assert hasattr(ollama, "generate")
```

### Step 2: Run to verify failure

```bash
cd /home/orbital/projects/pryzm/backend
./venv/bin/pytest tests/test_ollama_client.py -v
```

Expected: `ModuleNotFoundError: No module named 'core.ollama'`.

### Step 3: Write the lifespan and stub module

Modify `backend/main.py`'s lifespan to create + dispose the shared `httpx.AsyncClient`. Find the existing lifespan (around line 53) and update it:

```python
import httpx
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Existing startup (alembic upgrade, gc_task, etc.) stays.
    # New: create the shared httpx client, attach to app.state.
    app.state.http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(
            connect=settings.OLLAMA_CONNECT_TIMEOUT_SECONDS,
            read=settings.LLM_TIMEOUT_SECONDS,
            write=10.0,
            pool=5.0,
        ),
    )
    try:
        yield
    finally:
        await app.state.http_client.aclose()
        # Existing shutdown (gc_task cancellation, etc.) follows.
```

Preserve all existing lifespan logic — only ADD the client creation / disposal. Read the current body first.

Add the three new timeout settings to `backend/config.py`:

```python
class Settings(BaseSettings):
    # ... existing fields ...
    OLLAMA_CONNECT_TIMEOUT_SECONDS: float = 5.0
    LLM_TIMEOUT_SECONDS: float = 180.0       # Replaces hardcoded timeout=120 in ai_engine.py
    TOOL_TIMEOUT_SECONDS: float = 30.0        # Per-tool budget when wrapped in asyncio.wait_for
```

Bumped LLM timeout to 180s because Phase 2 testing exposed cold model loads taking >120s.

Create `backend/core/ollama.py` with shell functions:

```python
"""Ollama HTTP wrapper.

All Ollama-specific HTTP shape lives here. Consumers import from this module
instead of calling `httpx` / `requests` directly. This is NOT an abstract
interface — it's hygiene. The future llama.cpp swap introduces the abstract
client at that point; today it's just one module talking to Ollama.

The shared httpx.AsyncClient is owned by FastAPI's lifespan (see main.py) and
passed in as the first argument to every function here, so callers can use
Depends() to get it.
"""
from __future__ import annotations

from typing import AsyncIterator

import httpx

from config import settings


BASE_URL = settings.OLLAMA_URL.strip().rstrip("/")


async def chat_stream(
    client: httpx.AsyncClient,
    messages: list,
    tools: list | None,
    model: str,
) -> AsyncIterator[dict]:
    """Stream the /api/chat response. Implementation lands in T1."""
    raise NotImplementedError("chat_stream lands in Task 1")
    yield  # make this a generator function for type-checking


async def embed(client: httpx.AsyncClient, text: str, model: str) -> list[float]:
    """Return an embedding vector for `text`. Implementation lands in T1."""
    raise NotImplementedError("embed lands in Task 1")


async def list_models(client: httpx.AsyncClient) -> list[str]:
    """Return the list of installed Ollama model tags. Implementation lands in T1."""
    raise NotImplementedError("list_models lands in Task 1")


async def generate(
    client: httpx.AsyncClient,
    prompt: str,
    model: str,
    options: dict | None = None,
) -> str:
    """Single-shot /api/generate call (used by condense + title). Lands in T1."""
    raise NotImplementedError("generate lands in Task 1")
```

Add a dependency helper in `backend/main.py` or a new `backend/core/deps.py` so routes can obtain the client:

```python
# In main.py or a new core/deps.py:
from fastapi import Request

def get_http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client
```

### Step 4: Verify the existing app still starts

The backend should restart cleanly with the new lifespan + the shell module present but unused. Test:

```bash
cd /home/orbital/projects/pryzm/backend
# Kill the existing uvicorn:
PID=$(ss -ltnp 2>/dev/null | grep ':8000 ' | grep -oE 'pid=[0-9]+' | head -1 | cut -d= -f2)
[ -n "$PID" ] && kill $PID && sleep 2

# Restart:
./venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --reload &
sleep 4

# Health probe:
curl -s http://127.0.0.1:8000/health
```

Expected: backend starts, health probe returns 200.

### Step 5: Run tests

```bash
./venv/bin/pytest tests/test_ollama_client.py tests/ -v --ignore=tests/e2e
```

Expected: 4 new tests pass (just check exports exist) + 40 prior tests pass = 44 pass.

### Step 6: Commit

```bash
cd /home/orbital/projects/pryzm
git add backend/main.py backend/config.py backend/core/ollama.py backend/tests/test_ollama_client.py
git commit -m "feat(async): httpx.AsyncClient lifespan + ollama module shell."
```

---

## Task 1 — Implement `core/ollama.py` functions (async, no consumers yet)

Fill in the four shell functions. Test against the live Ollama (running in `pryzm_ollama` container). Consumers don't change yet — they still use `requests`. After T1, the new module works AND the old consumers also work; they just don't talk to each other.

**Files:**
- Modify: `backend/core/ollama.py`
- Modify: `backend/tests/test_ollama_client.py` (replace export tests with behavior tests)

### Step 1: Write the failing behavior tests

Replace the contents of `backend/tests/test_ollama_client.py` with:

```python
"""Behavior tests for core.ollama. These mock httpx so they don't need a live
Ollama container."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from core import ollama


@pytest.mark.asyncio
async def test_chat_stream_yields_parsed_chunks():
    """chat_stream should yield dict chunks parsed from NDJSON lines."""
    fake_lines = [
        json.dumps({"message": {"role": "assistant", "content": "hi"}, "done": False}),
        json.dumps({"message": {"role": "assistant", "content": " there"}, "done": False}),
        json.dumps({"done": True}),
    ]

    # Fake the streaming response.
    fake_response = AsyncMock()
    fake_response.status_code = 200
    fake_response.raise_for_status = MagicMock()
    fake_response.aiter_lines = lambda: _async_iter(fake_lines)

    fake_stream_ctx = AsyncMock()
    fake_stream_ctx.__aenter__.return_value = fake_response

    client = MagicMock(spec=httpx.AsyncClient)
    client.stream.return_value = fake_stream_ctx

    chunks = []
    async for chunk in ollama.chat_stream(client, messages=[], tools=None, model="x"):
        chunks.append(chunk)

    assert len(chunks) == 3
    assert chunks[0]["message"]["content"] == "hi"
    assert chunks[2]["done"] is True


@pytest.mark.asyncio
async def test_embed_returns_vector():
    """embed should return the 'embedding' field from the response."""
    expected = [0.1, 0.2, 0.3] * 256  # 768-dim
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {"embedding": expected}

    client = AsyncMock(spec=httpx.AsyncClient)
    client.post.return_value = fake_response

    result = await ollama.embed(client, text="hello", model="nomic-embed-text")
    assert result == expected


@pytest.mark.asyncio
async def test_list_models_returns_names():
    """list_models should extract the 'name' field from each tag."""
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {
        "models": [{"name": "gemma4:e4b"}, {"name": "qwen3.6:35b-a3b"}]
    }
    client = AsyncMock(spec=httpx.AsyncClient)
    client.get.return_value = fake_response

    names = await ollama.list_models(client)
    assert names == ["gemma4:e4b", "qwen3.6:35b-a3b"]


@pytest.mark.asyncio
async def test_generate_returns_response_text():
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {"response": "summary text"}
    client = AsyncMock(spec=httpx.AsyncClient)
    client.post.return_value = fake_response

    result = await ollama.generate(client, prompt="x", model="y")
    assert result == "summary text"


async def _async_iter(items):
    for item in items:
        yield item
```

Add `pytest-asyncio` to `backend/requirements-dev.txt` (we don't already have it):

```
pytest==8.3.4
pytest-cov==6.0.0
pytest-asyncio==0.24.0
```

Add a pytest config for asyncio mode. In `backend/pyproject.toml` (create if missing) or `pytest.ini`:

```ini
# pytest.ini
[pytest]
asyncio_mode = auto
```

Install the new dep:

```bash
cd /home/orbital/projects/pryzm/backend
./venv/bin/pip install -r requirements-dev.txt
```

### Step 2: Run to verify failure

```bash
./venv/bin/pytest tests/test_ollama_client.py -v
```

Expected: tests fail with `NotImplementedError` (the shell stubs).

### Step 3: Implement the four functions

In `backend/core/ollama.py`, replace the stubs:

```python
async def chat_stream(client, messages, tools, model):
    """POST /api/chat with stream=True. Yields parsed JSON chunks (one per NDJSON line).
    
    Ollama's chat endpoint accepts `tools` for tool-calling models. If tools is
    None, the field is omitted (some smaller models don't handle empty tool arrays).
    """
    payload = {"model": model, "messages": messages, "stream": True}
    if tools is not None:
        payload["tools"] = tools

    url = f"{BASE_URL}/api/chat"
    async with client.stream("POST", url, json=payload) as resp:
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                # Ollama can emit partial/malformed lines under load — skip them
                # rather than crashing the stream.
                continue


async def embed(client, text, model):
    """POST /api/embeddings. Returns the embedding vector."""
    url = f"{BASE_URL}/api/embeddings"
    payload = {"model": model, "prompt": text}
    resp = await client.post(url, json=payload, timeout=30.0)
    resp.raise_for_status()
    return resp.json()["embedding"]


async def list_models(client):
    """GET /api/tags. Returns the list of installed model names."""
    url = f"{BASE_URL}/api/tags"
    resp = await client.get(url, timeout=5.0)
    resp.raise_for_status()
    return [m["name"] for m in resp.json().get("models", [])]


async def generate(client, prompt, model, options=None):
    """POST /api/generate (non-streaming). Returns the response text.
    
    Used by condense_chat_memory and generate_title — short, single-shot
    completions where streaming is overhead.
    """
    url = f"{BASE_URL}/api/generate"
    payload = {"model": model, "prompt": prompt, "stream": False}
    if options:
        payload["options"] = options
    resp = await client.post(url, json=payload, timeout=60.0)
    resp.raise_for_status()
    return resp.json()["response"]
```

Add the `import json` at the top.

### Step 4: Verify tests pass

```bash
./venv/bin/pytest tests/test_ollama_client.py tests/ -v --ignore=tests/e2e
```

Expected: 4 new tests pass + 40 prior tests pass = 44 pass.

### Step 5: Quick live integration sanity (not committed)

Optional: hit the live Ollama via a one-liner to confirm the shapes:

```bash
./venv/bin/python -c "
import asyncio
import httpx
from core import ollama

async def main():
    async with httpx.AsyncClient() as c:
        print('models:', await ollama.list_models(c))
        print('embed dim:', len(await ollama.embed(c, 'hi', 'nomic-embed-text')))
        print('generate:', (await ollama.generate(c, 'Say hi.', 'gemma4:e4b'))[:50])

asyncio.run(main())
"
```

Expected: lists models, prints `embed dim: 768`, prints a short generation. If this fails, the module's wire shape doesn't match Ollama's — diagnose.

### Step 6: Commit

```bash
cd /home/orbital/projects/pryzm
git add backend/core/ollama.py backend/requirements-dev.txt backend/pytest.ini backend/tests/test_ollama_client.py
git commit -m "feat(async): implement ollama module (chat_stream, embed, list_models, generate)."
```

---

## Task 2 — Migrate `ai_engine.py` consumers to async + `core.ollama`

`ai_engine.py` has three functions that currently use sync `requests.post`:
- `stream_chat` (line 63) — the agentic loop, blocking calls to `/api/chat`
- `condense_chat_memory` (line 36) — blocking calls to `/api/generate`
- `generate_title` (line 229) — blocking calls to `/api/generate`

This task converts all three to async + replaces their HTTP calls with `core.ollama` calls. Callers of these functions in the routers will be updated in T3.

**Files:**
- Modify: `backend/core/ai_engine.py`
- Modify: `backend/tests/` — no existing tests for ai_engine specifically; we add behavior verification through the /analyze tests in T4. For now, ensure the existing 44 tests still pass after T2.

### Step 1: Read the current shape

```bash
sed -n '1,30p' /home/orbital/projects/pryzm/backend/core/ai_engine.py
sed -n '36,62p' /home/orbital/projects/pryzm/backend/core/ai_engine.py     # condense_chat_memory
sed -n '63,225p' /home/orbital/projects/pryzm/backend/core/ai_engine.py    # stream_chat
sed -n '229,265p' /home/orbital/projects/pryzm/backend/core/ai_engine.py   # generate_title
```

Read all three function bodies before editing. Take notes on:
- What additional logic exists beyond the `requests.post` call (prompt construction, response cleaning, agentic loop logic, etc.) — that stays.
- Where the `httpx.AsyncClient` should come from. The simplest pattern: each function accepts a `client` argument and the route handlers (T3) pass `request.app.state.http_client`.

### Step 2: Convert each function

For each of the three functions:

1. Add `async` to the def.
2. Add `client: httpx.AsyncClient` as the first parameter.
3. Replace `requests.post(...)` with the corresponding `await ollama.<func>(client, ...)`.
4. For `stream_chat`, the inner generator-yields-chunks loop is now `async for chunk in ollama.chat_stream(...)`.

Example pattern for `condense_chat_memory`:

```python
# Before:
def condense_chat_memory(old_memory: str, messages: list, model_name: str) -> str:
    # ... prompt construction ...
    payload = {"model": model_name, "prompt": prompt, "stream": False, "options": ...}
    url = f"{BASE_OLLAMA_URL}/api/generate"
    resp = requests.post(url, json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json().get("response", "").strip()

# After:
async def condense_chat_memory(
    client: httpx.AsyncClient,
    old_memory: str,
    messages: list,
    model_name: str,
) -> str:
    # ... prompt construction (unchanged) ...
    response_text = await ollama.generate(
        client, prompt=prompt, model=model_name, options={...}
    )
    return response_text.strip()
```

Similar pattern for `stream_chat` (yields chunks, becomes `async def` generator with `async for chunk in ollama.chat_stream(...)`) and `generate_title`.

### Step 3: Remove sync helper code from `ai_engine.py`

After the refactor, the file should NO LONGER:
- Import `requests`
- Reference `BASE_OLLAMA_URL` (that lives in `core.ollama` now)
- Have any sync `requests.post` or `requests.get` calls

Remove dead imports and constants. `import httpx` and `from core import ollama` are the new top-of-file imports.

### Step 4: Verify the existing test suite still passes

The ai_engine functions are imported but not directly tested. Existing tests will exercise them only indirectly (through /analyze flows we haven't migrated yet). So at this stage, the tests pass but the routers that call ai_engine functions WILL CRASH because they're calling async functions without `await`.

```bash
cd /home/orbital/projects/pryzm/backend
./venv/bin/pytest tests/ -v --ignore=tests/e2e
```

Expected: all 44 tests pass. (They don't touch ai_engine at runtime in any test.)

**Caveat:** the running backend (uvicorn --reload) WILL crash any user-facing chat or upload request at this point because the routers are still sync. Don't manually test chat in the browser until T3 lands.

### Step 5: Commit

```bash
cd /home/orbital/projects/pryzm
git add backend/core/ai_engine.py
git commit -m "feat(async): ai_engine functions async via core.ollama (stream_chat, condense, title)."
```

---

## Task 3 — Migrate other consumers + make `/analyze` async

Five more sites to migrate:
- `backend/services/knowledge.py:18` — `ingest_document` calls `requests.post` to embed; this is called from the SSE /upload route.
- `backend/routers/chat.py:152` — `/analyze` endpoint, currently sync `def`, calling sync `stream_chat`. Becomes `async def`.
- `backend/routers/chat.py:433` — `/api/models` route, sync `requests.get`.
- `backend/routers/workspaces.py:62` — `_validate_preferred_model`, sync HTTP call.
- `backend/routers/chat.py` — `/upload` route, which calls `ingest_document` (now async).

**Files:**
- Modify: `backend/services/knowledge.py`
- Modify: `backend/routers/chat.py`
- Modify: `backend/routers/workspaces.py`

### Step 1: Update `services/knowledge.py`

`ingest_document` currently:
- Adds a Document
- Splits content into chunks
- Calls `get_embedding(chunk_text)` → `requests.post` to Ollama
- Adds DocumentChunk rows

The embedding call must become async. Two options:
- Make `get_embedding` and `ingest_document` both async.
- Keep them sync but call from async contexts via `asyncio.to_thread`.

Option A (make them async) is the right shape. SQLAlchemy sync sessions don't mix great with async, but FastAPI's sync `Session = Depends(get_db)` is still fine if we don't await inside transactions for long. The pattern: do DB work synchronously, await the embedding outside the transaction.

```python
async def ingest_document(
    client: httpx.AsyncClient,
    db: Session,
    filename: str,
    content: str,
    workspace_id: str,
    session_id: str = None,
    is_global: bool = False,
):
    # Create the Document row.
    new_doc = models.Document(...)
    db.add(new_doc)
    db.commit()
    db.refresh(new_doc)

    splitter = RecursiveCharacterTextSplitter(...)
    chunks = splitter.split_text(content)

    # Embed each chunk. These are awaited outside any open DB transaction.
    for chunk_text in chunks:
        vector = await ollama.embed(client, chunk_text, "nomic-embed-text")
        db.add(models.DocumentChunk(
            document_id=new_doc.id,
            workspace_id=workspace_id,
            content=chunk_text,
            embedding=vector,
        ))

    db.commit()
    return {"status": "success", "chunks_created": len(chunks), "document_id": new_doc.id}
```

Update `services/knowledge.py:get_embedding` similarly — make it async, replace `requests.post` with `await ollama.embed(client, ...)`. Or remove `get_embedding` entirely and call `ollama.embed` directly from `ingest_document`.

### Step 2: Update `routers/chat.py`

`/analyze` — convert to `async def`. The function is huge (lines 152–293); convert in place:

```python
@router.post("/analyze")
async def analyze_data(
    request: AnalyzeRequest,
    http_request: Request,
    workspace: str = "it_copilot",
    db: Session = Depends(database.get_db),
    background_tasks: BackgroundTasks = None,
):
    client = http_request.app.state.http_client
    # ... existing route logic ...
    
    async def stream_generator():
        # Yields NDJSON lines. Now uses `async for` against ai_engine.stream_chat.
        nonlocal client
        try:
            async for chunk in ai_engine.stream_chat(client, full_messages, workspace.id, ...):
                # ... existing chunk handling ...
                yield json.dumps({"chunk": ...}) + "\n"
        except Exception as e:
            yield json.dumps({"error": str(e), "code": "engine_error"}) + "\n"
        finally:
            # Existing condensation-trigger block. We'll move it to BackgroundTasks in T4
            # for now keep it here as `await` since condense is async.
            ...

    return StreamingResponse(stream_generator(), media_type="application/x-ndjson")
```

`/upload` — convert to `async def` if not already; await `ingest_document`.

`/api/models` — convert to `async def`; use `await ollama.list_models(client)`.

### Step 3: Update `routers/workspaces.py`

`_validate_preferred_model` — `async def`, use `await ollama.list_models(client)`.

### Step 4: Verify with the test suite

```bash
cd /home/orbital/projects/pryzm/backend
./venv/bin/pytest tests/ -v --ignore=tests/e2e
```

Expected: 44 tests still pass. If anything fails, the migration broke something — diagnose.

### Step 5: Restart backend + manual sanity check

Restart backend. Open the frontend. Send a chat message in `personal` workspace. Confirm it streams normally. Upload a text file. Confirm it ingests.

(This is one of the few mid-phase manual verifications — chat path is too critical to leave to T7's e2e tests alone.)

### Step 6: Commit

```bash
cd /home/orbital/projects/pryzm
git add backend/services/knowledge.py backend/routers/chat.py backend/routers/workspaces.py
git commit -m "feat(async): /analyze, /upload, /api/models, validate_preferred_model are async."
```

---

## Task 4 — Cancellation propagation + per-tool timeouts

`/analyze`'s agentic loop should:
- Check `await request.is_disconnected()` between iterations and raise `CancelledError` on True.
- Wrap each tool call in `asyncio.wait_for(...)` with `settings.TOOL_TIMEOUT_SECONDS`.
- Run sync tools via `asyncio.to_thread` so cancellation is honored at thread boundaries.

**Files:**
- Modify: `backend/core/ai_engine.py` (the `stream_chat` agentic loop)
- Modify: `backend/routers/chat.py` (pass `http_request` into stream_chat so the engine can check disconnect)

### Step 1: Add disconnect propagation to stream_chat

`stream_chat`'s loop currently does something like:

```python
async for chunk in ollama.chat_stream(client, messages, tools, model):
    if chunk.get("done"):
        ...
        # If there's a tool call, execute it:
        for tool_call in chunk["message"].get("tool_calls", []):
            result = await execute_tool(tool_call)
            messages.append({"role": "tool", "content": result})
        # Loop continues with next ollama.chat_stream invocation.
```

Add a disconnect check before/after each tool call AND between each iteration of the outer agentic loop. Pass an optional `is_disconnected: Callable[[], Awaitable[bool]]` parameter to `stream_chat`:

```python
async def stream_chat(
    client: httpx.AsyncClient,
    messages: list,
    workspace_id: str,
    session_id: str = None,
    model_name: str = "gemma4:e4b",
    is_disconnected: Callable[[], Awaitable[bool]] | None = None,
):
    for loop_iteration in range(settings.MAXIMUM_TOOL_LOOPS):
        if is_disconnected and await is_disconnected():
            raise asyncio.CancelledError("client disconnected")
        async for chunk in ollama.chat_stream(client, messages, tools, model_name):
            yield chunk
            # ... handle tool calls ...
        # Tool call dispatch with timeout:
        for tool_call in tool_calls:
            try:
                result = await asyncio.wait_for(
                    _execute_tool_async(tool_call),
                    timeout=settings.TOOL_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                result = f"Tool {tool_call['function']['name']} timed out after {settings.TOOL_TIMEOUT_SECONDS}s"
            messages.append({"role": "tool", "content": result})
```

### Step 2: Wrap sync tools in `asyncio.to_thread`

The existing `execute_tool` (or equivalent dispatch) calls tools synchronously. Wrap:

```python
async def _execute_tool_async(tool_call):
    """Run a tool dispatch. Sync tools go through asyncio.to_thread so they
    don't block the event loop and cancellation can be honored at thread boundaries."""
    name = tool_call["function"]["name"]
    args = tool_call["function"].get("arguments", {})
    fn = AVAILABLE_TOOLS[name]
    # If the tool is async, await it. Otherwise, thread it.
    if asyncio.iscoroutinefunction(fn):
        return await fn(**args)
    return await asyncio.to_thread(fn, **args)
```

### Step 3: Pass `is_disconnected` from `/analyze`

In `routers/chat.py`'s `/analyze`:

```python
async def stream_generator():
    nonlocal client
    try:
        async for chunk in ai_engine.stream_chat(
            client, full_messages, workspace.id,
            is_disconnected=http_request.is_disconnected,
        ):
            yield json.dumps({"chunk": ...}) + "\n"
    except asyncio.CancelledError:
        # Client gone — nothing to yield. The finally will tidy up.
        return
    except Exception as e:
        yield json.dumps({"error": str(e), "code": "engine_error"}) + "\n"
    finally:
        # ... persistence + condensation trigger ...
```

### Step 4: Write the test

In `backend/tests/test_async_analyze.py`:

```python
"""Async-path tests for /analyze: disconnect propagation, per-tool timeout."""
import asyncio
import pytest
from unittest.mock import AsyncMock, patch

# Tests use the TestClient pattern from tests/smoke/.
# Each test asserts a specific behavior:
# 1. Concurrent /analyze requests don't serialize (timing-based, with mocked ollama).
# 2. Disconnect mid-stream propagates as CancelledError (mock is_disconnected to return True).
# 3. A tool that exceeds TOOL_TIMEOUT_SECONDS produces a timeout-message result.
# (Detailed test bodies below — write them mirroring the smoke probe style.)

# Implementation detail: mock core.ollama.chat_stream to yield slowly so the
# disconnect/timeout tests are deterministic.
```

(Implementer: write three real tests here. They go in a new file; same conftest as the smoke tests can be reused.)

### Step 5: Commit

```bash
cd /home/orbital/projects/pryzm
git add backend/core/ai_engine.py backend/routers/chat.py backend/tests/test_async_analyze.py
git commit -m "feat(async): cancellation propagation + per-tool timeouts in agentic loop."
```

---

## Task 5 — Background memory condensation with Postgres advisory lock

The condensation work currently lives in `/analyze`'s SSE generator `finally` block — it blocks response close. Move it to a real background task using FastAPI's `BackgroundTasks` and protect against concurrent condensers via a Postgres advisory lock keyed on `session_id`.

**Files:**
- Modify: `backend/routers/chat.py` (remove condensation from the SSE generator, schedule it via BackgroundTasks)
- Create: `backend/services/condense.py` (the background task body + advisory lock helper)

### Step 1: Create `services/condense.py`

```python
"""Background memory condensation.

Runs out-of-band after /analyze closes. Uses a Postgres advisory lock keyed
on the session id so concurrent requests for the same session don't both
condense at once.
"""
import logging
from contextlib import contextmanager

import httpx
from sqlalchemy import text

from core import ai_engine
from db import database, models

logger = logging.getLogger(__name__)


@contextmanager
def _session_advisory_lock(db, session_id: str):
    """Acquire a Postgres advisory lock keyed on hashtextextended('condense:<session>').
    Yields True if acquired, False otherwise. Caller decides what to do."""
    key_sql = text("SELECT hashtextextended(:k, 0)").bindparams(k=f"condense:{session_id}")
    key = db.execute(key_sql).scalar()
    acquired = db.execute(text("SELECT pg_try_advisory_lock(:k)").bindparams(k=key)).scalar()
    try:
        yield acquired
    finally:
        if acquired:
            db.execute(text("SELECT pg_advisory_unlock(:k)").bindparams(k=key))
            db.commit()


async def condense_for_session(client: httpx.AsyncClient, session_id: str, model_name: str):
    """Condense the messages for `session_id` if the threshold is met.
    
    Idempotent under concurrent calls — uses a session-keyed advisory lock to
    ensure only one condenser runs per session at a time.
    """
    db = database.SessionLocal()
    try:
        with _session_advisory_lock(db, session_id) as acquired:
            if not acquired:
                logger.info("condense skip: lock held for %s", session_id)
                return
            # Existing condensation logic moved here:
            # 1. Load messages above threshold.
            # 2. Load any prior memory row.
            # 3. Call ai_engine.condense_chat_memory.
            # 4. Persist new memory row.
            # (Implementer: lift this from the existing /analyze finally block verbatim,
            # adjust to await the now-async condense_chat_memory.)
            ...
    except Exception as e:
        logger.exception("condense failed for session %s: %s", session_id, e)
    finally:
        db.close()
```

### Step 2: Update `/analyze` to schedule the task

In `routers/chat.py`, replace the existing inline condensation in the SSE generator's `finally` block with:

```python
# At the end of /analyze, after the StreamingResponse is built:
background_tasks.add_task(
    condense.condense_for_session, client, chat_session.id, request.model,
)
return StreamingResponse(stream_generator(), media_type="application/x-ndjson", background=background_tasks)
```

The `background` parameter on `StreamingResponse` causes FastAPI to run the tasks AFTER the response is fully sent.

### Step 3: Write the test

In `backend/tests/test_condense.py`:

```python
"""Tests for the background condensation service."""
import pytest
from unittest.mock import AsyncMock, patch

from services import condense


def test_advisory_lock_acquires_and_releases(db_session):
    """Two simultaneous lock attempts on the same session id: first wins, second skips."""
    sid = "session-x"
    with condense._session_advisory_lock(db_session, sid) as a:
        assert a is True
        # Open a second connection (a separate Session) and try again.
        from db import database
        db2 = database.SessionLocal()
        try:
            with condense._session_advisory_lock(db2, sid) as b:
                assert b is False  # locked by the outer session
        finally:
            db2.close()
    # After releasing the outer lock, a third attempt should succeed.
    with condense._session_advisory_lock(db_session, sid) as c:
        assert c is True
```

### Step 4: Commit

```bash
cd /home/orbital/projects/pryzm
git add backend/services/condense.py backend/routers/chat.py backend/tests/test_condense.py
git commit -m "feat(async): condensation runs in BackgroundTasks with session advisory lock."
```

---

## Task 6 — SSE error envelope (backend + frontend)

The SSE generator currently emits `{"chunk": "<text>"}` for content and `{"done": true}` at the end. Errors get squashed into a chunk that contains "[Engine Error: ...]" text — indistinguishable from normal output.

New envelope: `{"error": "<human msg>", "code": "<machine_code>"}` for errors. Frontend detects and surfaces cleanly.

**Files:**
- Modify: `backend/routers/chat.py` (already partly addressed in T3/T4 — finalize the envelope shape)
- Modify: `frontend/src/hooks/useInference.ts` (SSE parser)

### Step 1: Backend — settle the error envelope contract

In `routers/chat.py`'s `stream_generator`, error paths emit:

```python
yield json.dumps({"error": "<human-readable message>", "code": "<machine_code>"}) + "\n"
```

Codes to define:
- `engine_error` — generic exception in the agentic loop.
- `ollama_unreachable` — httpx connect error.
- `ollama_timeout` — read timeout.
- `tool_timeout` — a tool exceeded TOOL_TIMEOUT_SECONDS.
- `model_unloaded` — Ollama returned a "model not found" / cold-load failure.

Map exception types to codes in a small `_envelope_for_exception(exc)` helper.

### Step 2: Frontend — useInference SSE parser

In `frontend/src/hooks/useInference.ts`, the parser splits the response body by lines and `JSON.parse`s each. Today it likely does:

```typescript
if (parsed.chunk) { /* append */ }
if (parsed.done) { /* finalize */ }
```

Add error handling:

```typescript
if (parsed.error) {
  // Replace the streaming bubble's content with the error message; mark status as failed.
  finalizeMessage(sessionId, assistantId, `⚠ ${parsed.error}`, "failed");
  // Could also surface a toast.
  return;
}
```

The detection must happen BEFORE the `done` check so a single message can be marked as failed cleanly.

### Step 3: Write a smoke probe

In `backend/tests/test_async_analyze.py`, add:

```python
@pytest.mark.asyncio
async def test_engine_error_emits_error_envelope():
    """An exception in ai_engine.stream_chat surfaces as {error, code}."""
    # Patch ai_engine.stream_chat to raise an exception immediately.
    # Send a /analyze request via TestClient.
    # Parse the response body line-by-line; assert one line is {"error", "code"}
    # and that no {"chunk"} line contains the error text.
```

### Step 4: Commit

```bash
cd /home/orbital/projects/pryzm
git add backend/routers/chat.py frontend/src/hooks/useInference.ts backend/tests/test_async_analyze.py
git commit -m "feat(async): SSE error envelope distinguishable from content chunks."
```

---

## Task 7 — Phase 3 UI smoke (Playwright e2e)

**Files:**
- Create: `backend/tests/e2e/test_phase3_smoke.py`

### Tests to write

1. **`test_chat_message_streams`** — send a message in `personal`, verify the assistant bubble appears and accumulates text. Tests the async streaming path end-to-end.

2. **`test_concurrent_chats_overlap`** — open two browser contexts (two sessions in parallel), fire a chat in each, verify both stream concurrently rather than one waiting for the other. The async refactor's headline win.

3. **`test_disconnect_during_stream_cancels`** — start a chat, close the page/context mid-stream, verify (via backend log assertion or a `/health`-style probe) that the loop terminates.

4. **`test_error_envelope_shows_error_ui`** — mock Ollama to return an error (or trigger a known failure path), verify the assistant bubble shows a `⚠`-prefixed error rather than crashing or being blank.

(Implementer: write the test bodies using `tests/e2e/conftest.py` fixtures. Adapt selectors to the actual UI.)

### Run + commit

```bash
cd /home/orbital/projects/pryzm/backend
./venv/bin/pytest tests/e2e/test_phase3_smoke.py -v
```

Expected: 4/4 pass.

```bash
cd /home/orbital/projects/pryzm
git add backend/tests/e2e/test_phase3_smoke.py
git commit -m "test(e2e): phase 3 UI smoke — streaming, concurrency, disconnect, error envelope."
```

---

## Task 8 — Final review + auto-merge

Controller work.

### Step 1: Branch sweep

```bash
git log main..HEAD --oneline    # ~9 commits expected
git diff main..HEAD --stat       # confirm only the planned files changed
```

### Step 2: Run the full suite

```bash
cd /home/orbital/projects/pryzm/backend
./venv/bin/pytest tests/ -v
```

Expected: 44 prior + new T1-T7 tests = ~55+ pass.

### Step 3: Push + open PR via gh

```bash
cd /home/orbital/projects/pryzm
git push -u origin refactor/phase-3-async-ollama
gh pr create --title "Phase 3 — async I/O + Ollama colocation + background condensation" --body "$(cat <<'EOF'
Phase 3 of the codebase remediation. The chat path is now actually async — `httpx.AsyncClient` shared across requests, all Ollama HTTP shape in `core/ollama.py`, agentic loop propagates client disconnect, per-tool timeouts, condensation moved to BackgroundTasks with a session-keyed advisory lock. SSE error envelope is now distinguishable from a content chunk. New required setting: none — defaults in `config.py` work out of the box.

See [spec](docs/specs/2026-05-14-codebase-remediation.md) (Phase 3) and [plan](docs/plans/2026-05-14-phase-3-async-ollama.md).

Tests: ~55 passing. Squash and merge.
EOF
)"
```

### Step 4: Run UI smoke

```bash
cd /home/orbital/projects/pryzm/backend
./venv/bin/pytest tests/e2e/ -v
```

Expected: 10/10 (6 Phase 2 + 4 Phase 3). Report results in chat.

### Step 5: Auto-merge if clean

```bash
gh pr merge --squash --delete-branch
git checkout main && git pull origin main
git branch -d refactor/phase-3-async-ollama
```

Report "Phase 3 merged at <new SHA>" in chat.

---

## Risks and rollback

- **The chat path is the biggest blast radius.** Phase 3 rewires the SSE generator. If the e2e smoke catches a regression, we fix on the branch before merge. After merge, `git revert <merge-commit>` rolls back the whole phase.
- **Async/sync interactions are subtle.** SQLAlchemy sync sessions inside an async route handler work but require care — never `await` something inside a transaction that holds DB locks for long. The new pattern is: do the DB write, commit, THEN await any LLM/embedding call.
- **The `httpx.AsyncClient` lifecycle** is a real source of bugs if mis-managed. Lifespan handles creation/disposal; per-request clients (not what we're doing) would leak connections.
- **The advisory lock** is keyed on the application-level session id (string) — `hashtextextended` gives us a bigint for `pg_try_advisory_lock`. If two unrelated session ids ever hash-collide, both would block each other. Vanishingly unlikely with 64-bit hashes but worth noting.
- **Tool timeouts.** Setting `TOOL_TIMEOUT_SECONDS=30` may be too short for genuinely slow tools (e.g., a network scan against a large subnet). Configurable, easy to bump.

---

## Related memory

- [[project-llama-cpp-swap]] — the colocation in `core/ollama.py` is the seam the future swap drops a `core/llama_cpp.py` next to.
- [[feedback-karpathy-for-subagents]] — implementer agents executing this plan get Karpathy guidelines.
- [[feedback-lean-pr-descriptions]] — the PR body for Phase 3 stays short; this plan is the depth-on-demand.
- [[feedback-auto-merge-authorized]] — Task 8 uses `gh pr merge --squash --delete-branch` autonomously.
- [[project-ui-smoke-harness]] — Task 7 is the per-phase e2e the harness was built for.
