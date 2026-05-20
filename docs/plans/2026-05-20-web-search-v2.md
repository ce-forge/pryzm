# Web search v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the existing `web_search` tool to fetch full page contents for the top-K SearxNG hits, extract main content, and let the chat model write cited responses with inline `[N]` markers and a `**Sources**` footer.

**Architecture:** Single tool, upgraded in place. No new mode, no new toggle. The existing `web_search` mode gains a `tier_override="web"` hint that the engine consumes to route the synthesis turn to whatever chat model carries the `web` tag in the llama-swap catalog (E2B for v1, easily moved to a larger model later). The tool itself becomes async, fetches all URLs in parallel with a 25s wall-clock budget under the engine's `TOOL_TIMEOUT_SECONDS=30`, extracts content via trafilatura, and emits structured `### Source [N]: <title>` blocks for the model to cite. Per-source failures degrade gracefully. Frontend collapses the tool-result block to a compact "Searched: N sources" pill for `web_search` only.

**Tech Stack:** Python 3.12, FastAPI, async/await, httpx (already a dep), trafilatura (new dep), respx (new dev dep for httpx mocking in tests), Next.js 16 / React 19, Playwright (for smoke).

**Spec:** `docs/specs/2026-05-20-web-search-v2.md`

---

### Task 1: Foundation — dependencies and model tag

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `backend/requirements-dev.txt`
- Modify: `infra/llama-swap-config.yaml`

- [ ] **Step 1: Add trafilatura to requirements.txt**

Add the line in alphabetical order (after `psycopg2-binary` or wherever it fits — the file is sorted):

```
trafilatura==2.0.0
```

If a different patch version is the current stable on PyPI, use that; the major version 2 is what we want.

- [ ] **Step 2: Add respx to requirements-dev.txt**

Append:

```
respx==0.22.0
```

- [ ] **Step 3: Install the new deps into the backend venv**

Run from `/home/orbital/projects/pryzm/backend`:

```bash
./venv/bin/pip install -r requirements.txt -r requirements-dev.txt
```

Expected: `Successfully installed trafilatura-2.0.0 respx-0.22.0 ...` (plus transitive deps for trafilatura: `lxml`, `justext`, `dateparser`, `htmldate`, `courlan`). Should be wheel-installable; no compile step.

- [ ] **Step 4: Tag the small model with `web` in the llama-swap config**

In `infra/llama-swap-config.yaml`, change the `gemma-4-E2B-it` model entry's `tags` from the empty list to include `web`:

```yaml
  "gemma-4-E2B-it":
    cmd: |-
      /app/llama-server --port ${PORT}
      -hf bartowski/google_gemma-4-E2B-it-GGUF:Q4_K_M
      -ngl 99 --ctx-size 8192 --jinja --flash-attn on
    tags:
      - web
    groups:
    - always-on
```

- [ ] **Step 5: Reload llama-swap so the new tag is picked up**

```bash
docker compose kill -s HUP llama-swap
```

(HUP is enough for tag-only changes — see `reference_llama_swap_hup` memory. No model `cmd:` changed.)

- [ ] **Step 6: Restart the backend so the router rereads the catalog**

The backend reads `infra/llama-swap-config.yaml` at startup via `build_catalog_from_yaml`. Bounce uvicorn (kill the existing process; the dev `--reload` only watches `.py` files, not the yaml).

```bash
ss -ltnp 2>/dev/null | grep ':8000\b'
# Find the python3/uvicorn pid and:
kill <pid>
cd /home/orbital/projects/pryzm/backend && ./venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --reload --reload-delay 2 &
```

- [ ] **Step 7: Commit**

```bash
git add backend/requirements.txt backend/requirements-dev.txt infra/llama-swap-config.yaml
git commit -m "deps: add trafilatura + respx; tag gemma-4-E2B-it with \`web\`"
```

---

### Task 2: Router exposes `web_capable_model()`

**Files:**
- Test: `backend/tests/test_llm_router.py` (create if absent — or extend if it exists)
- Modify: `backend/core/llm_router.py`

- [ ] **Step 1: Check whether the test file exists**

```bash
ls /home/orbital/projects/pryzm/backend/tests/test_llm_router.py 2>/dev/null && echo EXISTS || echo MISSING
```

If MISSING, create with the standard header:

```python
"""Unit tests for the heuristic LLM router (backend/core/llm_router.py)."""
from __future__ import annotations

import pytest

from core.llm_router import HeuristicRouter
```

- [ ] **Step 2: Write the failing test for `web_capable_model()`**

Append to `backend/tests/test_llm_router.py`:

```python
def test_web_capable_model_returns_first_web_tagged_chat_model():
    """A model carrying the `web` tag is returned. Embedding models are skipped
    even if mistakenly carrying the tag."""
    catalog = {
        "small-2b": {"web"},
        "large-26b": {"reasoning"},
        "embed": {"embedding", "web"},
    }
    router = HeuristicRouter(catalog)
    assert router.web_capable_model() == "small-2b"


def test_web_capable_model_none_when_no_model_tagged():
    """No `web` tag anywhere → None; caller falls back to the heuristic pick."""
    catalog = {
        "small-2b": set(),
        "large-26b": {"reasoning", "code"},
    }
    router = HeuristicRouter(catalog)
    assert router.web_capable_model() is None
```

- [ ] **Step 3: Run the test and verify it fails**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest tests/test_llm_router.py -v
```

Expected: `AttributeError: 'HeuristicRouter' object has no attribute 'web_capable_model'`.

- [ ] **Step 4: Implement `web_capable_model()`**

Open `backend/core/llm_router.py`. Find the `vision_capable_model` method (around line 85-96). Add an identically-shaped `web_capable_model` method immediately after it:

```python
def web_capable_model(self) -> str | None:
    """First chat model carrying the `web` tag, or None if no catalog
    entry has it. Used by the web_search mode to route the synthesis
    turn to a model designated for research output. Mirrors
    vision_capable_model — tag-driven so the YAML stays the single
    source of truth for which model handles which workload."""
    for model_id, tags in self.catalog.items():
        if "web" in tags and "embedding" not in tags:
            return model_id
    return None
```

- [ ] **Step 5: Run the tests and verify they pass**

```bash
./venv/bin/pytest tests/test_llm_router.py -v
```

Expected: both tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/core/llm_router.py backend/tests/test_llm_router.py
git commit -m "router: add web_capable_model() tag lookup"
```

---

