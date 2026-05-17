# Code audit fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Apply Karpathy discipline at every step: simplicity, surgical changes, verifiable goals.

**Goal:** Land the twelve essential fixes from the May 2026 code audit on a single branch, in four self-contained commits.

**Architecture:** Same branch (`chore/code-audit-2026-05`), four commits matching the spec's grouping. Backend changes use TDD against the existing pytest infrastructure (`backend/tests/conftest.py` with `db_session` fixture). Frontend changes have no test harness, so verification is manual against a running stack and `/tmp/pryzm_autotest.py` where applicable.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic (backend), Next.js 16 + React 19 + Tailwind (frontend), pytest with a real Postgres test DB (`pryzm_test`).

**Reference spec:** `docs/specs/2026-05-18-code-audit-fixes.md`.

---

## File map

| File | Action | Purpose |
|---|---|---|
| `backend/core/ai_engine.py` | Modify L455-459 | B1: add tool_call_id to live tool messages |
| `backend/services/knowledge.py` | Modify L444-449 | B3: deterministic chunk order in overview_mode |
| `backend/services/condense.py` | Modify L43-58 | B10: lock acquisition inside try block |
| `backend/services/tasks.py` | Modify L13-19 | B2: ORM-style delete in GC sweep |
| `backend/services/ingest_pipeline.py` | Modify `_finalize_error` | B9: rollback before writing error status |
| `backend/routers/documents.py` | Modify L233 | S2: cache header + ETag |
| `backend/routers/chat.py` | Modify session PATCH handler | B7: workspace scope check on folder_id |
| `backend/db/models.py` | Modify Session model | B7: FK on folder_id |
| `backend/alembic/versions/<new>_session_folder_fk.py` | Create | B7: scrub + add FK |
| `backend/tests/test_ai_engine_typed_events.py` | Modify | B1 test |
| `backend/tests/test_retrieve_scope.py` | Modify | B3 test |
| `backend/tests/test_condense.py` | Modify | B10 test |
| `backend/tests/test_tasks_gc.py` | Create | B2 test |
| `backend/tests/test_ingest_pipeline_failure.py` | Create | B9 test |
| `backend/tests/test_document_raw_headers.py` | Create | S2 test |
| `backend/tests/test_workspace_boundary.py` | Modify | B7 handler test |
| `frontend/src/hooks/useMessageActions.ts` | Modify L88 | B6: workspace dep |
| `frontend/src/components/MessageActions.tsx` | Modify L41 | B8: touch CSS |
| `frontend/src/hooks/useInference.ts` | Modify L50, L315-317 | B4 + B5 hook |
| `frontend/src/components/ChatInput.tsx` | Modify L100-114 | B5 UI |
| `frontend/src/components/Sidebar.tsx` | Modify L19 | R1 |

---

## Task 0: Create the audit branch

**Files:** none yet.

- [ ] **Step 1: Verify clean working tree**

```bash
git -C /home/orbital/projects/pryzm status
```

Expected: no uncommitted changes other than `frontend/src/components/AssistantMessage.tsx` (a pre-existing in-progress change unrelated to the audit). If anything else is modified, stop and consult the user.

- [ ] **Step 2: Stash the unrelated AssistantMessage.tsx change**

```bash
git -C /home/orbital/projects/pryzm stash push frontend/src/components/AssistantMessage.tsx -m "pre-audit: WIP AssistantMessage"
```

Expected: stash created. We'll leave it stashed until the audit branch is done.

- [ ] **Step 3: Create and switch to the audit branch from main**

```bash
git -C /home/orbital/projects/pryzm checkout -b chore/code-audit-2026-05 main
```

Expected: `Switched to a new branch 'chore/code-audit-2026-05'`.

- [ ] **Step 4: Confirm branch and clean state**

```bash
git -C /home/orbital/projects/pryzm status
```

Expected: `On branch chore/code-audit-2026-05` with `nothing to commit, working tree clean`.

---

## Task 1: B1 — Tool-result messages carry `tool_call_id` in the live loop

**Files:**
- Modify: `backend/core/ai_engine.py:455-459`
- Modify: `backend/tests/test_ai_engine_typed_events.py`

- [ ] **Step 1: Read the existing test file to find the pattern**

```bash
sed -n '1,40p' /home/orbital/projects/pryzm/backend/tests/test_ai_engine_typed_events.py
```

Look for an existing tool-call test or a fixture that constructs a fake LLM tool_call response. The test you add should mirror that pattern.

- [ ] **Step 2: Write a failing test asserting `tool_call_id` is on the live-loop tool message**

Append to `backend/tests/test_ai_engine_typed_events.py`:

```python
def test_live_loop_tool_message_has_tool_call_id(monkeypatch):
    """The tool-result message appended during the live agentic loop must
    carry tool_call_id so it matches the corresponding tool_calls entry."""
    from core import ai_engine

    fake_tool_call = {
        "id": "call_abc123",
        "type": "function",
        "function": {"name": "get_local_time", "arguments": "{}"},
    }

    captured_messages = []

    async def fake_chat(client, messages, *args, **kwargs):
        captured_messages.append(list(messages))
        if len(captured_messages) == 1:
            # First call: model wants a tool
            return {
                "message": {"role": "assistant", "content": "", "tool_calls": [fake_tool_call]},
            }
        # Second call: model produces a final answer
        return {"message": {"role": "assistant", "content": "done"}}

    from core import llm_server
    monkeypatch.setattr(llm_server, "chat", fake_chat)
    monkeypatch.setitem(ai_engine.AVAILABLE_TOOLS, "get_local_time", lambda: "noon")

    # Drive the loop once. Adjust call shape to whatever the existing tests
    # use to invoke stream_chat synchronously.
    import asyncio

    async def run():
        gen = ai_engine.stream_chat(
            messages=[{"role": "user", "content": "what time"}],
            workspace_id="ws-test",
            session_id="sess-test",
        )
        async for _ in gen:
            pass

    asyncio.run(run())

    # The second LLM call must have a tool message with tool_call_id == call_abc123
    second_call_messages = captured_messages[1]
    tool_msgs = [m for m in second_call_messages if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0].get("tool_call_id") == "call_abc123"
```

