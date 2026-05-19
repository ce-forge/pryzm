"""Unit tests for llm_server.chat_stream() against the captured llama-server
SSE shape. Mocks httpx's client.stream() context manager with a tiny fake
that yields canned `data: {json}` lines, matching what the live container
produces. Reference: docs/internal/2026-05-20-llama-server-sse-shape.md"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import AsyncIterator
from unittest.mock import MagicMock

import httpx
import pytest

from core import llm_server


def _sse(event: dict) -> str:
    return "data: " + json.dumps(event)


def _delta_event(delta: dict, finish_reason: str | None = None,
                 timings: dict | None = None) -> str:
    event: dict = {
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
        "model": "test-model",
    }
    if timings is not None:
        event["timings"] = timings
    return _sse(event)


class _FakeResponse:
    """Stands in for httpx.Response inside an `async with client.stream(...)`
    block. status_code is read first; aiter_lines yields the canned SSE."""

    def __init__(self, lines: list[str], status_code: int = 200,
                 body_bytes: bytes = b""):
        self.status_code = status_code
        self._lines = lines
        self._body_bytes = body_bytes
        self.request = MagicMock()

    async def aiter_lines(self) -> AsyncIterator[str]:
        for line in self._lines:
            yield line

    async def aread(self) -> bytes:
        return self._body_bytes


def _fake_client(lines: list[str], status_code: int = 200,
                 body_bytes: bytes = b"") -> MagicMock:
    """Build a MagicMock client whose `.stream(...)` returns an async context
    manager yielding the given SSE lines."""

    @asynccontextmanager
    async def _stream_ctx(*_args, **_kwargs):
        yield _FakeResponse(lines, status_code=status_code, body_bytes=body_bytes)

    client = MagicMock()
    client.stream = _stream_ctx
    return client


@pytest.mark.asyncio
async def test_chat_stream_yields_role_then_reasoning_then_content_then_terminal():
    """Mirrors probe1 from the SSE shape doc: role marker, reasoning_content
    chunks, content chunks, then a terminal event with finish_reason=stop
    and timings. Each upstream event yields one dict; the terminal event
    carries finish_reason in the yielded dict."""
    lines = [
        _delta_event({"role": "assistant", "content": None}),
        _delta_event({"reasoning_content": "First, "}),
        _delta_event({"reasoning_content": "think."}),
        _delta_event({"content": "7"}),
        _delta_event({}, finish_reason="stop",
                     timings={"prompt_ms": 100.0, "predicted_ms": 50.0,
                              "prompt_n": 10, "predicted_n": 5}),
        "data: [DONE]",
    ]
    client = _fake_client(lines)

    yields = []
    async for delta in llm_server.chat_stream(
        client, messages=[{"role": "user", "content": "hi"}],
        tools=None, model="test-model",
    ):
        yields.append(delta)

    assert yields == [
        {"role": "assistant", "content": None},
        {"reasoning_content": "First, "},
        {"reasoning_content": "think."},
        {"content": "7"},
        {"finish_reason": "stop"},
    ]


@pytest.mark.asyncio
async def test_chat_stream_yields_tool_call_deltas_as_separate_events():
    """Probe2 shape: reasoning chunks, then tool-call deltas (first delta has
    id/type/name + opening "{"; subsequent deltas carry only index +
    arguments fragments). chat_stream is intentionally dumb — it yields
    each delta untouched; the ai_engine consumer is what assembles by
    index. This test pins the wire shape, not the accumulator."""
    lines = [
        _delta_event({"role": "assistant", "content": None}),
        _delta_event({"reasoning_content": "Need weather."}),
        _delta_event({"tool_calls": [{
            "index": 0,
            "id": "call_abc",
            "type": "function",
            "function": {"name": "get_weather", "arguments": "{"},
        }]}),
        _delta_event({"tool_calls": [{
            "index": 0,
            "function": {"arguments": "\"location\":\"NYC\"}"},
        }]}),
        _delta_event({}, finish_reason="tool_calls",
                     timings={"prompt_ms": 50.0, "predicted_ms": 30.0,
                              "prompt_n": 8, "predicted_n": 3}),
        "data: [DONE]",
    ]
    client = _fake_client(lines)

    yields = []
    async for delta in llm_server.chat_stream(
        client, messages=[], tools=[{"type": "function"}], model="test-model",
    ):
        yields.append(delta)

    tool_call_deltas = [d for d in yields if "tool_calls" in d]
    assert len(tool_call_deltas) == 2
    assert tool_call_deltas[0]["tool_calls"][0]["function"]["name"] == "get_weather"
    assert tool_call_deltas[0]["tool_calls"][0]["function"]["arguments"] == "{"
    assert tool_call_deltas[1]["tool_calls"][0]["function"]["arguments"] == "\"location\":\"NYC\"}"
    # No name field on subsequent deltas — accumulator in ai_engine handles
    # the first-only semantics.
    assert "name" not in tool_call_deltas[1]["tool_calls"][0].get("function", {})
    assert yields[-1] == {"finish_reason": "tool_calls"}


@pytest.mark.asyncio
async def test_chat_stream_ignores_malformed_lines_and_keepalives():
    """Real SSE streams include keepalive comments (`: comment`) and blank
    lines between events. Bad JSON inside a `data:` line should be dropped
    silently, not crash the stream."""
    lines = [
        "",                                                # blank
        ": llama-server keepalive",                        # SSE comment
        "data: not-json-at-all",                           # garbage
        _delta_event({"role": "assistant", "content": None}),
        "data: {malformed",                                # truncated JSON
        _delta_event({"content": "ok"}),
        _delta_event({}, finish_reason="stop"),
        "data: [DONE]",
    ]
    client = _fake_client(lines)

    yields = [d async for d in llm_server.chat_stream(
        client, messages=[], tools=None, model="test-model",
    )]
    assert yields == [
        {"role": "assistant", "content": None},
        {"content": "ok"},
        {"finish_reason": "stop"},
    ]


@pytest.mark.asyncio
async def test_chat_stream_raises_on_upstream_4xx_with_body_detail():
    """llama-server returns JSON error bodies. The streaming entry point
    surfaces the same `error.message` detail the non-streaming chat()
    path does, so callers can tell `model not found` from `context
    overflow`."""
    body = json.dumps({"error": {"message": "model 'nope' not found"}}).encode()
    client = _fake_client(lines=[], status_code=404, body_bytes=body)

    with pytest.raises(httpx.HTTPStatusError) as excinfo:
        async for _ in llm_server.chat_stream(
            client, messages=[], tools=None, model="nope",
        ):
            pass
    assert "model 'nope' not found" in str(excinfo.value)
    assert "404" in str(excinfo.value)


@pytest.mark.asyncio
async def test_chat_stream_terminates_cleanly_on_done_sentinel():
    """`data: [DONE]` ends the stream even if more lines follow."""
    lines = [
        _delta_event({"role": "assistant", "content": None}),
        _delta_event({"content": "hi"}),
        _delta_event({}, finish_reason="stop"),
        "data: [DONE]",
        _delta_event({"content": "should not reach here"}),
    ]
    client = _fake_client(lines)

    yields = [d async for d in llm_server.chat_stream(
        client, messages=[], tools=None, model="test-model",
    )]
    assert {"content": "should not reach here"} not in yields
    # Three real events should land: role, content, terminal.
    assert len(yields) == 3
