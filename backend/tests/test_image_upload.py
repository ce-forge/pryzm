"""Integration tests for the image-upload + captioning ingestion path.

The path is: /upload (image MIME) → services.image_describe.describe →
services.knowledge.ingest_document → DocumentChunk rows.

Both `llm_server.chat` (the captioning call) and `llm_server.embed`
(the chunk embedding call) are monkeypatched so the tests don't depend
on a live llama-server.
"""
from __future__ import annotations

import httpx
import pytest

import os

from core import llm_server
from db import models
from services import image_describe, image_storage, knowledge


_FAKE_CAPTION = (
    "This image shows an IT console screenshot. Visible text: "
    "'Pryzm ITConsole Error 0x80070005', 'Device LAPTOP-042', "
    "'Backup failed: access denied'. The image is a Windows backup error."
)


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
async def test_caption_text_becomes_searchable_chunk(db_session, monkeypatch):
    """End-to-end at the service layer: image bytes → captioning →
    ingest_document → DocumentChunk rows that carry the caption text."""
    ws = _seed_workspace(db_session)

    async def fake_chat(client, messages, tools, model, options=None):
        return {"message": {"content": _FAKE_CAPTION}}

    async def fake_embed(client, text, model):
        return [0.1] * 768

    monkeypatch.setattr(llm_server, "chat", fake_chat)
    monkeypatch.setattr(llm_server, "embed", fake_embed)

    async with httpx.AsyncClient() as client:
        caption = await image_describe.describe(
            client=client, image_bytes=b"opaque-image-bytes", mime="image/png"
        )
        assert "Pryzm ITConsole" in caption

        result = await knowledge.ingest_document(
            client=client,
            db=db_session,
            filename="screenshot.png",
            content=caption,
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
    assert any("LAPTOP-042" in c.content for c in chunks)


def test_save_image_writes_bytes_and_returns_path(tmp_path, monkeypatch):
    """image_storage.save_image lays the bytes at data/uploads/<uuid>.<ext>
    and returns an absolute path that exists."""
    monkeypatch.setattr(image_storage, "_UPLOADS_DIR", str(tmp_path / "uploads"))
    path = image_storage.save_image(b"img-bytes", mime="image/png")
    assert os.path.isabs(path)
    assert path.endswith(".png")
    assert os.path.exists(path)
    with open(path, "rb") as f:
        assert f.read() == b"img-bytes"


def test_save_image_rejects_unsupported_mime(tmp_path, monkeypatch):
    monkeypatch.setattr(image_storage, "_UPLOADS_DIR", str(tmp_path / "uploads"))
    import pytest
    with pytest.raises(ValueError):
        image_storage.save_image(b"x", mime="image/tiff")


@pytest.mark.asyncio
async def test_document_delete_cleans_up_storage_file(db_session, monkeypatch, tmp_path):
    """SQLAlchemy after_delete listener removes the on-disk file when a
    Document with storage_path is deleted."""
    monkeypatch.setattr(image_storage, "_UPLOADS_DIR", str(tmp_path / "uploads"))
    ws = _seed_workspace(db_session, slug="img-delete-test")
    path = image_storage.save_image(b"keepalive-bytes", mime="image/png")
    assert os.path.exists(path)

    doc = models.Document(
        filename="x.png",
        workspace_id=ws.id,
        is_global=True,
        storage_path=path,
    )
    db_session.add(doc)
    db_session.commit()

    db_session.delete(doc)
    db_session.commit()
    assert not os.path.exists(path), "storage file should be cleaned up on Document delete"


def test_delete_document_endpoint_removes_row_and_file(db_session, monkeypatch, tmp_path):
    """DELETE /documents/{id} hard-deletes the row; the after_delete
    listener then cleans up the on-disk file. Used by the frontend
    when the user cancels an upload pill before sending."""
    from fastapi.testclient import TestClient
    from main import app
    from db import database
    from config import settings

    monkeypatch.setattr(image_storage, "_UPLOADS_DIR", str(tmp_path / "uploads"))
    ws = _seed_workspace(db_session, slug="img-endpoint-delete")
    path = image_storage.save_image(b"img-bytes", mime="image/png")

    doc = models.Document(
        id="doc-to-delete",
        filename="cancel-me.png",
        workspace_id=ws.id,
        is_global=False,
        storage_path=path,
    )
    db_session.add(doc); db_session.commit()
    assert os.path.exists(path)

    def _get_db_override():
        yield db_session
    monkeypatch.setattr(settings, "PRYZM_API_TOKEN", "test-token")
    monkeypatch.setattr(database, "init_db", lambda: None)
    app.dependency_overrides[database.get_db] = _get_db_override
    try:
        with TestClient(app) as c:
            c.headers.update({"Authorization": "Bearer test-token"})
            resp = c.delete("/documents/doc-to-delete")
        assert resp.status_code == 200
        assert resp.json() == {"status": "deleted"}
        assert db_session.query(models.Document).filter_by(id="doc-to-delete").first() is None
        assert not os.path.exists(path), "after_delete listener should have unlinked the file"
    finally:
        app.dependency_overrides.clear()


def test_delete_document_endpoint_404_when_missing(db_session, monkeypatch):
    """DELETE /documents/{id} returns 404 for an unknown id (idempotent
    enough — if the frontend retries on a stale pill, the second call
    is a no-op the user doesn't see)."""
    from fastapi.testclient import TestClient
    from main import app
    from db import database
    from config import settings

    def _get_db_override():
        yield db_session
    monkeypatch.setattr(settings, "PRYZM_API_TOKEN", "test-token")
    monkeypatch.setattr(database, "init_db", lambda: None)
    app.dependency_overrides[database.get_db] = _get_db_override
    try:
        with TestClient(app) as c:
            c.headers.update({"Authorization": "Bearer test-token"})
            resp = c.delete("/documents/nope")
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_ingest_document_persists_storage_path(db_session, monkeypatch):
    """ingest_document writes the storage_path kwarg onto the Document row."""
    ws = _seed_workspace(db_session, slug="img-persist-path")

    async def fake_embed(client, text, model):
        return [0.1] * 768

    monkeypatch.setattr(llm_server, "embed", fake_embed)

    async with httpx.AsyncClient() as client:
        result = await knowledge.ingest_document(
            client=client,
            db=db_session,
            filename="example.png",
            content="A captioned image.",
            workspace_id=ws.id,
            storage_path="/tmp/fake/example.png",
        )
    doc = (
        db_session.query(models.Document)
        .filter_by(id=result["document_id"])
        .one()
    )
    assert doc.storage_path == "/tmp/fake/example.png"


def test_upload_endpoint_returns_202_and_inserts_processing_row(
    db_session, monkeypatch
):
    """Async-ingestion contract: /upload commits a Document(status='processing')
    synchronously, then spawns the pipeline as a background task and returns
    202 with the doc id. The terminal flip arrives later via SSE.
    """
    from fastapi.testclient import TestClient
    from main import app
    from db import database
    from services import ingest_broker
    from config import settings

    _seed_workspace(db_session, slug="img-202-test")

    captured: list = []
    def _capture_task(coro):
        captured.append(coro)
        coro.close()  # we're verifying the route, not running the pipeline
        class _Stub:
            def add_done_callback(self, *_a, **_kw): pass
        return _Stub()
    monkeypatch.setattr(ingest_broker, "add_task", _capture_task)

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
                files={"file": ("hi.png", b"img-bytes", "image/png")},
                data={"workspace": "img-202-test"},
            )
        assert resp.status_code == 202, resp.text
        body = resp.json()
        assert body["status"] == "processing"
        assert body["filename"] == "hi.png"
        assert body["document_id"]
        # The row is real and queryable immediately — frontend depends
        # on this so the pill can open SSE against the returned id.
        doc = db_session.query(models.Document).filter_by(id=body["document_id"]).one()
        assert doc.status == "processing"
        assert doc.error_message is None
        # And the pipeline was scheduled.
        assert len(captured) == 1
    finally:
        app.dependency_overrides.clear()


