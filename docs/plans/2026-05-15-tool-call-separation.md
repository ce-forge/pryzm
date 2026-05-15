# Tool-call separation — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist tool calls as structured data on the assistant message row, stream them as typed SSE events, render them via a dedicated frontend component, and rebuild history into proper OpenAI-style structured messages — eliminating the LLM-mimicry impulse at its root.

**Architecture:** A new `messages.tool_calls JSONB NULL` column stores `[{name, args, result}, ...]` per assistant turn. `ai_engine.stream_chat` yields typed `{type: "tool_call"}` / `{type: "tool_result"}` events replacing the prior text emissions. The `/analyze` route handler accumulates them into the JSONB column at save time. History-rebuild reads both shapes (legacy single-content rows AND new structured rows) and produces proper OpenAI tool messages for the next LLM call. The frontend renders the structured data via a new `ToolCallsBlock` component matching today's visual style. The `_strip_tool_mimicry` band-aid (regex + tests + `format_tool_execution` / `format_code_block` formatters) is removed.

**Tech Stack:** FastAPI (Python), SQLAlchemy, Alembic, pytest, Next.js/React, TypeScript. No new dependencies.

**Spec:** `docs/specs/2026-05-15-tool-call-separation.md`

---

## File structure

**Modified (backend):**
- `backend/db/models.py` — add `tool_calls` column to `Message`
- `backend/alembic/versions/d2f9c4e7a8b1_add_messages_tool_calls.py` — NEW migration
- `backend/core/ai_engine.py` — replace text emissions with typed events; remove `_strip_tool_mimicry` and its regex constants
- `backend/routers/chat.py` — event-collection accumulator; structured save; history-rebuild via new helper; history endpoint returns `tool_calls`
- `backend/schemas.py` — add `ToolCall`, add `tool_calls` to `MessageHistory`
- `backend/utils/formatters.py` — delete `format_tool_execution` + `format_code_block`
- `backend/tests/test_tool_directive_render.py` — delete the two `_strip_tool_mimicry` tests

**Created (backend):**
- `backend/tests/test_migration_add_tool_calls.py`
- `backend/tests/test_history_rebuild.py`
- `backend/tests/test_event_pairing.py`
- `backend/tests/test_ai_engine_typed_events.py`

**Modified (frontend):**
- `frontend/src/types/chat.ts` — add `ToolCall`; add `toolCalls` to `Message`
- `frontend/src/hooks/useSession.ts` — map snake-case `tool_calls` → camel-case `toolCalls`
- `frontend/src/hooks/useInference.ts` — capture `tool_call` / `tool_result` events; `streamingToolCalls` slice
- `frontend/src/context/SessionContext.tsx` — `finalizeAssistantMessage` accepts `toolCalls`
- `frontend/src/components/ChatBubble.tsx` — render `ToolCallsBlock` between prose and `ReferencedFilesPreview`

**Created (frontend):**
- `frontend/src/components/ToolCallsBlock.tsx`

---

## Task 1: DB schema + alembic migration + test

**Files:**
- Modify: `backend/db/models.py`
- Create: `backend/alembic/versions/d2f9c4e7a8b1_add_messages_tool_calls.py`
- Create: `backend/tests/test_migration_add_tool_calls.py`

- [ ] **Step 1: Add the column to the Message ORM model**

In `backend/db/models.py`, find the `Message` class. Below the existing `referenced_docs` column, add:

```python
    # JSON list of tool calls executed during this assistant turn
    # ([{name, args, result}, ...]). NULL for user/memory rows and for
    # legacy assistant rows written before this column existed (those keep
    # using the single-content shape; history-rebuild handles both).
    tool_calls = Column(JSONB, nullable=True)
```

Place it directly after the `referenced_docs` column definition.

- [ ] **Step 2: Create the migration file**

Create `backend/alembic/versions/d2f9c4e7a8b1_add_messages_tool_calls.py` with this content:

```python
"""add messages.tool_calls JSONB column

Revision ID: d2f9c4e7a8b1
Revises: c1f8b27a4d56
Create Date: 2026-05-15 23:30:00.000000

Stores the list of tool calls executed during an assistant turn as a
structured JSONB array of {name, args, result} objects. Lets us re-emit
proper OpenAI-style {role: "assistant", tool_calls: ...} + {role: "tool"}
messages to the LLM on subsequent turns, instead of flattening tool
markdown into the assistant's content blob.

Shape: NULL when the assistant turn made no tool calls (the common case);
otherwise a JSON array. NULL is also the legacy shape — pre-migration
rows keep using the single-content blob and history-rebuild handles them.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d2f9c4e7a8b1"
down_revision: Union[str, Sequence[str], None] = "c1f8b27a4d56"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column(
            "tool_calls",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("messages", "tool_calls")
```

- [ ] **Step 3: Write the migration test**

Create `backend/tests/test_migration_add_tool_calls.py`:

```python
"""Verifies migration d2f9c4e7a8b1: add messages.tool_calls JSONB column."""
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool


def test_upgrade_adds_tool_calls_column(db_at_revision, alembic_cfg):
    """At parent revision the column doesn't exist; after upgrade it does."""
    engine = db_at_revision("c1f8b27a4d56")
    with engine.connect() as conn:
        before = conn.execute(text("""
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'messages' AND column_name = 'tool_calls'
        """)).scalar()
    engine.dispose()
    assert before is None

    command.upgrade(alembic_cfg, "d2f9c4e7a8b1")

    fresh = create_engine(alembic_cfg.get_main_option("sqlalchemy.url"), poolclass=NullPool)
    with fresh.connect() as conn:
        col = conn.execute(text("""
            SELECT data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'messages' AND column_name = 'tool_calls'
        """)).first()
    fresh.dispose()
    assert col is not None
    assert col.data_type == "jsonb"
    assert col.is_nullable == "YES"


def test_downgrade_removes_tool_calls_column(reset_test_db, alembic_cfg):
    """Downgrade from d2f9c4e7a8b1 drops the column cleanly."""
    command.downgrade(alembic_cfg, "base")
    command.upgrade(alembic_cfg, "head")
    command.downgrade(alembic_cfg, "c1f8b27a4d56")

    engine = create_engine(reset_test_db, poolclass=NullPool)
    with engine.connect() as conn:
        col = conn.execute(text("""
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'messages' AND column_name = 'tool_calls'
        """)).scalar()
    engine.dispose()
    assert col is None
```