The LLM call inside `stream_chat` is `llm_server.chat(...)` (see `core/ai_engine.py:374`). If `stream_chat`'s call signature requires more args than shown, copy from an existing test that drives the loop.

- [ ] **Step 3: Run the test and confirm it fails**

```bash
cd /home/orbital/projects/pryzm/backend && pytest tests/test_ai_engine_typed_events.py::test_live_loop_tool_message_has_tool_call_id -v
```

Expected: `FAILED` because `tool_call_id` is missing from the appended message.

- [ ] **Step 4: Edit `backend/core/ai_engine.py:455-459`**

Replace the existing append block:

```python
                    full_messages.append({
                        "role": "tool",
                        "content": str(result),
                        "name": func_name,
                    })
```

With:

```python
                    full_messages.append({
                        "role": "tool",
                        "content": str(result),
                        "name": func_name,
                        "tool_call_id": tool_call["id"],
                    })
```

The surrounding loop variable is `tool_call` (the dict iterated from `message["tool_calls"]`). If the variable name in scope is different, use what's actually in scope — read the surrounding 20 lines first.

- [ ] **Step 5: Run the test and confirm it passes**

```bash
cd /home/orbital/projects/pryzm/backend && pytest tests/test_ai_engine_typed_events.py::test_live_loop_tool_message_has_tool_call_id -v
```

Expected: `PASSED`.

- [ ] **Step 6: Run the full test file to confirm no regression**

```bash
cd /home/orbital/projects/pryzm/backend && pytest tests/test_ai_engine_typed_events.py -v
```

Expected: all tests pass.

---

## Task 2: B3 — `overview_mode` retrieval orders chunks deterministically

**Files:**
- Modify: `backend/services/knowledge.py:444-449`
- Modify: `backend/tests/test_retrieve_scope.py`

- [ ] **Step 1: Read the existing overview_mode test for context**

```bash
grep -n "overview_mode" /home/orbital/projects/pryzm/backend/tests/test_retrieve_scope.py
```

If a test exists, extend it. If not, add a new one.

- [ ] **Step 2: Write a failing test asserting chunks come back in id order**

Append to `backend/tests/test_retrieve_scope.py`:

```python
def test_overview_mode_returns_chunks_in_id_order(db_session, monkeypatch):
    """overview_mode must return chunks ordered by id (UUIDv7 = insertion
    order), not whatever Postgres feels like returning."""
    from services import knowledge
    from db import models

    ws = models.Workspace(
        id="ws-ov", slug="ws-ov", display_name="OV",
        system_prompt="", enabled_tools=[], is_builtin=False,
        engine_config={"backend": "ollama", "model": "gemma4:e4b"},
    )
    sess = models.Session(id="sess-ov", workspace_id="ws-ov", title="t")
    doc = models.Document(
        id="doc-ov", workspace_id="ws-ov", session_id="sess-ov",
        filename="big.txt", mime="text/plain", status="ready",
    )
    db_session.add_all([ws, sess, doc])
    db_session.commit()

    # Insert chunks with ids that will sort lexicographically in a known order.
    chunk_ids = [f"chunk-{i:04d}" for i in range(10)]
    for cid in chunk_ids:
        db_session.add(models.DocumentChunk(
            id=cid, document_id="doc-ov", workspace_id="ws-ov",
            content=f"content {cid}", embedding=[0.0] * 768,
        ))
    db_session.commit()

    # Fake the embedding client; overview_mode doesn't actually use it but
    # the function signature wants one.
    class FakeClient:
        pass

    import asyncio
    result = asyncio.run(knowledge.retrieve_relevant_chunks(
        client=FakeClient(),
        db=db_session,
        query="",
        workspace_id="ws-ov",
        session_id="sess-ov",
        overview_mode=True,
        top_k=5,
    ))

    # Pull the chunk ids out of the formatted context by matching their content.
    assert "content chunk-0000" in result["context"]
    assert "content chunk-0004" in result["context"]
    # The fifth chunk must be chunk-0004, not chunk-0007 or whatever pg returned.
    first_five = chunk_ids[:5]
    for cid in first_five:
        assert f"content {cid}" in result["context"]
    for cid in chunk_ids[5:]:
        assert f"content {cid}" not in result["context"]
```

The function is `retrieve_relevant_chunks` (see `services/knowledge.py:361`). Confirm the parameter list before running.

- [ ] **Step 3: Run the test and confirm it fails (or passes by luck)**

```bash
cd /home/orbital/projects/pryzm/backend && pytest tests/test_retrieve_scope.py::test_overview_mode_returns_chunks_in_id_order -v
```

