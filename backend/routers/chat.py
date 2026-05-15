"""Streaming AI endpoints + document upload surface.

This router owns the heavy long-lived endpoints: the SSE chat stream
(`/analyze`), the async document upload pipeline (`/upload` →
`/uploads/{id}/events`), and the document cleanup endpoint. Session,
folder, message, and metadata CRUD live in sibling routers.
"""
import asyncio
import json
from typing import Optional

import httpx
from fastapi import (
    APIRouter, BackgroundTasks, Depends, File, Form, HTTPException,
    Request, UploadFile,
)
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from config import settings
from core import ai_engine, llm_server
from core.auth import require_token
from core.deps import get_http_client
from core.engine_config import engine_config_for
from core.llm_metrics import get_last_chat_snapshot as _last_chat_metric_snapshot
from db import database, models
from schemas import InferenceRequest
from services import condense, ingest_broker, ingest_pipeline
from services.workspaces import get_or_default
from tools.registry import build_tool_set


router = APIRouter(tags=["AI Chat"])


def _error_envelope(exc: Exception) -> dict:
    """Map an exception to a {error, code} envelope for the SSE stream.

    Codes: llm_unreachable / llm_timeout / tool_timeout / engine_error.
    """
    if isinstance(exc, httpx.ConnectError):
        return {"error": "LLM server is not reachable.", "code": "llm_unreachable"}
    if isinstance(exc, (httpx.ReadTimeout, httpx.PoolTimeout)):
        return {"error": "LLM server took too long to respond.", "code": "llm_timeout"}
    if isinstance(exc, asyncio.TimeoutError):
        return {"error": "Tool execution timed out.", "code": "tool_timeout"}
    return {"error": str(exc) or "Engine error.", "code": "engine_error"}


def workspace_dep(
    workspace: Optional[str] = None,
    db: Session = Depends(database.get_db),
) -> models.Workspace:
    """422 if missing, 404 if the slug doesn't exist."""
    if not workspace:
        raise HTTPException(status_code=422, detail="workspace query parameter is required")
    ws = db.query(models.Workspace).filter(models.Workspace.slug == workspace).first()
    if not ws:
        raise HTTPException(status_code=404, detail=f"Workspace not found: {workspace}")
    return ws