- [ ] **Step 4: Run the migration test**

Run: `cd backend && ./venv/bin/pytest tests/test_migration_add_tool_calls.py -v`
Expected: 2 passed

- [ ] **Step 5: Apply the migration to the dev DB**

Run: `cd backend && ./venv/bin/alembic upgrade head`
Expected: revision `d2f9c4e7a8b1` applied; no errors

- [ ] **Step 6: Verify on the dev DB**

Run: `PGPASSWORD=postgres psql -h localhost -U pryzm_admin -d pryzm_core -c "\d messages" | grep tool_calls`
Expected: `tool_calls | jsonb |` (or similar shape)

- [ ] **Step 7: Commit**

```bash
cd /home/orbital/projects/pryzm
git add backend/db/models.py backend/alembic/versions/d2f9c4e7a8b1_add_messages_tool_calls.py backend/tests/test_migration_add_tool_calls.py
git commit -m "feat(db): add messages.tool_calls JSONB column for structured tool persistence"
```

---

## Task 2: ai_engine emits typed events (replacing text yields)

**Files:**
- Modify: `backend/core/ai_engine.py`
- Create: `backend/tests/test_ai_engine_typed_events.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_ai_engine_typed_events.py`:

```python
"""Verify ai_engine yields typed tool_call / tool_result dicts instead of
text-emitted format_tool_execution / format_code_block markdown."""
from unittest.mock import AsyncMock, patch
import asyncio
import pytest

from core.ai_engine import stream_chat
from tools.registry import ResolvedToolSet
from db import models


@pytest.mark.asyncio
async def test_tool_execution_yields_typed_events():
    """When the LLM emits a tool_call, stream_chat yields a {type: tool_call}
    event followed by a {type: tool_result} event — no text markdown."""

    def _fake_tool(query: str, workspace_id: str = "", session_id: str = None) -> str:
        return "FAKE_RESULT"

    callables = {"_probe_typed_event_tool": _fake_tool}
    definitions = [{
        "type": "function",
        "function": {
            "name": "_probe_typed_event_tool",
            "description": "test",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        }
    }]
    tool_set = ResolvedToolSet(callables=callables, definitions=definitions, per_tool_config={})

    # Two-step LLM behaviour: first call returns a tool_call, second call returns plain content.
    responses = iter([
        {"message": {"tool_calls": [{"function": {"name": "_probe_typed_event_tool", "arguments": {"query": "foo"}}}]}},
        {"message": {"content": "Done."}},
    ])

    async def fake_chat(*_args, **_kwargs):
        return next(responses)

    mock_workspace = models.Workspace(
        id="ws-test", slug="it_copilot", display_name="IT Copilot",
        system_prompt="You are a test.", enabled_tools=["_probe_typed_event_tool"],
        is_builtin=True, engine_config={"backend": "llama_cpp"},
    )

    yields: list = []
    with patch("core.ai_engine.llm_server.chat", new=fake_chat), \
         patch("core.ai_engine.database.SessionLocal") as mock_db_local:
        mock_db = mock_db_local.return_value
        mock_db.query.return_value.filter.return_value.first.return_value = mock_workspace

        engine_config = {"backend": "llama_cpp"}
        async for item in stream_chat(
            client=None,
            messages=[{"role": "user", "content": "hi"}],
            workspace_id="ws-test",
            engine_config=engine_config,
            tool_set=tool_set,
            session_id="s-test",
        ):
            yields.append(item)

    # Find the structured events in the yield sequence
    tool_call_events = [y for y in yields if isinstance(y, dict) and y.get("type") == "tool_call"]
    tool_result_events = [y for y in yields if isinstance(y, dict) and y.get("type") == "tool_result"]

    assert len(tool_call_events) == 1, f"expected 1 tool_call event, got {tool_call_events}"
    assert tool_call_events[0]["name"] == "_probe_typed_event_tool"
    assert tool_call_events[0]["args"] == {"query": "foo"}

    assert len(tool_result_events) == 1
    assert tool_result_events[0]["name"] == "_probe_typed_event_tool"
    assert tool_result_events[0]["result"] == "FAKE_RESULT"

    # And critically: no text chunk should contain the old markdown markers
    text_chunks = [y for y in yields if isinstance(y, str)]
    combined = "".join(text_chunks)
    assert "> **Tool:**" not in combined
    assert "```text" not in combined
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./venv/bin/pytest tests/test_ai_engine_typed_events.py -v`
Expected: FAIL — the test will see the OLD text-emission shape (`> **Tool:**` in chunks).

- [ ] **Step 3: Replace the text emissions in ai_engine.py**

In `backend/core/ai_engine.py`, find the tool-execution block. Locate this section (around the `format_tool_execution` and `format_code_block` calls inside the `for tool_call in message["tool_calls"]:` loop):

```python
                    yield format_tool_execution(func_name, display_args)

                    try:
                        result = await asyncio.wait_for(
                            _execute_tool(enriched_call, workspace_tools),
                            timeout=settings.TOOL_TIMEOUT_SECONDS,
                        )
                    except asyncio.TimeoutError:
                        result = (
                            f"Tool {func_name} timed out after "
                            f"{settings.TOOL_TIMEOUT_SECONDS}s. "
                            "Continue with what you have."
                        )
                        had_tool_error = True
                    except Exception as tool_err:
                        result = f"Tool execution failed: {str(tool_err)}"
                        had_tool_error = True

                    yield format_code_block(result)
```

Replace it with:

```python
                    yield {"type": "tool_call", "name": func_name, "args": display_args}

                    try:
                        result = await asyncio.wait_for(
                            _execute_tool(enriched_call, workspace_tools),
                            timeout=settings.TOOL_TIMEOUT_SECONDS,
                        )
                    except asyncio.TimeoutError:
                        result = (
                            f"Tool {func_name} timed out after "
                            f"{settings.TOOL_TIMEOUT_SECONDS}s. "
                            "Continue with what you have."
                        )
                        had_tool_error = True
                    except Exception as tool_err:
                        result = f"Tool execution failed: {str(tool_err)}"
                        had_tool_error = True

                    yield {"type": "tool_result", "name": func_name, "result": result}
