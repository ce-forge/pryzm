"""Behavior tests for core.ollama using mocked httpx responses.

These tests do NOT require a live Ollama. They verify the wire shape: each
function constructs the right URL/payload and parses the response correctly.
Integration with a real Ollama is covered indirectly via the chat-path tests
in tests/e2e/.
"""
import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from core import ollama


async def _async_iter(items):
    for item in items:
        yield item


@pytest.mark.asyncio
async def test_chat_stream_yields_parsed_chunks():
    """chat_stream POSTs to /api/chat with stream=True and yields parsed JSON lines."""
    fake_lines = [
        json.dumps({"message": {"role": "assistant", "content": "hi"}, "done": False}),
        json.dumps({"message": {"role": "assistant", "content": " there"}, "done": False}),
        json.dumps({"done": True}),
    ]

    # Mock the streaming response context manager.
    fake_response = AsyncMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.aiter_lines = lambda: _async_iter(fake_lines)

    fake_stream_ctx = AsyncMock()
    fake_stream_ctx.__aenter__.return_value = fake_response

    client = MagicMock(spec=httpx.AsyncClient)
    client.stream.return_value = fake_stream_ctx

    chunks = []
    async for chunk in ollama.chat_stream(client, messages=[{"role": "user", "content": "hi"}], tools=None, model="gemma4:e4b"):
        chunks.append(chunk)

    assert len(chunks) == 3
    assert chunks[0]["message"]["content"] == "hi"
    assert chunks[2]["done"] is True

    # Verify the request shape.
    call_args = client.stream.call_args
    assert call_args[0][0] == "POST"
    assert "/api/chat" in call_args[0][1]
    payload = call_args[1]["json"]
    assert payload["model"] == "gemma4:e4b"
    assert payload["stream"] is True
    assert "tools" not in payload  # tools=None should be omitted


@pytest.mark.asyncio
async def test_chat_stream_includes_tools_when_provided():
    fake_response = AsyncMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.aiter_lines = lambda: _async_iter([])
    fake_stream_ctx = AsyncMock()
    fake_stream_ctx.__aenter__.return_value = fake_response

    client = MagicMock(spec=httpx.AsyncClient)
    client.stream.return_value = fake_stream_ctx

    tools = [{"type": "function", "function": {"name": "x"}}]
    async for _ in ollama.chat_stream(client, messages=[], tools=tools, model="x"):
        pass

    payload = client.stream.call_args[1]["json"]
    assert payload["tools"] == tools


@pytest.mark.asyncio
async def test_chat_stream_skips_malformed_lines():
    """Ollama can emit partial/malformed lines under load — skip them rather than crashing."""
    fake_lines = [
        json.dumps({"message": {"content": "ok"}, "done": False}),
        "{not valid json",
        "",  # empty
        json.dumps({"done": True}),
    ]
    fake_response = AsyncMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.aiter_lines = lambda: _async_iter(fake_lines)
    fake_stream_ctx = AsyncMock()
    fake_stream_ctx.__aenter__.return_value = fake_response

    client = MagicMock(spec=httpx.AsyncClient)
    client.stream.return_value = fake_stream_ctx

    chunks = [c async for c in ollama.chat_stream(client, [], None, "x")]
    # Should have 2 valid chunks; malformed + empty silently skipped.
    assert len(chunks) == 2


@pytest.mark.asyncio
async def test_embed_returns_vector():
    """embed POSTs to /api/embeddings and returns the 'embedding' field."""
    expected = [0.1, 0.2, 0.3] * 256  # 768-dim
    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {"embedding": expected}

    client = AsyncMock(spec=httpx.AsyncClient)
    client.post.return_value = fake_response

    result = await ollama.embed(client, text="hello", model="nomic-embed-text")
    assert result == expected

    # Verify request shape.
    call_args = client.post.call_args
    assert "/api/embeddings" in call_args[0][0]
    payload = call_args[1]["json"]
    assert payload == {"model": "nomic-embed-text", "prompt": "hello"}


@pytest.mark.asyncio
async def test_list_models_returns_names():
    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {
        "models": [{"name": "gemma4:e4b"}, {"name": "qwen3.6:35b-a3b"}]
    }
    client = AsyncMock(spec=httpx.AsyncClient)
    client.get.return_value = fake_response

    names = await ollama.list_models(client)
    assert names == ["gemma4:e4b", "qwen3.6:35b-a3b"]
    assert "/api/tags" in client.get.call_args[0][0]


@pytest.mark.asyncio
async def test_list_models_empty_models_field():
    """If 'models' is absent or empty, return []."""
    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {}
    client = AsyncMock(spec=httpx.AsyncClient)
    client.get.return_value = fake_response

    assert await ollama.list_models(client) == []


@pytest.mark.asyncio
async def test_generate_returns_response_text():
    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {"response": "summary text"}
    client = AsyncMock(spec=httpx.AsyncClient)
    client.post.return_value = fake_response

    result = await ollama.generate(client, prompt="x", model="y")
    assert result == "summary text"

    call_args = client.post.call_args
    assert "/api/generate" in call_args[0][0]
    payload = call_args[1]["json"]
    assert payload["model"] == "y"
    assert payload["prompt"] == "x"
    assert payload["stream"] is False
    assert "options" not in payload  # options=None should be omitted


@pytest.mark.asyncio
async def test_generate_includes_options_when_provided():
    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {"response": "x"}
    client = AsyncMock(spec=httpx.AsyncClient)
    client.post.return_value = fake_response

    await ollama.generate(client, prompt="p", model="m", options={"temperature": 0.2})

    payload = client.post.call_args[1]["json"]
    assert payload["options"] == {"temperature": 0.2}