### Task 3: web_search mode sets `tier_override="web"`

**Files:**
- Modify: `backend/tests/test_modes.py`
- Modify: `backend/core/modes.py:141-145`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_modes.py` (the autouse fixture there already snapshot-restores the modes registry, so the assertion is safe):

```python
def test_web_search_mode_carries_web_tier_override():
    """The shipped web_search mode declares tier_override='web' so the engine
    can route the synthesis turn to a web-tagged model. Round-trips through
    apply_modes."""
    @tool(properties={}, required=[], workspaces=["it_copilot"])
    def web_search() -> str:  # noqa: ARG001 — minimal stub for tool_set assembly
        return ""

    # Re-import to pick up the registered mode with the new field.
    from core import modes as modes_module
    assert modes_module.MODES["web_search"].tier_override == "web"

    tool_set = _make_tool_set(["web_search"])
    _, _, tier_hint = apply_modes(tool_set, "system", ["web_search"])
    assert tier_hint == "web"
```

- [ ] **Step 2: Run the test and verify it fails**

```bash
./venv/bin/pytest tests/test_modes.py::test_web_search_mode_carries_web_tier_override -v
```

Expected: `AssertionError: assert None == 'web'` — the field defaults to `None`.

- [ ] **Step 3: Update the mode registration**

In `backend/core/modes.py`, find the `register_mode(Mode(name="web_search", ...))` call at the bottom of the file (around line 141-145). Add `tier_override="web"`:

```python
register_mode(Mode(
    name="web_search",
    force_tools=["web_search"],
    gates_tools=["web_search"],
    tier_override="web",
))
```

- [ ] **Step 4: Run the test and verify it passes**

```bash
./venv/bin/pytest tests/test_modes.py::test_web_search_mode_carries_web_tier_override -v
```

Expected: pass.

- [ ] **Step 5: Also run the full modes test file to make sure nothing else broke**

```bash
./venv/bin/pytest tests/test_modes.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/core/modes.py backend/tests/test_modes.py
git commit -m "modes: web_search mode gains tier_override=\"web\""
```

---

### Task 4: Engine consumes the tier hint

**Files:**
- Modify: `backend/tests/test_ai_engine.py` (or create if no good home — check first)
- Modify: `backend/core/ai_engine.py:316-330` (the router pick block)

- [ ] **Step 1: Find the right test file**

```bash
ls /home/orbital/projects/pryzm/backend/tests/test_ai_engine.py 2>/dev/null && echo EXISTS || echo MISSING
grep -rln "stream_chat\|tier_hint" /home/orbital/projects/pryzm/backend/tests/ 2>/dev/null | head
```

If a coherent ai_engine test file exists, append to it; otherwise create `backend/tests/test_ai_engine_routing.py` (narrow scope is fine — it isolates this concern from the rest of the engine).

- [ ] **Step 2: Write the failing test**

The test exercises the override directly without driving the whole `stream_chat` generator (which needs an LLM and DB). Extract the override logic into a small helper that takes `(router, tier_hint, default_model_id, default_reason)` and returns `(model_id, reason)`. Test the helper.

In the test file:

```python
"""Tests for the tier-hint override path in the chat engine — when a mode
declares a tag-based tier override, the engine picks the tagged model instead
of the router's heuristic choice."""
from __future__ import annotations

from core.ai_engine import _resolve_routed_model
from core.llm_router import HeuristicRouter


def test_resolve_routed_model_uses_web_tagged_model_when_hint_is_web():
    catalog = {"small-2b": {"web"}, "large-26b": {"reasoning"}}
    router = HeuristicRouter(catalog)
    model_id, reason = _resolve_routed_model(
        router, tier_hint="web", default_model_id="large-26b", default_reason="default",
    )
    assert model_id == "small-2b"
    assert reason == "mode_tier_override:web"


def test_resolve_routed_model_falls_back_when_no_tagged_model():
    catalog = {"small-2b": set(), "large-26b": {"reasoning"}}
    router = HeuristicRouter(catalog)
    model_id, reason = _resolve_routed_model(
        router, tier_hint="web", default_model_id="large-26b", default_reason="default",
    )
    assert model_id == "large-26b"
    assert reason == "default"


def test_resolve_routed_model_passthrough_when_no_hint():
    catalog = {"small-2b": {"web"}, "large-26b": {"reasoning"}}
    router = HeuristicRouter(catalog)
    model_id, reason = _resolve_routed_model(
        router, tier_hint=None, default_model_id="large-26b", default_reason="complex_verb",
    )
    assert model_id == "large-26b"
    assert reason == "complex_verb"
```

- [ ] **Step 3: Run the test and verify it fails**

```bash
./venv/bin/pytest tests/test_ai_engine_routing.py -v
```

Expected: `ImportError: cannot import name '_resolve_routed_model' from 'core.ai_engine'`.

- [ ] **Step 4: Add the helper to ai_engine.py**

In `backend/core/ai_engine.py`, near the existing `from core.llm_router import ...` imports at the top, add a module-level helper. Place it above `stream_chat`:

```python
def _resolve_routed_model(
    router,
    tier_hint: str | None,
    default_model_id: str,
    default_reason: str,
) -> tuple[str, str]:
    """Apply a mode-declared tier override on top of the router's heuristic pick.

    `tier_hint` is the third element returned by `apply_modes`. Today only the
    web_search mode sets one (`tier_override="web"`). Lookup is generic:
    `{hint}` → `router.{hint}_capable_model()` if the method exists. Falls back
    to the heuristic pick when no model carries the tag or no hint is supplied.

    Returns `(model_id, reason)` — reason is the keyword emitted to the route
    audit event so we can tell heuristic picks from mode overrides in logs.
    """
    if tier_hint is None:
        return default_model_id, default_reason
    lookup = getattr(router, f"{tier_hint}_capable_model", None)
    if lookup is None:
        return default_model_id, default_reason
    candidate = lookup()
    if candidate is None:
        return default_model_id, default_reason
    return candidate, f"mode_tier_override:{tier_hint}"
