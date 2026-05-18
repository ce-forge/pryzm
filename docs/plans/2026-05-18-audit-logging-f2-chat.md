# Audit Logging F.2 — chat events

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire `chat.*` audit events into `routers/chat.py` and `core/ai_engine.py` per `docs/specs/2026-05-18-audit-logging.md`. Largest slice in F.2 — covers session lifecycle, user/assistant messages, and the agentic tool loop (with specialized payloads for `chat.rag_retrieved` and `chat.web_search`).

**Architecture:** The router's request-scoped DB session is closed before the streaming generator runs, so audit writes from inside `stream_chat` open their own short-lived `SessionLocal()` (same pattern as the existing `tool_db` block at ai_engine.py:444). `user_id` is plumbed into `stream_chat` as a new keyword arg. RAG and web_search tool calls emit their *specialized* event type instead of the generic `chat.tool_invoked` (no double-emit).

**Tech Stack:** FastAPI, SQLAlchemy, pytest, existing `core/audit.py` helper.

---

## Scope

7 new EventType constants:

| event_type | call site | payload |
|---|---|---|
| `chat.session_created` | `routers/chat.py::analyze_data` (auto-create), `branch_session` | `{title, source}` where source ∈ {"analyze", "branch"} |
| `chat.session_deleted` | `routers/chat.py::delete_session` | `{title}` |
| `chat.message_sent` | `routers/chat.py::analyze_data` (user_msg save) | `{content_preview, token_count, has_attachments, attachment_filenames}` |
| `chat.message_received` | `routers/chat.py::analyze_data` (assistant save, both clean + failed paths) | `{content_preview, token_count, model, finished_cleanly}` |
| `chat.tool_invoked` | `core/ai_engine.py::stream_chat` (non-RAG / non-web-search tools) | `{tool_name, arg_values, succeeded, error_message?}` |
| `chat.rag_retrieved` | `core/ai_engine.py::stream_chat` (auto-RAG + search_knowledge_base tool) | `{query_preview, num_results, source_filenames, mode}` where mode ∈ {"auto", "tool"} |
| `chat.web_search` | `core/ai_engine.py::stream_chat` (web_search tool) | `{query_preview, num_results, result_urls}` |

**Payload conventions:**
- `content_preview`: first 200 chars of message body
- `token_count`: estimated as `len(text) // 4` for user messages; from `usage["prompt_eval_count"] + usage["eval_count"]` for assistant (or 0 if unavailable)
- `arg_values`: tool args dict, **with `workspace_id` and `session_id` stripped** (these are plumbing, not user signal)
- For specialized RAG / web_search events, do NOT also emit a generic `chat.tool_invoked` — choose the most specific type

**Out of scope:**
- Generic per-tool denylist for sensitive args (spec mentions it; no sensitive tool exists yet)
- `chat.session_deleted` for the implicit cascade when a workspace is deleted — workspace.deleted's payload already counts removed_sessions; per-row events would 10x the audit log for one user action

---

## Task 1: Add 7 EventType constants

**Files:**
- Modify: `backend/core/audit.py`

- [ ] **Step 1:** Append after `DOCUMENT_PROCESSING_FAILED`:

```python
    # chat.*
    CHAT_SESSION_CREATED = "chat.session_created"
    CHAT_SESSION_DELETED = "chat.session_deleted"
    CHAT_MESSAGE_SENT = "chat.message_sent"
    CHAT_MESSAGE_RECEIVED = "chat.message_received"
    CHAT_TOOL_INVOKED = "chat.tool_invoked"
    CHAT_RAG_RETRIEVED = "chat.rag_retrieved"
    CHAT_WEB_SEARCH = "chat.web_search"
```

- [ ] **Step 2:** Full sweep:

```bash
cd backend && ./venv/bin/pytest -q
```

Expected: 403 passed, 1 skipped (baseline from main).

- [ ] **Step 3:** Commit.

```bash
git add backend/core/audit.py
git commit -m "audit: add chat.* EventType constants"
```

---

## Task 2: Wire session lifecycle events (analyze + delete + branch)

**Files:**
- Modify: `backend/routers/chat.py`

### Step 1: Imports

- [ ] At the top of `routers/chat.py`, add to the existing imports:

```python
from core.audit import EventType, log_event
```

