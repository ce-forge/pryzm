"""Document ingestion + retrieval routes.

POST /upload returns 202 immediately and runs ingestion (chunk + embed,
or image captioning) as a background task. The client subscribes to
GET /uploads/{id}/events to learn when the doc flips to ready/error.

GET /documents/{id}/raw streams the original bytes of image documents
(the only type that persists original bytes — PDFs/text are stored as
chunks only). Uses a bearer-or-query-token auth fallback because
`<img src=...>` can't set custom headers.

DELETE /documents/{id} is fired by the frontend when the user removes
an upload pill before sending; without it the Document, embeddings, and
on-disk bytes would sit orphaned.
"""
import asyncio
import json
import os
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from config import settings
from core import cookie_auth
from core.deps import get_http_client
from core.workspace_access import verify_workspace_owns, workspace_query_dep
from db import database, models
from services import ingest_broker, ingest_pipeline


router = APIRouter(tags=["Documents"])


_IMAGE_MIME_BY_EXT = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


@router.post("/upload", status_code=202)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    workspace: str = Form("it_copilot"),
    session_id: Optional[str] = Form(None),
    is_global: bool = Form(False),
    db: Session = Depends(database.get_db),
    http_client: httpx.AsyncClient = Depends(get_http_client),
    user: models.User = Depends(cookie_auth.current_user),
):
    """Accept an upload, persist a `Document(status='processing')` row,
    and spawn the ingestion pipeline as a background task.

    Returns 202 immediately with `{document_id, status: 'processing',
    session_id, filename}`. The client opens an SSE connection at
    `/uploads/{document_id}/events` to learn when the doc flips to
    `ready` or `error`.
    """
    ws = (
        db.query(models.Workspace)
        .filter(
            models.Workspace.slug == workspace,
            models.Workspace.user_id == user.id,
        )
        .first()
    )
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    # Stream the upload in 8KB chunks and bail as soon as we cross the
    # configured ceiling. Reading the whole body unbounded (await file.read())
    # would let a single request balloon the worker's memory.
    max_bytes = settings.UPLOAD_MAX_BYTES
    buf = bytearray()
    while True:
        chunk = await file.read(8192)
        if not chunk:
            break
        buf.extend(chunk)
        if len(buf) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"File exceeds upload limit of {max_bytes} bytes.",
            )
    content = bytes(buf)
    content_type = (file.content_type or "").lower()

    active_session_id = None
    if session_id and session_id not in ["null", "undefined", "temp_new_chat", ""]:
        existing_session = db.query(models.Session).filter(models.Session.id == session_id).first()
        if existing_session:
            active_session_id = session_id

    doc = models.Document(
        filename=file.filename,
        workspace_id=ws.id,
        session_id=active_session_id,
        is_global=is_global,
        status="processing",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    document_id = doc.id

    ingest_broker.add_task(ingest_pipeline.ingest_doc(
        document_id=document_id,
        http_client=http_client,
        content=content,
        mime=content_type,
        filename=file.filename,
    ))

    return {
        "document_id": document_id,
        "status": "processing",
        "filename": file.filename,
        "session_id": active_session_id,
    }


@router.get("/uploads/{document_id}/events")
async def upload_events(
    document_id: str,
    request: Request,
    workspace: models.Workspace = Depends(workspace_query_dep),
    db: Session = Depends(database.get_db),
):
    """Server-Sent Events stream for one document's ingestion lifecycle.

    The handler:

    1. Subscribes to the broker FIRST (so we can't miss a publish that
       races us between the DB read and the subscribe).
    2. Reads the current Document.status. If it's already terminal
       (`ready` or `error`), replays it as a single event and returns —
       no point holding a connection open for a row that's done.
    3. Otherwise loops on the queue, forwarding events until a terminal
       one arrives or the client disconnects.

    Authenticates via `Authorization: Bearer` or `?token=` (EventSource
    can't set custom headers; the URL fallback is the SSE-friendly
    concession documented in core/auth.py).
    """
    doc = verify_workspace_owns(document_id, models.Document, workspace.id, db)

    broker = ingest_broker.broker()
    queue = broker.subscribe(document_id)

    # Snapshot terminal state after subscribing. Order matters: if the
    # task finishes between the snapshot and the subscribe call we'd
    # never wake up; subscribing first means the publish queues into
    # `queue` even if status is still 'processing' below.
    db.refresh(doc)
    initial_status = doc.status
    initial_error = doc.error_message

    async def event_stream():
        try:
            if initial_status in ("ready", "error"):
                payload = {"status": initial_status}
                if initial_status == "error" and initial_error:
                    payload["error"] = initial_error
                yield f"data: {json.dumps(payload)}\n\n"
                return

            while True:
                if await request.is_disconnected():
                    return
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    # SSE keepalive — browsers and proxies time out idle
                    # connections silently otherwise.
                    yield ": keepalive\n\n"
                    continue
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("status") in ("ready", "error"):
                    return
        finally:
            broker.unsubscribe(document_id, queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/documents/{document_id}/raw")
def get_document_raw(
    document_id: str,
    workspace: models.Workspace = Depends(workspace_query_dep),
    db: Session = Depends(database.get_db),
):
    """Stream the original bytes of an uploaded document.

    Only image documents are supported today — they're the only type
    that persists original bytes (Document.storage_path is non-NULL).
    PDFs and text are stored as chunks only.

    Returns:
      200 + image bytes (Content-Type inferred from filename ext)
      404 if doc is missing
      410 if the doc exists but has no storage_path (PDF/text)
      404 if the on-disk file is gone (e.g. cleanup race)

    Auth: bearer header OR `?token=` URL fallback. The URL fallback
    matters because `<img src=...>` can't set custom headers, just
    like EventSource.
    """
    doc = verify_workspace_owns(document_id, models.Document, workspace.id, db)
    if not doc.storage_path:
        raise HTTPException(
            status_code=410,
            detail="Original bytes not available for this document type.",
        )
    if not os.path.exists(doc.storage_path):
        raise HTTPException(status_code=404, detail="Document file is missing on disk.")

    ext = os.path.splitext(doc.filename.lower())[1]
    mime = _IMAGE_MIME_BY_EXT.get(ext, "application/octet-stream")

    def _stream():
        with open(doc.storage_path, "rb") as f:
            while chunk := f.read(64 * 1024):
                yield chunk

    return StreamingResponse(
        _stream(),
        media_type=mime,
        headers={
            "Cache-Control": "private, max-age=2592000",
            "ETag": f'"{doc.id}"',
            "Content-Disposition": f'inline; filename="{doc.filename}"',
        },
    )


@router.delete("/documents/{document_id}")
def delete_document(
    document_id: str,
    workspace: models.Workspace = Depends(workspace_query_dep),
    db: Session = Depends(database.get_db),
):
    """Hard-delete a Document + its chunks + its on-disk file.

    Called by the frontend when the user removes an upload pill before
    sending the prompt. Without this the Document, its embeddings, and
    the saved bytes would sit orphaned in the workspace forever.

    Scoped to workspace — cross-workspace 404s.

    Chunks cascade via the FK; the on-disk file is unlinked by the
    after_delete event listener on Document (db/models.py).
    """
    doc = verify_workspace_owns(document_id, models.Document, workspace.id, db)
    db.delete(doc)
    db.commit()
    return {"status": "deleted"}