```

- [ ] **Step 4: Remove the now-unused imports**

In `backend/core/ai_engine.py`, find the import block at the top that pulls in formatters. It probably looks like:

```python
from utils.formatters import (
    format_file_analyzed,
    format_tool_execution,
    format_code_block,
    format_knowledge_reference,
    format_error
)
```

Remove `format_tool_execution` and `format_code_block` from the import. The line becomes:

```python
from utils.formatters import (
    format_file_analyzed,
    format_knowledge_reference,
    format_error
)
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd backend && ./venv/bin/pytest tests/test_ai_engine_typed_events.py -v`
Expected: PASS — tool_call and tool_result events present, no text markdown.

- [ ] **Step 6: Run the broader test suite to confirm no immediate regression**

Run: `cd backend && ./venv/bin/pytest tests/ --ignore=tests/e2e --ignore=tests/perf -q`
Expected: existing tests still pass. (The route-handler tests will adapt in Task 3; if any test depending on text emissions fails here, note it and continue — it gets fixed in Task 3.)

- [ ] **Step 7: Commit**

```bash
cd /home/orbital/projects/pryzm
git add backend/core/ai_engine.py backend/tests/test_ai_engine_typed_events.py
git commit -m "feat(engine): replace text-emitted tool markdown with typed SSE events"
```

---

## Task 3: Route handler event accumulator + structured save

**Files:**
- Modify: `backend/routers/chat.py`
- Create: `backend/tests/test_event_pairing.py`

- [ ] **Step 1: Write the failing test for the pairing logic**

Create `backend/tests/test_event_pairing.py`:

```python
"""Tests the route handler's tool_call ↔ tool_result pairing logic in isolation.

The accumulator pairs by ORDER, not by name — handles two calls to the same
tool within one turn correctly. A tool_result always completes the most-
recent open (result=None) entry."""
from routers.chat import _accumulate_tool_event


def test_single_call_pairs_with_result():
    acc: list = []
    _accumulate_tool_event(acc, {"type": "tool_call", "name": "dns_lookup", "args": {"domain": "x.com"}})
    assert acc == [{"name": "dns_lookup", "args": {"domain": "x.com"}, "result": None}]

    _accumulate_tool_event(acc, {"type": "tool_result", "name": "dns_lookup", "result": "OK"})
    assert acc == [{"name": "dns_lookup", "args": {"domain": "x.com"}, "result": "OK"}]


def test_same_tool_called_twice_pairs_by_order():
    """Two consecutive tool_call/tool_result pairs for the same tool —
    each result attaches to its own call by ORDER, not by name."""
    acc: list = []
    _accumulate_tool_event(acc, {"type": "tool_call", "name": "search_knowledge_base", "args": {"queries": ["a"]}})
    _accumulate_tool_event(acc, {"type": "tool_result", "name": "search_knowledge_base", "result": "RESULT_A"})
    _accumulate_tool_event(acc, {"type": "tool_call", "name": "search_knowledge_base", "args": {"queries": ["b"]}})
    _accumulate_tool_event(acc, {"type": "tool_result", "name": "search_knowledge_base", "result": "RESULT_B"})

    assert len(acc) == 2
    assert acc[0]["args"] == {"queries": ["a"]} and acc[0]["result"] == "RESULT_A"
    assert acc[1]["args"] == {"queries": ["b"]} and acc[1]["result"] == "RESULT_B"


def test_orphan_tool_result_logged_and_dropped():
    """A tool_result with no preceding open call is a no-op (and would WARN
    in production; the test just confirms acc is unchanged)."""
    acc: list = []
    _accumulate_tool_event(acc, {"type": "tool_result", "name": "ghost", "result": "X"})
    assert acc == []