@router.post("/analyze")
async def analyze_data(
    http_request: Request,
    request: InferenceRequest,
    background_tasks: BackgroundTasks,
    workspace: models.Workspace = Depends(workspace_dep),
    http_client: httpx.AsyncClient = Depends(get_http_client),
):
    engine_config = engine_config_for(workspace)
    tool_set = build_tool_set(workspace)

    # Manual DB session so we can release the connection before the
    # streaming response starts. Depends(get_db)'s cleanup runs AFTER
    # the StreamingResponse finishes, which exhausts the pool under
    # concurrent streams.
    db = database.SessionLocal()
    try:
        chat_session = None

        if request.session_id:
            chat_session = db.query(models.Session).filter(models.Session.id == request.session_id).first()

        if not chat_session:
            generated_title = await ai_engine.generate_title(http_client, request.prompt, engine_config=engine_config)
            chat_session = models.Session(
                title=generated_title,
                workspace_id=workspace.id,
            )
            db.add(chat_session)
            db.commit()
            db.refresh(chat_session)
        elif chat_session.title in ["Document Upload Session", "New Diagnostic Session", "New Diagnostic Chat"]:
            chat_session.title = await ai_engine.generate_title(http_client, request.prompt, engine_config=engine_config)
            db.commit()
            db.refresh(chat_session)

        if request.attachments:
            # Scope the claim to documents the caller already owns —
            # otherwise foreign-workspace doc ids would get silently
            # re-parented into the caller's workspace.
            db.query(models.Document).filter(
                models.Document.id.in_(request.attachments),
                models.Document.workspace_id == workspace.id,
            ).update(
                {"session_id": chat_session.id},
                synchronize_session=False,
            )
            db.commit()

        user_message_id: Optional[str] = None
        if not request.skip_db_save:
            user_msg = models.Message(session_id=chat_session.id, role="user", content=request.prompt)
            db.add(user_msg)
            db.commit()
            db.refresh(user_msg)
            user_message_id = user_msg.id

        history = db.query(models.Message).filter(models.Message.session_id == chat_session.id).order_by(models.Message.created_at).all()
        safe_messages = [{"role": msg.role, "content": msg.content} for msg in history]

        session_id = chat_session.id
        workspace_id = workspace.id
    finally:
        db.close()

    async def generate():
        from core.llm_metrics import set_request_context
        set_request_context(workspace_id=workspace_id, session_id=session_id)

        # user_message_id lets the client swap its optimistic temp-id
        # for the real DB UUID at stream start, removing the rapid-send
        # race that a post-stream refetch caused.
        yield json.dumps({
            "status": "started",
            "session_id": session_id,
            "user_message_id": user_message_id,
        }) + "\n"

        full_response = ""
        completed = False
        disconnected = False
        assistant_message_id: Optional[str] = None

        try:
            async for chunk in ai_engine.stream_chat(
                http_client,
                safe_messages,
                workspace_id=workspace_id,
                engine_config=engine_config,
                tool_set=tool_set,
                session_id=session_id,
                is_disconnected=http_request.is_disconnected,
            ):
                if await http_request.is_disconnected():
                    disconnected = True
                    break
                full_response += chunk
                yield json.dumps({"chunk": chunk}) + "\n"

            if not disconnected:
                # Save NOW so `done` can carry the real id; avoids the
                # refetch race against the next user send.
                if full_response.strip():
                    save_db = database.SessionLocal()
                    try:
                        ai_msg = models.Message(
                            session_id=session_id,
                            role="assistant",
                            content=full_response,
                            status="complete",
                        )
                        save_db.add(ai_msg)
                        save_db.commit()
                        save_db.refresh(ai_msg)
                        assistant_message_id = ai_msg.id
                    except Exception as e:
                        save_db.rollback()
                        print(f"Failed to save assistant message: {e}")
                    finally:
                        save_db.close()

                # Usage is from the LAST chat call's snapshot — bench_llm.py
                # measures "how fast was the FINAL answer," not the
                # tool-loop aggregate.
                usage = _last_chat_metric_snapshot()
                yield json.dumps({
                    "done": True,
                    "usage": usage,
                    "assistant_message_id": assistant_message_id,
                }) + "\n"
                completed = True

        except asyncio.CancelledError:
            raise
        except Exception as e:
            yield json.dumps(_error_envelope(e)) + "\n"
            return

        finally:
            # Aborted/failed branch. The clean-completion path saved
            # before yielding `done`, so this only fires when the stream
            # ended without completed=True.
            if not completed:
                if disconnected:
                    status = "aborted"
                    full_response += "\n\n*[Response aborted by user.]*"
                else:
                    status = "failed"

                if full_response.strip():
                    background_db = database.SessionLocal()
                    try:
                        ai_msg = models.Message(
                            session_id=session_id,
                            role="assistant",
                            content=full_response,
                            status=status,
                        )
                        background_db.add(ai_msg)
                        background_db.commit()
                    except Exception as e:
                        background_db.rollback()
                        print(f"Failed to save assistant message: {e}")
                    finally:
                        background_db.close()

    # Advisory lock inside condense_for_session means concurrent
    # condensers skip silently; one wins per session.
    background_tasks.add_task(
        condense.condense_for_session,
        http_client,
        session_id,
        engine_config,
    )

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        background=background_tasks,
    )


@router.post("/upload", status_code=202)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    workspace: str = Form("it_copilot"),
    session_id: Optional[str] = Form(None),
    is_global: bool = Form(False),
    db: Session = Depends(database.get_db),
    http_client: httpx.AsyncClient = Depends(get_http_client),
):
    """Accept an upload, commit a `Document(status='processing')` row,
    spawn the ingestion pipeline. Returns 202 with the doc id; the
    client opens `/uploads/{id}/events` to learn the terminal status.
    """
    ws = get_or_default(db, workspace)
    # 8KB chunks so an unbounded upload can't balloon worker memory.
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
    db: Session = Depends(database.get_db),
    _auth: None = Depends(require_token),
):
    """SSE stream of one document's ingestion lifecycle.

    Subscribe first, then snapshot status. If the row is already
    terminal we replay the single event and close. Otherwise we
    forward events from the broker until a terminal one arrives.
    Auth: bearer header OR ?token= (EventSource can't set headers).
    """
    doc = db.query(models.Document).filter(models.Document.id == document_id).first()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    broker = ingest_broker.broker()
    queue = broker.subscribe(document_id)

    # Subscribe BEFORE reading status — otherwise a publish that lands
    # between the read and the subscribe is lost forever.
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
                    # Keepalive — proxies kill idle SSE streams silently.
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


@router.delete("/documents/{document_id}")
def delete_document(document_id: str, db: Session = Depends(database.get_db)):
    """Hard-delete a Document + chunks + on-disk file. Called when the
    user removes an upload pill pre-send. Chunks cascade via FK; the
    file is unlinked by Document's after_delete listener."""
    doc = db.query(models.Document).filter(models.Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    db.delete(doc)
    db.commit()
    return {"status": "deleted"}
