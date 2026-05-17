"""Unit tests for the unified single-VLM captioning pipeline.

`ingest_pipeline._caption_image` is a thin wrapper around
`image_describe.describe` — the captioning model handles both verbatim
text extraction and structural description in a single call.
"""
from __future__ import annotations

import httpx
import pytest

from core import llm_server
from services import image_describe, ingest_pipeline


@pytest.mark.asyncio
async def test_caption_returns_vlm_output(monkeypatch):
    """Happy path: VLM produces a caption containing both EXTRACTED
    TEXT and CONTEXT sections (per the prompt). _caption_image
    passes the response through unchanged."""
    async def fake_chat(client, messages, tools, model, options=None):
        return {
            "message": {
                "content": (
                    "EXTRACTED TEXT\n"
                    "Username: admin\n"
                    "Password: nfsyg9yehhp9bt9x\n\n"
                    "CONTEXT\n"
                    "Password manager view with form fields populated."
                )
            }
        }
    monkeypatch.setattr(llm_server, "chat", fake_chat)

    class _StubRouter:
        def vision_capable_model(self):
            return "qwen2-vl-2B-it"
    monkeypatch.setattr(image_describe, "get_router", lambda: _StubRouter())

    async with httpx.AsyncClient() as client:
        caption = await ingest_pipeline._caption_image(client, b"dummy", "image/png")

    assert "EXTRACTED TEXT" in caption
    assert "admin" in caption
    assert "nfsyg9yehhp9bt9x" in caption
    assert "CONTEXT" in caption


@pytest.mark.asyncio
async def test_caption_translates_invalid_image_to_ingestion_error(monkeypatch):
    """When the VLM seam rejects the MIME, the pipeline converts the
    `InvalidImage` exception into an `_IngestionError` so the
    ingest_doc background task can persist a clean error message on
    the Document row rather than crashing."""
    async def _raise(*args, **kwargs):
        raise image_describe.InvalidImage("Unsupported image MIME: image/tiff")

    monkeypatch.setattr(image_describe, "describe", _raise)

    async with httpx.AsyncClient() as client:
        with pytest.raises(ingest_pipeline._IngestionError) as exc:
            await ingest_pipeline._caption_image(client, b"dummy", "image/tiff")
    assert "Unsupported image MIME" in str(exc.value)


@pytest.mark.asyncio
async def test_caption_returns_empty_string_on_empty_vlm_response(monkeypatch):
    """If the VLM returns empty content (rare but possible), the
    caller checks `text_content.strip()` and surfaces a clear error
    on the Document row. This test confirms _caption_image returns
    empty rather than fabricating content."""
    async def empty_chat(client, messages, tools, model, options=None):
        return {"message": {"content": "", "reasoning_content": ""}}
    monkeypatch.setattr(llm_server, "chat", empty_chat)

    class _StubRouter:
        def vision_capable_model(self):
            return "qwen2-vl-2B-it"
    monkeypatch.setattr(image_describe, "get_router", lambda: _StubRouter())

    async with httpx.AsyncClient() as client:
        caption = await ingest_pipeline._caption_image(client, b"dummy", "image/png")

    assert caption == ""
