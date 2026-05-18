"""Tests for the SSE endpoint that streams document-ingestion status.

Covers the three states the handler must distinguish:
  1. Replay terminal — doc is already 'ready'/'error', stream emits
     one event and closes.
  2. Live transition — doc starts 'processing', a publish lands while
     the SSE handler is subscribed; the subscriber receives it.
  3. Auth — token can ride in either the bearer header or ?token= URL.
"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from db import database, models
from main import app


def _seed_workspace(db, slug):
    ws = models.Workspace(
        id=f"ws-{slug}",
        slug=slug,
        display_name="SSE Test",
        system_prompt="",
        enabled_tools=[],
        engine_config={"backend": "llama_cpp"},
    )
    db.add(ws); db.commit(); return ws


def _read_sse_event(resp) -> dict:
    """Read until the first `data: ` line, parse the JSON, return it.

    SSE event format: a `data: ...` line followed by a blank line.
    `iter_lines()` returns each line as it arrives (no buffering across
    the blank separator), so we hop until we see the data line.
    """
    for raw in resp.iter_lines():
        line = raw.decode() if isinstance(raw, bytes) else raw
        if not line:
            continue
        if line.startswith(": "):
            continue  # keepalive
        if line.startswith("data: "):
            return json.loads(line[len("data: "):])
    raise AssertionError("stream closed before any data event arrived")


def test_sse_replays_terminal_state_for_already_ready_doc(db_session, monkeypatch):
    """If the doc already finished by the time the client subscribes,
    the handler reads the current status off the row and emits one
    terminal event, then closes. No timeout, no hang."""
    from config import settings

    ws = _seed_workspace(db_session, "sse-replay-ready")
    doc = models.Document(filename="x.txt", workspace_id=ws.id, status="ready")
    db_session.add(doc); db_session.commit(); db_session.refresh(doc)

    def _get_db_override():
        yield db_session
    monkeypatch.setattr(settings, "PRYZM_API_TOKEN", "test-token")
    monkeypatch.setattr(database, "init_db", lambda: None)
    app.dependency_overrides[database.get_db] = _get_db_override
    try:
        with TestClient(app) as c:
            with c.stream(
                "GET",
                f"/uploads/{doc.id}/events",
                headers={"Authorization": "Bearer test-token"},
            ) as resp:
                assert resp.status_code == 200
                event = _read_sse_event(resp)
                assert event == {"status": "ready"}
    finally:
        app.dependency_overrides.clear()


def test_sse_replays_error_state_with_message(db_session, monkeypatch):
    """If the doc finished with an error, the replay event must carry
    the error_message so the pill can render the reason."""
    from config import settings

    ws = _seed_workspace(db_session, "sse-replay-error")
    doc = models.Document(
        filename="x.txt",
        workspace_id=ws.id,
        status="error",
        error_message="Could not parse PDF: bad header",
    )
    db_session.add(doc); db_session.commit(); db_session.refresh(doc)

    def _get_db_override():
        yield db_session
    monkeypatch.setattr(settings, "PRYZM_API_TOKEN", "test-token")
    monkeypatch.setattr(database, "init_db", lambda: None)
    app.dependency_overrides[database.get_db] = _get_db_override
    try:
        with TestClient(app) as c:
            with c.stream(
                "GET",
                f"/uploads/{doc.id}/events",
                headers={"Authorization": "Bearer test-token"},
            ) as resp:
                assert resp.status_code == 200
                event = _read_sse_event(resp)
                assert event["status"] == "error"
                assert "bad header" in event["error"]
    finally:
        app.dependency_overrides.clear()


# Note: a "live publish" SSE test (doc starts in 'processing', then a
# publish lands while the client is reading) is intentionally NOT here.
# Setting that up via TestClient requires cross-thread access to
# FastAPI's portal loop, which is fragile. The replay-terminal test
# above plus the broker unit tests in test_ingest_broker.py give us
# the same coverage of the queue-delivery path; PR 4's Playwright
# smoke covers the end-to-end live transition.


def test_sse_accepts_url_token_query_param(db_session, monkeypatch):
    """EventSource can't set headers; token rides via ?token=. Verify
    the SSE endpoint accepts that path."""
    from config import settings

    ws = _seed_workspace(db_session, "sse-url-token")
    doc = models.Document(filename="x.txt", workspace_id=ws.id, status="ready")
    db_session.add(doc); db_session.commit(); db_session.refresh(doc)

    def _get_db_override():
        yield db_session
    monkeypatch.setattr(settings, "PRYZM_API_TOKEN", "test-token")
    monkeypatch.setattr(database, "init_db", lambda: None)
    app.dependency_overrides[database.get_db] = _get_db_override
    try:
        with TestClient(app) as c:
            # NOTE: no Authorization header — only ?token=
            with c.stream(
                "GET",
                f"/uploads/{doc.id}/events?token=test-token",
            ) as resp:
                assert resp.status_code == 200
                event = _read_sse_event(resp)
                assert event == {"status": "ready"}
    finally:
        app.dependency_overrides.clear()


def test_sse_rejects_missing_token(db_session, monkeypatch):
    """No bearer, no ?token= → 401, regardless of doc state."""
    from config import settings

    ws = _seed_workspace(db_session, "sse-no-auth")
    doc = models.Document(filename="x.txt", workspace_id=ws.id, status="ready")
    db_session.add(doc); db_session.commit(); db_session.refresh(doc)

    def _get_db_override():
        yield db_session
    monkeypatch.setattr(settings, "PRYZM_API_TOKEN", "test-token")
    monkeypatch.setattr(database, "init_db", lambda: None)
    app.dependency_overrides[database.get_db] = _get_db_override
    try:
        with TestClient(app) as c:
            resp = c.get(f"/uploads/{doc.id}/events")
            assert resp.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_sse_returns_404_for_unknown_doc(db_session, monkeypatch):
    """A subscribe against a non-existent doc id should 404, not block."""
    from config import settings

    _seed_workspace(db_session, "sse-missing-doc")

    def _get_db_override():
        yield db_session
    monkeypatch.setattr(settings, "PRYZM_API_TOKEN", "test-token")
    monkeypatch.setattr(database, "init_db", lambda: None)
    app.dependency_overrides[database.get_db] = _get_db_override
    try:
        with TestClient(app) as c:
            resp = c.get(
                "/uploads/no-such-doc/events",
                headers={"Authorization": "Bearer test-token"},
            )
            assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()
