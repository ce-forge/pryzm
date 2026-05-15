"""Unit tests for services/image_describe.py.

The captioning module wraps llm_server.chat — we test it by stubbing
that call. No real LLM, no real network, no real image bytes needed.
"""
from __future__ import annotations

import base64

import pytest

from services import image_describe


@pytest.fixture(autouse=True)
def _stub_vision_router(monkeypatch):
    """`describe()` queries the router for the vision-tagged model.
    In unit-test isolation the router isn't initialised — stub it so
    describe() can resolve a model name without standing up the full
    app lifespan."""
    class _StubRouter:
        def vision_capable_model(self):
            return "qwen2-vl-2B-it"
    monkeypatch.setattr(image_describe, "get_router", lambda: _StubRouter())


@pytest.mark.asyncio
async def test_describe_calls_llm_with_image_url(monkeypatch):
    """The outgoing chat payload must include the image as a base64
    data URL and the right system prompt."""
    captured = {}

    async def fake_chat(client, messages, tools, model, options=None):
        captured["messages"] = messages
        captured["model"] = model
        captured["options"] = options
        captured["tools"] = tools
        return {"message": {"content": "A test description."}}

    monkeypatch.setattr(image_describe.llm_server, "chat", fake_chat)

    result = await image_describe.describe(
        client=None, image_bytes=b"binary-bytes-content", mime="image/png"
    )

    assert result == "A test description."
    assert captured["model"] == "qwen2-vl-2B-it"
    assert captured["tools"] is None
    assert "max_tokens" in captured["options"]

    user_msg = captured["messages"][1]
    assert user_msg["role"] == "user"
    blocks = user_msg["content"]
    image_block = next(b for b in blocks if b["type"] == "image_url")
    url = image_block["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")
    encoded = url.split(",", 1)[1]
    assert base64.b64decode(encoded) == b"binary-bytes-content"


@pytest.mark.asyncio
async def test_describe_falls_back_to_reasoning_content(monkeypatch):
    """If `content` is empty but `reasoning_content` is set (Gemma 4
    sometimes routes the answer through the thinking field), the seam
    returns reasoning_content."""

    async def fake_chat(client, messages, tools, model, options=None):
        return {"message": {"content": "", "reasoning_content": "Fallback caption."}}

    monkeypatch.setattr(image_describe.llm_server, "chat", fake_chat)

    result = await image_describe.describe(
        client=None, image_bytes=b"x", mime="image/jpeg"
    )
    assert result == "Fallback caption."


@pytest.mark.asyncio
async def test_describe_returns_empty_string_when_model_gives_nothing(monkeypatch):
    """Both content and reasoning_content empty → empty string, NOT a
    raised exception. The router maps empty → 422."""

    async def fake_chat(client, messages, tools, model, options=None):
        return {"message": {"content": "", "reasoning_content": ""}}

    monkeypatch.setattr(image_describe.llm_server, "chat", fake_chat)

    result = await image_describe.describe(
        client=None, image_bytes=b"x", mime="image/webp"
    )
    assert result == ""


@pytest.mark.asyncio
async def test_describe_rejects_unsupported_mime():
    """The seam owns its MIME contract — TIFF and others raise InvalidImage."""
    with pytest.raises(image_describe.InvalidImage):
        await image_describe.describe(
            client=None, image_bytes=b"x", mime="image/tiff"
        )