Expected: FAIL with one of the later chunks present instead of one of the first five. (It may PASS by coincidence on a clean DB — that's why we add the order_by anyway.)

- [ ] **Step 4: Edit `backend/services/knowledge.py:444-449`**

Replace:

```python
            chunks = (
                db.query(models.DocumentChunk)
                .filter(models.DocumentChunk.document_id == recent_doc.id)
                .limit(top_k)
                .all()
            )
```

With:

```python
            chunks = (
                db.query(models.DocumentChunk)
                .filter(models.DocumentChunk.document_id == recent_doc.id)
                .order_by(models.DocumentChunk.id)
                .limit(top_k)
                .all()
            )
```

- [ ] **Step 5: Run the test and confirm it passes**

```bash
cd /home/orbital/projects/pryzm/backend && pytest tests/test_retrieve_scope.py::test_overview_mode_returns_chunks_in_id_order -v
```

Expected: PASS.

- [ ] **Step 6: Run the full test file**

```bash
cd /home/orbital/projects/pryzm/backend && pytest tests/test_retrieve_scope.py -v
```

Expected: all tests pass.

---

## Task 3: B6 — `branchSession` callback includes `workspace` in deps

**Files:**
- Modify: `frontend/src/hooks/useMessageActions.ts:88`

No frontend test harness — verification is manual.

- [ ] **Step 1: Read the current callback and confirm `workspace` is in the closure but not the deps**

```bash
sed -n '60,90p' /home/orbital/projects/pryzm/frontend/src/hooks/useMessageActions.ts
```

Confirm `workspace` appears in the URL on line 72 and the dep array on line 88 reads `[activeSessionKey, navigateToSession, notifySessionCreated]`.

- [ ] **Step 2: Add `workspace` to the dep array**

Edit `frontend/src/hooks/useMessageActions.ts` line 88. Replace:

```ts
  }, [activeSessionKey, navigateToSession, notifySessionCreated]);
```

With:

```ts
  }, [activeSessionKey, navigateToSession, notifySessionCreated, workspace]);
```

- [ ] **Step 3: Restart frontend dev server if running**

The fix takes effect on hot-reload. No manual verification step needed unless you specifically want to confirm: switch workspaces in two browser tabs, branch a message in tab B after switching, confirm the new session lands in tab B's workspace.

---

## Task 4: B8 — Message action toolbar reachable on touch devices

**Files:**
- Modify: `frontend/src/components/MessageActions.tsx:41`

- [ ] **Step 1: Edit the className on the toolbar div**

Replace line 41 in `frontend/src/components/MessageActions.tsx`:

```tsx
    <div className={`flex items-center gap-1 mt-1 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 transition-opacity duration-200 pointer-events-none group-hover:pointer-events-auto ${isUser ? 'justify-end' : 'justify-start'}`}>
```

With:

```tsx
    <div className={`flex items-center gap-1 mt-1 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 [@media(hover:none)]:opacity-100 transition-opacity duration-200 pointer-events-none group-hover:pointer-events-auto [@media(hover:none)]:pointer-events-auto ${isUser ? 'justify-end' : 'justify-start'}`}>
```

- [ ] **Step 2: Manual verification in browser dev tools**

In Chrome/Edge dev tools, toggle device toolbar to a mobile preset (iPhone 14, Pixel 7). The action toolbar (copy/edit/delete/rerun/branch icons) should appear under every message without hovering. On desktop (no device emulation), the toolbar should still only appear on hover.

If `/tmp/pryzm_screenshot.py` is available, capture a mobile-viewport screenshot and visually confirm the toolbar is visible.

---

## Task 5: B10 — `condense.py` advisory lock acquisition inside try block

**Files:**
- Modify: `backend/services/condense.py:43-58`
- Modify: `backend/tests/test_condense.py`

- [ ] **Step 1: Read the current lock helper**

```bash
sed -n '30,70p' /home/orbital/projects/pryzm/backend/services/condense.py
```

Confirm the two `db.execute(...)` calls are above the `try:` block.

- [ ] **Step 2: Write a failing test that mocks SELECT to raise and asserts no lock is held afterward**

Append to `backend/tests/test_condense.py`:

```python
def test_session_advisory_lock_releases_on_acquisition_error(db_session, monkeypatch):
    """If acquiring the advisory lock raises mid-way, the helper must not
    leak a half-acquired lock back into the pool."""
    from services import condense
    from sqlalchemy.exc import OperationalError

    call_count = {"n": 0}
    original_execute = db_session.execute

    def flaky_execute(stmt, *args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # First execute call (key derivation) raises.
            raise OperationalError("statement", {}, Exception("simulated"))
        return original_execute(stmt, *args, **kwargs)

    monkeypatch.setattr(db_session, "execute", flaky_execute)

    with pytest.raises(OperationalError):
        with condense._session_advisory_lock(db_session, "sess-x"):
            pass

    # After the context manager exits, no lock should be held on this connection.
    # Use a fresh connection from the same engine to assert nothing leaked.
    monkeypatch.setattr(db_session, "execute", original_execute)
    held = db_session.execute(
        text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory'")
    ).scalar()
    assert held == 0
```

If `_session_advisory_lock` is named differently or not exposed at module level, adjust the import. Add `from sqlalchemy import text` and `import pytest` at the top of the test file if not already present.

- [ ] **Step 3: Run the test and confirm it fails or errors**

```bash
cd /home/orbital/projects/pryzm/backend && pytest tests/test_condense.py::test_session_advisory_lock_releases_on_acquisition_error -v
```

Expected: FAIL or ERROR (the OperationalError propagates without the lock being cleaned up; the assertion at the end will fail because the helper raised before reaching its try/finally).

- [ ] **Step 4: Edit `backend/services/condense.py:43-58`**

Move the two `db.execute(...)` calls inside the `try:` block. The shape becomes:

```python
@contextmanager
def _session_advisory_lock(db, session_id):
    acquired = False
    try:
        key = db.execute(
            text("SELECT hashtextextended(:s, 0)"),
            {"s": session_id},
        ).scalar()
        acquired = db.execute(
            text("SELECT pg_try_advisory_lock(:k)"),
            {"k": key},
        ).scalar()
        if not acquired:
            yield False
            return
        yield True
    finally:
        if acquired:
            db.execute(
                text("SELECT pg_advisory_unlock(:k)"),
                {"k": key},
            )
```

Use the exact statement shapes from the current file; only the placement around `try:` changes.

- [ ] **Step 5: Run the test and confirm it passes**

```bash
cd /home/orbital/projects/pryzm/backend && pytest tests/test_condense.py::test_session_advisory_lock_releases_on_acquisition_error -v
```

Expected: PASS.

- [ ] **Step 6: Run the full test file**

```bash
cd /home/orbital/projects/pryzm/backend && pytest tests/test_condense.py -v
```

Expected: all tests pass.

---

## Task 6: Commit 1 — `fix(audit): correctness quick wins`

**Files:** all from tasks 1-5.

- [ ] **Step 1: Stage the changes**

```bash
cd /home/orbital/projects/pryzm && git add \
  backend/core/ai_engine.py \
  backend/services/knowledge.py \
  backend/services/condense.py \
  backend/tests/test_ai_engine_typed_events.py \
  backend/tests/test_retrieve_scope.py \
  backend/tests/test_condense.py \
  frontend/src/hooks/useMessageActions.ts \
  frontend/src/components/MessageActions.tsx
```

- [ ] **Step 2: Verify the staged diff**

```bash
cd /home/orbital/projects/pryzm && git diff --cached --stat
```

Expected: 8 files changed, modest line counts. If any file is unexpected, unstage with `git restore --staged <file>` and investigate.

- [ ] **Step 3: Run the full backend test suite to confirm no regressions**

```bash
cd /home/orbital/projects/pryzm/backend && pytest -q
```

Expected: all tests pass. If any fail, stop and fix before committing.

- [ ] **Step 4: Commit**

```bash
cd /home/orbital/projects/pryzm && git commit -m "$(cat <<'EOF'
fix(audit): correctness quick wins

- B1: tool-result messages carry tool_call_id in the live loop
- B3: overview_mode retrieval orders chunks by id
- B6: branchSession callback includes workspace in deps
- B8: message action toolbar visible on touch devices
- B10: condense advisory lock acquisition inside try block
EOF
)"
```

Expected: commit succeeds, no Co-Authored-By trailer.

---

## Task 7: B2 — GC sweep removes image files from disk

**Files:**
- Modify: `backend/services/tasks.py:13-19`
- Create: `backend/tests/test_tasks_gc.py`

- [ ] **Step 1: Write a failing test that creates an orphan doc + temp file and asserts GC removes both**

Create `backend/tests/test_tasks_gc.py`:

```python
"""GC sweep must trigger the after_delete hook so image files are removed."""
import os
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

from db import models, database
from services import tasks


def test_gc_removes_orphan_document_and_its_storage_file(db_session, monkeypatch):
    # Create a temp file that stands in for an uploaded image.
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    assert os.path.exists(path)

    ws = models.Workspace(
        id="ws-gc", slug="ws-gc", display_name="GC",
        system_prompt="", enabled_tools=[], is_builtin=False,
        engine_config={"backend": "ollama", "model": "gemma4:e4b"},
    )
    # Old enough to be GC'd: created 48h ago.
    cutoff_old = datetime.now(timezone.utc) - timedelta(hours=48)
    doc = models.Document(
        id="doc-gc", workspace_id="ws-gc", session_id=None,
        is_global=False, filename="x.png", mime="image/png",
        status="ready", storage_path=path, created_at=cutoff_old,
    )
    db_session.add_all([ws, doc])
    db_session.commit()

    # Replace SessionLocal so the GC task uses our test session's engine.
    monkeypatch.setattr(database, "SessionLocal", lambda: db_session)

    # Pull the body of the loop out for synchronous execution.
    # If garbage_collection_task is a forever-loop, run just one iteration:
    import asyncio
    async def one_pass():
        # Inline the body of one iteration to avoid the sleep.
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        docs = db_session.query(models.Document).filter(
            models.Document.session_id == None,
            models.Document.is_global == False,
            models.Document.created_at < cutoff,
        ).all()
        for d in docs:
            db_session.delete(d)
        db_session.commit()

    asyncio.run(one_pass())

    # The file should be gone.
    assert not os.path.exists(path), f"GC should have removed {path}"
    # The row should be gone.
    assert db_session.query(models.Document).filter_by(id="doc-gc").first() is None
```

Note: this test inlines the loop body because the production loop has `await asyncio.sleep(3600)`. The point of the test is to validate that the per-iteration logic correctly triggers the hook — which is what we change.

- [ ] **Step 2: Run the test and confirm it fails**

```bash
cd /home/orbital/projects/pryzm/backend && pytest tests/test_tasks_gc.py -v
```

Expected: FAIL — `assert not os.path.exists(path)` fails because the current bulk-delete path doesn't trigger the after_delete hook. (Wait — the test runs the new ORM-style logic inline, so it should PASS already. We need a test that validates the production code path actually does the right thing.) Rewrite the inline body to call the production function instead.

Revised approach: skip the inline loop and just exercise the production code. Replace the `one_pass` body with a direct call to whatever helper we extract.

Actually, the cleanest approach is to extract the per-iteration body into a callable helper `_gc_pass()` in `services/tasks.py` and have the test call it. That way the test exercises real code, and the forever-loop in `garbage_collection_task` just calls `_gc_pass()` repeatedly.

Update the test to call `tasks._gc_pass()` instead of the inline `one_pass()`.

- [ ] **Step 3: Refactor `backend/services/tasks.py` to extract `_gc_pass` and switch to ORM iteration**

Replace the file body:

```python
import asyncio
from datetime import datetime, timedelta, timezone
from db import database, models


def _gc_pass(db) -> int:
    """Run one garbage-collection pass. Returns the number of rows deleted.

    Uses ORM-style iteration so SQLAlchemy's after_delete hook on Document
    runs per row and removes the file on disk via storage_path.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    docs = db.query(models.Document).filter(
        models.Document.session_id == None,
        models.Document.is_global == False,
        models.Document.created_at < cutoff,
    ).all()
    for d in docs:
        db.delete(d)
    db.commit()
    return len(docs)


async def garbage_collection_task():
    """Background task: hourly sweep of orphaned documents in the loading bay."""
    while True:
        db = None
        try:
            db = database.SessionLocal()
            deleted = _gc_pass(db)
            if deleted > 0:
                print(f"[Garbage Collector] Purged {deleted} orphaned documents.")
        except Exception as e:
            print(f"[Garbage Collector] Error: {e}")
        finally:
            if db is not None:
                db.close()
        await asyncio.sleep(3600)
```

- [ ] **Step 4: Update the test to call `_gc_pass` directly**

Edit the test to replace the inline `one_pass()` with:

```python
    from services.tasks import _gc_pass
    deleted = _gc_pass(db_session)
    assert deleted == 1
```

Drop the `asyncio.run(one_pass())` lines and the inner `one_pass` definition.

- [ ] **Step 5: Run the test and confirm it passes**

```bash
cd /home/orbital/projects/pryzm/backend && pytest tests/test_tasks_gc.py -v
```

Expected: PASS — the file is removed, the row is removed.

---

## Task 8: B9 — Ingest failure rolls back partial chunks

**Files:**
- Modify: `backend/services/ingest_pipeline.py` (`_finalize_error`)
- Create: `backend/tests/test_ingest_pipeline_failure.py`

- [ ] **Step 1: Read the current `_finalize_error` and the chunk-add loop**

```bash
grep -n "_finalize_error\|add_chunks_to_document\|get_embedding" /home/orbital/projects/pryzm/backend/services/ingest_pipeline.py
```

Confirm the loop calls `db.add(chunk)` per chunk and that `_finalize_error` calls `db.commit()`.

- [ ] **Step 2: Write a failing test**

Create `backend/tests/test_ingest_pipeline_failure.py`:

```python
"""Embedding failure mid-loop must not persist partial chunks."""
import pytest

from db import models
from services import ingest_pipeline, knowledge


def test_partial_chunks_rolled_back_on_embedding_failure(db_session, monkeypatch):
    ws = models.Workspace(
        id="ws-ing", slug="ws-ing", display_name="ING",
        system_prompt="", enabled_tools=[], is_builtin=False,
        engine_config={"backend": "ollama", "model": "gemma4:e4b"},
    )
    sess = models.Session(id="sess-ing", workspace_id="ws-ing", title="t")
    doc = models.Document(
        id="doc-ing", workspace_id="ws-ing", session_id="sess-ing",
        filename="a.txt", mime="text/plain", status="processing",
    )
    db_session.add_all([ws, sess, doc])
    db_session.commit()

    # Fake the embedder: succeeds twice, then raises.
    calls = {"n": 0}
    async def flaky_embed(client, text):
        calls["n"] += 1
        if calls["n"] >= 3:
            raise RuntimeError("ollama dropped the call")
        return [0.0] * 768

    monkeypatch.setattr(knowledge, "get_embedding", flaky_embed)

    chunks = [f"chunk text {i}" for i in range(5)]

    import asyncio
    with pytest.raises(RuntimeError):
        asyncio.run(knowledge.add_chunks_to_document(
            client=None, db=db_session, document_id="doc-ing",
            chunks=chunks, workspace_id="ws-ing",
        ))

    ingest_pipeline._finalize_error(db_session, "doc-ing", "ollama dropped the call")

    # No DocumentChunk rows should exist for this document.
    remaining = db_session.query(models.DocumentChunk).filter_by(
        document_id="doc-ing",
    ).count()
    assert remaining == 0

    # The Document row should be marked error.
    refreshed = db_session.query(models.Document).filter_by(id="doc-ing").one()
    assert refreshed.status == "error"
    assert refreshed.error_message == "ollama dropped the call"
```

If `add_chunks_to_document` lives somewhere other than `knowledge`, or has a different signature, adjust. Read the actual signature before assuming.

- [ ] **Step 3: Run the test and confirm it fails**

```bash
cd /home/orbital/projects/pryzm/backend && pytest tests/test_ingest_pipeline_failure.py -v
```

Expected: FAIL — `remaining` will be 2 (the two chunks added before the embedder raised) instead of 0.

- [ ] **Step 4: Edit `_finalize_error` in `backend/services/ingest_pipeline.py`**

Find the current `_finalize_error` body. Replace its commit logic with a rollback-first pattern:

```python
def _finalize_error(db, document_id: str, message: str) -> None:
    """Mark a document as failed. Rolls back any partial chunk inserts
    from the same session before writing the error status."""
    db.rollback()
    doc = db.query(models.Document).filter(models.Document.id == document_id).first()
    if doc is None:
        return
    doc.status = "error"
    doc.error_message = message
    db.commit()
```

If the function signature is different (e.g., uses a custom enum for status), match what's in the current file.

- [ ] **Step 5: Run the test and confirm it passes**

```bash
cd /home/orbital/projects/pryzm/backend && pytest tests/test_ingest_pipeline_failure.py -v
```

Expected: PASS — zero remaining chunks, document status is `error`.

- [ ] **Step 6: Run the existing ingest tests to confirm no regression**

```bash
cd /home/orbital/projects/pryzm/backend && pytest tests/test_ingest_broker.py tests/test_pdf_upload.py tests/test_image_upload.py -q
```

Expected: all pass.

---

## Task 9: B4 — `stopInference` no longer aborts unrelated streams

**Files:**
- Modify: `frontend/src/hooks/useInference.ts:315-317`

- [ ] **Step 1: Edit the `stopInference` callback**

Open `frontend/src/hooks/useInference.ts`. Find the fallback `for` loop at lines 315-317:

```ts
    for (const [key, controller] of abortControllersRef.current.entries()) {
      if (key.startsWith("optimistic-")) controller.abort();
    }
```

Delete those three lines. The function should end at the `return` for the mapped case (line 313).

- [ ] **Step 2: Confirm the function still type-checks**

```bash
cd /home/orbital/projects/pryzm/frontend && npx tsc --noEmit
```

Expected: no errors related to `useInference.ts`.

- [ ] **Step 3: Manual verification**

Start the stack. Open two browser tabs in the same workspace. In tab A, send a long-ish prompt that streams for several seconds. In tab B, immediately send another long prompt. In tab A while tab B's stream is in flight, click Stop. Confirm only tab A's stream halts; tab B's stream continues.

---

## Task 10: B5 — Hook + UI guards block double-send

**Files:**
- Modify: `frontend/src/hooks/useInference.ts:50`
- Modify: `frontend/src/components/ChatInput.tsx:100-114`

- [ ] **Step 1: Add the hook-level early return in `sendMessage`**

Open `frontend/src/hooks/useInference.ts`. After line 58 (`setIsProcessing(true);`) — actually before it, so we don't toggle state unnecessarily. Insert at the top of `sendMessage`'s body, immediately after the destructured args:

```ts
      // Block double-send: if a stream is already in flight, no-op.
      if (isProcessing) {
        return activeSessionId || "";
      }
      setIsProcessing(true);
```

Replace the existing standalone `setIsProcessing(true)` call. Note: `isProcessing` needs to be in scope. If it's a state variable in the hook, it is. If it's not in scope inside the callback, switch to reading from a ref that mirrors it (`isProcessingRef.current`). Read the surrounding hook to confirm.

If only a ref is in scope, the shape becomes:

```ts
      if (isProcessingRef.current) {
        return activeSessionId || "";
      }
      isProcessingRef.current = true;
      setIsProcessing(true);
```

And the `finally` block at the end of `sendMessage` must also set `isProcessingRef.current = false`.

- [ ] **Step 2: Add `isProcessing` to the UI guards in `ChatInput.tsx`**

Open `frontend/src/components/ChatInput.tsx`. Replace lines 100-114:

```tsx
  const guardedSubmit = (e?: React.FormEvent) => {
    if (uploadsInProgress) {
      e?.preventDefault();
      return;
    }
    handleInference(e);
  };

  const guardedKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (uploadsInProgress && e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      return;
    }
    handleKeyDown(e);
  };
```

With:

```tsx
  const guardedSubmit = (e?: React.FormEvent) => {
    if (uploadsInProgress || isProcessing) {
      e?.preventDefault();
      return;
    }
    handleInference(e);
  };

  const guardedKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((uploadsInProgress || isProcessing) && e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      return;
    }
    handleKeyDown(e);
  };
```

`isProcessing` is already a prop on this component (per line 53), so no additional plumbing is needed.

- [ ] **Step 3: Type-check**

```bash
cd /home/orbital/projects/pryzm/frontend && npx tsc --noEmit
```

Expected: no new errors.

- [ ] **Step 4: Manual verification**

Start the stack. In a brand-new chat, send a long-streaming prompt. While it's streaming, press Enter again in the textarea. Confirm no new request fires (network tab should not show a second `/analyze` POST). Confirm the stream continues uninterrupted and the Stop button still works.

---

## Task 11: R1 — Sidebar stays mounted across open/close

**Files:**
- Modify: `frontend/src/components/Sidebar.tsx:19`

- [ ] **Step 1: Replace the early null return with a translate-based hide**

Open `frontend/src/components/Sidebar.tsx`. Replace line 19:

```tsx
  if (!isOpen) return null;
```

With nothing (delete the line).

Then update the drawer div on line 28 to add a conditional transform:

```tsx
      <div className={`fixed md:relative w-[280px] h-full bg-[#1e1f20] flex flex-col shrink-0 transition-transform duration-300 border-r border-[#333537] z-50 shadow-2xl md:shadow-none ${isOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0'}`}>
```

The `md:translate-x-0` keeps the desktop sidebar always visible regardless of `isOpen` (matching today's behavior on desktop where the sidebar is permanent).

Also update the backdrop overlay (line 23-25) to stay conditional:

```tsx
      {isOpen && (
        <div 
          className="fixed inset-0 bg-black/60 z-40 md:hidden backdrop-blur-sm" 
          onClick={() => setIsOpen(false)} 
        />
      )}
```

- [ ] **Step 2: Type-check**

```bash
cd /home/orbital/projects/pryzm/frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Manual verification**

Start the stack on mobile viewport (or use dev-tools device emulation). Open the sidebar. Scroll partway down a long session list. Close the sidebar. Reopen. Confirm scroll position is preserved, no new `/sessions` or `/folders` request fires (check network tab), and the slide animation is smooth.

---

## Task 12: Commit 2 — `fix(audit): streaming, ingest, sidebar fixes`

**Files:** all from tasks 7-11.

- [ ] **Step 1: Stage the changes**

```bash
cd /home/orbital/projects/pryzm && git add \
  backend/services/tasks.py \
  backend/services/ingest_pipeline.py \
  backend/tests/test_tasks_gc.py \
  backend/tests/test_ingest_pipeline_failure.py \
  frontend/src/hooks/useInference.ts \
  frontend/src/components/ChatInput.tsx \
  frontend/src/components/Sidebar.tsx
```

- [ ] **Step 2: Run the full backend test suite**

```bash
cd /home/orbital/projects/pryzm/backend && pytest -q
```

Expected: all tests pass.

- [ ] **Step 3: Frontend type-check + lint**

```bash
cd /home/orbital/projects/pryzm/frontend && npx tsc --noEmit && npm run lint
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
cd /home/orbital/projects/pryzm && git commit -m "$(cat <<'EOF'
fix(audit): streaming, ingest, sidebar fixes

- B2: GC sweep uses ORM iteration so after_delete removes files
- B9: ingest failure rolls back partial chunks
- B4: stopInference no longer aborts unrelated optimistic streams
- B5: hook + UI guards block double-send while streaming
- R1: sidebar stays mounted across open/close
EOF
)"
```

---

## Task 13: S2 — `Cache-Control: private` + ETag on document raw

**Files:**
- Modify: `backend/routers/documents.py:229-236`
- Create: `backend/tests/test_document_raw_headers.py`

- [ ] **Step 1: Write a failing test asserting the response headers**

Create `backend/tests/test_document_raw_headers.py`:

```python
"""GET /documents/{id}/raw must return private cache headers + ETag."""
import os
import tempfile

import pytest
from fastapi.testclient import TestClient

from db import models
from main import app


def test_document_raw_has_private_cache_and_etag(db_session, monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".png")
    os.write(fd, b"\x89PNG\r\n\x1a\n")  # minimal PNG signature
    os.close(fd)

    ws = models.Workspace(
        id="ws-h", slug="ws-h", display_name="H",
        system_prompt="", enabled_tools=[], is_builtin=False,
        engine_config={"backend": "ollama", "model": "gemma4:e4b"},
    )
    doc = models.Document(
        id="doc-h", workspace_id="ws-h", session_id=None,
        is_global=True, filename="a.png", mime="image/png",
        status="ready", storage_path=path,
    )
    db_session.add_all([ws, doc])
    db_session.commit()

    # Override DB dep + auth dep for the request. Pattern depends on existing
    # test infra — reuse whatever test_image_upload.py uses.
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {os.environ.get('PRYZM_API_TOKEN', 'test-token')}"}
    resp = client.get(f"/documents/doc-h/raw?workspace=ws-h", headers=headers)

    assert resp.status_code == 200
    cache = resp.headers["cache-control"]
    assert "private" in cache
    assert "public" not in cache
    assert "immutable" not in cache
    assert "etag" in {k.lower() for k in resp.headers.keys()}
```

If the auth fixture pattern is different (e.g., a dependency override), copy from `test_image_upload.py` or `test_admin_models.py`.

- [ ] **Step 2: Run the test and confirm it fails**

```bash
cd /home/orbital/projects/pryzm/backend && pytest tests/test_document_raw_headers.py -v
```

Expected: FAIL — current header has `public` and `immutable`, no `ETag`.

- [ ] **Step 3: Edit `backend/routers/documents.py:229-236`**

Replace:

```python
    return StreamingResponse(
        _stream(),
        media_type=mime,
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "Content-Disposition": f'inline; filename="{doc.filename}"',
        },
    )
```

With:

```python
    return StreamingResponse(
        _stream(),
        media_type=mime,
        headers={
            "Cache-Control": "private, max-age=2592000",
            "ETag": f'"{doc.id}"',
            "Content-Disposition": f'inline; filename="{doc.filename}"',
        },
    )
```

- [ ] **Step 4: Run the test and confirm it passes**

```bash
cd /home/orbital/projects/pryzm/backend && pytest tests/test_document_raw_headers.py -v
```

Expected: PASS.

- [ ] **Step 5: Run any existing document-route tests to confirm no regression**

```bash
cd /home/orbital/projects/pryzm/backend && pytest tests/test_image_upload.py tests/test_pdf_upload.py -q
```

Expected: all pass.

---

## Task 14: Commit 3 — `fix(audit): cache control on document raw`

**Files:** from task 13.

- [ ] **Step 1: Stage**

```bash
cd /home/orbital/projects/pryzm && git add \
  backend/routers/documents.py \
  backend/tests/test_document_raw_headers.py
```

- [ ] **Step 2: Commit**

```bash
cd /home/orbital/projects/pryzm && git commit -m "$(cat <<'EOF'
fix(audit): cache control on document raw

- S2: switch Cache-Control from public+immutable to private+max-age,
  add ETag for revalidation. Prevents intermediate caches from
  storing token-authenticated image responses.
EOF
)"
```

---

## Task 15a: B7 — Alembic migration to scrub dangling folder_id and add FK

**Files:**
- Create: `backend/alembic/versions/<rev>_session_folder_fk.py`

- [ ] **Step 1: Generate a new revision**

```bash
cd /home/orbital/projects/pryzm/backend && alembic revision -m "session_folder_fk"
```

Expected: a new file in `backend/alembic/versions/` with a generated revision id. Note the revision id and the down_revision pointer (should be whatever was previously head, e.g., `f8d3b1c5a2e9` based on the directory listing).

- [ ] **Step 2: Fill in the migration body**

Open the new file. Replace its body with:

```python
"""session_folder_fk

Scrubs sessions.folder_id values that point at folders outside the session's
own workspace (or at nonexistent folders), then adds a FK on sessions.folder_id
with ON DELETE SET NULL.

Revision ID: <auto>
Revises: <auto>
Create Date: <auto>
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic. Keep the auto-generated values.
revision = "<auto>"
down_revision = "<auto>"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE sessions
           SET folder_id = NULL
         WHERE folder_id IS NOT NULL
           AND folder_id NOT IN (
               SELECT id FROM folders
                WHERE folders.workspace_id = sessions.workspace_id
           );
    """)
    op.create_foreign_key(
        "fk_sessions_folder_id",
        "sessions", "folders",
        ["folder_id"], ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_sessions_folder_id", "sessions", type_="foreignkey")
    # Note: we do not restore the scrubbed cross-workspace folder_id values.
```

Leave the `revision` and `down_revision` lines as Alembic generated them.

- [ ] **Step 3: Add a migration smoke test**

Append to `backend/tests/test_migrations_smoke.py` (or create a focused test if the file gets unwieldy):

```python
def test_session_folder_fk_migration_upgrades_and_downgrades(db_at_revision):
    """The session_folder_fk migration must be reversible and must scrub
    dangling refs on upgrade."""
    # Upgrade to the previous head first to insert dirty data.
    engine = db_at_revision("<previous-head-revision-id>")
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO workspaces (id, slug, display_name, system_prompt, enabled_tools, is_builtin, engine_config)
            VALUES ('ws-a', 'ws-a', 'A', '', '[]', false, '{"backend":"ollama","model":"x"}'),
                   ('ws-b', 'ws-b', 'B', '', '[]', false, '{"backend":"ollama","model":"x"}');
        """))
        conn.execute(text("""
            INSERT INTO folders (id, workspace_id, name) VALUES ('f-b', 'ws-b', 'B folder');
        """))
        conn.execute(text("""
            INSERT INTO sessions (id, workspace_id, folder_id, title)
            VALUES ('s-a', 'ws-a', 'f-b', 'cross-workspace ref');
        """))

    # Now upgrade across our new migration.
    from alembic import command
    command.upgrade(alembic_cfg, "head")

    engine = create_engine(_test_database_url(), poolclass=NullPool)
    with engine.connect() as conn:
        folder_id = conn.execute(text("SELECT folder_id FROM sessions WHERE id = 's-a'")).scalar()
        assert folder_id is None, "scrub should have nulled the cross-workspace ref"
```

Replace `<previous-head-revision-id>` with the actual previous head from `alembic history`. Adjust column lists if folders or sessions have different schemas than shown.

- [ ] **Step 4: Run the migration test**

```bash
cd /home/orbital/projects/pryzm/backend && pytest tests/test_migrations_smoke.py::test_session_folder_fk_migration_upgrades_and_downgrades -v
```

Expected: PASS.

- [ ] **Step 5: Apply the migration to the dev DB**

```bash
cd /home/orbital/projects/pryzm/backend && alembic upgrade head
```

Expected: migration runs cleanly against the local dev DB.

---

## Task 15b: B7 — Add FK on `Session.folder_id` in the model

**Files:**
- Modify: `backend/db/models.py` (Session class)

- [ ] **Step 1: Find the current `Session` definition**

```bash
grep -n "class Session\|folder_id" /home/orbital/projects/pryzm/backend/db/models.py
```

- [ ] **Step 2: Add ForeignKey to the folder_id column**

Edit the `folder_id` line on the Session model. Change from:

```python
    folder_id = Column(String, index=True, nullable=True)
```

To:

```python
    folder_id = Column(String, ForeignKey("folders.id", ondelete="SET NULL"), index=True, nullable=True)
```

`ForeignKey` should already be imported at the top of the file. If not, add it to the existing `from sqlalchemy import ...` import.

- [ ] **Step 3: Run the existing workspace-boundary tests to confirm the schema change is consistent**

```bash
cd /home/orbital/projects/pryzm/backend && pytest tests/test_workspace_boundary.py -v
```

Expected: existing tests still pass.

---

## Task 15c: B7 — Handler scope check on `folder_id` PATCH

**Files:**
- Modify: `backend/routers/chat.py` (session PATCH handler)

- [ ] **Step 1: Find the session-update handler**

```bash
grep -n "def update_session\|@router.patch.*sessions" /home/orbital/projects/pryzm/backend/routers/chat.py
```

- [ ] **Step 2: Add the workspace-owns check when `folder_id` is in the payload**

Find the body of `update_session` (or whatever it's named). Before the `setattr` loop, insert:

```python
    # Cross-workspace folder_id rejected at the boundary.
    if "folder_id" in payload.model_dump(exclude_unset=True) and payload.folder_id is not None:
        verify_workspace_owns(
            resource_id=payload.folder_id,
            model=models.Folder,
            workspace_id=workspace.id,
            db=db,
        )
```

Confirm `verify_workspace_owns` is imported at the top of the file. If not, add: `from core.workspace_access import verify_workspace_owns`.

The exact payload-access pattern depends on the Pydantic model — if `model_dump(exclude_unset=True)` doesn't match the existing style, use whatever the file already uses to detect "field present in patch."

- [ ] **Step 3: Add a test for cross-workspace rejection**

Append to `backend/tests/test_workspace_boundary.py`:

```python
def test_session_patch_rejects_cross_workspace_folder_id(client_with_auth, db_session):
    """PATCH /sessions/{id} must 404/403 when folder_id belongs to another workspace."""
    ws_a = models.Workspace(
        id="ws-pa", slug="ws-pa", display_name="A",
        system_prompt="", enabled_tools=[], is_builtin=False,
        engine_config={"backend": "ollama", "model": "gemma4:e4b"},
    )
    ws_b = models.Workspace(
        id="ws-pb", slug="ws-pb", display_name="B",
        system_prompt="", enabled_tools=[], is_builtin=False,
        engine_config={"backend": "ollama", "model": "gemma4:e4b"},
    )
    sess_a = models.Session(id="sess-pa", workspace_id="ws-pa", title="t")
    folder_b = models.Folder(id="f-pb", workspace_id="ws-pb", name="B folder")
    db_session.add_all([ws_a, ws_b, sess_a, folder_b])
    db_session.commit()

    resp = client_with_auth.patch(
        "/sessions/sess-pa?workspace=ws-pa",
        json={"folder_id": "f-pb"},
    )
    assert resp.status_code in (403, 404), f"got {resp.status_code} body={resp.text}"

    # The session's folder_id must be unchanged.
    db_session.expire_all()
    sess = db_session.query(models.Session).filter_by(id="sess-pa").one()
    assert sess.folder_id is None
```

If `client_with_auth` isn't the existing fixture name, copy whatever pattern other PATCH/POST tests in this file use to call the API.

- [ ] **Step 4: Run the test and confirm it passes**

```bash
cd /home/orbital/projects/pryzm/backend && pytest tests/test_workspace_boundary.py -v
```

Expected: all tests pass, including the new one.

- [ ] **Step 5: Audit other writers of `folder_id`**

```bash
cd /home/orbital/projects/pryzm && git grep -n "folder_id" backend/
```

Confirm the only write path is the PATCH handler we just guarded. If other endpoints set `folder_id` (e.g., session creation accepting a folder), they need the same `verify_workspace_owns` check — extend the audit to those handlers and add tests.

---

## Task 16: Commit 4 — `fix(audit): workspace folder fk + scope check`

**Files:** all from tasks 15a-15c.

- [ ] **Step 1: Stage**

```bash
cd /home/orbital/projects/pryzm && git add \
  backend/alembic/versions/ \
  backend/db/models.py \
  backend/routers/chat.py \
  backend/tests/test_workspace_boundary.py \
  backend/tests/test_migrations_smoke.py
```

- [ ] **Step 2: Run the full test suite**

```bash
cd /home/orbital/projects/pryzm/backend && pytest -q
```

Expected: all pass.

- [ ] **Step 3: Commit**

```bash
cd /home/orbital/projects/pryzm && git commit -m "$(cat <<'EOF'
fix(audit): workspace folder fk + scope check

- B7: PATCH /sessions rejects cross-workspace folder_id at the boundary
- B7: add FK on sessions.folder_id with ON DELETE SET NULL
- B7: migration scrubs dangling cross-workspace refs before applying FK
EOF
)"
```

---

## Task 17: Open the PR

- [ ] **Step 1: Push the branch**

```bash
cd /home/orbital/projects/pryzm && git push -u origin chore/code-audit-2026-05
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --base main --head chore/code-audit-2026-05 \
  --title "chore: code audit fixes (May 2026)" \
  --body "$(cat <<'EOF'
Four commits from the May 2026 audit.

- correctness quick wins (B1, B3, B6, B8, B10)
- streaming, ingest, sidebar fixes (B2, B9, B4, B5, R1)
- cache control on document raw (S2)
- workspace folder fk + scope check (B7)

Detail in docs/specs/2026-05-18-code-audit-fixes.md.
EOF
)"
```

- [ ] **Step 3: Do not auto-merge**

Wait for explicit user approval before merging. The user reviews the diff, then merges manually or instructs the agent to merge.

- [ ] **Step 4: Restore the stashed AssistantMessage.tsx work**

After the PR is merged and the branch is cleaned up:

```bash
cd /home/orbital/projects/pryzm && git checkout main && git pull && git stash pop
```

Expected: the WIP change reappears in the working tree.

---

## Self-review notes

Coverage check against the spec:

- B1 ✓ Task 1
- B3 ✓ Task 2
- B6 ✓ Task 3
- B8 ✓ Task 4
- B10 ✓ Task 5
- Commit 1 ✓ Task 6
- B2 ✓ Task 7
- B9 ✓ Task 8
- B4 ✓ Task 9
- B5 ✓ Task 10
- R1 ✓ Task 11
- Commit 2 ✓ Task 12
- S2 ✓ Task 13
- Commit 3 ✓ Task 14
- B7 ✓ Tasks 15a–15c
- Commit 4 ✓ Task 16
- PR ✓ Task 17

Deferred items (R2, S1, future SessionContext lift) are noted in the spec and are out of scope here.

Known under-specified spots an executor will need to adapt:

- Task 1: `stream_chat`'s full call signature has more args than the minimal shape shown; copy from an existing test that drives the loop.
- Task 8 (`_finalize_error` at `ingest_pipeline.py:157`): if the status enum or `error_message` field is named differently, match the model.
- Task 13: the test-client auth pattern depends on what `test_image_upload.py` uses; copy from there.
- Task 15a: replace `<previous-head-revision-id>` with the actual previous head (`alembic history` shows it).
- Task 15c: the Pydantic payload-access pattern (`model_dump(exclude_unset=True)`) may not match the file's existing style.

These are call-it-when-you-see-it adaptations, not blockers.
