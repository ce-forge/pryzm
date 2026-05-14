"""Integration tests for the image-upload + OCR ingestion path.

These tests render PNG bytes in memory, run them through the same
service layer the `/upload` endpoint uses (services.knowledge.ingest_document),
and verify that the OCR'd text lands as searchable DocumentChunk rows.

llm_server.embed is monkeypatched to return a fixed 768-dim vector so
the tests do not depend on the llama-swap embedding model being up.
"""
from io import BytesIO

import httpx
import pytest
from PIL import Image, ImageDraw

from core import llm_server
from db import models
from services import knowledge, ocr


def _render_png(text: str) -> bytes:
    img = Image.new("RGB", (500, 120), "white")
    ImageDraw.Draw(img).text((20, 30), text, fill="black")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _seed_workspace(db, slug="img-test") -> models.Workspace:
    ws = models.Workspace(
        id=f"ws-{slug}",
        slug=slug,
        display_name="Image Test",
        system_prompt="",
        enabled_tools=[],
        is_builtin=False,
        engine_config={"backend": "llama_cpp"},
    )
    db.add(ws)
    db.commit()
    return ws


@pytest.mark.asyncio
async def test_image_ocr_text_becomes_searchable_chunk(db_session, monkeypatch):
    """End-to-end at the service layer: PNG → OCR text → ingest_document →
    DocumentChunk rows that contain the rendered string."""
    ws = _seed_workspace(db_session)

    png = _render_png("ROUTER ENERGY 12345")
    text = ocr.extract_text(png)
    assert "ROUTER" in text.upper()

    async def fake_embed(client, text, model):
        return [0.1] * 768

    monkeypatch.setattr(llm_server, "embed", fake_embed)

    async with httpx.AsyncClient() as client:
        result = await knowledge.ingest_document(
            client=client,
            db=db_session,
            filename="screenshot.png",
            content=text,
            workspace_id=ws.id,
            is_global=True,
        )

    assert result["status"] == "success"
    assert result["chunks_created"] >= 1

    chunks = (
        db_session.query(models.DocumentChunk)
        .filter_by(document_id=result["document_id"])
        .all()
    )
    assert chunks, "no chunks created"
    assert any("ROUTER" in c.content.upper() for c in chunks), (
        f"OCR text not found in any chunk content: {[c.content for c in chunks]!r}"
    )


def test_upload_endpoint_rejects_unsupported_image_type(db_session, monkeypatch):
    """/upload returns 400 when content_type is image/* but not in the
    supported set (jpeg, png, webp)."""
    from fastapi.testclient import TestClient

    from main import app
    from db import database
    from config import settings

    _seed_workspace(db_session, slug="img-tiff-test")

    def _get_db_override():
        try:
            yield db_session
        finally:
            pass

    monkeypatch.setattr(settings, "PRYZM_API_TOKEN", "test-token")
    monkeypatch.setattr(database, "init_db", lambda: None)
    app.dependency_overrides[database.get_db] = _get_db_override
    try:
        with TestClient(app) as c:
            c.headers.update({"Authorization": "Bearer test-token"})
            resp = c.post(
                "/upload",
                files={"file": ("t.tiff", b"\x00" * 64, "image/tiff")},
                data={"workspace": "img-tiff-test"},
            )
        assert resp.status_code == 400
        assert "Unsupported image type" in resp.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_upload_endpoint_rejects_blank_image_with_422(db_session, monkeypatch):
    """/upload returns 422 when OCR extracts no text from a valid image."""
    from fastapi.testclient import TestClient

    from main import app
    from db import database
    from config import settings

    _seed_workspace(db_session, slug="img-blank-test")

    blank = Image.new("RGB", (200, 100), "white")
    buf = BytesIO()
    blank.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    def _get_db_override():
        try:
            yield db_session
        finally:
            pass

    monkeypatch.setattr(settings, "PRYZM_API_TOKEN", "test-token")
    monkeypatch.setattr(database, "init_db", lambda: None)
    app.dependency_overrides[database.get_db] = _get_db_override
    try:
        with TestClient(app) as c:
            c.headers.update({"Authorization": "Bearer test-token"})
            resp = c.post(
                "/upload",
                files={"file": ("blank.png", png_bytes, "image/png")},
                data={"workspace": "img-blank-test"},
            )
        assert resp.status_code == 422
        assert "No text could be extracted" in resp.json()["detail"]
    finally:
        app.dependency_overrides.clear()
