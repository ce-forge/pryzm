"""Integration tests for /upload's PDF branch.

Mocks the embed call so the test doesn't depend on a running embed
model. Uses the same in-memory PDF helper as test_pdf_extract.
"""
from __future__ import annotations

import httpx
import pytest

from core import llm_server
from db import models
from services import knowledge, pdf_extract
from tests.test_pdf_extract import _make_text_pdf


def _seed_workspace(db, slug="pdf-test") -> models.Workspace:
    ws = models.Workspace(
        id=f"ws-{slug}",
        slug=slug,
        display_name="PDF Test",
        system_prompt="",
        enabled_tools=[],
        is_builtin=False,
        engine_config={"backend": "llama_cpp"},
    )
    db.add(ws)
    db.commit()
    return ws


@pytest.mark.asyncio
async def test_pdf_text_becomes_searchable_chunk(db_session, monkeypatch):
    """Build a PDF, extract its text via the seam, ingest, then assert
    the ingested chunks carry the original PDF text."""
    ws = _seed_workspace(db_session, slug="pdf-end-to-end")
    pdf = _make_text_pdf("RUNBOOK 2026 BACKUP PROCEDURE")

    text = pdf_extract.extract_text(pdf)
    assert "RUNBOOK" in text.upper()

    async def fake_embed(client, text, model):
        return [0.1] * 768
    monkeypatch.setattr(llm_server, "embed", fake_embed)

    async with httpx.AsyncClient() as client:
        result = await knowledge.ingest_document(
            client=client,
            db=db_session,
            filename="runbook.pdf",
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
    assert chunks
    assert any("RUNBOOK" in c.content.upper() for c in chunks)


def test_upload_endpoint_accepts_pdf(db_session, monkeypatch):
    """End-to-end at the endpoint: POST a PDF, assert 200 and the
    captioned/extracted text persisted as chunks."""
    from fastapi.testclient import TestClient
    from main import app
    from db import database
    from config import settings

    _seed_workspace(db_session, slug="pdf-endpoint")
    pdf = _make_text_pdf("DEVICE LAPTOP-042 NETWORK CONFIG")

    async def fake_embed(client, text, model):
        return [0.1] * 768
    monkeypatch.setattr(llm_server, "embed", fake_embed)

    def _get_db_override():
        yield db_session
    monkeypatch.setattr(settings, "PRYZM_API_TOKEN", "test-token")
    monkeypatch.setattr(database, "init_db", lambda: None)
    app.dependency_overrides[database.get_db] = _get_db_override

    try:
        with TestClient(app) as c:
            c.headers.update({"Authorization": "Bearer test-token"})
            resp = c.post(
                "/upload",
                files={"file": ("config.pdf", pdf, "application/pdf")},
                data={"workspace": "pdf-endpoint", "is_global": "true"},
            )
        assert resp.status_code == 200, resp.text
        doc_id = resp.json()["details"]["document_id"]
        chunks = (
            db_session.query(models.DocumentChunk)
            .filter_by(document_id=doc_id)
            .all()
        )
        assert any("LAPTOP-042" in c.content for c in chunks)
    finally:
        app.dependency_overrides.clear()


def test_upload_endpoint_rejects_invalid_pdf(db_session, monkeypatch):
    """Bytes that aren't a valid PDF but advertise application/pdf →
    400 with the parser error."""
    from fastapi.testclient import TestClient
    from main import app
    from db import database
    from config import settings

    _seed_workspace(db_session, slug="pdf-bad")

    def _get_db_override():
        yield db_session
    monkeypatch.setattr(settings, "PRYZM_API_TOKEN", "test-token")
    monkeypatch.setattr(database, "init_db", lambda: None)
    app.dependency_overrides[database.get_db] = _get_db_override
    try:
        with TestClient(app) as c:
            c.headers.update({"Authorization": "Bearer test-token"})
            resp = c.post(
                "/upload",
                files={"file": ("bad.pdf", b"not a pdf at all", "application/pdf")},
                data={"workspace": "pdf-bad"},
            )
        assert resp.status_code == 400
        assert "Could not parse PDF" in resp.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_upload_endpoint_returns_422_when_pdf_has_no_text(db_session, monkeypatch):
    """A valid PDF with no extractable text (e.g. a scanned image-only
    PDF in shape) → 422 with the right message. Built here as a
    structurally-valid empty-content PDF."""
    from fastapi.testclient import TestClient
    from main import app
    from db import database
    from config import settings

    _seed_workspace(db_session, slug="pdf-empty")

    # Empty-content PDF: same shape used in test_pdf_extract's no-text test.
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = [0]
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n"
    ).encode()

    def _get_db_override():
        yield db_session
    monkeypatch.setattr(settings, "PRYZM_API_TOKEN", "test-token")
    monkeypatch.setattr(database, "init_db", lambda: None)
    app.dependency_overrides[database.get_db] = _get_db_override
    try:
        with TestClient(app) as c:
            c.headers.update({"Authorization": "Bearer test-token"})
            resp = c.post(
                "/upload",
                files={"file": ("scan.pdf", out, "application/pdf")},
                data={"workspace": "pdf-empty"},
            )
        assert resp.status_code == 422
        assert "No extractable text" in resp.json()["detail"]
    finally:
        app.dependency_overrides.clear()