```

- [ ] **Step 5: Wire the helper into the router-pick block**

In the same file, find the block around lines 316-330 (the `if tier is None: ... router.pick(...) ... emit_route(...)` block) and update it so the helper sits between the router call and the `emit_route` call:

```python
    router = get_router()
    if tier is None:
        last_user = recent_messages[-1] if recent_messages and recent_messages[-1].get("role") == "user" else None
        prompt_for_routing = (last_user or {}).get("content", "") or ""
        attachments_for_routing = ["file"] if "[Attached_File:" in prompt_for_routing else []
        history_for_routing = recent_messages[:-1] if last_user else recent_messages
        routed_model, tier, route_reason = router.pick(
            prompt_for_routing, history_for_routing, attachments_for_routing,
        )
        routed_model, route_reason = _resolve_routed_model(
            router, tier_hint_from_modes, routed_model, route_reason,
        )
        emit_route(
            model=routed_model,
            tier=tier.value,
            reason=route_reason,
            prompt_len=len(prompt_for_routing),
        )
    else:
        routed_model = router.small if tier is Tier.SMALL else router.large
```

Note: the override changes `routed_model` but not `tier`. `tier` is still used downstream for non-routing concerns (e.g. ctx-size adjustments). That's correct — the override means "use this specific model" not "use a different tier policy."

- [ ] **Step 6: Run the routing tests and verify they pass**

```bash
./venv/bin/pytest tests/test_ai_engine_routing.py -v
```

Expected: all three pass.

- [ ] **Step 7: Run the full backend suite to verify nothing else broke**

```bash
./venv/bin/pytest -q --ignore=tests/test_image_upload.py --ignore=tests/test_upload_sse.py
```

(Those two ignores follow the pattern in `2026-05-18-session-handoff.md` — 7 pre-existing failures unrelated to this work.)

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add backend/core/ai_engine.py backend/tests/test_ai_engine_routing.py
git commit -m "engine: consume mode tier_override; web_search routes synthesis to web-tagged model"
```

---

### Task 5: Sentence-aware truncation helper

**Files:**
- Test: `backend/tests/test_web_search_truncate.py` (new, narrow)
- Create: `backend/tools/_web_truncate.py`

We split this into its own module because it's pure-function and easy to test in isolation, and keeps the main `tools/web.py` rewrite focused on orchestration.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_web_search_truncate.py`:

```python
"""Unit tests for the sentence-aware truncation used by the web_search tool's
per-page body cap. The helper walks sentence boundaries and stops before
exceeding the char cap; a single sentence longer than the cap is hard-cut at
the cap with an ellipsis."""
from __future__ import annotations

from tools._web_truncate import truncate_to_sentences


def test_returns_unchanged_when_under_cap():
    body = "First sentence. Second sentence."
    assert truncate_to_sentences(body, max_chars=200) == body


def test_drops_trailing_sentence_to_stay_under_cap():
    body = "Sentence one is here. Sentence two is here. Sentence three is here."
    out = truncate_to_sentences(body, max_chars=45)
    assert out == "Sentence one is here. Sentence two is here."
    assert len(out) <= 45


def test_hard_cuts_a_single_oversized_sentence():
    body = "A" * 200 + ". Short follow-up."
    out = truncate_to_sentences(body, max_chars=50)
    assert out.endswith("…")
    assert len(out) <= 50


def test_handles_question_and_exclamation_endings():
    body = "Question one? Answer two! Statement three. Statement four."
    out = truncate_to_sentences(body, max_chars=30)
    assert out == "Question one? Answer two!"


def test_empty_input_returns_empty():
    assert truncate_to_sentences("", max_chars=100) == ""
    assert truncate_to_sentences("   ", max_chars=100) == "   "
```

- [ ] **Step 2: Run the tests and verify they fail**

```bash
./venv/bin/pytest tests/test_web_search_truncate.py -v
```

Expected: `ModuleNotFoundError: No module named 'tools._web_truncate'`.

- [ ] **Step 3: Implement the helper**

Create `backend/tools/_web_truncate.py`:

```python
"""Sentence-aware truncation for web_search page bodies.

The web_search tool caps each fetched page's extracted text at a configurable
char limit so the synthesis prompt stays inside the model's context window.
We prefer sentence-boundary cuts so the model never has to read a half-finished
sentence; if a single sentence already exceeds the cap, we hard-cut with an
ellipsis so the budget is honored.
"""
from __future__ import annotations

import re


_SENTENCE_END = re.compile(r'(?<=[.!?])\s+')


def truncate_to_sentences(text: str, max_chars: int) -> str:
    """Return at most `max_chars` chars of `text`, cut on a sentence boundary
    when possible. A single sentence longer than `max_chars` is hard-cut and
    suffixed with `…`. Whitespace-only or empty input is returned unchanged."""
    if not text or not text.strip():
        return text
    if len(text) <= max_chars:
        return text

    sentences = _SENTENCE_END.split(text)
    out: list[str] = []
    used = 0
    for sent in sentences:
        # +1 for the separator we'll join with (space).
        addition = len(sent) + (1 if out else 0)
        if used + addition > max_chars:
            break
        out.append(sent)
        used += addition

    if out:
        return " ".join(out)

    # Single oversized sentence — hard-cut with ellipsis.
    return text[: max_chars - 1].rstrip() + "…"
```

- [ ] **Step 4: Run the tests and verify they pass**

```bash
./venv/bin/pytest tests/test_web_search_truncate.py -v
```

Expected: all five pass.

- [ ] **Step 5: Commit**

```bash
git add backend/tools/_web_truncate.py backend/tests/test_web_search_truncate.py
git commit -m "tools: add sentence-aware truncation helper for web_search bodies"
```

---

### Task 6: Per-URL fetch + extract helper

**Files:**
- Test: `backend/tests/test_web_search_fetch.py` (new)
- Create: `backend/tools/_web_fetch.py`

Same isolation rationale as Task 5. The orchestrator in Task 7 composes these.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_web_search_fetch.py`:

```python
"""Unit tests for the per-URL fetch+extract helper used by web_search.

Mocks httpx via respx so no real HTTP traffic happens. Each test isolates one
failure mode or the happy path; the orchestrator in tools/web.py composes them.
"""
from __future__ import annotations

import httpx
import pytest
import respx

from tools._web_fetch import FetchResult, fetch_and_extract


@pytest.mark.asyncio
async def test_happy_path_returns_extracted_body():
    html = (
        "<html><body><article>"
        "<p>This is the article body. It is long enough to extract.</p>"
        "</article></body></html>"
    )
    async with httpx.AsyncClient() as client:
        with respx.mock:
            respx.get("https://example.com/a").mock(
                return_value=httpx.Response(200, text=html, headers={"content-type": "text/html"})
            )
            result = await fetch_and_extract(client, "https://example.com/a", per_request_timeout=2)
    assert result.ok
    assert "article body" in result.body
    assert result.failure_reason is None


