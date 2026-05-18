"""End-to-end document ingestion pipeline.

`/upload` inserts a `Document(status='processing')` row synchronously
and hands the row's id to `ingest_doc`, which runs as a background task.
The task does caption-or-extract → save → chunk + embed → flip status,
publishing progress to the broker the whole way.

Contract:

- Never raises. Failure modes (unsupported MIME, empty caption,
  non-UTF-8 text, etc.) are persisted onto the Document as
  `status='error'` + `error_message=...` and published as a terminal
  event. The route handler has already committed the row by the time
  the background task starts; there's nobody to receive a thrown
  exception.
- Always publishes a single terminal event (`status: 'ready'` or
  `status: 'error'`) to the broker before returning, so SSE
  subscribers complete cleanly.
- Owns its own DB session. `/upload`'s session is closed by the time
  the task runs.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from core.audit import EventType, log_event
from db import database, models
from services import image_describe, image_storage, ingest_broker, knowledge, pdf_extract

_logger = logging.getLogger(__name__)


async def ingest_doc(
    *,
    document_id: str,
    http_client: httpx.AsyncClient,
    content: bytes,
    mime: str,
    filename: str,
) -> None:
    """Run the ingestion pipeline for an already-created Document row.

    See module docstring for the contract. Caller spawns this via
    `ingest_broker.add_task` and forgets — completion arrives on the
    broker channel keyed by `document_id`.
    """
    broker = ingest_broker.broker()
    db: Session = database.SessionLocal()
    try:
        doc = db.query(models.Document).filter(models.Document.id == document_id).first()
        if doc is None:
            # The row was deleted between /upload committing it and the
            # task starting (e.g., user cancelled the pill). Publish a
            # terminal event so any subscribers wake up, then exit.
            _logger.info("ingest_doc: document %s vanished before task ran", document_id)
            await broker.publish(document_id, {"status": "error", "error": "Document was deleted before ingestion started."})
            return

        try:
            text_content, storage_path = await _extract_text(http_client, content, mime, filename)
        except _IngestionError as e:
            await _finalize_error(db, broker, doc, str(e))
            return
        except Exception as e:
            _logger.exception("ingest_doc: unexpected extraction failure for %s", document_id)
            await _finalize_error(db, broker, doc, f"Extraction failed: {e}")
            return

        try:
            if storage_path:
                doc.storage_path = storage_path
                db.commit()
            chunks_created = await knowledge.add_chunks_to_document(http_client, db, doc, text_content)
        except Exception as e:
            _logger.exception("ingest_doc: chunk/embed failed for %s", document_id)
            await _finalize_error(db, broker, doc, f"Embedding failed: {e}")
            return

        doc.status = "ready"
        doc.error_message = None
        db.commit()
        await broker.publish(document_id, {
            "status": "ready",
            "chunks_created": chunks_created,
            "filename": doc.filename,
        })
    finally:
        db.close()


class _IngestionError(Exception):
    """Internal sentinel for predictable, user-facing extraction failures
    (unsupported MIME, empty caption, etc.). Distinct from unhandled
    exceptions so the finalize path can keep them out of the log noise."""


async def _caption_image(
    http_client: httpx.AsyncClient,
    content: bytes,
    mime: str,
) -> str:
    """Single VLM call. The captioning model (currently Qwen2-VL-2B
    via the `vision` tag in llama-swap-config.yaml) produces both the
    verbatim text extraction and the structural description in one
    response.

    Previously a hybrid pipeline ran RapidOCR + a structure-only VLM
    in parallel and merged their outputs, but that approach had a
    fundamental flaw: RapidOCR flattened multi-column form layouts
    into a 1D text stream, breaking value-label relationships
    (sidebar items at the same Y as form values got mashed into the
    same output position). A single VLM with full spatial awareness
    handles both concerns without the layout-collapse failure mode.
    """
    try:
        return await image_describe.describe(http_client, content, mime=mime)
    except image_describe.InvalidImage as e:
        raise _IngestionError(str(e))


async def _extract_text(
    http_client: httpx.AsyncClient,
    content: bytes,
    mime: str,
    filename: str,
) -> tuple[str, Optional[str]]:
    """Return (text_content, storage_path). storage_path is non-None
    only for images, which we persist to disk after captioning succeeds."""
    if mime.startswith("image/"):
        text_content = await _caption_image(http_client, content, mime)
        if not text_content.strip():
            raise _IngestionError("Neither OCR nor the VLM produced any text for this image.")
        storage_path = image_storage.save_image(content, mime=mime)
        return text_content, storage_path

    if mime == "application/pdf" or filename.lower().endswith(".pdf"):
        try:
            text_content = await asyncio.to_thread(pdf_extract.extract_text, content)
        except pdf_extract.InvalidPdf as e:
            raise _IngestionError(f"Could not parse PDF: {e}")
        if not text_content.strip():
            raise _IngestionError(
                "No extractable text in this PDF. Scanned/image-only PDFs aren't supported yet."
            )
        return text_content, None

    try:
        return content.decode("utf-8"), None
    except UnicodeDecodeError:
        raise _IngestionError("Only UTF-8 text files are currently supported.")


async def _finalize_error(
    db: Session,
    broker: ingest_broker.IngestBroker,
    doc: models.Document,
    message: str,
) -> None:
    """Persist the error state and publish a terminal event.

    Rolls back first to discard any chunks that were added to the session
    by a partially-completed embed loop — otherwise the status-update
    commit below would flush them, leaving an `error` document with half
    its embeddings and duplicating them on re-upload. Re-fetches the row
    after rollback because the rollback detaches ORM instances.

    Best-effort: if the DB write itself fails we still want the SSE
    subscriber to wake up, so the publish runs unconditionally.
    """
    try:
        db.rollback()
        fresh = db.query(models.Document).filter(models.Document.id == doc.id).first()
        if fresh is not None:
            fresh.status = "error"
            fresh.error_message = message
            db.commit()

            ws = db.query(models.Workspace).filter_by(id=fresh.workspace_id).first()
            user_obj = (
                db.query(models.User).filter_by(id=ws.user_id).first()
                if ws and ws.user_id
                else None
            )
            session_obj = (
                db.query(models.Session).filter_by(id=fresh.session_id).first()
                if fresh.session_id
                else None
            )
            log_event(
                db,
                EventType.DOCUMENT_PROCESSING_FAILED,
                user=user_obj,
                workspace=ws,
                session=session_obj,
                resource_type="document",
                resource_id=fresh.id,
                payload={
                    "document_id": fresh.id,
                    "filename": fresh.filename,
                    "error": message,
                },
            )
            db.commit()
    except Exception:
        _logger.exception("ingest_doc: could not persist error state for %s", doc.id)
        db.rollback()
    await broker.publish(doc.id, {"status": "error", "error": message})
