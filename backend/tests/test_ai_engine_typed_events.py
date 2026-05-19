"""Verify ai_engine yields typed tool_call / tool_result dicts instead of
text-emitted format_tool_execution / format_code_block markdown."""
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio
import json
import pytest

from core.ai_engine import stream_chat
from core.llm_router import Tier
from tools.registry import ResolvedToolSet
from db import models


def _message_to_deltas(message: dict, finish_reason: str | None = None):
    """Convert a full message dict (Ollama shape — `{content, reasoning_content,
    tool_calls}`) into the SSE delta sequence llama-server emits in streaming
    mode. See docs/internal/2026-05-20-llama-server-sse-shape.md. The loop's
    chat_stream consumer is what these tests exercise; the dict-shape mock
    pre-dated streaming."""
    # Role marker — always first.
    yield {"role": "assistant", "content": None}

    reasoning = message.get("reasoning_content")
    if reasoning:
        yield {"reasoning_content": reasoning}

    content = message.get("content")
    if content:
        yield {"content": content}

    tool_calls = message.get("tool_calls") or []
    if tool_calls:
        finish_reason = finish_reason or "tool_calls"
        for tc in tool_calls:
            args = tc["function"].get("arguments", {})
            if isinstance(args, dict):
                args = json.dumps(args)
            yield {"tool_calls": [{
                "index": 0,
                "id": tc.get("id", "test-call-id"),
                "type": "function",
                "function": {
                    "name": tc["function"]["name"],
                    "arguments": args,
                },
            }]}

    yield {"finish_reason": finish_reason or "stop"}


def _async_iter_from_message(message: dict):
    """Build the async-generator chat_stream() returns, sourced from one
    full message. Use this to convert pre-streaming mock responses."""
    async def _gen(*_args, **_kwargs):
        for delta in _message_to_deltas(message):
            yield delta
    return _gen


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
        {"tool_calls": [{"function": {"name": "_probe_typed_event_tool", "arguments": {"query": "foo"}}}]},
        {"content": "Done."},
    ])

    def fake_chat_stream(*_args, **_kwargs):
        msg = next(responses)
        async def _gen():
            for delta in _message_to_deltas(msg):
                yield delta
        return _gen()

    mock_workspace = models.Workspace(
        id="ws-test", slug="it_copilot", display_name="IT Copilot",
        system_prompt="You are a test.", enabled_tools=["_probe_typed_event_tool"],
        engine_config={"backend": "llama_cpp"},
    )

    mock_router = MagicMock()
    mock_router.small = "small-model"
    mock_router.large = "large-model"
    mock_router.pick.return_value = ("small-model", Tier.SMALL, "test")

    yields: list = []
    with patch("core.ai_engine.llm_server.chat_stream", new=fake_chat_stream), \
         patch("core.ai_engine.database.SessionLocal") as mock_db_local, \
         patch("core.ai_engine.get_router", return_value=mock_router):
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

    # Critically: tool-call markers must not appear inline in text chunks
    # (tool events ride a separate typed channel).
    text_chunks = [y for y in yields if isinstance(y, str)]
    combined = "".join(text_chunks)
    assert "> **Tool:**" not in combined
    assert "```text" not in combined


