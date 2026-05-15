"""End-to-end document ingestion pipeline.

Async-ingestion PR 3 (docs/specs/2026-05-15-async-ingestion.md). The
shape is: `/upload` inserts a `Document(status='processing')` row
synchronously and hands the row's id to `ingest_doc`, which runs as a
background task. The task does caption-or-extract → save → chunk +
embed → flip status, publishing progress to the broker the whole way.

Contract:

- Never raises. Anything that previously surfaced as a 4xx (unsupported
  MIME, empty caption, non-UTF-8 text, etc.) is persisted onto the
  Document as `status='error'` + `error_message=...` and published as
  a terminal event. The route handler has already committed the row
  by the time the background task starts — there's nobody left to
  receive a thrown exception.
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

from db import database, models
from services import image_describe, image_storage, ingest_broker, knowledge, ocr_extract, pdf_extract

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
    """Build the stored caption by running OCR and VLM in parallel and
    merging their outputs. Each engine owns one section:

      EXTRACTED TEXT (OCR): canonical verbatim text. No language-prior
      pattern completion — OCR reads pixels into characters.

      CONTEXT (VLM): structure, layout, what kind of screen, what
      fields are visible by role and position. The VLM is prompted to
      AVOID transcribing text content; OCR handles that.

    There is exactly one source of verbatim text in the caption, so
    the chat-time LLM cannot surface ambiguous "X or Y" readings.

    Fallback: if OCR returns nothing meaningful (rare on screen photos
    but real for hand-drawn diagrams, photos without legible text), we
    re-run the VLM with the original verbatim-extraction prompt so we
    never store an empty caption.
    """
    try:
        ocr_task = asyncio.to_thread(ocr_extract.extract_text, content, mime)
        vlm_task = image_describe.describe(http_client, content, mime=mime)
        ocr_text, vlm_text = await asyncio.gather(ocr_task, vlm_task)
    except image_describe.InvalidImage as e:
        raise _IngestionError(str(e))

    if ocr_text and ocr_text.strip():
        sections = [f"EXTRACTED TEXT (OCR):\n{ocr_text.strip()}"]
        if vlm_text and vlm_text.strip():
            sections.append(f"CONTEXT:\n{vlm_text.strip()}")
        return "\n\n".join(sections)

    # OCR found nothing — fall back to VLM with the verbatim prompt so
    # text-light images (hardware photos, diagrams) still get useful
    # captions.
    _logger.info("ingest: OCR empty, falling back to VLM-with-verbatim-prompt")
    try:
        fallback_text = await image_describe.describe(
            http_client, content, mime=mime, verbatim_fallback=True,
        )
    except image_describe.InvalidImage as e:
        raise _IngestionError(str(e))
    return (fallback_text or "").strip()


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

    We re-read the row before mutating it because the failure path may
    have been hit after a partial commit (e.g., storage_path set).
    Best-effort: if the DB write itself fails we still want the SSE
    subscriber to wake up, so the publish runs unconditionally.
    """
    try:
        doc.status = "error"
        doc.error_message = message
        db.commit()
    except Exception:
        _logger.exception("ingest_doc: could not persist error state for %s", doc.id)
        db.rollback()
    await broker.publish(doc.id, {"status": "error", "error": message})