@pytest.mark.asyncio
async def test_non_html_content_type_returns_non_html_failure():
    async with httpx.AsyncClient() as client:
        with respx.mock:
            respx.get("https://example.com/pdf").mock(
                return_value=httpx.Response(200, text="%PDF...", headers={"content-type": "application/pdf"})
            )
            result = await fetch_and_extract(client, "https://example.com/pdf", per_request_timeout=2)
    assert not result.ok
    assert result.failure_reason == "non-html"


@pytest.mark.asyncio
async def test_403_returns_status_failure():
    async with httpx.AsyncClient() as client:
        with respx.mock:
            respx.get("https://example.com/locked").mock(
                return_value=httpx.Response(403, text="Forbidden")
            )
            result = await fetch_and_extract(client, "https://example.com/locked", per_request_timeout=2)
    assert not result.ok
    assert result.failure_reason == "403"


@pytest.mark.asyncio
async def test_empty_extraction_returns_empty_failure():
    """trafilatura returns empty for pages with no usable main content."""
    async with httpx.AsyncClient() as client:
        with respx.mock:
            respx.get("https://example.com/shell").mock(
                return_value=httpx.Response(200, text="<html><body></body></html>", headers={"content-type": "text/html"})
            )
            result = await fetch_and_extract(client, "https://example.com/shell", per_request_timeout=2)
    assert not result.ok
    assert result.failure_reason == "empty"


@pytest.mark.asyncio
async def test_timeout_returns_timeout_failure():
    async with httpx.AsyncClient() as client:
        with respx.mock:
            respx.get("https://example.com/slow").mock(side_effect=httpx.TimeoutException("timed out"))
            result = await fetch_and_extract(client, "https://example.com/slow", per_request_timeout=2)
    assert not result.ok
    assert result.failure_reason == "timeout"


@pytest.mark.asyncio
async def test_other_request_errors_return_error_failure():
    async with httpx.AsyncClient() as client:
        with respx.mock:
            respx.get("https://example.com/boom").mock(side_effect=httpx.ConnectError("nope"))
            result = await fetch_and_extract(client, "https://example.com/boom", per_request_timeout=2)
    assert not result.ok
    assert result.failure_reason == "error"
```

- [ ] **Step 2: Run the tests and verify they fail**

```bash
./venv/bin/pytest tests/test_web_search_fetch.py -v
```

Expected: `ModuleNotFoundError: No module named 'tools._web_fetch'`.

- [ ] **Step 3: Implement the helper**

Create `backend/tools/_web_fetch.py`:

```python
"""Single-URL fetch + extract for the web_search tool.

Wraps an httpx GET with content-type guarding, trafilatura extraction, and a
small enum of failure reasons. The orchestrator in tools/web.py composes many
of these in parallel under a wall-clock budget.
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx
import trafilatura


@dataclass(frozen=True)
class FetchResult:
    """Outcome of a single URL fetch.

    On success, `body` carries the extracted main text. On failure, `body` is
    empty and `failure_reason` is one of: `timeout`, a 3-char HTTP status code
    like `"403"`, `non-html`, `empty`, or `error` (catch-all for connect /
    transport / unexpected errors)."""
    url: str
    ok: bool
    body: str = ""
    failure_reason: str | None = None


async def fetch_and_extract(
    client: httpx.AsyncClient,
    url: str,
    per_request_timeout: float,
) -> FetchResult:
    """Fetch one URL, validate content type, run trafilatura. Never raises —
    every failure mode maps to a populated `failure_reason`."""
    try:
        resp = await client.get(url, timeout=per_request_timeout, follow_redirects=True)
    except httpx.TimeoutException:
        return FetchResult(url=url, ok=False, failure_reason="timeout")
    except httpx.RequestError:
        return FetchResult(url=url, ok=False, failure_reason="error")

    if resp.status_code >= 400:
        return FetchResult(url=url, ok=False, failure_reason=str(resp.status_code))

    content_type = (resp.headers.get("content-type") or "").lower()
    if not (content_type.startswith("text/html") or "xhtml" in content_type):
        return FetchResult(url=url, ok=False, failure_reason="non-html")

    extracted = trafilatura.extract(
        resp.text,
        include_comments=False,
        include_tables=True,
        favor_recall=False,
    )
    if not extracted or not extracted.strip():
        return FetchResult(url=url, ok=False, failure_reason="empty")

    return FetchResult(url=url, ok=True, body=extracted.strip())
```

- [ ] **Step 4: Run the tests and verify they pass**

```bash
./venv/bin/pytest tests/test_web_search_fetch.py -v
```

Expected: all six pass.

- [ ] **Step 5: Commit**

```bash
git add backend/tools/_web_fetch.py backend/tests/test_web_search_fetch.py
git commit -m "tools: add per-URL fetch+extract helper with failure-reason classification"
```

---

### Task 7: Rewrite web_search orchestration

**Files:**
- Modify: `backend/tests/test_web_search.py` (existing tests need updating to the new shape)
- Modify: `backend/tools/web.py` (full rewrite)

This is the biggest task. The existing test file tests the old snippet-only shape and will need most cases rewritten.

- [ ] **Step 1: Read the existing test file to know what to replace**

```bash
cat /home/orbital/projects/pryzm/backend/tests/test_web_search.py
```

Note the structure (top-level docstring, `_mock_searx_response` helper, individual test functions).

- [ ] **Step 2: Write the new tests**

Replace the entire contents of `backend/tests/test_web_search.py` with:

```python
"""Unit tests for the web_search tool (SearxNG + page fetch + structured output).

SearxNG is still mocked via the requests library; page fetches are mocked via
respx so the new async fetch path doesn't touch the network. End-to-end
exercise against a running SearxNG + the live web is the manual smoke step on
the PR.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest
import requests
import respx


def _mock_searx_response(results: list[dict] | None = None, status: int = 200) -> MagicMock:
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status
    if status >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(f"{status} error")
    else:
        resp.raise_for_status.return_value = None
    resp.json.return_value = {"results": results if results is not None else []}
    return resp


def _fake_hits(n: int) -> list[dict]:
    return [
        {"title": f"Title {i}", "url": f"https://example.com/p{i}", "content": f"snippet {i}"}
        for i in range(1, n + 1)
    ]


def _ok_html(body_text: str) -> httpx.Response:
    return httpx.Response(
        200,
        text=f"<html><body><article><p>{body_text}</p></article></body></html>",
        headers={"content-type": "text/html"},
    )


