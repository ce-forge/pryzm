"""Unit tests for `services.ingest_pipeline._caption_image` — the
OCR-canonical merge logic that combines OCR's verbatim text with the
VLM's structural description into a single stored caption."""
from __future__ import annotations

import httpx
import pytest

from core import llm_server
from services import image_describe, ingest_pipeline, ocr_extract


@pytest.mark.asyncio
async def test_merge_combines_ocr_and_vlm_into_two_sections(monkeypatch):
    """Happy path: OCR returns verbatim text, VLM returns a context
    paragraph. Caption has both sections, OCR first."""
    monkeypatch.setattr(
        ocr_extract, "extract_text",
        lambda content, mime: "Username: admin\nError: 0x80070005",
    )

    async def fake_chat(client, messages, tools, model, options=None):
        return {"message": {"content": "A Windows backup error dialog with a button row at the bottom."}}
    monkeypatch.setattr(llm_server, "chat", fake_chat)

    # Stub the vision_capable_model lookup since the router isn't init'd in unit tests.
    class _StubRouter:
        def vision_capable_model(self):
            return "gemma-4-E4B-it"
    # image_describe imported get_router directly, so patch the binding
    # in image_describe's namespace (patching core.llm_router.get_router
    # doesn't reach the already-imported reference).
    monkeypatch.setattr(image_describe, "get_router", lambda: _StubRouter())

    async with httpx.AsyncClient() as client:
        caption = await ingest_pipeline._caption_image(client, b"dummy", "image/png")

    assert "EXTRACTED TEXT (OCR):" in caption
    assert "admin" in caption
    assert "0x80070005" in caption
    assert "CONTEXT:" in caption
    assert "Windows backup error dialog" in caption
    # OCR section must come before CONTEXT — verbatim text first.
    assert caption.index("EXTRACTED TEXT") < caption.index("CONTEXT")


@pytest.mark.asyncio
async def test_merge_falls_back_to_verbatim_vlm_when_ocr_empty(monkeypatch):
    """OCR returns None (e.g., hand-drawn diagram with no readable
    text) → VLM re-runs with verbatim prompt and that becomes the
    sole caption. We never store an empty caption while content exists."""
    monkeypatch.setattr(ocr_extract, "extract_text", lambda content, mime: None)

    call_log = []
    async def fake_chat(client, messages, tools, model, options=None):
        # Capture the system prompt to verify the fallback path used
        # the verbatim prompt on the SECOND call.
        system = messages[0]["content"] if messages else ""
        call_log.append(system)
        if "OCR engine handles" in system:
            # First call (structure-only prompt) — return empty so we exercise the fallback.
            return {"message": {"content": ""}}
        # Second call (verbatim fallback prompt) — return the verbatim caption.
        return {"message": {"content": "Hand-drawn network diagram showing three nodes connected by lines."}}
    monkeypatch.setattr(llm_server, "chat", fake_chat)

    class _StubRouter:
        def vision_capable_model(self):
            return "gemma-4-E4B-it"
    # image_describe imported get_router directly, so patch the binding
    # in image_describe's namespace (patching core.llm_router.get_router
    # doesn't reach the already-imported reference).
    monkeypatch.setattr(image_describe, "get_router", lambda: _StubRouter())

    async with httpx.AsyncClient() as client:
        caption = await ingest_pipeline._caption_image(client, b"dummy", "image/png")

    assert "Hand-drawn network diagram" in caption
    # Did NOT emit empty OCR section just because OCR returned None.
    assert "EXTRACTED TEXT (OCR):" not in caption
    # Verified both prompts were used.
    assert any("OCR engine handles" in s for s in call_log)
    assert any("verbatim" in s.lower() for s in call_log)


@pytest.mark.asyncio
async def test_merge_drops_empty_vlm_section_keeps_ocr(monkeypatch):
    """VLM returns empty content; OCR has results. Caption still has
    OCR section. CONTEXT section is omitted (we don't write empty
    sections — they'd look like authoritative 'no context' claims)."""
    monkeypatch.setattr(ocr_extract, "extract_text", lambda content, mime: "Some extracted text")

    async def empty_chat(client, messages, tools, model, options=None):
        return {"message": {"content": "", "reasoning_content": ""}}
    monkeypatch.setattr(llm_server, "chat", empty_chat)

    class _StubRouter:
        def vision_capable_model(self):
            return "gemma-4-E4B-it"
    # image_describe imported get_router directly, so patch the binding
    # in image_describe's namespace (patching core.llm_router.get_router
    # doesn't reach the already-imported reference).
    monkeypatch.setattr(image_describe, "get_router", lambda: _StubRouter())

    async with httpx.AsyncClient() as client:
        caption = await ingest_pipeline._caption_image(client, b"dummy", "image/png")

    assert "EXTRACTED TEXT (OCR):" in caption
    assert "Some extracted text" in caption
    assert "CONTEXT:" not in caption


@pytest.mark.asyncio
async def test_merge_returns_empty_when_both_engines_fail(monkeypatch):
    """OCR returns None, VLM-with-fallback-prompt also returns empty.
    Caller (ingest_doc) checks the empty result and flips the row to
    status='error'; this test confirms the function returns the
    empty string rather than crashing or fabricating content."""
    monkeypatch.setattr(ocr_extract, "extract_text", lambda content, mime: None)

    async def empty_chat(client, messages, tools, model, options=None):
        return {"message": {"content": "", "reasoning_content": ""}}
    monkeypatch.setattr(llm_server, "chat", empty_chat)

    class _StubRouter:
        def vision_capable_model(self):
            return "gemma-4-E4B-it"
    # image_describe imported get_router directly, so patch the binding
    # in image_describe's namespace (patching core.llm_router.get_router
    # doesn't reach the already-imported reference).
    monkeypatch.setattr(image_describe, "get_router", lambda: _StubRouter())

    async with httpx.AsyncClient() as client:
        caption = await ingest_pipeline._caption_image(client, b"dummy", "image/png")

    assert caption == ""