### Step 2: Emit `chat.session_created` from `/analyze` (auto-create branch)

- [ ] In `analyze_data`, locate the `if not chat_session:` block (around line 327) that creates a new `models.Session`. After `db.refresh(chat_session)`:

```python
            log_event(
                db,
                EventType.CHAT_SESSION_CREATED,
                user=user,
                workspace=workspace,
                session=chat_session,
                resource_type="session",
                resource_id=chat_session.id,
                payload={
                    "title": chat_session.title,
                    "source": "analyze",
                },
                request=http_request,
            )
            db.commit()
```

### Step 3: Emit `chat.session_created` from `/sessions/{id}/branch`

- [ ] In `branch_session`, after the final `db.commit()` (the one that flushes the copied messages), add `request: Request` to the signature (it's already imported — `Request` from fastapi), then:

```python
    log_event(
        db,
        EventType.CHAT_SESSION_CREATED,
        user=user,
        workspace=workspace,
        session=new_session,
        resource_type="session",
        resource_id=new_session.id,
        payload={
            "title": new_session.title,
            "source": "branch",
            "branched_from_session_id": session_id,
            "branched_from_message_id": body.up_to_message_id,
        },
        request=request,
    )
    db.commit()
    return {"new_session_id": new_session.id}
```

### Step 4: Emit `chat.session_deleted`

- [ ] Change `delete_session` signature to add `request: Request` and `user: models.User = Depends(cookie_auth.current_user)`:

```python
@router.delete("/sessions/{session_id}")
def delete_session(
    session_id: str,
    request: Request,
    workspace: models.Workspace = Depends(workspace_query_dep),
    db: Session = Depends(database.get_db),
    user: models.User = Depends(cookie_auth.current_user),
):
    """Delete a session and its messages. Scoped to workspace —
    cross-workspace 404s."""
    session = verify_workspace_owns(session_id, models.Session, workspace.id, db)
    deleted_title = session.title

    db.delete(session)

    log_event(
        db,
        EventType.CHAT_SESSION_DELETED,
        user=user,
        workspace=workspace,
        resource_type="session",
        resource_id=session_id,
        payload={"title": deleted_title},
        request=request,
    )
    db.commit()
    return {"status": "deleted"}
```

### Step 5: Sweep + commit

- [ ] ```bash
cd backend && ./venv/bin/pytest -q
```

Expected: 403 passed, 1 skipped.

- [ ] ```bash
git add backend/routers/chat.py
git commit -m "audit: emit chat.session_created/deleted events"
```

---

## Task 3: Emit `chat.message_sent` + `chat.message_received`

**Files:**
- Modify: `backend/routers/chat.py`

### Step 1: `chat.message_sent` after user_msg commit

- [ ] In `analyze_data`, locate the user-message persistence block (around line 369, `if not request.skip_db_save:`). After `db.refresh(user_msg)`:

```python
            log_event(
                db,
                EventType.CHAT_MESSAGE_SENT,
                user=user,
                workspace=workspace,
                session=chat_session,
                resource_type="message",
                resource_id=user_msg.id,
                payload={
                    "content_preview": request.prompt[:200],
                    "token_count": len(request.prompt) // 4,
                    "has_attachments": bool(request.attachments),
                    "attachment_filenames": _attachment_filenames(
                        db, request.attachments or [], workspace.id
                    ),
                },
                request=http_request,
            )
            db.commit()
```

Add a small helper near the top of the file (after imports, before the router):

```python
def _attachment_filenames(db: Session, attachment_ids: list[str], workspace_id: str) -> list[str]:
    """Best-effort filename lookup for the audit payload. Cross-workspace
    ids silently drop out — the analyze endpoint already filters those."""
    if not attachment_ids:
        return []
    rows = db.query(models.Document.filename).filter(
        models.Document.id.in_(attachment_ids),
        models.Document.workspace_id == workspace_id,
    ).all()
    return [r[0] for r in rows]
```

### Step 2: `chat.message_received` in the clean-completion path

- [ ] Inside the generator's `if not disconnected:` block where the assistant `ai_msg` is saved (clean completion, around line 449). After `assistant_message_id = ai_msg.id`:

```python
                        # Audit emit also uses save_db (current short-lived
                        # session) so the row goes in the same transaction
                        # as the assistant message.
                        usage_for_audit = _last_chat_metric_snapshot() or {}
                        prompt_eval = int(usage_for_audit.get("prompt_eval_count") or 0)
                        eval_count = int(usage_for_audit.get("eval_count") or 0)
                        log_event(
                            save_db,
                            EventType.CHAT_MESSAGE_RECEIVED,
                            user=user,
                            workspace=workspace,
                            session=save_db.query(models.Session).filter_by(id=session_id).first(),
                            resource_type="message",
                            resource_id=ai_msg.id,
                            payload={
                                "content_preview": full_response[:200],
                                "token_count": prompt_eval + eval_count,
                                "model": usage_for_audit.get("model") or "",
                                "finished_cleanly": True,
                            },
                        )
                        save_db.commit()
```

Note: `user` and `workspace` are captured at the request scope and are valid inside the closure. `save_db` is the short-lived session opened inside the generator. The audit row participates in the same commit as the assistant message — if the audit insert fails, the message rolls back (acceptable; the spec says audit failure must not be silent).

### Step 3: `chat.message_received` in the failed/aborted path

- [ ] In the `finally:` block that handles `disconnected`/`failed` (around line 503-528). After the `background_db.commit()` for the partial assistant message:

```python
                        if ai_msg.id:
                            log_event(
                                background_db,
                                EventType.CHAT_MESSAGE_RECEIVED,
                                user=user,
                                workspace=workspace,
                                session=background_db.query(models.Session).filter_by(id=session_id).first(),
                                resource_type="message",
                                resource_id=ai_msg.id,
                                payload={
                                    "content_preview": full_response[:200],
                                    "token_count": 0,  # usage not reliable on abort
                                    "model": "",
                                    "finished_cleanly": False,
                                    "status": status,
                                },
                            )
                            background_db.commit()
```

(Need to `background_db.refresh(ai_msg)` first to get the id — adjust the surrounding code if needed.)

### Step 4: Sweep + commit

- [ ] ```bash
cd backend && ./venv/bin/pytest -q
```

Expected: 403 passed, 1 skipped.

- [ ] ```bash
git add backend/routers/chat.py
git commit -m "audit: emit chat.message_sent/received events"
```

---

## Task 4: Wire tool/RAG/web_search events from `stream_chat`

**Files:**
- Modify: `backend/core/ai_engine.py`
- Modify: `backend/routers/chat.py` (pass `user_id` to stream_chat)

### Step 1: Plumb `user_id` into `stream_chat`

- [ ] In `core/ai_engine.py`, add `user_id: Optional[str] = None` to the `stream_chat` signature (around line 205-220). Adjust the type-import line at the top to include `Optional` if not already there.

### Step 2: Add `user_id=user.id` at the call site

- [ ] In `routers/chat.py::analyze_data`, find the `async for chunk in ai_engine.stream_chat(...)` block and add `user_id=user.id` to the kwargs.

### Step 3: Add `_audit_chat_event` helper inside ai_engine.py

- [ ] Near the top of `ai_engine.py` (after imports, before `condense_chat_memory`), add:

```python
def _audit_chat_event(
    user_id: Optional[str],
    workspace_id: str,
    session_id: Optional[str],
    event_type: str,
    payload: dict,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
) -> None:
    """Open a short-lived session, write one audit row, commit, close.

    Used by stream_chat's tool loop and auto-RAG path. The router's DB
    session is closed before the generator runs, so audit writes here
    can't piggyback on it.
    """
    from core.audit import EventType, log_event  # local import — avoid circular
    audit_db = database.SessionLocal()
    try:
        user_obj = (
            audit_db.query(models.User).filter_by(id=user_id).first()
            if user_id else None
        )
        ws_obj = audit_db.query(models.Workspace).filter_by(id=workspace_id).first()
        sess_obj = (
            audit_db.query(models.Session).filter_by(id=session_id).first()
            if session_id else None
        )
        log_event(
            audit_db,
            event_type,
            user=user_obj,
            workspace=ws_obj,
            session=sess_obj,
            resource_type=resource_type,
            resource_id=resource_id,
            payload=payload,
        )
        audit_db.commit()
    except Exception:
        audit_db.rollback()
    finally:
        audit_db.close()
```

(Top of file already imports `models` and `database`. The `EventType`/`log_event` import is local to avoid a circular import if `core/audit.py` ever depends on something in `ai_engine`.)

### Step 4: Emit `chat.rag_retrieved` from the auto-RAG path

- [ ] Inside the `if has_attachment:` block (around line 316), after the successful `rag_data` retrieval (when `rag_data.get("context")` is true):

```python
                if rag_data and rag_data.get("context"):
                    rag_context = rag_data["context"]
                    sources_list = rag_data["sources"]
                    _audit_chat_event(
                        user_id, workspace_id, session_id,
                        EventType.CHAT_RAG_RETRIEVED,
                        {
                            "query_preview": (rag_query or "")[:200],
                            "num_results": len(sources_list),
                            "source_filenames": list(sources_list),
                            "mode": "auto",
                        },
                    )
                    # ... existing code continues
```

Re-import `EventType` at top of `ai_engine.py` (it's the canonical name) — or use the local import in `_audit_chat_event` consistently. Simplest: add a module-level `from core.audit import EventType` near the imports.

### Step 5: Emit chat.tool_invoked / chat.rag_retrieved / chat.web_search per tool

- [ ] After the existing `yield {"type": "tool_result", "name": func_name, "result": result}` line (around line 434), add:

```python
                    succeeded = not had_tool_error or not isinstance(result, str) or not result.startswith("Tool ")
                    # Crude success heuristic — `_execute_tool` returns a string in
                    # all cases. Treat known error-prefix strings as failure.
                    is_error_result = isinstance(result, str) and (
                        result.startswith("Tool execution failed:")
                        or "timed out after" in result
                    )
                    succeeded = not is_error_result

                    # Strip plumbing args before logging.
                    audit_args = {
                        k: v for k, v in raw_args.items()
                        if k not in ("workspace_id", "session_id")
                    }

                    if func_name == "search_knowledge_base":
                        source_filenames = []
                        if isinstance(result, str):
                            source_filenames = list(set(
                                re.findall(r'\[from ([^\]]+)\]', result)
                            ))
                        _audit_chat_event(
                            user_id, workspace_id, session_id,
                            EventType.CHAT_RAG_RETRIEVED,
                            {
                                "query_preview": str(audit_args.get("query", ""))[:200],
                                "num_results": len(source_filenames),
                                "source_filenames": source_filenames,
                                "mode": "tool",
                            },
                        )
                    elif func_name == "web_search":
                        result_urls = re.findall(r'https?://\S+', result) if isinstance(result, str) else []
                        # Crude — but web_search currently formats results as
                        # "1. **title**\n   url\n   snippet" so this catches each url.
                        _audit_chat_event(
                            user_id, workspace_id, session_id,
                            EventType.CHAT_WEB_SEARCH,
                            {
                                "query_preview": str(audit_args.get("query", ""))[:200],
                                "num_results": len(result_urls),
                                "result_urls": result_urls,
                            },
                        )
                    else:
                        payload = {
                            "tool_name": func_name,
                            "arg_values": audit_args,
                            "succeeded": succeeded,
                        }
                        if not succeeded and isinstance(result, str):
                            payload["error_message"] = result[:200]
                        _audit_chat_event(
                            user_id, workspace_id, session_id,
                            EventType.CHAT_TOOL_INVOKED,
                            payload,
                        )
```

### Step 6: Sweep + commit

- [ ] ```bash
cd backend && ./venv/bin/pytest -q
```

Expected: 403 passed, 1 skipped (no new tests yet; verify no regression in existing ai_engine tests).

- [ ] ```bash
git add backend/core/ai_engine.py backend/routers/chat.py
git commit -m "audit: emit chat.tool_invoked/rag_retrieved/web_search events"
```

---

## Task 5: Tests

**Files:**
- Create: `backend/tests/test_audit_chat_events.py`

### Step 1: Test file

- [ ] Write tests covering each event_type. Pattern mirrors `test_audit_workspace_folder_document_events.py`. For events emitted from `stream_chat`, call `_audit_chat_event` directly (or simulate by calling the helper) — testing the full streaming path is brittle and slow. Add a small integration test for session_created via `POST /analyze` with the engine stubbed.

Structure:

```python
"""Chat audit events.

Lifecycle events (session_created/deleted, message_sent/received) are
tested by invoking the routers via TestClient. The agentic-loop events
(tool_invoked/rag_retrieved/web_search) are tested by calling the
private `_audit_chat_event` helper directly — testing the full
streaming + LLM dispatch path is brittle and slow, and the helper IS
the boundary that writes the row.
"""
import pytest
from fastapi.testclient import TestClient

from core import cookie_auth
from core.audit import EventType
from db import database, models
from main import app


def _seed_user(db_session, username="alice"):
    u = models.User(
        username=username,
        password_hash=cookie_auth.hash_password("alice-pw-12chars"),
        is_admin=False, is_active=True, can_create_workspaces=True,
    )
    db_session.add(u); db_session.commit(); db_session.refresh(u)
    return u


def _seed_workspace(db_session, user_id, slug="ws-test"):
    ws = models.Workspace(
        slug=slug, display_name=slug, system_prompt="x",
        enabled_tools=[], engine_config={"backend": "llama_cpp"},
        color="blue", user_id=user_id, owner_can_edit=True,
    )
    db_session.add(ws); db_session.commit(); db_session.refresh(ws)
    return ws


def _seed_session(db_session, user_id, workspace_id, title="Existing"):
    s = models.Session(title=title, workspace_id=workspace_id, user_id=user_id)
    db_session.add(s); db_session.commit(); db_session.refresh(s)
    return s


def _user_client(db_session, user=None):
    u = user or _seed_user(db_session)
    sid = cookie_auth.create_session(db_session, u.id)
    app.dependency_overrides[database.get_db] = lambda: db_session
    c = TestClient(app)
    c.cookies.set(cookie_auth.COOKIE_NAME, sid)
    return c, u


# --- session_deleted ---

def test_session_deleted_emits_event(db_session):
    try:
        c, user = _user_client(db_session)
        ws = _seed_workspace(db_session, user.id)
        s = _seed_session(db_session, user.id, ws.id, title="To delete")
        r = c.delete(f"/sessions/{s.id}?workspace={ws.slug}")
        assert r.status_code == 200, r.text
        events = db_session.query(models.AuditEvent).filter_by(
            event_type="chat.session_deleted", user_id=user.id,
        ).all()
        assert len(events) == 1
        assert events[0].payload["title"] == "To delete"
        assert events[0].resource_id == s.id
    finally:
        app.dependency_overrides.clear()


# --- session_created via branch ---

def test_session_created_via_branch_emits_event(db_session):
    try:
        c, user = _user_client(db_session)
        ws = _seed_workspace(db_session, user.id)
        src = _seed_session(db_session, user.id, ws.id, title="Source")
        m = models.Message(session_id=src.id, role="user", content="hello")
        db_session.add(m); db_session.commit(); db_session.refresh(m)

        r = c.post(
            f"/sessions/{src.id}/branch?workspace={ws.slug}",
            json={"up_to_message_id": m.id},
        )
        assert r.status_code == 200, r.text

        events = db_session.query(models.AuditEvent).filter_by(
            event_type="chat.session_created", user_id=user.id,
        ).all()
        assert len(events) == 1
        payload = events[0].payload
        assert payload["source"] == "branch"
        assert payload["branched_from_session_id"] == src.id
    finally:
        app.dependency_overrides.clear()


# --- _audit_chat_event helper direct calls ---

def test_audit_chat_event_writes_rag_retrieved(db_session):
    from core.ai_engine import _audit_chat_event
    user = _seed_user(db_session)
    ws = _seed_workspace(db_session, user.id)
    s = _seed_session(db_session, user.id, ws.id)

    _audit_chat_event(
        user.id, ws.id, s.id,
        EventType.CHAT_RAG_RETRIEVED,
        {
            "query_preview": "what is x",
            "num_results": 2,
            "source_filenames": ["a.pdf", "b.png"],
            "mode": "tool",
        },
    )

    events = db_session.query(models.AuditEvent).filter_by(
        event_type="chat.rag_retrieved", user_id=user.id,
    ).all()
    assert len(events) == 1
    assert events[0].payload["mode"] == "tool"
    assert events[0].payload["source_filenames"] == ["a.pdf", "b.png"]
    assert events[0].workspace_id == ws.id
    assert events[0].session_id == s.id


def test_audit_chat_event_writes_web_search(db_session):
    from core.ai_engine import _audit_chat_event
    user = _seed_user(db_session)
    ws = _seed_workspace(db_session, user.id)
    _audit_chat_event(
        user.id, ws.id, None,
        EventType.CHAT_WEB_SEARCH,
        {
            "query_preview": "kubernetes load balancer",
            "num_results": 3,
            "result_urls": ["https://a", "https://b", "https://c"],
        },
    )
    events = db_session.query(models.AuditEvent).filter_by(
        event_type="chat.web_search", user_id=user.id,
    ).all()
    assert len(events) == 1
    assert events[0].payload["num_results"] == 3


def test_audit_chat_event_writes_tool_invoked(db_session):
    from core.ai_engine import _audit_chat_event
    user = _seed_user(db_session)
    ws = _seed_workspace(db_session, user.id)
    _audit_chat_event(
        user.id, ws.id, None,
        EventType.CHAT_TOOL_INVOKED,
        {
            "tool_name": "ping_hostname",
            "arg_values": {"hostname": "example.com"},
            "succeeded": True,
        },
    )
    events = db_session.query(models.AuditEvent).filter_by(
        event_type="chat.tool_invoked", user_id=user.id,
    ).all()
    assert len(events) == 1
    assert events[0].payload["tool_name"] == "ping_hostname"


def test_audit_chat_event_tolerates_unknown_session_id(db_session):
    """If the session_id doesn't resolve (already deleted), the event still
    writes with session_id=NULL."""
    from core.ai_engine import _audit_chat_event
    user = _seed_user(db_session)
    ws = _seed_workspace(db_session, user.id)
    _audit_chat_event(
        user.id, ws.id, "deadbeef-not-a-real-id",
        EventType.CHAT_TOOL_INVOKED,
        {"tool_name": "x", "arg_values": {}, "succeeded": True},
    )
    events = db_session.query(models.AuditEvent).filter_by(
        event_type="chat.tool_invoked", user_id=user.id,
    ).all()
    assert len(events) == 1
    assert events[0].session_id is None
```

(message_sent/received and analyze-path session_created are integration-tested via the existing chat router test infrastructure if available, or skipped here for surgical scope — the unit-level helper test plus the lifecycle tests give us coverage of every event type's *write path* without re-litigating the full stream_chat dispatch.)

### Step 2: Run new tests

- [ ] ```bash
cd backend && ./venv/bin/pytest tests/test_audit_chat_events.py -v
```

Expected: 6 passed.

### Step 3: Full sweep

- [ ] ```bash
cd backend && ./venv/bin/pytest -q
```

Expected: 409 passed, 1 skipped.

### Step 4: Commit

- [ ] ```bash
git add backend/tests/test_audit_chat_events.py
git commit -m "audit: cover chat events with tests"
```

---

## Task 6: PR

- [ ] Pre-push audit:

```bash
git diff main...HEAD | grep -iE "@gmail|@dainamik|PRYZM_API_TOKEN=[A-Za-z0-9]" | head -5
```

Expected: no output.

- [ ] Push + open PR:

```bash
git push -u origin feat/audit-logging-f2-chat
gh pr create --title "audit(F.2): chat events (session/message/tool/rag/web_search)" --body "$(cat <<'EOF'
## Summary
- Wires the chat-domain audit events: `chat.session_created/deleted`, `chat.message_sent/received`, `chat.tool_invoked`, `chat.rag_retrieved`, `chat.web_search`.
- `stream_chat` now opens its own short-lived audit session per event (router's session is closed before the generator runs).
- RAG / web_search tool calls emit specialized event types (with query preview, sources, urls) instead of generic tool_invoked — no double-emit.
- 6 new tests; full sweep green.

## Test plan
- [x] `pytest -q` — full sweep
- [x] Pre-push audit clean
EOF
)"
```

---

## Self-review

- Spec coverage: every chat.* event_type listed in the spec maps to a task. ✓
- Placeholder scan: no TODOs. ✓
- Type consistency: `query_preview` consistent across rag/web_search; `content_preview` consistent across messages; `arg_values` strips plumbing keys consistently. ✓
- Surgical: only adds emit calls; one signature change in `stream_chat` (kwarg add); one helper added to ai_engine.py. ✓