@pytest.mark.asyncio
async def test_returns_structured_source_blocks_for_each_fetched_page():
    from tools.web import web_search

    with patch("tools.web.requests.get") as mock_get, respx.mock:
        mock_get.return_value = _mock_searx_response(_fake_hits(3))
        respx.get("https://example.com/p1").mock(return_value=_ok_html("Article one content."))
        respx.get("https://example.com/p2").mock(return_value=_ok_html("Article two content."))
        respx.get("https://example.com/p3").mock(return_value=_ok_html("Article three content."))

        out = await web_search("anything", num_results=3)

    assert "### Source [1]: Title 1" in out
    assert "https://example.com/p1" in out
    assert "Article one content." in out
    assert "### Source [2]: Title 2" in out
    assert "### Source [3]: Title 3" in out


@pytest.mark.asyncio
async def test_failed_sources_listed_in_footer_others_still_returned():
    from tools.web import web_search

    with patch("tools.web.requests.get") as mock_get, respx.mock:
        mock_get.return_value = _mock_searx_response(_fake_hits(3))
        respx.get("https://example.com/p1").mock(return_value=_ok_html("Body one."))
        respx.get("https://example.com/p2").mock(return_value=httpx.Response(403, text="nope"))
        respx.get("https://example.com/p3").mock(side_effect=httpx.TimeoutException("slow"))

        out = await web_search("anything", num_results=3)

    assert "### Source [1]: Title 1" in out
    # Failed sources don't get numbered blocks.
    assert "### Source [2]" not in out
    assert "### Source [3]" not in out
    assert "**Failed sources**" in out
    assert "https://example.com/p2 — 403" in out
    assert "https://example.com/p3 — timeout" in out


@pytest.mark.asyncio
async def test_all_fail_returns_single_line_error():
    from tools.web import web_search

    with patch("tools.web.requests.get") as mock_get, respx.mock:
        mock_get.return_value = _mock_searx_response(_fake_hits(2))
        respx.get("https://example.com/p1").mock(return_value=httpx.Response(403))
        respx.get("https://example.com/p2").mock(side_effect=httpx.TimeoutException("slow"))

        out = await web_search("anything", num_results=2)

    assert "### Source" not in out
    assert "none could be fetched" in out


@pytest.mark.asyncio
async def test_no_searxng_results_returns_no_results_message():
    from tools.web import web_search

    with patch("tools.web.requests.get") as mock_get:
        mock_get.return_value = _mock_searx_response([])
        out = await web_search("zzzz no hits")

    assert "No results for" in out


@pytest.mark.asyncio
async def test_searxng_unreachable_returns_failure_message():
    from tools.web import web_search

    with patch("tools.web.requests.get") as mock_get:
        mock_get.side_effect = requests.ConnectionError("refused")
        out = await web_search("anything")

    assert "Web search failed" in out


@pytest.mark.asyncio
async def test_num_results_clamped_at_eight():
    from tools.web import web_search

    with patch("tools.web.requests.get") as mock_get, respx.mock:
        mock_get.return_value = _mock_searx_response(_fake_hits(10))
        for i in range(1, 9):
            respx.get(f"https://example.com/p{i}").mock(return_value=_ok_html(f"body {i}"))

        out = await web_search("anything", num_results=20)

    # 9th and 10th hits never get fetched.
    assert "### Source [8]" in out
    assert "### Source [9]" not in out
    # Verify the SearxNG call asked for at most 8 — the tool caps before calling.
    call_args = mock_get.call_args
    assert call_args is not None
    # Either via num_results param or by slicing — tool implementation choice;
    # either way, no 9+ in the output is the contract.


@pytest.mark.asyncio
async def test_body_is_truncated_to_max_chars():
    from tools.web import web_search

    long_body = "Sentence. " * 1000  # ~10K chars
    with patch("tools.web.requests.get") as mock_get, respx.mock:
        mock_get.return_value = _mock_searx_response(_fake_hits(1))
        respx.get("https://example.com/p1").mock(return_value=_ok_html(long_body))

        out = await web_search("anything", num_results=1)

    # Extracted body inside the Source block should not exceed ~6000 chars.
    # The block has small surrounding boilerplate so we check the body line
    # contains "Sentence." many times but the whole output stays bounded.
    assert len(out) < 6500
    assert "Sentence." in out
```

- [ ] **Step 3: Run the tests and verify they fail**

```bash
./venv/bin/pytest tests/test_web_search.py -v
```

Expected: all fail with various errors (the existing `web_search` is sync and snippet-only).

- [ ] **Step 4: Rewrite `tools/web.py`**

Replace the entire contents of `backend/tools/web.py` with:

```python
"""Web search tool — SearxNG + per-page fetch + extraction.

The tool calls a locally-hosted SearxNG instance for the top-K hits, then
fetches each URL in parallel and extracts main content via trafilatura. Output
is a sequence of structured `### Source [N]: <title>` blocks for the chat
model to cite. Per-source failures (timeout, 4xx, 5xx, non-HTML, empty
extraction) are listed in a `**Failed sources**` footer so the model can
caveat without aborting the turn.

Wall-clock budget for the fetch loop is 25s — under the engine's
`TOOL_TIMEOUT_SECONDS=30` so the inner budget always trips first and the tool
returns a partial result rather than getting cancelled by the outer guard.
"""
from __future__ import annotations

import asyncio

import httpx
import requests

from config import settings
from tools._web_fetch import FetchResult, fetch_and_extract
from tools._web_truncate import truncate_to_sentences
from .registry import tool


_MAX_RESULTS = 8
_DEFAULT_RESULTS = 5
_PER_REQUEST_TIMEOUT_S = 8.0
_FETCH_WALL_CLOCK_S = 25.0
_MAX_CHARS_PER_PAGE = 6000


WEB_SEARCH_DIRECTIVE = (
    "Use `web_search` for factual questions whose answer may have changed since "
    "training (current events, recent vendor releases, newly-published docs, "
    "news). Do NOT use it for questions answerable from local knowledge-base "
    "documents or general background knowledge.\n"
    "Results are returned as one or more `### Source [N]: <title>` blocks, each "
    "containing the source URL on its own line and an extracted page body below. "
    "When writing your reply, cite every factual claim by appending `[N]` "
    "referring to the source index. End your reply with a `**Sources**` section "
    "listing each cited source as `[N] <URL>`. Do not cite sources you did not "
    "use."
)


