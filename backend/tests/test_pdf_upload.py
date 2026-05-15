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


def _bind_pipeline_db(monkeypatch, db_session):
    """Re-bind `database.SessionLocal` so the pipeline (which opens its
    own session) hits the same test DB the fixture is writing to."""
    from sqlalchemy.orm import sessionmaker
    from db import database
    test_engine = db_session.get_bind()
    TestSessionLocal = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(database, "SessionLocal", TestSessionLocal)


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


@pytest.mark.asyncio
async def test_pipeline_ingests_pdf_end_to_end(db_session, monkeypatch):
    """End-to-end at the pipeline layer: a Document is inserted in
    'processing' state, then ingest_doc reads bytes → extracts text →
    chunks → flips status='ready' and publishes a terminal event."""
    from services import ingest_broker, ingest_pipeline

    ws = _seed_workspace(db_session, slug="pdf-pipeline-end-to-end")
    pdf = _make_text_pdf("DEVICE LAPTOP-042 NETWORK CONFIG")

    async def fake_embed(client, text, model):
        return [0.1] * 768
    monkeypatch.setattr(llm_server, "embed", fake_embed)

    doc = models.Document(
        filename="config.pdf", workspace_id=ws.id, is_global=True, status="processing"
    )
    db_session.add(doc); db_session.commit(); db_session.refresh(doc)
    _bind_pipeline_db(monkeypatch, db_session)

    broker = ingest_broker.broker()
    queue = broker.subscribe(doc.id)

    async with httpx.AsyncClient() as client:
        await ingest_pipeline.ingest_doc(
            document_id=doc.id,
            http_client=client,
            content=pdf,
            mime="application/pdf",
            filename="config.pdf",
        )

    db_session.refresh(doc)
    assert doc.status == "ready"
    assert doc.error_message is None
    chunks = (
        db_session.query(models.DocumentChunk)
        .filter_by(document_id=doc.id)
        .all()
    )
    assert any("LAPTOP-042" in c.content for c in chunks)
    import asyncio
    event = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert event["status"] == "ready"


@pytest.mark.asyncio
async def test_pipeline_marks_invalid_pdf_as_error(db_session, monkeypatch):
    """Bytes that aren't a valid PDF → row flips to status='error'
    with the parser-error message, terminal event published."""
    from services import ingest_broker, ingest_pipeline

    ws = _seed_workspace(db_session, slug="pdf-bad-async")
    doc = models.Document(filename="bad.pdf", workspace_id=ws.id, status="processing")
    db_session.add(doc); db_session.commit(); db_session.refresh(doc)
    _bind_pipeline_db(monkeypatch, db_session)

    broker = ingest_broker.broker()
    queue = broker.subscribe(doc.id)

    async with httpx.AsyncClient() as client:
        await ingest_pipeline.ingest_doc(
            document_id=doc.id,
            http_client=client,
            content=b"not a pdf at all",
            mime="application/pdf",
            filename="bad.pdf",
        )

    db_session.refresh(doc)
    assert doc.status == "error"
    assert "Could not parse PDF" in (doc.error_message or "")
    import asyncio
    event = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert event["status"] == "error"


@pytest.mark.asyncio
async def test_pipeline_marks_textless_pdf_as_error(db_session, monkeypatch):
    """Valid PDF with no extractable text → status='error' on the row
    with the explicit no-extractable-text message."""
    from services import ingest_broker, ingest_pipeline

    ws = _seed_workspace(db_session, slug="pdf-empty-async")
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

    doc = models.Document(filename="scan.pdf", workspace_id=ws.id, status="processing")
    db_session.add(doc); db_session.commit(); db_session.refresh(doc)
    _bind_pipeline_db(monkeypatch, db_session)

    broker = ingest_broker.broker()
    queue = broker.subscribe(doc.id)

    async with httpx.AsyncClient() as client:
        await ingest_pipeline.ingest_doc(
            document_id=doc.id,
            http_client=client,
            content=out,
            mime="application/pdf",
            filename="scan.pdf",
        )

    db_session.refresh(doc)
    assert doc.status == "error"
    assert "No extractable text" in (doc.error_message or "")
    import asyncio
    event = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert event["status"] == "error"