@pytest.mark.asyncio
async def test_live_loop_tool_message_has_tool_call_id():
    """The tool-result message appended during the live agentic loop must
    carry tool_call_id so it matches the corresponding tool_calls entry."""

    def _fake_tool(workspace_id: str = "", session_id: str = None) -> str:
        return "noon"

    callables = {"get_local_time": _fake_tool}
    definitions = [{
        "type": "function",
        "function": {
            "name": "get_local_time",
            "description": "test",
            "parameters": {"type": "object", "properties": {}, "required": []},
        }
    }]
    tool_set = ResolvedToolSet(callables=callables, definitions=definitions, per_tool_config={})

    fake_tool_call = {
        "id": "call_abc123",
        "type": "function",
        "function": {"name": "get_local_time", "arguments": "{}"},
    }

    captured_messages: list = []

    def fake_chat_stream(client, messages, *args, **kwargs):
        captured_messages.append([dict(m) for m in messages])
        if len(captured_messages) == 1:
            msg = {"role": "assistant", "content": "", "tool_calls": [fake_tool_call]}
        else:
            msg = {"role": "assistant", "content": "done"}
        async def _gen():
            for delta in _message_to_deltas(msg):
                yield delta
        return _gen()

    mock_workspace = models.Workspace(
        id="ws-test", slug="it_copilot", display_name="IT Copilot",
        system_prompt="You are a test.", enabled_tools=["get_local_time"],
        engine_config={"backend": "llama_cpp"},
    )

    mock_router = MagicMock()
    mock_router.small = "small-model"
    mock_router.large = "large-model"
    mock_router.pick.return_value = ("small-model", Tier.SMALL, "test")

    with patch("core.ai_engine.llm_server.chat_stream", new=fake_chat_stream), \
         patch("core.ai_engine.database.SessionLocal") as mock_db_local, \
         patch("core.ai_engine.get_router", return_value=mock_router):
        mock_db = mock_db_local.return_value
        mock_db.query.return_value.filter.return_value.first.return_value = mock_workspace

        async for _ in stream_chat(
            client=None,
            messages=[{"role": "user", "content": "what time"}],
            workspace_id="ws-test",
            engine_config={"backend": "llama_cpp"},
            tool_set=tool_set,
            session_id="sess-test",
        ):
            pass

    # The second LLM call must have a tool message with tool_call_id == call_abc123
    assert len(captured_messages) >= 2, f"expected at least 2 LLM calls, got {len(captured_messages)}"
    second_call_messages = captured_messages[1]
    tool_msgs = [m for m in second_call_messages if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0].get("tool_call_id") == "call_abc123"


@pytest.mark.asyncio
async def test_reasoning_content_yields_typed_events():
    """When the LLM returns a `reasoning_content` field alongside `content`,
    stream_chat fake-streams the reasoning as {type: reasoning_chunk} events
    BEFORE any content words, and emits a {type: reasoning_done} terminator
    with a duration_s. Models without reasoning_content produce neither event."""

    fake_chat_stream = _async_iter_from_message({
        "role": "assistant",
        "content": "The answer is forty-two.",
        "reasoning_content": "Step one: consider the question. Step two: answer it.",
    })

    mock_workspace = models.Workspace(
        id="ws-test", slug="it_copilot", display_name="IT Copilot",
        system_prompt="You are a test.", enabled_tools=[],
        engine_config={"backend": "llama_cpp"},
    )

    mock_router = MagicMock()
    mock_router.small = "small-model"
    mock_router.large = "large-model"
    mock_router.pick.return_value = ("small-model", Tier.SMALL, "test")
    mock_router.catalog = {"small-model": {"reasoning"}, "large-model": {"reasoning"}}

    tool_set = ResolvedToolSet(callables={}, definitions=[], per_tool_config={})

    yields: list = []
    with patch("core.ai_engine.llm_server.chat_stream", new=fake_chat_stream), \
         patch("core.ai_engine.database.SessionLocal") as mock_db_local, \
         patch("core.ai_engine.get_router", return_value=mock_router):
        mock_db = mock_db_local.return_value
        mock_db.query.return_value.filter.return_value.first.return_value = mock_workspace

        async for item in stream_chat(
            client=None,
            messages=[{"role": "user", "content": "hi"}],
            workspace_id="ws-test",
            engine_config={"backend": "llama_cpp"},
            tool_set=tool_set,
            session_id="s-reasoning",
        ):
            yields.append(item)

    reasoning_chunks = [y for y in yields if isinstance(y, dict) and y.get("type") == "reasoning_chunk"]
    reasoning_done = [y for y in yields if isinstance(y, dict) and y.get("type") == "reasoning_done"]
    text_chunks = [y for y in yields if isinstance(y, str)]

    assert reasoning_chunks, "expected reasoning_chunk events"
    assembled = "".join(c["chunk"] for c in reasoning_chunks).strip()
    assert assembled == "Step one: consider the question. Step two: answer it."

    assert len(reasoning_done) == 1
    assert isinstance(reasoning_done[0]["duration_s"], (int, float))
    assert reasoning_done[0]["duration_s"] >= 0

    # Final answer still streams as plain text chunks AFTER reasoning_done.
    assert "forty-two" in "".join(text_chunks)
    first_text_index = next(i for i, y in enumerate(yields) if isinstance(y, str))
    last_reasoning_index = max(
        i for i, y in enumerate(yields)
        if isinstance(y, dict) and y.get("type") in {"reasoning_chunk", "reasoning_done"}
    )
    assert last_reasoning_index < first_text_index


