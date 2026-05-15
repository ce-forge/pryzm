from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, UploadFile, File, Form, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import Dict, Optional, List
import asyncio
import json

from db import database, models
from core import ai_engine
from core.auth import require_token
from core.prompt_manager import MICRO_PROMPTS
from core.engine_config import engine_config_for
from services import ingest_broker, ingest_pipeline
from services.workspaces import get_or_default
from schemas import (InferenceRequest, SessionResponse, SessionUpdate,
                     FolderUpdate, MessageHistory, FolderCreate, BranchRequest,
                     MessageUpdate)
from sqlalchemy import tuple_, func as sqlfunc
from sqlalchemy.exc import IntegrityError
from config import settings
from utils.formatters import format_error
import httpx
from core import llm_server
from core.deps import get_http_client
from core.llm_metrics import get_last_chat_snapshot as _last_chat_metric_snapshot
from services import condense
from tools.registry import build_tool_set


def _error_envelope(exc: Exception) -> dict:
    """Map an exception to a {error, code} envelope for the SSE stream.

    Codes:
      llm_unreachable — connection refused, DNS fail, etc.
      llm_timeout     — read timeout (model hung)
      tool_timeout    — a tool exceeded TOOL_TIMEOUT_SECONDS
      engine_error    — anything else (generic catch-all)
    """
    if isinstance(exc, httpx.ConnectError):
        return {"error": "LLM server is not reachable.", "code": "llm_unreachable"}
    if isinstance(exc, (httpx.ReadTimeout, httpx.PoolTimeout)):
        return {"error": "LLM server took too long to respond.", "code": "llm_timeout"}
    if isinstance(exc, asyncio.TimeoutError):
        return {"error": "Tool execution timed out.", "code": "tool_timeout"}
    return {"error": str(exc) or "Engine error.", "code": "engine_error"}


router = APIRouter(tags=["AI Chat"])


# Bound on how long /analyze will wait for in-flight attachments to
# finish ingestion. Larger than typical captioning (~10-15s) so we
# don't bail prematurely; smaller than a runaway "stuck task" so we
# can degrade gracefully to "no RAG context for that doc" instead.
_ATTACHMENT_WAIT_TIMEOUT_SECONDS = 60.0


async def _wait_for_processing_attachments(
    attachment_ids: list[str],
    workspace_id: str,
    db: Session,
) -> None:
    """Wait for any 'processing' attachments to reach terminal state.

    Subscribes to the ingest broker for each in-flight doc and awaits
    the first terminal event (or the global timeout). Already-terminal
    docs are skipped. Reads status fresh from DB after subscribing —
    if it flipped between the check and subscribe, we won't block.
    """
    if not attachment_ids:
        return
    docs = (
        db.query(models.Document)
        .filter(
            models.Document.id.in_(attachment_ids),
            models.Document.workspace_id == workspace_id,
        )
        .all()
    )
    processing_ids = [d.id for d in docs if d.status == "processing"]
    if not processing_ids:
        return

    broker = ingest_broker.broker()
    queues: dict[str, asyncio.Queue] = {
        doc_id: broker.subscribe(doc_id) for doc_id in processing_ids
    }
    deadline = asyncio.get_event_loop().time() + _ATTACHMENT_WAIT_TIMEOUT_SECONDS
    try:
        for doc_id, queue in queues.items():
            # Re-check status — task may have finished between subscribe
            # call above and now. Avoids waiting on an already-terminal
            # row that never publishes again.
            db.expire_all()
            doc = db.query(models.Document).filter(models.Document.id == doc_id).first()
            if doc is None or doc.status in ("ready", "error"):
                continue
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                break
            try:
                await asyncio.wait_for(queue.get(), timeout=remaining)
            except asyncio.TimeoutError:
                # Bail out of the wait; the auto-RAG path will still run,
                # just without context from the still-processing doc.
                break
    finally:
        for doc_id, queue in queues.items():
            broker.unsubscribe(doc_id, queue)


def _resolve_workspace_or_404(slug: str, db: Session) -> models.Workspace:
    """Resolve a workspace slug to its ORM object; 404 if not found."""
    workspace = db.query(models.Workspace).filter(models.Workspace.slug == slug).first()
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace


def workspace_dep(
    workspace: Optional[str] = None,
    db: Session = Depends(database.get_db),
) -> models.Workspace:
    """Resolve a workspace slug (from query param) to its ORM row.

    422 if missing, 404 if the slug does not exist. This is the single
    boundary where slug → id resolution happens for the /analyze route.
    """
    if not workspace:
        raise HTTPException(status_code=422, detail="workspace query parameter is required")
    ws = db.query(models.Workspace).filter(models.Workspace.slug == workspace).first()
    if not ws:
        raise HTTPException(status_code=404, detail=f"Workspace not found: {workspace}")
    return ws


def _message_in_workspace_or_404(
    message_id: str,
    workspace_id: str,
    db: Session,
) -> models.Message:
    """Return the message if it belongs to a session in workspace_id, else 404.

    Message has no direct workspace_id — it's scoped via Session.workspace_id.
    Returns 404 (not 403) on cross-workspace access to avoid info leakage,
    matching the convention in core.workspace_access.
    """
    msg = (
        db.query(models.Message)
        .join(models.Session, models.Message.session_id == models.Session.id)
        .filter(
            models.Message.id == message_id,
            models.Session.workspace_id == workspace_id,
        )
        .first()
    )
    if msg is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return msg


@router.get("/sessions", response_model=List[SessionResponse])
def get_sessions(
    workspace: str = "it_copilot",
    folder_id: Optional[str] = None,
    limit: Optional[int] = None,
    offset: int = 0,
    db: Session = Depends(database.get_db),
):
    """List sessions for a workspace, newest first.

    folder_id (optional) — restrict to a single folder. Omit to return all
    sessions in the workspace; "unsorted" sessions (folder_id NULL) are
    currently filtered client-side, since query params can't cleanly express
    'null match'.

    limit/offset (optional) — pagination. With no params the response is
    unbounded to preserve the existing frontend's 'load all' behaviour.
    """
    ws = get_or_default(db, workspace)
    q = db.query(models.Session).filter(models.Session.workspace_id == ws.id)
    if folder_id is not None:
        q = q.filter(models.Session.folder_id == folder_id)
    q = q.order_by(models.Session.created_at.desc())
    if offset:
        q = q.offset(offset)
    if limit is not None:
        q = q.limit(limit)
    return q.all()