def test_finalize_drops_unpaired_calls():
    """If a stream disconnects mid-execution and a tool_call has no result,
    the finalize helper drops the unpaired entry."""
    from routers.chat import _finalize_tool_calls
    acc = [
        {"name": "a", "args": {}, "result": "RESULT_A"},
        {"name": "b", "args": {}, "result": None},  # disconnected mid-execution
    ]
    final = _finalize_tool_calls(acc)
    assert final == [{"name": "a", "args": {}, "result": "RESULT_A"}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./venv/bin/pytest tests/test_event_pairing.py -v`
Expected: FAIL with `ImportError: cannot import name '_accumulate_tool_event' from 'routers.chat'` (or similar).

- [ ] **Step 3: Implement the pairing helpers in routers/chat.py**

In `backend/routers/chat.py`, near the top after the existing imports but before the route definitions, add:

```python
import logging
_log = logging.getLogger(__name__)


def _accumulate_tool_event(acc: list, event: dict) -> None:
    """Append/update tool-call accumulator from a streamed event.

    Pairs by ORDER (not by name): a tool_result always completes the most-
    recent entry whose result is still None. A tool_result with no open
    entry is logged and dropped (defensive guard against engine bugs)."""
    etype = event.get("type")
    if etype == "tool_call":
        acc.append({
            "name": event.get("name", ""),
            "args": event.get("args") or {},
            "result": None,
        })
    elif etype == "tool_result":
        for i in range(len(acc) - 1, -1, -1):
            if acc[i]["result"] is None:
                acc[i]["result"] = event.get("result", "")
                return
        _log.warning("tool_result %r arrived with no open tool_call; dropping", event.get("name"))


def _finalize_tool_calls(acc: list) -> list:
    """Drop entries with no result (left unpaired by a mid-stream disconnect).

    Returned list is safe to persist as the assistant row's tool_calls JSONB."""
    return [tc for tc in acc if tc.get("result") is not None]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && ./venv/bin/pytest tests/test_event_pairing.py -v`
Expected: 4 passed

- [ ] **Step 5: Wire the accumulator into the /analyze stream loop**

In `backend/routers/chat.py`, find the `/analyze` route handler's event-dispatch block. It currently has:

```python
        referenced_docs: list[dict] | None = None
        try:
            async for item in ai_engine.stream_chat(
                ...
            ):
                if await http_request.is_disconnected():
                    disconnected = True
                    break
                # ai_engine yields either a markdown chunk string (the
                # common case) OR a dict structured event ...
                if isinstance(item, dict):
                    # Capture files_referenced so we can persist them ...
                    if item.get("type") == "files_referenced":
                        ...
                        referenced_docs = merged or None
                    yield json.dumps(item) + "\n"
                    continue
                full_response += item
                yield json.dumps({"chunk": item}) + "\n"
```

Add a `tool_calls_acc` accumulator alongside `referenced_docs`, and handle the two new event types. The block becomes:

```python
        referenced_docs: list[dict] | None = None
        tool_calls_acc: list[dict] = []
        try:
            async for item in ai_engine.stream_chat(
                ...
            ):
                if await http_request.is_disconnected():
                    disconnected = True
                    break
                if isinstance(item, dict):
                    if item.get("type") == "files_referenced":
                        files = item.get("files") or []
                        merged = list(referenced_docs or [])
                        seen = {f["id"] for f in merged}
                        for f in files:
                            if f.get("id") and f["id"] not in seen:
                                merged.append(f)
                                seen.add(f["id"])
                        referenced_docs = merged or None
                    elif item.get("type") in ("tool_call", "tool_result"):
                        _accumulate_tool_event(tool_calls_acc, item)
                    yield json.dumps(item) + "\n"
                    continue
                full_response += item
                yield json.dumps({"chunk": item}) + "\n"
```

(Keep the exact surrounding context — `…` here is the elided existing code that stays as-is.)

- [ ] **Step 6: Add tool_calls to the save path**

In the same file, find the assistant-message save block (the one that calls `models.Message(...)` with `role="assistant"`). It currently looks like:

```python
                if full_response.strip():
                    save_db = database.SessionLocal()
                    try:
                        ai_msg = models.Message(
                            session_id=session_id,
                            role="assistant",
                            content=full_response,
                            status="complete",
                            referenced_docs=referenced_docs,
                        )
```

Change the `Message(...)` call to:

```python
                        ai_msg = models.Message(
                            session_id=session_id,
                            role="assistant",
                            content=full_response,
                            status="complete",
                            referenced_docs=referenced_docs,
                            tool_calls=_finalize_tool_calls(tool_calls_acc) or None,
                        )
```

- [ ] **Step 7: Run the broader test suite**

Run: `cd backend && ./venv/bin/pytest tests/ --ignore=tests/e2e --ignore=tests/perf -q`
Expected: tests pass (the event-pairing tests + previously passing tests).

- [ ] **Step 8: Commit**

```bash
cd /home/orbital/projects/pryzm
git add backend/routers/chat.py backend/tests/test_event_pairing.py
git commit -m "feat(chat): accumulate tool_call/tool_result events into structured save"
```

---

## Task 4: History-rebuild helper for structured messages

**Files:**
- Modify: `backend/routers/chat.py`
- Create: `backend/tests/test_history_rebuild.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_history_rebuild.py`:

```python
"""Tests build_safe_messages: emits flat shape for legacy rows (tool_calls
NULL) and OpenAI-style structured shape for new rows. Mixed history works."""
from routers.chat import build_safe_messages


class _FakeMsg:
    def __init__(self, role, content, tool_calls=None):
        self.role = role
        self.content = content
        self.tool_calls = tool_calls


def test_legacy_row_emits_flat_shape():
    """An assistant row with tool_calls=NULL emits one flat {role, content}."""
    msgs = [_FakeMsg("assistant", "old narrative + > **Tool:** mimicry", tool_calls=None)]
    out = build_safe_messages(msgs)
    assert out == [{"role": "assistant", "content": "old narrative + > **Tool:** mimicry"}]


def test_new_row_emits_structured_assistant_plus_tool_messages():
    """An assistant row with populated tool_calls emits:
       1. {role: "assistant", content, tool_calls: [{function: ...}, ...]}
       2. one {role: "tool", name, content: result} per call, in order."""
    msgs = [_FakeMsg(
        "assistant",
        "Here are the results.",
        tool_calls=[
            {"name": "dns_lookup", "args": {"domain": "x.com"}, "result": "1.2.3.4"},
            {"name": "execute_ping", "args": {"hostname": "1.2.3.4"}, "result": "Ping ok"},
        ],
    )]
    out = build_safe_messages(msgs)
    assert out == [
        {
            "role": "assistant",
            "content": "Here are the results.",
            "tool_calls": [
                {"function": {"name": "dns_lookup", "arguments": {"domain": "x.com"}}},
                {"function": {"name": "execute_ping", "arguments": {"hostname": "1.2.3.4"}}},
            ],
        },
        {"role": "tool", "name": "dns_lookup", "content": "1.2.3.4"},
        {"role": "tool", "name": "execute_ping", "content": "Ping ok"},
    ]


def test_mixed_history_per_row_shape():
    """Mixed: legacy user, legacy assistant, new assistant. Each row gets
    its own shape; no cross-contamination."""
    msgs = [
        _FakeMsg("user", "hi"),
        _FakeMsg("assistant", "old style", tool_calls=None),
        _FakeMsg("user", "follow up"),
        _FakeMsg("assistant", "new synthesis", tool_calls=[
            {"name": "dns_lookup", "args": {"domain": "y.com"}, "result": "5.6.7.8"},
        ]),
    ]
    out = build_safe_messages(msgs)
    assert len(out) == 5  # 4 messages + 1 tool message
    assert out[0] == {"role": "user", "content": "hi"}
    assert out[1] == {"role": "assistant", "content": "old style"}
    assert out[2] == {"role": "user", "content": "follow up"}
    assert out[3]["role"] == "assistant"
    assert out[3]["tool_calls"][0]["function"]["name"] == "dns_lookup"
    assert out[4] == {"role": "tool", "name": "dns_lookup", "content": "5.6.7.8"}


def test_empty_history_returns_empty_list():
    assert build_safe_messages([]) == []


def test_malformed_tool_calls_falls_back_to_flat():
    """A row with non-list garbage in tool_calls is treated like a legacy row."""
    msgs = [_FakeMsg("assistant", "x", tool_calls="not-a-list")]
    out = build_safe_messages(msgs)
    assert out == [{"role": "assistant", "content": "x"}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./venv/bin/pytest tests/test_history_rebuild.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_safe_messages' from 'routers.chat'`.

- [ ] **Step 3: Implement build_safe_messages in routers/chat.py**

In `backend/routers/chat.py`, near the helpers added in Task 3, add:

```python
def build_safe_messages(history) -> list[dict]:
    """Convert DB Message rows into the structured shape ai_engine consumes.

    Legacy rows (tool_calls NULL) emit one flat {role, content}. New rows
    with structured tool_calls emit one {role: "assistant", content,
    tool_calls: [...]} followed by one {role: "tool", name, content: result}
    per call, in order. Malformed tool_calls (non-list) is treated as legacy."""
    out: list[dict] = []
    for msg in history:
        tcs = getattr(msg, "tool_calls", None)
        if msg.role == "assistant" and isinstance(tcs, list) and tcs:
            out.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {"function": {"name": tc["name"], "arguments": tc.get("args") or {}}}
                    for tc in tcs
                ],
            })
            for tc in tcs:
                out.append({
                    "role": "tool",
                    "name": tc["name"],
                    "content": tc.get("result") or "",
                })
        else:
            out.append({"role": msg.role, "content": msg.content})
    return out
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && ./venv/bin/pytest tests/test_history_rebuild.py -v`
Expected: 5 passed

- [ ] **Step 5: Use build_safe_messages in the /analyze handler**

In `backend/routers/chat.py`, find the line that currently does:

```python
        safe_messages = [{"role": msg.role, "content": msg.content} for msg in history]
```

Replace it with:

```python
        safe_messages = build_safe_messages(history)
```

- [ ] **Step 6: Run the broader test suite**

Run: `cd backend && ./venv/bin/pytest tests/ --ignore=tests/e2e --ignore=tests/perf -q`
Expected: all tests pass

- [ ] **Step 7: Commit**

```bash
cd /home/orbital/projects/pryzm
git add backend/routers/chat.py backend/tests/test_history_rebuild.py
git commit -m "feat(chat): structured history-rebuild for both legacy and new rows"
```

---

## Task 5: MessageHistory schema gets tool_calls field

**Files:**
- Modify: `backend/schemas.py`
- Modify: `backend/routers/chat.py` (history endpoint already returns MessageHistory; we just verify the new field propagates)

- [ ] **Step 1: Add ToolCall + extend MessageHistory in schemas.py**

In `backend/schemas.py`, find the existing `ReferencedFile` class. Add a new `ToolCall` class below it:

```python
class ToolCall(BaseModel):
    name: str
    args: dict
    result: str
```

Then find the `MessageHistory` class. Add `tool_calls`:

```python
class MessageHistory(BaseModel):
    id: str
    role: str
    content: str
    status: str = "complete"
    timestamp: Optional[str] = None
    referenced_files: Optional[List[ReferencedFile]] = None
    # Tool calls executed during this assistant turn (NULL for user/memory
    # rows and for legacy assistant rows). See spec
    # docs/specs/2026-05-15-tool-call-separation.md for the shape.
    tool_calls: Optional[List[ToolCall]] = None
```

- [ ] **Step 2: Verify the history endpoint surfaces the field**

Find the `get_session_history` endpoint in `backend/routers/chat.py` (around line 191). It currently builds responses like:

```python
        return [
            MessageHistory(
                id=m.id,
                role=m.role,
                content=m.content,
                status=m.status,
                timestamp=m.created_at.isoformat() if m.created_at else None,
                referenced_files=m.referenced_docs or None,
            )
            for m in messages
        ]
```

Update the list comprehension to also include `tool_calls`:

```python
        return [
            MessageHistory(
                id=m.id,
                role=m.role,
                content=m.content,
                status=m.status,
                timestamp=m.created_at.isoformat() if m.created_at else None,
                referenced_files=m.referenced_docs or None,
                tool_calls=m.tool_calls or None,
            )
            for m in messages
        ]
```

- [ ] **Step 3: Quick smoke check via the actual endpoint**

Run (backend should already be running):

```bash
TOKEN=$(grep PRYZM_API_TOKEN /home/orbital/projects/pryzm/.env | cut -d= -f2)
SESSION=$(PGPASSWORD=postgres psql -h localhost -U pryzm_admin -d pryzm_core -tA -c "SELECT id FROM sessions ORDER BY created_at DESC LIMIT 1")
curl -s "http://127.0.0.1:8000/sessions/$SESSION" -H "Authorization: Bearer $TOKEN" | python3 -m json.tool | grep -c "tool_calls"
```

Expected: non-zero count (every message in the response includes the `tool_calls` field, even if `null`).

- [ ] **Step 4: Run the test suite**

Run: `cd backend && ./venv/bin/pytest tests/ --ignore=tests/e2e --ignore=tests/perf -q`
Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
cd /home/orbital/projects/pryzm
git add backend/schemas.py backend/routers/chat.py
git commit -m "feat(api): MessageHistory exposes tool_calls in /sessions/{id} response"
```

---

## Task 6: Remove the strip-mimicry band-aid + dead formatters

**Files:**
- Modify: `backend/core/ai_engine.py` (remove regex constants + `_strip_tool_mimicry` + its call sites)
- Modify: `backend/tests/test_tool_directive_render.py` (remove the two mimicry tests)
- Modify: `backend/utils/formatters.py` (delete `format_tool_execution` + `format_code_block`)

- [ ] **Step 1: Remove the strip-mimicry code from ai_engine.py**

In `backend/core/ai_engine.py`, find and delete:

1. The regex constants block:

```python
# Strip LLM-generated mimicry of the engine's own tool-call rendering. The
# engine emits `> **Tool:** ...` headers and ```text``` result blocks itself
# after each real tool execution (see format_tool_execution / format_code_block
# in utils/formatters.py). When the model's *narrative content* contains those
# same patterns it's regurgitating prior-turn context, not invoking a new tool
# — drop it before the chunk reaches the chat surface so the displayed tool
# output stays trustworthy.
_TOOL_HEADER_MIMICRY = re.compile(r"^\s*> \*\*Tool:\*\* [^\n]*\n?", re.MULTILINE)
_TEXT_BLOCK_MIMICRY = re.compile(r"```text\n.*?\n```\n?", re.DOTALL)


def _strip_tool_mimicry(content: str) -> str:
    content = _TOOL_HEADER_MIMICRY.sub("", content)
    content = _TEXT_BLOCK_MIMICRY.sub("", content)
    return content
```

2. The call site inside the `else: content = message.get("content") ...` block. Currently:

```python
                content = _THINK_BLOCK_RE.sub('', content)
                content = _strip_tool_mimicry(content).strip()
```

Change to:

```python
                content = _THINK_BLOCK_RE.sub('', content).strip()
```

- [ ] **Step 2: Remove the strip-mimicry tests**

In `backend/tests/test_tool_directive_render.py`, delete the two test functions:

- `test_strip_tool_mimicry_removes_lookalike_blocks`
- `test_strip_tool_mimicry_preserves_other_code_blocks`

- [ ] **Step 3: Delete the dead formatters**

In `backend/utils/formatters.py`, find and delete `format_tool_execution` (the function that returns `f"\n\n> **Tool:** \`{func_name}\`..."` strings) and `format_code_block` (the function that returns `"```text\n{result}\n```"`).

If any helper functions used ONLY by those two formatters exist in the same file, delete them too. Check by searching for callers; leave anything still in use.

- [ ] **Step 4: Run the suite to confirm no regressions**

Run: `cd backend && ./venv/bin/pytest tests/ --ignore=tests/e2e --ignore=tests/perf -q`
Expected: all tests pass; reduced count by 2 (the deleted mimicry tests).

- [ ] **Step 5: Commit**

```bash
cd /home/orbital/projects/pryzm
git add backend/core/ai_engine.py backend/tests/test_tool_directive_render.py backend/utils/formatters.py
git commit -m "cleanup(chat): remove strip-mimicry band-aid + dead text-emit formatters"
```

---

## Task 7: Frontend types + history mapper

**Files:**
- Modify: `frontend/src/types/chat.ts`
- Modify: `frontend/src/hooks/useSession.ts`

- [ ] **Step 1: Add the ToolCall interface and extend Message**

In `frontend/src/types/chat.ts`, add the `ToolCall` interface alongside the existing `ReferencedFile`:

```typescript
export interface ToolCall {
  name: string;
  args: Record<string, unknown>;
  result: string;
}
```

Then update the `Message` interface to include the optional `toolCalls`:

```typescript
export interface Message {
  id?: string;
  role: "user" | "assistant";
  content: string;
  timestamp?: string;
  referencedFiles?: ReferencedFile[];
  toolCalls?: ToolCall[];
}
```

- [ ] **Step 2: Update the history mapper in useSession.ts**

In `frontend/src/hooks/useSession.ts`, find the history fetch's `mapped: Message[] = historyData.map(...)` block. It currently looks like:

```typescript
          const mapped: Message[] = historyData.map((m: Message & { referenced_files?: ReferencedFile[] }) => ({
              id: m.id,
              role: m.role,
              content: m.content,
              timestamp: m.timestamp,
              referencedFiles: m.referenced_files ?? undefined,
          }));
```

Update it to include `toolCalls`:

```typescript
          const mapped: Message[] = historyData.map((m: Message & {
              referenced_files?: ReferencedFile[];
              tool_calls?: ToolCall[];
          }) => ({
              id: m.id,
              role: m.role,
              content: m.content,
              timestamp: m.timestamp,
              referencedFiles: m.referenced_files ?? undefined,
              toolCalls: m.tool_calls ?? undefined,
          }));
```

Then add `ToolCall` to the import line at the top of the file:

```typescript
import { Message, ReferencedFile, ToolCall } from "@/types/chat";
```

- [ ] **Step 3: Run the frontend linter**

Run: `cd frontend && npm run lint 2>&1 | tail -10`
Expected: no new errors. (Pre-existing lints can stay; this task introduces no new ones.)

- [ ] **Step 4: Commit**

```bash
cd /home/orbital/projects/pryzm
git add frontend/src/types/chat.ts frontend/src/hooks/useSession.ts
git commit -m "feat(types): frontend ToolCall type + history mapper"
```

---

## Task 8: SSE consumer captures tool_call / tool_result events

**Files:**
- Modify: `frontend/src/hooks/useInference.ts`
- Modify: `frontend/src/context/SessionContext.tsx`

- [ ] **Step 1: Extend SessionContext.finalizeAssistantMessage to accept toolCalls**

In `frontend/src/context/SessionContext.tsx`, find the `finalizeAssistantMessage` callback. It currently looks like:

```typescript
  const finalizeAssistantMessage = useCallback(
    (ws: string, sid: string, content: string, referencedFiles?: ReferencedFile[]) => {
      const key = cacheKey(ws, sid);
      setMessageCache((prev) => {
        const msgs = prev[key];
        if (!msgs || msgs.length === 0) return prev;
        const next = [...msgs];
        const last = next[next.length - 1];
        next[next.length - 1] = {
          ...last,
          content,
          referencedFiles: referencedFiles ?? last.referencedFiles,
        };
        return { ...prev, [key]: next };
      });
    },
    [setMessageCache],
  );
```

Update to:

```typescript
  const finalizeAssistantMessage = useCallback(
    (ws: string, sid: string, content: string, referencedFiles?: ReferencedFile[], toolCalls?: ToolCall[]) => {
      const key = cacheKey(ws, sid);
      setMessageCache((prev) => {
        const msgs = prev[key];
        if (!msgs || msgs.length === 0) return prev;
        const next = [...msgs];
        const last = next[next.length - 1];
        next[next.length - 1] = {
          ...last,
          content,
          referencedFiles: referencedFiles ?? last.referencedFiles,
          toolCalls: toolCalls ?? last.toolCalls,
        };
        return { ...prev, [key]: next };
      });
    },
    [setMessageCache],
  );
```

Also update the type interface that exposes `finalizeAssistantMessage`. Find the corresponding line in the same file (likely in an interface declaration):

```typescript
  finalizeAssistantMessage: (
    ws: string,
    sid: string,
    content: string,
    referencedFiles?: ReferencedFile[],
  ) => void;
```

Update to:

```typescript
  finalizeAssistantMessage: (
    ws: string,
    sid: string,
    content: string,
    referencedFiles?: ReferencedFile[],
    toolCalls?: ToolCall[],
  ) => void;
```

And update the import:

```typescript
import { Message, ReferencedFile, ToolCall } from "@/types/chat";
```

- [ ] **Step 2: Capture tool_call / tool_result events in useInference**

In `frontend/src/hooks/useInference.ts`, find the existing `streamingContent` slice. Right next to it, add a sibling slice for streaming tool calls:

```typescript
  const [streamingToolCalls, setStreamingToolCalls] = useState<Record<string, ToolCall[]>>({});
```

Add the import:

```typescript
import { Message, ReferencedFile, ToolCall } from "@/types/chat";
```

Inside `sendMessage`, find where `referencedFiles` is declared at the top of the function:

```typescript
      let referencedFiles: ReferencedFile[] | undefined;
```

Right below it, add:

```typescript
      const pendingToolCalls: ToolCall[] = [];
```

Then find the existing SSE-parse loop's `if (parsed.type === "files_referenced" ...)` branch. Right after that branch, add two new branches:

```typescript
                if (parsed.type === "tool_call" && parsed.name) {
                  pendingToolCalls.push({
                    name: parsed.name,
                    args: parsed.args ?? {},
                    result: "",
                  });
                  setStreamingToolCalls((prev) => ({ ...prev, [optimisticId]: [...pendingToolCalls] }));
                  if (realDbId !== null) {
                    setStreamingToolCalls((prev) => ({ ...prev, [realDbId!]: [...pendingToolCalls] }));
                  }
                }
                if (parsed.type === "tool_result" && parsed.name) {
                  // Pair by ORDER (back-to-front: complete the most recent
                  // entry with empty result). Mirrors the backend pairing.
                  for (let i = pendingToolCalls.length - 1; i >= 0; i--) {
                    if (pendingToolCalls[i].result === "") {
                      pendingToolCalls[i].result = parsed.result ?? "";
                      break;
                    }
                  }
                  setStreamingToolCalls((prev) => ({ ...prev, [optimisticId]: [...pendingToolCalls] }));
                  if (realDbId !== null) {
                    setStreamingToolCalls((prev) => ({ ...prev, [realDbId!]: [...pendingToolCalls] }));
                  }
                }
```

- [ ] **Step 3: Pass toolCalls through finalize**

In the same file, find the finally block's call to `finalizeAssistantMessage`. It currently looks like:

```typescript
        sessionApi.finalizeAssistantMessage(ws, finalKeySid, fullAssistantMessage, referencedFiles);
```

Update to:

```typescript
        sessionApi.finalizeAssistantMessage(ws, finalKeySid, fullAssistantMessage, referencedFiles, pendingToolCalls.length > 0 ? pendingToolCalls : undefined);
```

And add `streamingToolCalls` cleanup in the same finally:

```typescript
        setStreamingToolCalls((prev) => {
          const next = { ...prev };
          delete next[optimisticId];
          if (realDbId !== null) delete next[realDbId];
          return next;
        });
```

Place it next to the existing `setStreamingContent` cleanup that runs the same delete pattern.

- [ ] **Step 4: Expose streamingToolCalls in the InferenceApi return**

Update the `InferenceApi` interface at the top of `useInference.ts`:

```typescript
export interface InferenceApi {
  isProcessing: boolean;
  streamingContent: Record<string, string>;
  streamingToolCalls: Record<string, ToolCall[]>;
  ...
}
```

And add `streamingToolCalls` to the return object at the bottom of `useInference`:

```typescript
  return {
    isProcessing,
    streamingContent,
    streamingToolCalls,
    sendMessage,
    stopInference,
    migratedIds,
    setLinkSessionCallback,
  };
```

- [ ] **Step 5: Run the linter**

Run: `cd frontend && npm run lint 2>&1 | tail -10`
Expected: no new errors.

- [ ] **Step 6: Commit**

```bash
cd /home/orbital/projects/pryzm
git add frontend/src/hooks/useInference.ts frontend/src/context/SessionContext.tsx
git commit -m "feat(stream): capture tool_call/tool_result SSE events into streamingToolCalls"
```

---

## Task 9: ToolCallsBlock component + ChatBubble integration

**Files:**
- Create: `frontend/src/components/ToolCallsBlock.tsx`
- Modify: `frontend/src/components/ChatBubble.tsx`
- Modify: `frontend/src/components/ActiveSession.tsx`

- [ ] **Step 1: Create the ToolCallsBlock component**

Create `frontend/src/components/ToolCallsBlock.tsx`:

```typescript
"use client";
/**
 * Renders the structured tool_calls list on an assistant turn.
 *
 * Visual style mirrors what users have seen in chat all along — a `> **Tool:**`
 * blockquote header followed by a `text` code block — but driven by structured
 * props instead of markdown embedded in the message content. Source of truth
 * lives in the assistant row's tool_calls JSONB column (or, mid-stream, in
 * useInference's streamingToolCalls slice).
 */
import type { ToolCall } from "@/types/chat";


function _formatArgs(args: Record<string, unknown>): string {
  const keys = Object.keys(args);
  if (keys.length === 0) return "";
  if (keys.length === 1) {
    const v = args[keys[0]];
    return `\`${JSON.stringify(v)}\``;
  }
  return keys.map((k) => `\`${k}=${JSON.stringify(args[k])}\``).join(", ");
}


export default function ToolCallsBlock({ calls }: { calls: ToolCall[] }) {
  if (!calls || calls.length === 0) return null;

  return (
    <div className="mt-2 flex flex-col gap-3 w-full">
      {calls.map((tc, i) => {
        const argsRendered = _formatArgs(tc.args);
        const header = argsRendered
          ? `> **Tool:** \`${tc.name}\` → ${argsRendered}`
          : `> **Tool:** \`${tc.name}\``;
        return (
          <div key={i} className="flex flex-col gap-1.5 w-full">
            <div className="text-[13px] text-gray-300 whitespace-pre-wrap">{header}</div>
            {tc.result ? (
              <pre className="rounded-lg bg-[#1e1f20] border border-[#333537] px-3 py-2 text-[12px] text-gray-200 whitespace-pre-wrap overflow-x-auto">
                {tc.result}
              </pre>
            ) : (
              <div className="text-[12px] text-gray-500 italic">running…</div>
            )}
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 2: Render ToolCallsBlock in ChatBubble**

In `frontend/src/components/ChatBubble.tsx`, find the existing `ReferencedFilesPreview` import:

```typescript
import ReferencedFilesPreview from "./ReferencedFilesPreview";
```

Add right below it:

```typescript
import ToolCallsBlock from "./ToolCallsBlock";
```

Then add `toolCalls` to the `ChatBubbleProps`'s `message` type:

```typescript
  message: { id?: string; role: string; content: string; timestamp?: string; referencedFiles?: ReferencedFile[]; toolCalls?: ToolCall[] };
```

And update the import line for types at the top:

```typescript
import type { ReferencedFile, ToolCall } from "@/types/chat";
```

Find the existing render block for `ReferencedFilesPreview`:

```typescript
          {/* Image previews from auto-RAG. Only renders on assistant
              turns where the backend retrieved image documents. */}
          {message.role !== "user" && message.referencedFiles && message.referencedFiles.length > 0 && (
            <ReferencedFilesPreview files={message.referencedFiles} />
          )}
```

Right before it (so tool calls render between prose and image previews), add:

```typescript
          {/* Structured tool calls — engine-emitted, persisted on the
              messages.tool_calls JSONB column. Only renders on assistant
              turns that actually executed tools. */}
          {message.role !== "user" && message.toolCalls && message.toolCalls.length > 0 && (
            <ToolCallsBlock calls={message.toolCalls} />
          )}
```

- [ ] **Step 3: Wire live-stream toolCalls through ActiveSession**

In `frontend/src/components/ActiveSession.tsx`, find the `messages.map(...)` block (the one that renders each `ChatBubble`). The current code wraps the streaming-content override:

```typescript
            const displayContent = isLastStreaming && myStreamingText ? myStreamingText : m.content;
```

Add parallel handling for tool calls. Right above the `displayContent` line, get the live tool-call list:

```typescript
            const liveToolCalls = isLastStreaming ? ai.streamingToolCalls[session.currentSession ?? ""] : undefined;
            const displayToolCalls = liveToolCalls ?? (m as Message).toolCalls;
```

Then pass `displayToolCalls` to a new prop on `ChatBubble`. Update the `ChatBubble` call site to add the prop:

```typescript
                <ChatBubble
                  message={{ ...m, toolCalls: displayToolCalls }}
                  displayContent={displayContent}
                  index={i}
                  ...
                />
```

(The spread `{...m, toolCalls: displayToolCalls}` overrides the saved `toolCalls` with the live-stream version when mid-stream; falls back to the saved value when stable.)

Add the import at the top of `ActiveSession.tsx` if not already present:

```typescript
import { Message } from "@/types/chat";
```

- [ ] **Step 4: Visual smoke test via Playwright**

Backend should be hot-reloading via uvicorn; frontend dev server via `npm run dev`. With both up:

```bash
cd /home/orbital/projects/pryzm/backend
./venv/bin/python << 'PYEOF'
from playwright.sync_api import sync_playwright
TOKEN = open("/home/orbital/projects/pryzm/.env").read().split("PRYZM_API_TOKEN=")[1].split("\n")[0].strip()

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1200, "height": 900})
    ctx.add_init_script(f"localStorage.setItem('pryzm_api_token', '{TOKEN}');")
    page = ctx.new_page()
    page.goto("http://127.0.0.1:3000/?workspace=it_copilot", wait_until="networkidle")
    page.wait_for_timeout(2000)
    page.locator("textarea").fill("Check if reddit.com is up")
    page.locator("button[type='submit']").click()
    # Wait for the response (up to 120s for a local LLM with tool-loop)
    page.wait_for_selector("button[type='submit']:not([disabled])", timeout=120000, state="visible")
    page.wait_for_timeout(1500)
    # The new ToolCallsBlock should render the > **Tool:** prefix as part of its visible text
    body = page.locator("body").inner_text()
    assert "Tool:" in body or "tool" in body.lower(), "no tool call block visible in chat"
    page.screenshot(path="/tmp/tool_call_block_render.png", full_page=True)
    print("OK: tool-call block visible in chat surface")
    b.close()
PYEOF
```

Expected: prints `OK: tool-call block visible in chat surface` and writes `/tmp/tool_call_block_render.png`.

- [ ] **Step 5: Run the frontend linter**

Run: `cd frontend && npm run lint 2>&1 | tail -10`
Expected: no new errors.

- [ ] **Step 6: Commit**

```bash
cd /home/orbital/projects/pryzm
git add frontend/src/components/ToolCallsBlock.tsx frontend/src/components/ChatBubble.tsx frontend/src/components/ActiveSession.tsx
git commit -m "feat(ui): ToolCallsBlock renders structured tool_calls in ChatBubble"
```

---

## Task 10: End-to-end verification

**Files:** none modified — verification-only task.

- [ ] **Step 1: Send a tool-using prompt via the autotest helper**

```bash
cd /home/orbital/projects/pryzm/backend
TOKEN=$(grep PRYZM_API_TOKEN /home/orbital/projects/pryzm/.env | cut -d= -f2)
./venv/bin/python /tmp/pryzm_autotest.py --workspace it_copilot \
    --prompt "Check if reddit.com is up" \
    --expect-tool-any "dns_lookup,check_port,execute_ping"
```

Expected: `OK: tool_calls=['...']`

- [ ] **Step 2: Inspect the saved assistant row**

```bash
PGPASSWORD=postgres psql -h localhost -U pryzm_admin -d pryzm_core -c "
SELECT
    id,
    length(content) AS content_len,
    jsonb_array_length(tool_calls) AS num_tool_calls,
    content ~ '> \*\*Tool:\*\*' AS has_mimicry_marker
FROM messages
WHERE role = 'assistant'
ORDER BY created_at DESC
LIMIT 1;
"
```

Expected:
- `content_len` > 0 (synthesis is present)
- `num_tool_calls` ≥ 1 (structured column populated)
- `has_mimicry_marker = f` (content is clean — no `> **Tool:**` substring)

- [ ] **Step 3: Verify the history endpoint returns tool_calls**

```bash
SESSION=$(PGPASSWORD=postgres psql -h localhost -U pryzm_admin -d pryzm_core -tA -c "SELECT session_id FROM messages WHERE role='assistant' ORDER BY created_at DESC LIMIT 1")
curl -s "http://127.0.0.1:8000/sessions/$SESSION" -H "Authorization: Bearer $TOKEN" | python3 -c "
import sys, json
data = json.load(sys.stdin)
last_asst = [m for m in data if m['role']=='assistant'][-1]
print('tool_calls=', last_asst.get('tool_calls'))
assert last_asst.get('tool_calls'), 'history endpoint did not return tool_calls'
print('OK')
"
```

Expected: `OK` printed; `tool_calls=[{...}]` shown.

- [ ] **Step 4: Run the entire backend test suite**

Run: `cd backend && ./venv/bin/pytest tests/ --ignore=tests/e2e --ignore=tests/perf -q`
Expected: all tests pass (count should be roughly N - 2 from previous, due to deleted mimicry tests; plus the new tests added across tasks 1–4).

- [ ] **Step 5: Run frontend lint and build**

Run: `cd frontend && npm run lint && npm run build 2>&1 | tail -10`
Expected: no errors.

- [ ] **Step 6: Manual UI verification** (the user does this once before merge — surface in the report)

Confirm in the browser:
- Send "Check if reddit.com is up" — tool block renders during streaming AND after refresh
- Send a question with no tool use — no tool block shown
- Refresh an old session (pre-PR) — content with embedded markdown renders the same as before
- Refresh a new session (post-PR) — content is clean prose; tool block renders separately
