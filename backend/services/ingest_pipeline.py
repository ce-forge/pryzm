"""End-to-end document ingestion pipeline.

Async-ingestion PR 2 (docs/specs/2026-05-15-async-ingestion.md).
This module owns the "what does ingesting one upload mean" logic
that used to live inline in /upload. PR 2 extracts it into a single
seam without changing externally-observable behavior — /upload
awaits ingest_doc synchronously, validation errors still surface
as HTTPException, the response shape is unchanged.

PR 3 will rewrite this to operate on an already-committed Document
row, publish status events to the broker, and stop raising
HTTPException in favor of persisting error_message on the row.
"""
from __future__ import annotations

import asyncio
from typing import Optional

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from services import image_describe, image_storage, knowledge, pdf_extract


async def ingest_doc(
    *,
    http_client: httpx.AsyncClient,
    db: Session,
    content: bytes,
    mime: str,
    filename: str,
    workspace_id: str,
    session_id: Optional[str] = None,
    is_global: bool = False,
) -> dict:
    """Caption-or-extract → save (image only) → chunk + embed.

    Returns the same `result` dict that `/upload` used to build inline:
    {"status": "success", "chunks_created": N, "document_id": "..."}.
    Raises HTTPException on validation failure (unsupported MIME,
    empty caption, non-UTF-8 text, etc.) so the route handler can
    return a meaningful 4xx without touching the body.
    """
    storage_path: Optional[str] = None
    if mime.startswith("image/"):
        try:
            text_content = await image_describe.describe(http_client, content, mime=mime)
        except image_describe.InvalidImage as e:
            raise HTTPException(status_code=400, detail=str(e))
        if not text_content.strip():
            raise HTTPException(
                status_code=422,
                detail="The model returned no description for this image.",
            )
        # Persist bytes only after captioning succeeds, so failed
        # uploads don't leak files on disk.
        storage_path = image_storage.save_image(content, mime=mime)
    elif mime == "application/pdf" or filename.lower().endswith(".pdf"):
        try:
            text_content = await asyncio.to_thread(pdf_extract.extract_text, content)
        except pdf_extract.InvalidPdf as e:
            raise HTTPException(status_code=400, detail=f"Could not parse PDF: {e}")
        if not text_content.strip():
            raise HTTPException(
                status_code=422,
                detail="No extractable text in this PDF. Scanned/image-only PDFs aren't supported yet.",
            )
    else:
        try:
            text_content = content.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(
                status_code=400,
                detail="Only UTF-8 text files are currently supported.",
            )

    return await knowledge.ingest_document(
        http_client,
        db=db,
        filename=filename,
        content=text_content,
        workspace_id=workspace_id,
        session_id=session_id,
        is_global=is_global,
        storage_path=storage_path,
    )
