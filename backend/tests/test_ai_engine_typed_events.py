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

    # And critically: no text chunk should contain the old markdown markers
    text_chunks = [y for y in yields if isinstance(y, str)]
    combined = "".join(text_chunks)
    assert "> **Tool:**" not in combined
    assert "```text" not in combined
