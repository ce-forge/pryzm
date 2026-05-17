"""Verify ai_engine yields typed tool_call / tool_result dicts instead of
text-emitted format_tool_execution / format_code_block markdown."""
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio
import pytest

from core.ai_engine import stream_chat
from core.llm_router import Tier
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

    mock_router = MagicMock()
    mock_router.small = "small-model"
    mock_router.large = "large-model"
    mock_router.pick.return_value = ("small-model", Tier.SMALL, "test")

    yields: list = []
    with patch("core.ai_engine.llm_server.chat", new=fake_chat), \
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

    async def fake_chat(client, messages, *args, **kwargs):
        captured_messages.append([dict(m) for m in messages])
        if len(captured_messages) == 1:
            return {"message": {"role": "assistant", "content": "", "tool_calls": [fake_tool_call]}}
        return {"message": {"role": "assistant", "content": "done"}}

    mock_workspace = models.Workspace(
        id="ws-test", slug="it_copilot", display_name="IT Copilot",
        system_prompt="You are a test.", enabled_tools=["get_local_time"],
        is_builtin=True, engine_config={"backend": "llama_cpp"},
    )

    mock_router = MagicMock()
    mock_router.small = "small-model"
    mock_router.large = "large-model"
    mock_router.pick.return_value = ("small-model", Tier.SMALL, "test")

    with patch("core.ai_engine.llm_server.chat", new=fake_chat), \
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
