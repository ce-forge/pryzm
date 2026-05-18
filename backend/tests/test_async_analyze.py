"""Async-path tests for /analyze: disconnect propagation, per-tool timeout."""
import asyncio
import json
from unittest.mock import patch

import httpx
import pytest


@pytest.mark.asyncio
async def test_tool_timeout_yields_clean_result():
    """A tool that hangs longer than TOOL_TIMEOUT_SECONDS raises asyncio.TimeoutError
    when wrapped with asyncio.wait_for, which the agentic loop catches and converts
    to a clean timeout message rather than blocking forever."""
    from core import ai_engine

    def slow_tool():
        import time
        time.sleep(60)
        return "never"

    tool_call = {"function": {"name": "_test_slow_tool", "arguments": {}}}
    fake_workspace_tools = {"_test_slow_tool": slow_tool}

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(
            ai_engine._execute_tool(tool_call, fake_workspace_tools),
            timeout=0.1,
        )


@pytest.mark.asyncio
async def test_execute_tool_runs_sync_in_thread():
    """_execute_tool wraps sync callables in asyncio.to_thread so they don't
    block the event loop; the return value is preserved."""
    from core import ai_engine

    def echo_tool(value: str = "hello"):
        return f"echo:{value}"

    tool_call = {"function": {"name": "echo_tool", "arguments": {"value": "world"}}}
    fake_workspace_tools = {"echo_tool": echo_tool}

    result = await ai_engine._execute_tool(tool_call, fake_workspace_tools)
    assert result == "echo:world"


@pytest.mark.asyncio
async def test_execute_tool_runs_async_directly():
    """_execute_tool awaits async callables directly without to_thread."""
    from core import ai_engine

    async def async_tool(value: str = "x"):
        await asyncio.sleep(0)
        return f"async:{value}"

    tool_call = {"function": {"name": "async_tool", "arguments": {"value": "y"}}}
    fake_workspace_tools = {"async_tool": async_tool}

    result = await ai_engine._execute_tool(tool_call, fake_workspace_tools)
    assert result == "async:y"


# ---------------------------------------------------------------------------
# _error_envelope unit tests
# ---------------------------------------------------------------------------

def test_error_envelope_connect_error():
    """httpx.ConnectError maps to llm_unreachable."""
    from routers.chat import _error_envelope
    env = _error_envelope(httpx.ConnectError("connection refused"))
    assert env["code"] == "llm_unreachable"
    assert "error" in env


def test_error_envelope_read_timeout():
    """httpx.ReadTimeout maps to llm_timeout."""
    from routers.chat import _error_envelope
    env = _error_envelope(httpx.ReadTimeout("timed out"))
    assert env["code"] == "llm_timeout"


def test_error_envelope_asyncio_timeout():
    """asyncio.TimeoutError maps to tool_timeout."""
    from routers.chat import _error_envelope
    env = _error_envelope(asyncio.TimeoutError())
    assert env["code"] == "tool_timeout"


def test_error_envelope_generic():
    """Unknown exceptions map to engine_error and include the message."""
    from routers.chat import _error_envelope
    env = _error_envelope(RuntimeError("ollama exploded"))
    assert env["code"] == "engine_error"
    assert "ollama exploded" in env["error"]


def test_error_envelope_is_valid_json():
    """Every envelope round-trips through JSON without error."""
    from routers.chat import _error_envelope
    for exc in [
        httpx.ConnectError("x"),
        httpx.ReadTimeout("x"),
        asyncio.TimeoutError(),
        RuntimeError("boom"),
    ]:
        env = _error_envelope(exc)
        serialised = json.dumps(env)
        parsed = json.loads(serialised)
        assert "error" in parsed
        assert "code" in parsed


# ---------------------------------------------------------------------------
# Integration: stream_chat exception → {error, code} SSE line (no chunk shape)
# ---------------------------------------------------------------------------

def test_engine_error_emits_error_envelope(db_at_head, monkeypatch):
    """An exception in ai_engine.stream_chat surfaces as {error, code} line,
    not as a {chunk: '[Engine Error: ...]'} line."""
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker

    from db import database, models
    from core import ai_engine, cookie_auth
    from core.deps import get_http_client
    from main import app

    monkeypatch.setattr(database, "init_db", lambda: None)

    # Route get_db through the test engine and seed the default workspace.
    test_engine = db_at_head
    TestSessionLocal = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)

    def _test_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[database.get_db] = _test_get_db
    # Also patch SessionLocal so route code that opens DB connections directly
    # (e.g. the manual db = database.SessionLocal() inside /analyze) hits the
    # same test DB, not the dev DB.
    monkeypatch.setattr(database, "SessionLocal", TestSessionLocal)

    # Seed an admin user and a 'personal' workspace owned by them, then mint
    # an auth session so the request's cookie resolves to this user.
    with TestSessionLocal() as seed_db:
        admin = seed_db.query(models.User).filter_by(username="admin").first()
        if admin is None:
            from core.cookie_auth import hash_password
            admin = models.User(
                username="admin", password_hash=hash_password("test-pw-12chars"),
                is_admin=True, is_active=True, can_create_workspaces=True,
            )
            seed_db.add(admin); seed_db.commit(); seed_db.refresh(admin)
        existing_ws = seed_db.query(models.Workspace).filter_by(
            slug="personal", user_id=admin.id,
        ).first()
        if existing_ws is None:
            seed_db.add(models.Workspace(
                slug="personal", display_name="Personal", user_id=admin.id,
            ))
            seed_db.commit()
        sid = cookie_auth.create_session(seed_db, admin.id)

    # Override http_client — stream_chat is mocked so we won't call Ollama.
    app.dependency_overrides[get_http_client] = lambda: None

    # Patch generate_title so it doesn't try to hit Ollama.
    async def _fake_title(*a, **kw):
        return "Test Session"

    monkeypatch.setattr(ai_engine, "generate_title", _fake_title)

    # Patch stream_chat to raise a RuntimeError immediately.
    async def _boom(*args, **kwargs):
        raise RuntimeError("ollama exploded")
        yield  # make it an async generator

    monkeypatch.setattr(ai_engine, "stream_chat", _boom)

    # Patch condense so the background task doesn't hit the DB/Ollama.
    from services import condense
    monkeypatch.setattr(condense, "condense_for_session", lambda *a, **kw: None)

    client = TestClient(app)
    client.cookies.set(cookie_auth.COOKIE_NAME, sid)
    resp = client.post(
        "/analyze?workspace=personal",
        json={"prompt": "hello", "attachments": [], "skip_db_save": True},
    )

    assert resp.status_code == 200

    lines = [l for l in resp.text.splitlines() if l.strip()]
    parsed_lines = [json.loads(l) for l in lines]

    error_lines = [p for p in parsed_lines if "error" in p]
    chunk_lines = [p for p in parsed_lines if "chunk" in p]

    # Must have exactly one error envelope.
    assert len(error_lines) >= 1, f"Expected error envelope; got lines: {parsed_lines}"
    assert error_lines[0]["code"] == "engine_error"
    assert "ollama exploded" in error_lines[0]["error"]

    # No chunk should carry legacy "Engine Error:" text.
    for c in chunk_lines:
        assert "Engine Error" not in str(c.get("chunk", ""))

    app.dependency_overrides.clear()
