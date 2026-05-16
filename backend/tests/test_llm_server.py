"""Unit tests for the OpenAI-compatible LLM server wrapper.

These tests mock httpx responses rather than hitting a real llama-server —
they cover the wire-format adapter, not the actual inference. End-to-end
exercise lives in the e2e suite and the bench_llm harness."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from core import llm_server


def _make_mock_client(post_response: dict):
    """Builds an httpx.AsyncClient stand-in whose .post returns a
    Response-shaped object carrying the given JSON body."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value=post_response)
    client = MagicMock()
    client.post = AsyncMock(return_value=mock_resp)
    return client, mock_resp


@pytest.mark.asyncio
async def test_chat_returns_openai_message_dict():
    """chat() returns the inner message dict (with role + content + optional
    tool_calls) — same shape ai_engine expects after Ollama's adapter."""
    openai_response = {
        "id": "chatcmpl-xxx",
        "object": "chat.completion",
        "model": "gemma-4-E4B-it",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Hello!",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 12,
            "completion_tokens": 3,
            "total_tokens": 15,
        },
    }
    client, _ = _make_mock_client(openai_response)
    out = await llm_server.chat(client, messages=[{"role": "user", "content": "hi"}], tools=None, model="m")
    assert out["message"]["role"] == "assistant"
    assert out["message"]["content"] == "Hello!"
    # Ollama-shape fields still expected by core/llm_metrics: re-mapped from usage.
    assert out["prompt_eval_count"] == 12
    assert out["eval_count"] == 3


@pytest.mark.asyncio
async def test_chat_adapts_llama_server_timings():
    """llama-server adds a `timings` extension to the OpenAI response with
    millisecond-precision prompt/predict splits. The adapter maps them into
    Ollama's nanosecond fields so Phase A's metric emitter computes a real TPS."""
    openai_response = {
        "choices": [{"message": {"role": "assistant", "content": "ok"}}],
        "usage": {"prompt_tokens": 17, "completion_tokens": 210, "total_tokens": 227},
        "timings": {
            "prompt_ms": 44.7,
            "predicted_ms": 1730.3,
            "predicted_per_second": 121.36,
        },
    }
    client, _ = _make_mock_client(openai_response)
    out = await llm_server.chat(client, messages=[], tools=None, model="m")
    # ms → ns conversion: 44.7 * 1e6 = 44_700_000, 1730.3 * 1e6 = 1_730_300_000
    assert out["prompt_eval_duration"] == 44_700_000
    assert out["eval_duration"] == 1_730_300_000
    assert out["total_duration"] == 44_700_000 + 1_730_300_000


@pytest.mark.asyncio
async def test_chat_handles_missing_timings_block():
    """When the upstream server omits `timings` (a non-llama-server OpenAI
    backend), all timing fields are 0 — the metric emitter falls back to
    caller-measured wall clock for duration_ms."""
    openai_response = {
        "choices": [{"message": {"role": "assistant", "content": "ok"}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        # no timings block
    }
    client, _ = _make_mock_client(openai_response)
    out = await llm_server.chat(client, messages=[], tools=None, model="m")
    assert out["prompt_eval_duration"] == 0
    assert out["eval_duration"] == 0
    assert out["total_duration"] == 0


@pytest.mark.asyncio
async def test_chat_passes_tool_calls_through():
    """When the model emits tool_calls, they flow through unchanged."""
    openai_response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "check_port", "arguments": '{"port": 22}'},
                        }
                    ],
                }
            }
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 8, "total_tokens": 13},
    }
    client, _ = _make_mock_client(openai_response)
    out = await llm_server.chat(client, messages=[], tools=[{"type": "function"}], model="m")
    assert out["message"]["tool_calls"][0]["function"]["name"] == "check_port"