def _bind_pipeline_db(monkeypatch, db_session):
    """Re-bind `database.SessionLocal` to the test engine so that the
    pipeline (which opens its own session via `database.SessionLocal()`)
    reads/writes the same DB the test fixture is using."""
    from sqlalchemy.orm import sessionmaker
    from db import database
    test_engine = db_session.get_bind()
    TestSessionLocal = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(database, "SessionLocal", TestSessionLocal)


@pytest.mark.asyncio
async def test_pipeline_marks_unsupported_image_mime_as_error(db_session, monkeypatch):
    """Pipeline-level error path: an unsupported image MIME used to raise
    HTTPException at /upload (400). Under async ingestion the task
    catches it, persists status='error' + error_message, and publishes
    a terminal event."""
    from services import ingest_pipeline, ingest_broker

    ws = _seed_workspace(db_session, slug="img-tiff-async")
    doc = models.Document(filename="t.tiff", workspace_id=ws.id, status="processing")
    db_session.add(doc); db_session.commit(); db_session.refresh(doc)
    _bind_pipeline_db(monkeypatch, db_session)

    broker = ingest_broker.broker()
    queue = broker.subscribe(doc.id)

    async with httpx.AsyncClient() as client:
        await ingest_pipeline.ingest_doc(
            document_id=doc.id,
            http_client=client,
            content=b"\x00" * 64,
            mime="image/tiff",
            filename="t.tiff",
        )

    db_session.refresh(doc)
    assert doc.status == "error"
    assert "Unsupported image MIME" in (doc.error_message or "")
    import asyncio
    event = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert event["status"] == "error"
    assert "Unsupported image MIME" in event["error"]


@pytest.mark.asyncio
async def test_pipeline_marks_empty_caption_as_error(db_session, monkeypatch):
    """VLM returns an empty caption → row flips to status='error' with
    a description-of-no-description message."""
    from services import ingest_pipeline, ingest_broker

    ws = _seed_workspace(db_session, slug="img-empty-async")
    doc = models.Document(filename="blank.png", workspace_id=ws.id, status="processing")
    db_session.add(doc); db_session.commit(); db_session.refresh(doc)
    _bind_pipeline_db(monkeypatch, db_session)

    async def empty_chat(client, messages, tools, model, options=None):
        return {"message": {"content": "", "reasoning_content": ""}}
    monkeypatch.setattr(llm_server, "chat", empty_chat)

    broker = ingest_broker.broker()
    queue = broker.subscribe(doc.id)

    async with httpx.AsyncClient() as client:
        await ingest_pipeline.ingest_doc(
            document_id=doc.id,
            http_client=client,
            content=b"opaque-png-bytes",
            mime="image/png",
            filename="blank.png",
        )

    db_session.refresh(doc)
    assert doc.status == "error"
    assert "no description" in (doc.error_message or "").lower()
    import asyncio
    event = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert event["status"] == "error"