@router.get("/sessions/{session_id}", response_model=List[MessageHistory])
def get_session_history(
    session_id: str,
    limit: Optional[int] = None,
    offset: int = 0,
    db: Session = Depends(database.get_db),
):
    """Return user/assistant messages in chronological order.

    limit/offset (optional) — pagination. Defaults preserve the existing
    'load everything' behaviour so the chat UI keeps working unchanged.
    """
    session = db.query(models.Session).filter(models.Session.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    q = db.query(models.Message).filter(
        models.Message.session_id == session_id,
        models.Message.role.in_(["user", "assistant"]),
    ).order_by(models.Message.created_at)
    if offset:
        q = q.offset(offset)
    if limit is not None:
        q = q.limit(limit)
    messages = q.all()

    return [{"id": m.id,
            "role": m.role,
            "content": m.content,
            "status": m.status,
            "timestamp": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
    ]

@router.patch("/sessions/{session_id}")
def update_session(session_id: str, payload: SessionUpdate, db: Session = Depends(database.get_db)):
    db_session = db.query(models.Session).filter(models.Session.id == session_id).first()
    if db_session:
        update_data = payload.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(db_session, key, value)
        db.commit()
        return {"status": "success"}
    return {"status": "error", "message": "Session not found"}

@router.patch("/folders/{folder_id}")
def update_folder(folder_id: str, payload: FolderUpdate, db: Session = Depends(database.get_db)):
    db_folder = db.query(models.Folder).filter(models.Folder.id == folder_id).first()
    if db_folder:
        db_folder.name = payload.name
        db.commit()
        return {"status": "success"}
    return {"status": "error", "message": "Folder not found"}

@router.delete("/sessions/{session_id}")
def delete_session(session_id: str, db: Session = Depends(database.get_db)):
    session = db.query(models.Session).filter(models.Session.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    db.delete(session)
    db.commit()
    return {"status": "deleted"}

@router.post("/analyze")
async def analyze_data(
    http_request: Request,
    request: InferenceRequest,
    background_tasks: BackgroundTasks,
    workspace: models.Workspace = Depends(workspace_dep),
    http_client: httpx.AsyncClient = Depends(get_http_client),
):
    # Resolve engine config and tool set once at the boundary.
    engine_config = engine_config_for(workspace)
    tool_set = build_tool_set(workspace)

    # We manage the upfront DB session manually instead of using
    # Depends(get_db) so the connection is returned to the pool BEFORE the
    # long-lived streaming response begins. With Depends, the dependency's
    # cleanup runs after the StreamingResponse finishes, which can hold the
    # connection for the full generation lifetime and exhaust the pool when
    # multiple sessions stream concurrently.
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
            # Scope the claim to documents the caller already owns. Without this
            # filter, a client could attach foreign-workspace document ids and the
            # update would re-parent them into the caller's workspace — silent
            # cross-workspace data theft.
            db.query(models.Document).filter(
                models.Document.id.in_(request.attachments),
                models.Document.workspace_id == workspace.id,
            ).update(
                {"session_id": chat_session.id},
                synchronize_session=False,
            )
            db.commit()

            # Frontend may have submitted before all attached docs finished
            # processing. Wait for terminal status on each via the broker
            # so auto-RAG sees the captions when we hit knowledge.retrieve_*.
            # Bounded so a stuck ingestion doesn't deadlock the chat call.
            await _wait_for_processing_attachments(
                request.attachments, workspace.id, db,
            )

        user_message_id: Optional[str] = None
        if not request.skip_db_save:
            user_msg = models.Message(session_id=chat_session.id, role="user", content=request.prompt)
            db.add(user_msg)
            db.commit()
            db.refresh(user_msg)
            user_message_id = user_msg.id

        history = db.query(models.Message).filter(models.Message.session_id == chat_session.id).order_by(models.Message.created_at).all()
        safe_messages = [{"role": msg.role, "content": msg.content} for msg in history]

        # Capture identifiers needed inside the generator so we don't reach into
        # `chat_session` after the local `db` is closed below.
        session_id = chat_session.id
        workspace_id = workspace.id
    finally:
        db.close()

    async def generate():
        from core.llm_metrics import set_request_context
        set_request_context(workspace_id=workspace_id, session_id=session_id)

        # `user_message_id` is sent here so the client can swap its optimistic
        # temp-u id for the real DB UUID at the moment of stream start — no
        # post-stream /sessions/{id} refetch needed (and therefore no race
        # against the next send).
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
                # Save the assistant message NOW so the `done` event can carry
                # its real DB id. Previously we saved in the finally block and
                # the client had to refetch the session history to learn the
                # id — that refetch was the source of the rapid-sends race.
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

                # The terminating chunk now carries an aggregate `usage` block so
                # bench_llm.py can read it directly without scraping logs. Token counts
                # come from the LAST chat call's snapshot (the call that produced the
                # user-visible answer). Earlier tool-loop iterations are intentionally
                # not summed — bench_llm asks "how fast was the FINAL answer", not
                # "how many tokens did the agentic loop burn in total."
                usage = _last_chat_metric_snapshot()
                yield json.dumps({
                    "done": True,
                    "usage": usage,
                    "assistant_message_id": assistant_message_id,
                }) + "\n"
                completed = True

        except asyncio.CancelledError:
            # Client disconnected. Re-raise so the framework cleans up cleanly.
            raise
        except Exception as e:
            yield json.dumps(_error_envelope(e)) + "\n"
            # Don't re-raise; the response ends here gracefully.
            return

        finally:
            # Save aborted/failed responses here. The clean-completion path
            # already saved before yielding `done`; this branch only fires
            # when the stream ended without `completed=True`.
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

    # Schedule condensation to run after the response is fully sent.
    # The advisory lock in condense_for_session ensures only one condenser
    # runs per session at a time — concurrent requests skip silently.
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
    """Accept an upload, persist a `Document(status='processing')` row,
    and spawn the ingestion pipeline as a background task.

    Returns 202 immediately with `{document_id, status: 'processing',
    session_id, filename}`. The client opens an SSE connection at
    `/uploads/{document_id}/events` to learn when the doc flips to
    `ready` or `error`.
    """
    ws = get_or_default(db, workspace)
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
    db: Session = Depends(database.get_db),
    _auth: None = Depends(require_token),
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
    doc = db.query(models.Document).filter(models.Document.id == document_id).first()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

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


@router.delete("/documents/{document_id}")
def delete_document(document_id: str, db: Session = Depends(database.get_db)):
    """Hard-delete a Document + its chunks + its on-disk file.

    Called by the frontend when the user removes an upload pill before
    sending the prompt. Without this the Document, its embeddings, and
    the saved bytes would sit orphaned in the workspace forever.

    Chunks cascade via the FK; the on-disk file is unlinked by the
    after_delete event listener on Document (db/models.py).
    """
    doc = db.query(models.Document).filter(models.Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    db.delete(doc)
    db.commit()
    return {"status": "deleted"}


@router.get("/folders")
def get_folders(workspace: str = "it_copilot", db: Session = Depends(database.get_db)):
    ws = get_or_default(db, workspace)
    return db.query(models.Folder).filter(models.Folder.workspace_id == ws.id).all()


@router.post("/folders")
def create_folder(folder: FolderCreate, db: Session = Depends(database.get_db)):
    ws = get_or_default(db, folder.workspace)
    if db.query(models.Folder).filter(models.Folder.id == folder.id).first():
        raise HTTPException(status_code=409, detail="Folder with that id already exists.")
    new_folder = models.Folder(id=folder.id, name=folder.name, workspace_id=ws.id)
    db.add(new_folder)
    try:
        db.commit()
    except IntegrityError:
        # Defensive — covers the rare race where two requests pass the SELECT
        # check before either commits.
        db.rollback()
        raise HTTPException(status_code=409, detail="Folder with that id already exists.")
    return {"status": "success", "id": folder.id}

@router.delete("/folders/{folder_id}")
def delete_folder(folder_id: str, db: Session = Depends(database.get_db)):
    # Null out folder_id on any sessions that lived in this folder so they
    # show up in "Unsorted Logs" rather than carrying a dangling reference.
    db.query(models.Session).filter(models.Session.folder_id == folder_id).update(
        {"folder_id": None}, synchronize_session=False,
    )
    db.query(models.Folder).filter(models.Folder.id == folder_id).delete()
    db.commit()
    return {"status": "success"}

@router.get("/api/tools")
def get_tools_metadata():
    """Lists registered tools with their schemas for the workspace settings UI."""
    from tools.registry import TOOL_DEFINITIONS
    return [
        {
            "name": d["function"]["name"],
            "description": d["function"]["description"],
        }
        for d in TOOL_DEFINITIONS
    ]

@router.get("/api/models")
async def get_chat_models(http_client: httpx.AsyncClient = Depends(get_http_client)):
    """List the chat-capable models llama-swap has configured. The list is
    derived from infra/llama-swap-config.yaml at server start; embedding-tagged
    models are filtered out."""
    try:
        all_models = await llm_server.list_models(http_client)
        return [m for m in all_models if "embed" not in m.lower()]
    except Exception:
        return [llm_server.DEFAULT_CHAT_MODEL]

@router.get("/api/prompts")
def get_prompts():
    return MICRO_PROMPTS.get_all()

@router.patch("/api/prompts")
def update_prompts(payload: Dict[str, str]):
    """Upsert one or more prompt overrides. Values are constrained to strings
    by the schema so callers can't smuggle non-string JSON into the file.
    To remove an override (and fall back to the default), DELETE the key."""
    MICRO_PROMPTS.save_prompts(payload)
    return {"status": "success"}

@router.delete("/api/prompts/{key}")
def delete_prompt_override(key: str):
    """Drop a single prompt override so the default takes effect again."""
    removed = MICRO_PROMPTS.delete_prompt(key)
    if not removed:
        raise HTTPException(status_code=404, detail="No override exists for that key.")
    return {"status": "deleted", "key": key}

@router.patch("/messages/{message_id}")
def update_message(
    message_id: str,
    payload: MessageUpdate,
    workspace: str = Query(..., description="Slug of the workspace the message belongs to"),
    db: Session = Depends(database.get_db),
):
    """Edit the content of a message. Scoped to workspace — cross-workspace
    attempts return 404 (not 403) for info-leak protection."""
    workspace_obj = _resolve_workspace_or_404(workspace, db)
    msg = _message_in_workspace_or_404(message_id, workspace_obj.id, db)

    msg.content = payload.content
    db.commit()
    return {"status": "success"}

@router.delete("/messages/{message_id}")
def delete_message(
    message_id: str,
    workspace: str = Query(..., description="Slug of the workspace the message belongs to"),
    db: Session = Depends(database.get_db),
):
    workspace_obj = _resolve_workspace_or_404(workspace, db)
    msg = _message_in_workspace_or_404(message_id, workspace_obj.id, db)

    session_id_resp = msg.session_id
    db.delete(msg)
    db.commit()
    return {"status": "success", "session_id": session_id_resp}

@router.post("/sessions/{session_id}/branch")
def branch_session(session_id: str, body: BranchRequest, db: Session = Depends(database.get_db)):
    old_session = db.query(models.Session).filter(models.Session.id == session_id).first()
    if not old_session:
        raise HTTPException(status_code=404, detail="Source session not found")

    target = db.query(models.Message).filter(
        models.Message.id == body.up_to_message_id,
        models.Message.session_id == session_id,
    ).first()
    if not target:
        raise HTTPException(status_code=404, detail="up_to_message_id does not belong to this session")

    # Avoid stacking "(Branch) (Branch) (Branch) ..." when re-branching a branch.
    branched_title = old_session.title if old_session.title.endswith("(Branch)") else f"{old_session.title} (Branch)"
    new_session = models.Session(title=branched_title, workspace_id=old_session.workspace_id)
    db.add(new_session)
    db.commit()
    db.refresh(new_session)

    # Pull only user/assistant rows in chronological order. Memory rows are
    # skipped because their JSON payload references message IDs that won't
    # exist in the new branch and would corrupt the condenser state.
    messages = db.query(models.Message).filter(
        models.Message.session_id == session_id,
        models.Message.role.in_(["user", "assistant"]),
    ).order_by(models.Message.created_at, models.Message.id).all()

    for m in messages:
        # clock_timestamp() returns real wall-clock time per row, so each
        # copy gets a distinct created_at. The default `now()` would have
        # given every row in this transaction the same timestamp, breaking
        # any later truncate that orders by created_at.
        new_msg = models.Message(
            session_id=new_session.id,
            role=m.role,
            content=m.content,
            status=m.status,
            created_at=sqlfunc.clock_timestamp(),
        )
        db.add(new_msg)
        if m.id == body.up_to_message_id:
            break

    db.commit()
    return {"new_session_id": new_session.id}

@router.delete("/sessions/{session_id}/truncate/{message_id}")
def truncate_session(
    session_id: str,
    message_id: str,
    workspace: str = Query(..., description="Slug of the workspace the session belongs to"),
    db: Session = Depends(database.get_db),
):
    """Delete all messages in a session that occurred AFTER the specified message_id.

    Uses (created_at, id) as a tuple ordering so two messages sharing a
    created_at (which can happen when multiple rows commit in the same
    transaction — see branch_session) still produce a deterministic split.

    Scoped to workspace — cross-workspace 404s.
    """
    workspace_obj = _resolve_workspace_or_404(workspace, db)

    # Look up the session AND target message in one go, both scoped by workspace.
    target_msg = (
        db.query(models.Message)
        .join(models.Session, models.Message.session_id == models.Session.id)
        .filter(
            models.Message.id == message_id,
            models.Message.session_id == session_id,
            models.Session.workspace_id == workspace_obj.id,
        )
        .first()
    )
    if not target_msg:
        raise HTTPException(status_code=404, detail="Target message not found")

    deleted_count = db.query(models.Message).filter(
        models.Message.session_id == session_id,
        tuple_(models.Message.created_at, models.Message.id) >
            (target_msg.created_at, target_msg.id),
    ).delete(synchronize_session=False)

    # If the memory row references a now-deleted message_id, the condenser
    # would silently restart from index 0 next time and re-summarize content
    # already baked into the summary. Easier and safer to just drop the
    # memory row whenever the session is truncated — the next condense pass
    # rebuilds from whatever survives.
    db.query(models.Message).filter(
        models.Message.session_id == session_id,
        models.Message.role == "memory",
    ).delete(synchronize_session=False)

    db.commit()
    return {"status": "success", "deleted_count": deleted_count}