@tool(
    properties={
        "query": {
            "type": "string",
            "description": "The search query — natural language is fine.",
        },
        "num_results": {
            "type": "integer",
            "description": (
                "How many top hits to fetch and read (default 5, max 8). "
                "Each adds one page-fetch round to the wall-clock budget."
            ),
        },
    },
    required=["query"],
    workspaces=["it_copilot", "personal"],
    system_prompt_directive=WEB_SEARCH_DIRECTIVE,
)
async def web_search(query: str, num_results: int = _DEFAULT_RESULTS) -> str:
    """Search the web via SearxNG, fetch the top hits, and return their extracted
    main content as structured per-source blocks ready for the model to cite."""
    capped = max(1, min(num_results, _MAX_RESULTS))

    # SearxNG call stays synchronous (requests library) — it's a single fast
    # local call and changing it to httpx would buy nothing here.
    try:
        resp = requests.get(
            f"{settings.SEARXNG_URL}/search",
            params={"q": query, "format": "json", "language": "en"},
            timeout=settings.TOOL_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException as exc:
        return f"Web search failed: {exc}"

    hits = (payload.get("results") or [])[:capped]
    if not hits:
        return f"No results for {query!r}."

    urls_titles = [(h.get("url", ""), h.get("title", "(no title)")) for h in hits]

    # Fetch all URLs in parallel under a single wall-clock budget. asyncio.wait_for
    # cancels the gather on timeout — for partial results we'd need to handle this
    # case, but with the engine's outer TOOL_TIMEOUT_SECONDS=30 and our 25s inner,
    # the typical case is "all done in well under 25s." Mark URLs that didn't
    # come back as `timeout` on cancellation.
    results: list[FetchResult] = []
    async with httpx.AsyncClient(
        headers={"user-agent": "Pryzm/1.0 (+self-hosted IT copilot)"},
        timeout=_PER_REQUEST_TIMEOUT_S,
    ) as client:
        try:
            results = await asyncio.wait_for(
                asyncio.gather(
                    *(fetch_and_extract(client, url, _PER_REQUEST_TIMEOUT_S) for url, _ in urls_titles)
                ),
                timeout=_FETCH_WALL_CLOCK_S,
            )
        except asyncio.TimeoutError:
            # Whole gather cancelled — treat everything as timeout. (Future
            # improvement: shield individual fetches and collect partials.)
            results = [FetchResult(url=url, ok=False, failure_reason="timeout") for url, _ in urls_titles]

    successes: list[tuple[str, str, str]] = []  # (title, url, body)
    failures: list[tuple[str, str]] = []  # (url, reason)
    for (url, title), fr in zip(urls_titles, results):
        if fr.ok:
            body = truncate_to_sentences(fr.body, _MAX_CHARS_PER_PAGE)
            successes.append((title, url, body))
        else:
            failures.append((url, fr.failure_reason or "error"))

    if not successes:
        reason_counts: dict[str, int] = {}
        for _, reason in failures:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
        summary = ", ".join(f"{n}× {r}" for r, n in sorted(reason_counts.items()))
        return (
            f"Web search returned {len(hits)} results but none could be fetched. "
            f"Reasons: {summary}."
        )

    blocks: list[str] = []
    for i, (title, url, body) in enumerate(successes, 1):
        blocks.append(f"### Source [{i}]: {title}\n{url}\n\n{body}")

    out = "\n\n".join(blocks)

    if failures:
        failure_lines = "\n".join(f"- {url} — {reason}" for url, reason in failures)
        out += f"\n\n**Failed sources**\n{failure_lines}"

    return out
```

- [ ] **Step 5: Run the tests and verify they pass**

```bash
./venv/bin/pytest tests/test_web_search.py tests/test_web_search_truncate.py tests/test_web_search_fetch.py -v
```

Expected: all pass.

- [ ] **Step 6: Run the full backend suite to verify nothing else broke**

```bash
./venv/bin/pytest -q --ignore=tests/test_image_upload.py --ignore=tests/test_upload_sse.py
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add backend/tools/web.py backend/tests/test_web_search.py
git commit -m "tools(web): rewrite for parallel fetch + trafilatura extraction + structured source blocks"
```

---

### Task 8: Verify the new tool directive renders correctly

**Files:**
- Modify: `backend/tests/test_tool_registry.py` (or wherever `render_tool_directives` is tested — look first)

The new `WEB_SEARCH_DIRECTIVE` was set in Task 7. This task adds a targeted test ensuring it round-trips through `render_tool_directives` into the `== AVAILABLE TOOLS ==` block.

- [ ] **Step 1: Find the existing directive-rendering tests**

```bash
grep -rln "render_tool_directives" /home/orbital/projects/pryzm/backend/tests/ 2>/dev/null
```

If `test_tool_registry.py` exists, add to it. Otherwise create a small `test_web_search_directive.py` next to the others.

- [ ] **Step 2: Write the test**

Append (or create as new file):

```python
def test_web_search_directive_includes_citation_rules():
    """The new web_search tool directive instructs the model to cite each
    factual claim with [N] and end with a **Sources** footer. Verify both
    pieces appear in the rendered AVAILABLE TOOLS block."""
    from tools.registry import build_tool_set, render_tool_directives
    from types import SimpleNamespace

    workspace = SimpleNamespace(enabled_tools=["web_search"], tool_config={})
    rendered = render_tool_directives(build_tool_set(workspace))

    assert "web_search" in rendered
    assert "[N]" in rendered
    assert "**Sources**" in rendered
```

- [ ] **Step 3: Run the test and verify it passes**

```bash
./venv/bin/pytest tests/test_web_search_directive.py -v
# or wherever you put it
```

Expected: pass.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_web_search_directive.py
git commit -m "test: web_search tool directive includes citation rules"
```

---

### Task 9: Enrich the `chat.web_search` audit payload

**Files:**
- Modify: `backend/core/ai_engine.py:615-629` (the audit-emit block for web_search)
- Modify: `backend/tools/web.py` (add a small "stats" return path)
- Modify: `backend/tests/test_audit_chat_events.py` (extend the web_search case)

The cleanest path: the tool returns the markdown result as today, but also stashes its observability stats on a thread-local or module-level dict the engine reads after the call. Simpler alternative: have the tool return a `(markdown, stats)` tuple — but that breaks the `@tool` ABI (return type is `str`). We'll use a module-level `_last_stats` dict keyed by no key (single-flight per process is fine since the engine reads stats immediately after the call returns), then add a small accessor.

This is a pragmatic shortcut. A proper fix is to extend the `@tool` decorator with optional observability metadata; that's out of scope.

- [ ] **Step 1: Add `import time` to the top of tools/web.py**

In the imports block at the top of `backend/tools/web.py`, add a `time` import alongside the others:

```python
import asyncio
import time

import httpx
import requests
```

- [ ] **Step 2: Extend tools/web.py with the stats stash**

In `backend/tools/web.py`, add a module-level dict and populate it before each return path. After the `_MAX_CHARS_PER_PAGE = 6000` line, add:

```python
# Per-call stats stash for the engine's audit emission. The engine reads
# `get_last_stats()` immediately after each web_search call. Single-flight
# per process — concurrent web_search calls would race, but the engine
# serializes tool calls inside a single chat turn so this is safe today.
_LAST_STATS: dict = {}


def get_last_stats() -> dict:
    """Return the stats dict from the most recent web_search call."""
    return dict(_LAST_STATS)


def _set_stats(**kwargs) -> None:
    _LAST_STATS.clear()
    _LAST_STATS.update(kwargs)
```

Then inside `web_search`, populate stats at every return point. After the `hits = ...` line:

```python
    _set_stats(
        k_requested=capped,
        k_returned_by_searxng=len(hits),
        k_fetched_ok=0,
        k_failed=0,
        failure_reasons={},
        fetch_wall_clock_ms=0,
        extracted_bytes_total=0,
    )
```

And add timing + final counts around the gather. Replace the `async with httpx.AsyncClient(...) as client:` block with:

```python
    fetch_t0 = time.monotonic()
    async with httpx.AsyncClient(
        headers={"user-agent": "Pryzm/1.0 (+self-hosted IT copilot)"},
        timeout=_PER_REQUEST_TIMEOUT_S,
    ) as client:
        try:
            results = await asyncio.wait_for(
                asyncio.gather(
                    *(fetch_and_extract(client, url, _PER_REQUEST_TIMEOUT_S) for url, _ in urls_titles)
                ),
                timeout=_FETCH_WALL_CLOCK_S,
            )
        except asyncio.TimeoutError:
            results = [FetchResult(url=url, ok=False, failure_reason="timeout") for url, _ in urls_titles]
    fetch_wall_clock_ms = int((time.monotonic() - fetch_t0) * 1000)
```

And populate final stats after the successes/failures loop:

```python
    reason_counts: dict[str, int] = {}
    for _, reason in failures:
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
    _set_stats(
        k_requested=capped,
        k_returned_by_searxng=len(hits),
        k_fetched_ok=len(successes),
        k_failed=len(failures),
        failure_reasons=reason_counts,
        fetch_wall_clock_ms=fetch_wall_clock_ms,
        extracted_bytes_total=sum(len(b) for _, _, b in successes),
    )
```

- [ ] **Step 3: Update the engine's audit emit to use the stats**

In `backend/core/ai_engine.py` around line 615-629, replace the `elif func_name == "web_search":` block with:

```python
                    elif func_name == "web_search":
                        from tools.web import get_last_stats as _web_stats
                        stats = _web_stats()
                        _audit_chat_event(
                            user_id, workspace_id, session_id,
                            EventType.CHAT_WEB_SEARCH,
                            {
                                "query_preview": str(audit_args.get("query", ""))[:200],
                                "k_requested": stats.get("k_requested", 0),
                                "k_returned_by_searxng": stats.get("k_returned_by_searxng", 0),
                                "k_fetched_ok": stats.get("k_fetched_ok", 0),
                                "k_failed": stats.get("k_failed", 0),
                                "failure_reasons": stats.get("failure_reasons", {}),
                                "fetch_wall_clock_ms": stats.get("fetch_wall_clock_ms", 0),
                                "extracted_bytes_total": stats.get("extracted_bytes_total", 0),
                                "synthesis_model_id": routed_model,
                            },
                        )
```

Note: `routed_model` is in scope at this point in `stream_chat` — it's the model the engine picked for this turn (already overridden by the tier hint if applicable).

- [ ] **Step 4: Update the existing audit test for the new payload shape**

Find the existing web_search audit test:

```bash
grep -n "web_search\|CHAT_WEB_SEARCH" /home/orbital/projects/pryzm/backend/tests/test_audit_chat_events.py | head
```

Update it (or add a new case) to assert the new keys are present. The exact shape:

```python
def test_web_search_audit_includes_v2_payload():
    """chat.web_search event carries the v2 payload — fetch stats, failure
    breakdown, synthesis model, extracted bytes — not just URLs."""
    # ... existing fixture setup that drives a web_search call ...
    event = _get_chat_web_search_event(...)
    payload = event.payload_json
    assert payload["query_preview"]
    assert "k_requested" in payload
    assert "k_returned_by_searxng" in payload
    assert "k_fetched_ok" in payload
    assert "k_failed" in payload
    assert "failure_reasons" in payload
    assert "fetch_wall_clock_ms" in payload
    assert "extracted_bytes_total" in payload
    assert "synthesis_model_id" in payload
```

(Adapt to the existing fixture style in that test file.)

- [ ] **Step 5: Run the audit tests and verify they pass**

```bash
./venv/bin/pytest tests/test_audit_chat_events.py -v -k web_search
```

Expected: pass.

- [ ] **Step 6: Run the full backend suite**

```bash
./venv/bin/pytest -q --ignore=tests/test_image_upload.py --ignore=tests/test_upload_sse.py
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add backend/tools/web.py backend/core/ai_engine.py backend/tests/test_audit_chat_events.py
git commit -m "audit: enrich chat.web_search event with fetch stats, failure breakdown, synthesis model"
```

---

### Task 10: Frontend — collapsed pill for web_search tool result

**Files:**
- Modify: `frontend/src/components/ToolCallsBlock.tsx`

Manual verification only (no FE unit-test framework). The Playwright smoke in Task 11 will pin the behavior.

- [ ] **Step 1: Add a special-case render for `web_search` tool results**

In `frontend/src/components/ToolCallsBlock.tsx`, replace the body of the `.map` (lines ~55-71) so it special-cases `tc.name === "web_search"` when a `tc.result` is present:

```tsx
import { useState } from "react";

// ...

function WebSearchResultPill({ result }: { result: string }) {
  const [expanded, setExpanded] = useState(false);
  const sourceCount = (result.match(/^### Source \[\d+\]:/gm) || []).length;
  const failedCount = (result.match(/^- .+? — /gm) || []).length;

  return (
    <div className="-mt-1 mb-2">
      <button
        type="button"
        onClick={() => setExpanded((e) => !e)}
        className="text-[12px] text-gray-300 bg-[#1e1f20] border border-[#333537] rounded-lg px-3 py-1.5 hover:bg-[#252627] transition-colors cursor-pointer"
      >
        🌐 Searched: {sourceCount} source{sourceCount === 1 ? "" : "s"}
        {failedCount > 0 ? ` (${failedCount} failed)` : ""}
        {expanded ? " ▼" : " ▶"}
      </button>
      {expanded && (
        <pre className="mt-2 rounded-lg bg-[#1e1f20] border border-[#333537] px-3 py-2 text-[12px] text-gray-200 whitespace-pre-wrap overflow-x-auto">
          {result}
        </pre>
      )}
    </div>
  );
}

// ...

export default function ToolCallsBlock({ calls }: { calls: ToolCall[] }) {
  if (!calls || calls.length === 0) return null;

  return (
    <div className="w-full flex flex-col gap-3">
      {calls.map((tc, i) => (
        <div key={i} className="w-full">
          <blockquote className="bg-[#1a1b1c] border border-[#333537] border-l-4 border-l-blue-500 text-gray-300 px-4 py-3 rounded-r-lg my-2 flex items-start gap-3">
            <TerminalIcon />
            <div className="flex-1 text-[13px] break-words min-w-0">
              <strong>Tool:</strong>{" "}
              <code className="bg-[#2a2b2c] px-1.5 py-0.5 rounded text-[12px] font-mono">
                {tc.name}
              </code>
              <ArgPills args={tc.args} />
            </div>
          </blockquote>
          {tc.result ? (
            tc.name === "web_search" ? (
              <WebSearchResultPill result={tc.result} />
            ) : (
              <pre className="rounded-lg bg-[#1e1f20] border border-[#333537] px-3 py-2 text-[12px] text-gray-200 whitespace-pre-wrap overflow-x-auto -mt-1 mb-2">
                {tc.result}
              </pre>
            )
          ) : (
            <div className="text-[12px] text-gray-500 italic px-3 -mt-1 mb-2">running…</div>
          )}
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Manually verify in the browser**

Open `http://localhost:3000`, log in as `qatest` / `test`. Make sure the IT Copilot workspace has `web_search` enabled, toggle the globe icon on, send a turn like:

```
What were the most recent Microsoft 365 admin center changes announced this month?
```

Verify:
- Tool-result area shows a single-line "🌐 Searched: N sources" pill, NOT the raw markdown.
- Clicking the pill expands to reveal the `### Source [1]: ...` blocks.
- The assistant prose contains `[1]`, `[2]` markers and ends with a `**Sources**` section that has clickable URLs.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ToolCallsBlock.tsx
git commit -m "ui: collapse web_search tool result into a one-line \"Searched: N sources\" pill"
```

---

### Task 11: Playwright smoke test

**Files:**
- Create: `tests/smoke/web_search.spec.ts`

Mirrors the pattern in the existing smoke harness (`tests/smoke/README.md` documents how to run it).

- [ ] **Step 1: Read the existing smoke setup**

```bash
ls /home/orbital/projects/pryzm/tests/smoke/
cat /home/orbital/projects/pryzm/tests/smoke/README.md
```

Note the helpers for login + selectors. Reuse them.

- [ ] **Step 2: Write the smoke test**

Create `tests/smoke/web_search.spec.ts`:

```ts
import { test, expect } from '@playwright/test';
import { loginAs } from './helpers/login';

test('web_search v2: globe-on turn produces a Searched-N-sources pill', async ({ page }) => {
  await loginAs(page, 'qatest', 'test');

  // Pick the IT Copilot workspace (the test account's default).
  await page.waitForSelector('[data-testid="chat-input"]');

  // Toggle the globe.
  const globe = page.getByRole('button', { name: /web search/i });
  await globe.click();

  // Send a research-shaped query.
  await page.getByTestId('chat-input').fill(
    'What were the latest features added to TypeScript in the past month?'
  );
  await page.getByTestId('chat-send').click();

  // Wait for the assistant to finish (button[type="submit"] reappears when stream done).
  await expect(page.locator('button[type="submit"]')).toBeVisible({ timeout: 60_000 });

  // Pill is present, raw markdown blocks are NOT visible until expanded.
  const pill = page.getByRole('button', { name: /Searched: \d+ sources?/ });
  await expect(pill).toBeVisible();
  await expect(page.locator('text=### Source [1]:')).toHaveCount(0);

  // Expand and verify Source block appears.
  await pill.click();
  await expect(page.locator('text=### Source [1]:').first()).toBeVisible();

  // Assistant message contains a [N] citation and a Sources footer.
  const lastAssistant = page.locator('[data-role="assistant"]').last();
  await expect(lastAssistant).toContainText(/\[\d\]/);
  await expect(lastAssistant).toContainText(/sources/i);
});
```

(If the smoke harness uses different selectors / helpers, adapt to match. The key assertions are: pill renders, raw blocks hidden by default, expansion works, assistant text has citation markers + Sources footer.)

- [ ] **Step 3: Run the smoke test**

```bash
cd /home/orbital/projects/pryzm && ./backend/venv/bin/python -m playwright install chromium 2>/dev/null
cd /home/orbital/projects/pryzm/tests/smoke && ./node_modules/.bin/playwright test web_search.spec.ts
```

(Or follow whatever runner the README documents.)

Expected: green.

- [ ] **Step 4: Commit**

```bash
git add tests/smoke/web_search.spec.ts
git commit -m "tests(smoke): web_search v2 globe-on turn produces collapsed pill + cited reply"
```

---

### Wrap-up

After Task 11 lands, run the full backend sweep one more time to make sure nothing drifted:

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest -q --ignore=tests/test_image_upload.py --ignore=tests/test_upload_sse.py
```

Then open a PR. PR body should reference the spec (`docs/specs/2026-05-20-web-search-v2.md`) and list:
- New tool behavior (parallel fetch + trafilatura + cited blocks)
- New `web` tag on the catalog and the engine's tier-hint consumption
- Frontend pill collapse for web_search results
- Manual smoke run by hand against the live web with the `qatest` account

No manual checklist needed in the PR body — the Playwright smoke covers the FE path and the backend tests cover the BE path.