@pytest.mark.asyncio
async def test_absent_reasoning_content_emits_nothing_extra():
    """A response with no `reasoning_content` field (or empty string) should
    NOT emit reasoning_chunk or reasoning_done events. Older / non-thinking
    models flow through unchanged."""

    fake_chat_stream = _async_iter_from_message(
        {"role": "assistant", "content": "Plain answer."}
    )

    mock_workspace = models.Workspace(
        id="ws-test", slug="it_copilot", display_name="IT Copilot",
        system_prompt="You are a test.", enabled_tools=[],
        engine_config={"backend": "llama_cpp"},
    )

    mock_router = MagicMock()
    mock_router.small = "small-model"
    mock_router.large = "large-model"
    mock_router.pick.return_value = ("small-model", Tier.SMALL, "test")

    tool_set = ResolvedToolSet(callables={}, definitions=[], per_tool_config={})

    yields: list = []
    with patch("core.ai_engine.llm_server.chat_stream", new=fake_chat_stream), \
         patch("core.ai_engine.database.SessionLocal") as mock_db_local, \
         patch("core.ai_engine.get_router", return_value=mock_router):
        mock_db = mock_db_local.return_value
        mock_db.query.return_value.filter.return_value.first.return_value = mock_workspace

        async for item in stream_chat(
            client=None,
            messages=[{"role": "user", "content": "hi"}],
            workspace_id="ws-test",
            engine_config={"backend": "llama_cpp"},
            tool_set=tool_set,
            session_id="s-no-reasoning",
        ):
            yields.append(item)

    reasoning_events = [
        y for y in yields
        if isinstance(y, dict) and y.get("type") in {"reasoning_chunk", "reasoning_done"}
    ]
    assert reasoning_events == []
    assert "Plain answer" in "".join(y for y in yields if isinstance(y, str))


@pytest.mark.asyncio
async def test_reasoning_content_suppressed_for_unreasoning_models():
    """Models NOT tagged `reasoning` in the catalog must not surface their
    reasoning_content as typed SSE events — small chat models emit short,
    low-signal CoT that adds noise on regular turns. Gating happens at the
    backend so DB rows stay empty too."""

    fake_chat_stream = _async_iter_from_message({
        "role": "assistant",
        "content": "Plain answer.",
        "reasoning_content": "Thinking Process: 1. Read. 2. Respond.",
    })

    mock_workspace = models.Workspace(
        id="ws-test", slug="it_copilot", display_name="IT Copilot",
        system_prompt="You are a test.", enabled_tools=[],
        engine_config={"backend": "llama_cpp"},
    )

    mock_router = MagicMock()
    mock_router.small = "small-model"
    mock_router.large = "large-model"
    mock_router.pick.return_value = ("small-model", Tier.SMALL, "test")
    # small-model has no `reasoning` tag — gate must suppress emission.
    mock_router.catalog = {"small-model": set(), "large-model": {"reasoning"}}

    tool_set = ResolvedToolSet(callables={}, definitions=[], per_tool_config={})

    yields: list = []
    with patch("core.ai_engine.llm_server.chat_stream", new=fake_chat_stream), \
         patch("core.ai_engine.database.SessionLocal") as mock_db_local, \
         patch("core.ai_engine.get_router", return_value=mock_router):
        mock_db = mock_db_local.return_value
        mock_db.query.return_value.filter.return_value.first.return_value = mock_workspace

        async for item in stream_chat(
            client=None,
            messages=[{"role": "user", "content": "hi"}],
            workspace_id="ws-test",
            engine_config={"backend": "llama_cpp"},
            tool_set=tool_set,
            session_id="s-gated",
        ):
            yields.append(item)

    reasoning_events = [
        y for y in yields
        if isinstance(y, dict) and y.get("type") in {"reasoning_chunk", "reasoning_done"}
    ]
    assert reasoning_events == [], "reasoning_chunk/done must not fire for untagged models"
    assert "Plain answer" in "".join(y for y in yields if isinstance(y, str))