@pytest.mark.asyncio
async def test_chat_payload_uses_openai_endpoint():
    """The POST hits /v1/chat/completions, not /api/chat."""
    client, _ = _make_mock_client({
        "choices": [{"message": {"role": "assistant", "content": ""}}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    })
    await llm_server.chat(client, messages=[], tools=None, model="m")
    args, kwargs = client.post.call_args
    assert args[0].endswith("/v1/chat/completions")


@pytest.mark.asyncio
async def test_generate_uses_chat_completions_with_user_role():
    """generate() is a thin shim around /v1/chat/completions with a single
    user message — llama-server has no /api/generate equivalent."""
    openai_response = {
        "choices": [{"message": {"role": "assistant", "content": "answer text"}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
    }
    client, _ = _make_mock_client(openai_response)
    out = await llm_server.generate(client, prompt="hello", model="m")
    assert out == "answer text"


@pytest.mark.asyncio
async def test_embed_returns_vector():
    """embed() unwraps OpenAI's nested `data[0].embedding` and returns the float
    list directly — same shape Ollama's adapter returned."""
    openai_response = {
        "object": "list",
        "data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}],
        "model": "nomic-embed-text-v1.5",
        "usage": {"prompt_tokens": 4, "total_tokens": 4},
    }
    client, _ = _make_mock_client(openai_response)
    out = await llm_server.embed(client, text="hello", model="nomic-embed-text-v1.5")
    assert out == [0.1, 0.2, 0.3]


def _make_error_response(status: int, body: dict | str):
    """Build a Response-shaped mock that simulates an HTTP error.

    raise_for_status() raises httpx.HTTPStatusError carrying a request + response;
    .text returns the body; .json() works only if `body` is a dict.
    """
    request = httpx.Request("POST", "http://127.0.0.1:8080/v1/chat/completions")
    text_body = json.dumps(body) if isinstance(body, dict) else body
    mock_resp = MagicMock()
    mock_resp.status_code = status
    mock_resp.text = text_body
    mock_resp.json = MagicMock(return_value=body if isinstance(body, dict) else {})
    mock_resp.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            f"{status} error", request=request, response=mock_resp,
        )
    )
    return mock_resp


@pytest.mark.asyncio
async def test_chat_400_surfaces_llama_server_error_message():
    """When llama-server returns a 400 with an `error.message` JSON body
    (e.g. exceed_context_size_error), the raised exception's str() includes
    that message so users see what's actually wrong."""
    body = {
        "error": {
            "code": 400,
            "message": "request (12016 tokens) exceeds the available context size (8192 tokens), try increasing it",
            "type": "exceed_context_size_error",
        }
    }
    mock_resp = _make_error_response(400, body)
    client = MagicMock()
    client.post = AsyncMock(return_value=mock_resp)
    with pytest.raises(httpx.HTTPStatusError) as ei:
        await llm_server.chat(
            client,
            messages=[{"role": "user", "content": "x"}],
            tools=None,
            model="gemma-4-E4B-it",
        )
    msg = str(ei.value)
    assert "exceeds the available context size" in msg
    assert "8192" in msg


@pytest.mark.asyncio
async def test_chat_400_with_non_json_body_falls_back_to_raw_text():
    """If the upstream error body isn't JSON, the raw text is still surfaced
    (truncated if very long)."""
    mock_resp = _make_error_response(503, "upstream timeout")
    client = MagicMock()
    client.post = AsyncMock(return_value=mock_resp)
    with pytest.raises(httpx.HTTPStatusError) as ei:
        await llm_server.chat(
            client,
            messages=[{"role": "user", "content": "x"}],
            tools=None,
            model="gemma-4-E4B-it",
        )
    assert "upstream timeout" in str(ei.value)


@pytest.mark.asyncio
async def test_embed_400_surfaces_body():
    """Same surfacing applied to the embed path (used by RAG ingest)."""
    body = {"error": {"message": "model not loaded", "code": 400}}
    mock_resp = _make_error_response(400, body)
    client = MagicMock()
    client.post = AsyncMock(return_value=mock_resp)
    with pytest.raises(httpx.HTTPStatusError) as ei:
        await llm_server.embed(client, text="hi", model="nomic-embed-text-v1.5")
    assert "model not loaded" in str(ei.value)


@pytest.mark.asyncio
async def test_list_models_returns_ids():
    """list_models() returns the `id` strings from /v1/models."""
    openai_response = {
        "object": "list",
        "data": [
            {"id": "gemma-4-E2B-it", "object": "model"},
            {"id": "gemma-4-E4B-it", "object": "model"},
            {"id": "nomic-embed-text-v1.5", "object": "model"},
        ],
    }
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value=openai_response)
    client = MagicMock()
    client.get = AsyncMock(return_value=mock_resp)
    out = await llm_server.list_models(client)
    assert out == ["gemma-4-E2B-it", "gemma-4-E4B-it", "nomic-embed-text-v1.5"]
