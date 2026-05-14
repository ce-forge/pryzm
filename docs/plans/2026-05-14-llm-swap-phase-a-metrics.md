# LLM Swap — Phase A — Per-Request Metrics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking. Implementation agents must apply Karpathy guidelines: minimum code, no speculative abstractions, surgical changes, verifiable success criteria.

**Goal:** Capture per-request LLM performance metrics on the existing Ollama path (TTFT, total duration, tokens-per-second, prompt/completion token counts) via structured log lines, plus a benchmark CLI that produces a markdown comparison table. This is the *baseline-capture* phase — Phase C will re-run the same script against the llama-swap stack and diff.

**Architecture:** A small `core/llm_metrics.py` module owns metric emission (helper functions + per-request `contextvars` for workspace/session). `core/ollama.py`'s three production functions (`chat`, `generate`, `embed`) call into the helpers after each HTTP round-trip — extracting Ollama's native `prompt_eval_count`, `eval_count`, and nanosecond-precision duration fields rather than doing client-side timing. The router sets the request context at `/analyze` entry. A standalone `backend/tests/perf/bench_llm.py` CLI runs a fixed prompt set against the live backend and aggregates the metrics it emitted into a markdown table.

**Tech stack:** Python stdlib `logging` + `contextvars`, `httpx` (already in deps for the bench script's HTTP client), no new dependencies. Test runner is the existing pytest harness.

**Spec reference:** [`docs/specs/2026-05-14-llm-server-swap.md`](../specs/2026-05-14-llm-server-swap.md) — Phase A section.

**Branch:** `refactor/llm-swap-phase-a-metrics` (cut from `main` after the codebase remediation Phases 1–6 merged).

---

## File Map

### Created
- `backend/core/llm_metrics.py` — `set_request_context()`, `emit_chat_metric()`, `emit_embed_metric()`, plus `_workspace_id` / `_session_id` `ContextVar`s.
- `backend/tests/test_llm_metrics.py` — pytest unit tests for the emit functions (extracts the right fields from a mocked Ollama response, formats the log line correctly).
- `backend/tests/perf/__init__.py` — empty marker file.
- `backend/tests/perf/prompts.py` — the fixed prompt set (5 classes: short Q, medium Q, code task, tool-use trigger, RAG-with-attachment-omitted). Each class has 3 prompts.
- `backend/tests/perf/bench_llm.py` — CLI: hits `/analyze`, parses the metric lines from the response stream, aggregates min/median/p95/max for `ttft_ms`, `duration_ms`, `tokens_per_sec` per prompt class, prints a markdown table.
- `backend/tests/perf/results/.gitkeep` — placeholder so the directory exists in git but the actual result files are gitignored.

### Modified
- `backend/core/ollama.py` — wrap `chat`, `generate`, `embed` with metric emission. ~30 lines added across the three functions.
- `backend/routers/chat.py` — call `set_request_context(workspace_id, session_id)` at the top of the `/analyze` async generator. Append a `usage` block (`{prompt_tokens, completion_tokens, ttft_ms, duration_ms, tokens_per_sec}`) to the final SSE chunk so the bench script can read it without log scraping.
- `backend/.gitignore` — add `backend/tests/perf/results/*.md` (allow `.gitkeep`).

### Untouched
- `backend/core/ai_engine.py` — no changes; instrumentation is at the `core/ollama.py` level so all callers benefit transparently.
- `backend/services/knowledge.py` — no changes for the same reason (it calls `ollama.embed`).
- Frontend code — Phase A is backend-only.
- Database schema — no migrations.

---

## Pre-flight

Confirm clean baseline + create the working branch:

```bash
cd /home/orbital/projects/pryzm
git checkout main
git pull --ff-only
git checkout -b refactor/llm-swap-phase-a-metrics

# Existing tests baseline.
./backend/venv/bin/pytest backend/tests/ --quiet --ignore=backend/tests/e2e | tail -3
# Expected: 74 passed

# Confirm dev backend is reachable (used by Task 9).
curl -sf http://127.0.0.1:8000/health && echo "backend up" || echo "backend down — start it first"
```

---

## Task 1 — `llm_metrics` module skeleton

**Files:**
- Create: `backend/core/llm_metrics.py`
- Create: `backend/tests/test_llm_metrics.py`

### Step 1: Write the failing tests

`backend/tests/test_llm_metrics.py`:

```python
"""Unit tests for the LLM metric emission helpers."""
import logging

import pytest

from core.llm_metrics import (
    emit_chat_metric,
    emit_embed_metric,
    set_request_context,
)


def _capture(caplog):
    return [r for r in caplog.records if r.name == "pryzm.llm"]


def test_emit_chat_metric_extracts_ollama_fields(caplog):
    """Given a chat response with Ollama's standard timing fields, the metric
    line should carry the parsed values."""
    set_request_context(workspace_id="ws-1", session_id="s-1")
    response = {
        "prompt_eval_count": 312,
        "eval_count": 187,
        "prompt_eval_duration": 420_000_000,   # ns -> 420 ms
        "eval_duration": 4_410_000_000,        # ns -> 4410 ms
        "total_duration": 4_830_000_000,       # ns -> 4830 ms
    }
    with caplog.at_level(logging.INFO, logger="pryzm.llm"):
        emit_chat_metric(model="gemma4:e4b", response=response, fallback_duration_s=4.83)

    records = _capture(caplog)
    assert len(records) == 1
    msg = records[0].getMessage()
    assert "llm.metric" in msg
    assert "model=gemma4:e4b" in msg
    assert "prompt_tokens=312" in msg
    assert "completion_tokens=187" in msg
    assert "ttft_ms=420" in msg
    assert "duration_ms=4830" in msg
    # 187 tokens / 4.41s = 42.40 tps
    assert "tokens_per_sec=42.40" in msg
    assert "workspace_id=ws-1" in msg
    assert "session_id=s-1" in msg


def test_emit_chat_metric_falls_back_when_ollama_omits_timings(caplog):
    """Some Ollama versions omit duration fields under load. The helper falls
    back to the wall-clock seconds the caller measured."""
    set_request_context(workspace_id="ws-2", session_id="s-2")
    response = {"prompt_eval_count": 10, "eval_count": 5}  # no durations
    with caplog.at_level(logging.INFO, logger="pryzm.llm"):
        emit_chat_metric(model="m", response=response, fallback_duration_s=2.0)

    records = _capture(caplog)
    assert len(records) == 1
    msg = records[0].getMessage()
    assert "duration_ms=2000" in msg  # fallback
    assert "ttft_ms=0" in msg          # unknown -> 0
    assert "tokens_per_sec=0.00" in msg # cannot compute without eval_duration


def test_emit_embed_metric(caplog):
    set_request_context(workspace_id="ws-3", session_id="")
    with caplog.at_level(logging.INFO, logger="pryzm.llm"):
        emit_embed_metric(model="nomic-embed-text", char_count=423, duration_s=0.18)
    records = _capture(caplog)
    assert len(records) == 1
    msg = records[0].getMessage()
    assert "llm.embed_metric" in msg
    assert "model=nomic-embed-text" in msg
    assert "char_count=423" in msg
    assert "duration_ms=180" in msg
    assert "workspace_id=ws-3" in msg
    assert "session_id=" in msg


def test_context_defaults_when_unset(caplog):
    """If the request handler didn't call set_request_context, both fields are
    empty strings (not None) so the log line is still well-formed."""
    # Reset by setting to defaults
    set_request_context(workspace_id="", session_id="")
    response = {"prompt_eval_count": 0, "eval_count": 0}
    with caplog.at_level(logging.INFO, logger="pryzm.llm"):
        emit_chat_metric(model="m", response=response, fallback_duration_s=1.0)
    msg = _capture(caplog)[0].getMessage()
    assert "workspace_id=" in msg
    assert "session_id=" in msg
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
./backend/venv/bin/pytest backend/tests/test_llm_metrics.py -v
```

Expected: collection error (`ModuleNotFoundError: No module named 'core.llm_metrics'`).

### Step 3: Write the minimal implementation

`backend/core/llm_metrics.py`:

```python
"""Per-request LLM performance metric emission.

Helpers used by core/ollama.py to log timing/token counts for every chat,
generate, and embed call. Workspace and session ids are threaded via
contextvars so call sites don't need new positional parameters — the router
sets the context at /analyze entry; the helpers pick it up here.

Output shape is a single key=value-formatted log line per LLM call. Grep-able
from the backend log; also re-aggregated by tests/perf/bench_llm.py for the
phase comparison.
"""
from __future__ import annotations

import contextvars
import logging

_logger = logging.getLogger("pryzm.llm")

_workspace_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "pryzm_llm_workspace_id", default=""
)
_session_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "pryzm_llm_session_id", default=""
)


def set_request_context(*, workspace_id: str, session_id: str) -> None:
    """Sets per-request identifiers used by subsequent metric emissions on the
    same asyncio task. Call once at the top of each request that will trigger
    LLM activity."""
    _workspace_id.set(workspace_id or "")
    _session_id.set(session_id or "")


def emit_chat_metric(
    *,
    model: str,
    response: dict,
    fallback_duration_s: float,
) -> None:
    """Logs a single 'llm.metric' line. Prefers Ollama's native nanosecond
    timing fields; falls back to the wall-clock seconds the caller passes in
    if Ollama omitted them.

    Tokens/sec is computed from eval_count / eval_duration, NOT from
    completion_tokens / total_duration — the latter would penalise the model
    for prompt-eval time it doesn't control."""
    prompt_tokens = int(response.get("prompt_eval_count", 0))
    completion_tokens = int(response.get("eval_count", 0))

    prompt_eval_ns = int(response.get("prompt_eval_duration", 0))
    eval_ns = int(response.get("eval_duration", 0))
    total_ns = int(response.get("total_duration", 0))

    ttft_ms = prompt_eval_ns // 1_000_000 if prompt_eval_ns else 0
    duration_ms = total_ns // 1_000_000 if total_ns else int(fallback_duration_s * 1000)
    tokens_per_sec = (
        (completion_tokens * 1_000_000_000.0) / eval_ns
        if eval_ns and completion_tokens
        else 0.0
    )

    _logger.info(
        "llm.metric model=%s prompt_tokens=%d completion_tokens=%d "
        "ttft_ms=%d duration_ms=%d tokens_per_sec=%.2f "
        "workspace_id=%s session_id=%s",
        model, prompt_tokens, completion_tokens,
        ttft_ms, duration_ms, tokens_per_sec,
        _workspace_id.get(), _session_id.get(),
    )


def emit_embed_metric(
    *,
    model: str,
    char_count: int,
    duration_s: float,
) -> None:
    """Logs a single 'llm.embed_metric' line. Embeddings don't have a
    streaming-vs-prompt-eval split, so duration is wall-clock only."""
    _logger.info(
        "llm.embed_metric model=%s char_count=%d duration_ms=%d "
        "workspace_id=%s session_id=%s",
        model, char_count, int(duration_s * 1000),
        _workspace_id.get(), _session_id.get(),
    )
```

- [ ] **Step 4: Re-run the tests**

```bash
./backend/venv/bin/pytest backend/tests/test_llm_metrics.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/core/llm_metrics.py backend/tests/test_llm_metrics.py
git commit -m "feat(metrics): llm_metrics emission helpers + unit tests"
```

---

## Task 2 — Wrap `ollama.chat` with metric emission

**Files:**
- Modify: `backend/core/ollama.py`

### Step 1: Edit `chat` to emit a metric line after each call

In `backend/core/ollama.py`, replace the existing `chat` function with:

```python
import time
from core.llm_metrics import emit_chat_metric


async def chat(
    client: httpx.AsyncClient,
    messages: list,
    tools: list | None,
    model: str,
    options: dict | None = None,
) -> dict:
    """POST /api/chat with stream=False. Returns the full message dict.

    Used by ai_engine.stream_chat — the engine receives the whole payload first,
    then fake-streams it word-by-word. If `tools` is None, the field is omitted.

    Emits an 'llm.metric' log line on every successful call.
    """
    payload: dict = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"num_ctx": 8192},
    }
    if tools is not None:
        payload["tools"] = tools
    if options:
        payload["options"].update(options)

    url = f"{BASE_URL}/api/chat"
    t0 = time.perf_counter()
    resp = await client.post(url, json=payload, timeout=120.0)
    resp.raise_for_status()
    duration_s = time.perf_counter() - t0
    data = resp.json()
    emit_chat_metric(model=model, response=data, fallback_duration_s=duration_s)
    return data
```

> Add the `import time` at the top of the file alongside `import json` if it's not already there. Add `from core.llm_metrics import emit_chat_metric` next to the existing import block.

- [ ] **Step 2: Run a smoke check** that the module still imports

```bash
./backend/venv/bin/python -c "from core import ollama; print('ok')"
```

Expected: `ok`.

- [ ] **Step 3: Run the existing test suite to confirm nothing broke**

```bash
./backend/venv/bin/pytest backend/tests/ --quiet --ignore=backend/tests/e2e | tail -3
```

Expected: 74 + 4 = 78 passed.

- [ ] **Step 4: Commit**

```bash
git add backend/core/ollama.py
git commit -m "feat(metrics): emit llm.metric on every ollama.chat call"
```

---

## Task 3 — Wrap `ollama.generate` with metric emission

**Files:**
- Modify: `backend/core/ollama.py`

### Step 1: Edit `generate` to emit a metric line after each call

Replace the existing `generate` function with:

```python
async def generate(
    client: httpx.AsyncClient,
    prompt: str,
    model: str,
    options: dict | None = None,
) -> str:
    """POST /api/generate (non-streaming). Returns the response text.

    Used by ai_engine.condense_chat_memory and ai_engine.generate_title — short,
    single-shot completions where streaming is overhead. Emits an 'llm.metric'
    line per call (the chat-shape extractor works fine here — /api/generate's
    response carries the same prompt_eval_count / eval_count / *_duration fields)."""
    url = f"{BASE_URL}/api/generate"
    payload: dict = {"model": model, "prompt": prompt, "stream": False}
    if options:
        payload["options"] = options
    t0 = time.perf_counter()
    resp = await client.post(url, json=payload, timeout=60.0)
    resp.raise_for_status()
    duration_s = time.perf_counter() - t0
    data = resp.json()
    emit_chat_metric(model=model, response=data, fallback_duration_s=duration_s)
    return data["response"]
```

- [ ] **Step 2: Re-run the import smoke + existing tests**

```bash
./backend/venv/bin/python -c "from core import ollama; print('ok')"
./backend/venv/bin/pytest backend/tests/ --quiet --ignore=backend/tests/e2e | tail -3
```

Expected: 78 passed (no regressions; no new tests added in this task).

- [ ] **Step 3: Commit**

```bash
git add backend/core/ollama.py
git commit -m "feat(metrics): emit llm.metric on every ollama.generate call"
```

---

## Task 4 — Wrap `ollama.embed` with metric emission

**Files:**
- Modify: `backend/core/ollama.py`

### Step 1: Edit `embed` to emit a metric line after each call

Add the `emit_embed_metric` import next to `emit_chat_metric`:

```python
from core.llm_metrics import emit_chat_metric, emit_embed_metric
```

Replace the existing `embed` function with:

```python
async def embed(client: httpx.AsyncClient, text: str, model: str) -> list[float]:
    """POST /api/embeddings. Returns the embedding vector. Emits an
    'llm.embed_metric' line per call."""
    url = f"{BASE_URL}/api/embeddings"
    payload = {"model": model, "prompt": text}
    t0 = time.perf_counter()
    resp = await client.post(url, json=payload, timeout=30.0)
    resp.raise_for_status()
    duration_s = time.perf_counter() - t0
    emit_embed_metric(model=model, char_count=len(text), duration_s=duration_s)
    return resp.json()["embedding"]
```

- [ ] **Step 2: Re-run the existing tests**

```bash
./backend/venv/bin/pytest backend/tests/ --quiet --ignore=backend/tests/e2e | tail -3
```

Expected: 78 passed.

- [ ] **Step 3: Commit**

```bash
git add backend/core/ollama.py
git commit -m "feat(metrics): emit llm.embed_metric on every ollama.embed call"
```

---

## Task 5 — Set request context in the `/analyze` router

**Files:**
- Modify: `backend/routers/chat.py`

### Step 1: Set the metric context at the top of the streaming generator

Find the `analyze_data` handler in `backend/routers/chat.py` (currently around line 192). Inside the `async def generate():` block (around line 260), set the context as the first statement, BEFORE the `yield json.dumps({"status": "started", ...})` line:

```python
    async def generate():
        from core.llm_metrics import set_request_context
        set_request_context(workspace_id=workspace_id, session_id=session_id)

        yield json.dumps({"status": "started", "session_id": session_id}) + "\n"
        # ... rest of the existing generator body unchanged ...
```

> The import is intentionally inside the function rather than at module top-level: it avoids a top-of-file import churn for a one-call-site addition, and `set_request_context` is cheap to import on every request (Python caches module imports).

- [ ] **Step 2: Run the existing tests to confirm no regression**

```bash
./backend/venv/bin/pytest backend/tests/ --quiet --ignore=backend/tests/e2e | tail -3
```

Expected: 78 passed.

- [ ] **Step 3: Manual smoke against live backend**

> Prerequisite: backend running on :8000 with a workspace + token configured.

Send a chat message via curl and watch for the `llm.metric` line in the backend log:

```bash
curl -s -X POST "http://127.0.0.1:8000/analyze?workspace=personal" \
  -H "Authorization: Bearer $(grep PRYZM_API_TOKEN .env | cut -d= -f2)" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "say one word", "session_id": null, "attachments": []}' \
  -o /dev/null
```

Expected (in the backend log): a line of the form
```
llm.metric model=<...> prompt_tokens=<n> completion_tokens=<n> ttft_ms=<n> duration_ms=<n> tokens_per_sec=<n.nn> workspace_id=<uuid> session_id=<uuid>
```

If `workspace_id=` is empty, the context wasn't set in time — re-check the placement of `set_request_context` (it must run before any LLM call, including the title-generation path).

- [ ] **Step 4: Commit**

```bash
git add backend/routers/chat.py
git commit -m "feat(metrics): set request context for llm metric emission in /analyze"
```

---

## Task 6 — Emit `usage` block on the final `/analyze` SSE chunk

The bench script needs a low-friction way to read per-request token counts without scraping the backend log. Append a `usage` block to the final chunk so the client-side script can consume it directly.

**Files:**
- Modify: `backend/routers/chat.py`

### Step 1: Find the loop's "completed cleanly" exit and emit usage before the `done` chunk

Locate the existing `generate()` body in `analyze_data`. After the `async for chunk in ai_engine.stream_chat(...)` loop completes successfully (the `if completed:` / final-chunk block), include a `usage` field on the terminating JSON line.

Replace the existing terminating chunk emission with the following (keep all other lines in the `finally`/disconnect path as-is):

```python
        # The terminating chunk now carries an aggregate `usage` block so
        # bench_llm.py can read it directly without scraping logs.
        # Token counts here are best-effort: we accumulate them by hooking the
        # last chat call's metric (the one that produced the user-visible
        # answer). Earlier tool-loop iterations are intentionally not summed —
        # the bench_llm script is asking "how fast was the FINAL answer", not
        # "how many tokens did the agentic loop burn in total."
        usage = _last_chat_metric_snapshot()  # see Task 6, Step 2
        yield json.dumps({"done": True, "usage": usage}) + "\n"
```

> Replace the line `yield json.dumps({"done": True}) + "\n"` (or equivalent — check the current file) with the snippet above.

### Step 2: Add the `_last_chat_metric_snapshot` accessor

The snapshot is provided by a small contextvar, set inside `emit_chat_metric` and read at the end of the request.

In `backend/core/llm_metrics.py`, ADD (don't replace) the snapshot mechanism. Append to the bottom of the file:

```python
_last_chat_snapshot: contextvars.ContextVar[dict] = contextvars.ContextVar(
    "pryzm_last_chat_snapshot", default={}
)


def _record_chat_snapshot(snapshot: dict) -> None:
    _last_chat_snapshot.set(snapshot)


def get_last_chat_snapshot() -> dict:
    """Returns the most recent chat metric for this request task. Empty dict if
    no chat call has been made yet on this task."""
    return _last_chat_snapshot.get()
```

Then update `emit_chat_metric` (in the same file) to record the snapshot as a side effect, immediately before the `_logger.info(...)` call:

```python
    snapshot = {
        "model": model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "ttft_ms": ttft_ms,
        "duration_ms": duration_ms,
        "tokens_per_sec": round(tokens_per_sec, 2),
    }
    _record_chat_snapshot(snapshot)

    _logger.info(
        "llm.metric model=%s prompt_tokens=%d completion_tokens=%d "
        # ... rest unchanged ...
    )
```

### Step 3: Wire the accessor into the router

In `backend/routers/chat.py`, replace the `_last_chat_metric_snapshot()` placeholder used in Step 1 with a real import at the top of `chat.py`:

```python
from core.llm_metrics import get_last_chat_snapshot as _last_chat_metric_snapshot
```

(The alias keeps the call site readable; the import sits with the other `core` imports.)

- [ ] **Step 4: Re-run unit tests**

```bash
./backend/venv/bin/pytest backend/tests/ --quiet --ignore=backend/tests/e2e | tail -3
```

Expected: 78 passed.

- [ ] **Step 5: Add a unit test for the snapshot mechanism**

Append to `backend/tests/test_llm_metrics.py`:

```python
def test_snapshot_records_last_chat_metric(caplog):
    """get_last_chat_snapshot returns the most recent emit_chat_metric values
    for the current asyncio task (used by /analyze's final SSE chunk)."""
    from core.llm_metrics import get_last_chat_snapshot

    set_request_context(workspace_id="w", session_id="s")
    response = {
        "prompt_eval_count": 50,
        "eval_count": 100,
        "prompt_eval_duration": 200_000_000,
        "eval_duration": 1_000_000_000,
        "total_duration": 1_200_000_000,
    }
    emit_chat_metric(model="m", response=response, fallback_duration_s=1.2)

    snap = get_last_chat_snapshot()
    assert snap["model"] == "m"
    assert snap["prompt_tokens"] == 50
    assert snap["completion_tokens"] == 100
    assert snap["ttft_ms"] == 200
    assert snap["duration_ms"] == 1200
    assert snap["tokens_per_sec"] == 100.0
```

Run:
```bash
./backend/venv/bin/pytest backend/tests/test_llm_metrics.py -v
```

Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/core/llm_metrics.py backend/tests/test_llm_metrics.py backend/routers/chat.py
git commit -m "feat(metrics): final SSE chunk carries usage block for bench script"
```

---

## Task 7 — Benchmark prompt set

**Files:**
- Create: `backend/tests/perf/__init__.py`
- Create: `backend/tests/perf/prompts.py`

### Step 1: Create the package marker

```bash
touch backend/tests/perf/__init__.py
```

### Step 2: Create the prompt set

`backend/tests/perf/prompts.py`:

```python
"""Fixed prompt set for the LLM perf benchmark.

Five classes covering Pryzm's representative workload:

  short_q       — a one-line factual question; tier-1 territory
  medium_q      — a couple of paragraphs of context + a question
  code_task    — code-shaped prompt with a fence, expects a code answer
  tool_use      — a question that should trigger a tool call (network/RAG)
  rag_inline    — the prompt asks the assistant to summarise file content
                  embedded inline (Phase A doesn't upload a file; we paste a
                  ~500-char synthetic blob to exercise the longer-context path)

Each class has 3 prompts. The bench harness sends all 15 (5x3) sequentially
with N repeats per prompt (default N=3 per harness arg)."""

PROMPTS: dict[str, list[str]] = {
    "short_q": [
        "What is my IP address?",
        "Who is the CEO of Apple?",
        "What does CIDR stand for?",
    ],
    "medium_q": [
        "Explain in two paragraphs what DNS is and why caching matters at the resolver level.",
        "Summarize the difference between RAID 1, RAID 5, and RAID 10 for a small office NAS deployment.",
        "Walk me through what happens when I type a URL into a browser and press Enter.",
    ],
    "code_task": [
        "Write a Python function that takes a list of integers and returns only the prime numbers. Include a docstring.\n\n```python\ndef primes(nums):\n    pass\n```",
        "Refactor the following snippet to be more idiomatic:\n\n```python\nresult = []\nfor i in range(len(items)):\n    if items[i].active:\n        result.append(items[i].name)\n```",
        "Show me a bash one-liner that finds all .log files modified in the last hour under /var/log and prints them sorted by size.",
    ],
    "tool_use": [
        "Check whether port 22 is open on 127.0.0.1.",
        "Look up the documentation we have on attack-surface checklists.",
        "What does our knowledge base say about responding to an account-lockout incident?",
    ],
    "rag_inline": [
        # ~500-char synthetic config blob the model will be asked to summarise.
        "Summarise this firewall rules file in a sentence:\n\n"
        + "ACCEPT tcp -- anywhere anywhere tcp dpt:ssh\n"
        * 8
        + "REJECT tcp -- anywhere anywhere tcp dpt:telnet\n",
        "Summarise this access log:\n\n"
        + "192.0.2.1 - - [10/Oct/2025:13:55:36 +0000] \"GET /api/health HTTP/1.1\" 200 12\n"
        * 10,
        "Summarise this SLA:\n\n"
        + "Service availability target: 99.9%. "
        + "Incident response: P1 30min, P2 2h, P3 next business day. "
        * 5,
    ],
}
```

### Step 3: Commit

- [ ] No tests for the prompts module (it's data). Commit:

```bash
git add backend/tests/perf/__init__.py backend/tests/perf/prompts.py
git commit -m "feat(perf): fixed benchmark prompt set (5 classes, 3 prompts each)"
```

---

## Task 8 — Benchmark CLI

**Files:**
- Create: `backend/tests/perf/bench_llm.py`
- Create: `backend/tests/perf/results/.gitkeep`
- Modify: `backend/.gitignore`

### Step 1: Add gitignore entry + placeholder

```bash
mkdir -p backend/tests/perf/results
touch backend/tests/perf/results/.gitkeep
```

Append to `backend/.gitignore`:

```
# Per-run benchmark output (the .gitkeep is tracked; everything else isn't)
tests/perf/results/*
!tests/perf/results/.gitkeep
```

### Step 2: Write the bench script

`backend/tests/perf/bench_llm.py`:

```python
"""LLM perf benchmark harness.

Sends each prompt in tests/perf/prompts.py against a running Pryzm backend
N times. For each call, parses the `usage` block from the final SSE chunk
emitted by /analyze (see Task 6 in the Phase A plan). Aggregates min /
median / p95 / max for ttft_ms, duration_ms, tokens_per_sec per prompt
class. Prints a markdown table to stdout; optionally writes the same to a
file under tests/perf/results/ for later diff against the post-swap run.

Usage:
    cd backend
    ./venv/bin/python tests/perf/bench_llm.py \\
        --backend http://127.0.0.1:8000 \\
        --workspace personal \\
        --token "$(grep PRYZM_API_TOKEN ../.env | cut -d= -f2)" \\
        --repeats 3 \\
        --label ollama-baseline-2026-05-14
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

import httpx

from prompts import PROMPTS


def _percentile(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    k = (len(s) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _send_one(
    client: httpx.Client, backend: str, token: str, workspace: str, prompt: str
) -> dict | None:
    """Sends one prompt to /analyze, returns the usage dict from the final chunk
    (or None on parse / network failure)."""
    url = f"{backend}/analyze?workspace={workspace}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {"prompt": prompt, "session_id": None, "attachments": []}

    last_usage = None
    with client.stream("POST", url, json=body, headers=headers, timeout=180.0) as resp:
        resp.raise_for_status()
        for raw in resp.iter_lines():
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if obj.get("done") and isinstance(obj.get("usage"), dict):
                last_usage = obj["usage"]
    return last_usage


def _aggregate(records: list[dict]) -> dict:
    """records: a list of usage dicts. Returns aggregate stats."""
    if not records:
        return {"count": 0}
    ttfts = [r["ttft_ms"] for r in records]
    durs = [r["duration_ms"] for r in records]
    tps = [r["tokens_per_sec"] for r in records]
    return {
        "count": len(records),
        "ttft_ms_med": int(statistics.median(ttfts)),
        "ttft_ms_p95": int(_percentile(ttfts, 0.95)),
        "duration_ms_med": int(statistics.median(durs)),
        "duration_ms_p95": int(_percentile(durs, 0.95)),
        "tps_med": round(statistics.median(tps), 2),
        "tps_max": round(max(tps), 2),
    }


def _markdown_table(label: str, by_class: dict[str, dict]) -> str:
    lines = [
        f"# LLM Perf Benchmark — {label}",
        "",
        "| Prompt class | N | TTFT (ms) median | TTFT (ms) p95 | Duration (ms) median | Duration (ms) p95 | TPS median | TPS max |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for cls, stats in by_class.items():
        if stats["count"] == 0:
            lines.append(f"| {cls} | 0 | — | — | — | — | — | — |")
            continue
        lines.append(
            f"| {cls} | {stats['count']} | {stats['ttft_ms_med']} | {stats['ttft_ms_p95']} | "
            f"{stats['duration_ms_med']} | {stats['duration_ms_p95']} | "
            f"{stats['tps_med']} | {stats['tps_max']} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", default="http://127.0.0.1:8000")
    parser.add_argument("--workspace", default="personal")
    parser.add_argument("--token", required=True, help="PRYZM_API_TOKEN value")
    parser.add_argument("--repeats", type=int, default=3, help="N repeats per prompt")
    parser.add_argument("--label", required=True, help="Label for the results file (e.g. 'ollama-baseline')")
    args = parser.parse_args()

    by_class: dict[str, list[dict]] = {cls: [] for cls in PROMPTS}

    print(f"[bench_llm] backend={args.backend} workspace={args.workspace} repeats={args.repeats}")
    with httpx.Client(http2=False) as client:
        for cls, prompts in PROMPTS.items():
            for prompt in prompts:
                for i in range(args.repeats):
                    t0 = time.perf_counter()
                    try:
                        usage = _send_one(client, args.backend, args.token, args.workspace, prompt)
                    except Exception as e:
                        print(f"  [{cls}] prompt {prompt[:30]!r} run {i+1}: ERROR {e}")
                        continue
                    elapsed = time.perf_counter() - t0
                    if usage is None:
                        print(f"  [{cls}] prompt {prompt[:30]!r} run {i+1}: no usage block (elapsed={elapsed:.1f}s)")
                        continue
                    by_class[cls].append(usage)
                    print(
                        f"  [{cls}] run {i+1}: model={usage['model']} "
                        f"tokens={usage['completion_tokens']} ttft={usage['ttft_ms']}ms "
                        f"dur={usage['duration_ms']}ms tps={usage['tokens_per_sec']}"
                    )

    aggregated = {cls: _aggregate(records) for cls, records in by_class.items()}
    md = _markdown_table(args.label, aggregated)

    out_path = Path(__file__).parent / "results" / f"{args.label}.md"
    out_path.write_text(md)
    print()
    print(md)
    print(f"[bench_llm] wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Smoke the script with --help to confirm it parses**

```bash
cd backend && ./venv/bin/python tests/perf/bench_llm.py --help
```

Expected: argparse usage line printed cleanly.

- [ ] **Step 4: Commit**

```bash
cd ..  # back to repo root
git add backend/.gitignore backend/tests/perf/bench_llm.py backend/tests/perf/results/.gitkeep
git commit -m "feat(perf): bench_llm CLI for capturing per-class LLM perf snapshots"
```

---

## Task 9 — Run the Ollama baseline benchmark

**Files:**
- Create (artifact): `backend/tests/perf/results/ollama-baseline-2026-05-14.md`

### Step 1: Pre-flight

> Prerequisite: backend running, Ollama responsive, `gemma4:e4b` (or whatever the current default is) loaded.

```bash
curl -sf http://127.0.0.1:8000/health -o /dev/null && echo "backend ok" || echo "backend NOT ok"
```

### Step 2: Run the benchmark

```bash
cd /home/orbital/projects/pryzm/backend
./venv/bin/python tests/perf/bench_llm.py \
  --backend http://127.0.0.1:8000 \
  --workspace personal \
  --token "$(grep PRYZM_API_TOKEN ../.env | cut -d= -f2)" \
  --repeats 3 \
  --label ollama-baseline-2026-05-14
```

Expected: ~5 minutes total (15 prompts × 3 repeats × ~6s each on a warm model). Final stdout shows the markdown table; the file lands at `backend/tests/perf/results/ollama-baseline-2026-05-14.md`.

If individual runs print "ERROR" or "no usage block":
- Confirm the backend log shows the corresponding `llm.metric` line — if absent, `set_request_context` placement is wrong (re-check Task 5).
- Confirm the final SSE chunk includes `"usage":` — if absent, Task 6 wiring is wrong.

### Step 3: Commit the result file

```bash
cd /home/orbital/projects/pryzm
git add backend/tests/perf/results/ollama-baseline-2026-05-14.md
git commit -m "perf(baseline): Ollama run captured pre-llama-swap"
```

---

## Task 10 — Open Phase A PR

### Step 1: Push + create PR

```bash
git push -u origin refactor/llm-swap-phase-a-metrics

gh pr create --title "LLM Swap Phase A — per-request metrics + benchmark harness" --body "$(cat <<'EOF'
## Summary

- Adds \`core/llm_metrics.py\` — emits a single \`llm.metric\` log line per chat/generate call with token counts + nanosecond-precision timings from Ollama's response payload.
- Adds \`llm.embed_metric\` for embedding calls.
- Final \`/analyze\` SSE chunk now carries a \`usage\` block so the bench script can read per-request stats without log scraping.
- Adds \`backend/tests/perf/bench_llm.py\`, a CLI that runs a fixed 5-class prompt set against the live backend and prints a markdown comparison table.
- Captures the Ollama baseline at \`backend/tests/perf/results/ollama-baseline-2026-05-14.md\` for the Phase C diff.

## Test plan

- backend pytest: 79 passed (74 existing + 5 new for llm_metrics)
- benchmark runs end-to-end against current Ollama stack; markdown table written.

EOF
)"
```

### Step 2: Sync local main after merge

> Per the auto-merge memory, enable squash auto-merge:

```bash
gh pr merge --squash --auto
```

Then once merged:

```bash
git checkout main && git pull --ff-only origin main
```

---

## Self-Review Checklist

After completing all tasks, verify spec coverage:

- [x] **`llm.metric` log line per chat/generate** — Tasks 1, 2, 3.
- [x] **`llm.embed_metric` per embed** — Tasks 1, 4.
- [x] **Token counts from Ollama's native fields** — Task 1's helper extracts `prompt_eval_count` / `eval_count` / `*_duration`.
- [x] **TPS computed from `eval_count` / `eval_duration` (not penalised by prompt-eval time)** — Task 1.
- [x] **Workspace + session ids on each metric line** — Task 1 (contextvars), Task 5 (context set in router).
- [x] **`usage` block on final SSE chunk** — Task 6.
- [x] **Bench script CLI exists** — Tasks 7, 8.
- [x] **Five prompt classes (short_q, medium_q, code_task, tool_use, rag_inline)** — Task 7.
- [x] **Markdown output table** — Task 8.
- [x] **Baseline captured to results/** — Task 9.

Out of scope and explicitly NOT in this plan (per spec):

- No persistent metrics table (no DB migration).
- No `/api/metrics` endpoint.
- No frontend UI surfacing metrics.
- No histograms or rolling-window aggregations.
- No new dependencies.

---

## Plan Self-Review

Before handing off:

1. **Spec coverage:** Phase A in the spec maps task-by-task above. ✓
2. **Placeholder scan:** No "TBD" / "TODO" in tasks; the `2026-05-14` date placeholder in the result filename is the actual date the user runs the benchmark, so it's not a placeholder, it's a literal label. ✓
3. **Type consistency:** `emit_chat_metric` / `emit_embed_metric` / `set_request_context` / `get_last_chat_snapshot` names are used consistently across Tasks 1–6. ✓
