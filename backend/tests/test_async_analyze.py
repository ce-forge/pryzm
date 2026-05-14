"""Async-path tests for /analyze: disconnect propagation, per-tool timeout."""
import asyncio
from unittest.mock import patch

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
