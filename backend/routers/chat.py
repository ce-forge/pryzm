from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import Dict, Optional, List
import json

from db import database, models
from core import ai_engine
from core.prompt_manager import MICRO_PROMPTS
from services import knowledge
from services.workspaces import get_or_default
from schemas import (InferenceRequest, SessionResponse, SessionUpdate,
                     FolderUpdate, MessageHistory, FolderCreate, BranchRequest,
                     MessageUpdate)
from sqlalchemy import tuple_, func as sqlfunc
from sqlalchemy.exc import IntegrityError
from config import settings
from utils.formatters import format_error
import httpx
from core import ollama
from core.deps import get_http_client



router = APIRouter(tags=["AI Chat"])


def _resolve_workspace_or_404(slug: str, db: Session) -> models.Workspace:
    """Resolve a workspace slug to its ORM object; 404 if not found."""
    workspace = db.query(models.Workspace).filter(models.Workspace.slug == slug).first()
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace


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
    http_client: httpx.AsyncClient = Depends(get_http_client),
):
    # We manage the upfront DB session manually instead of using
    # Depends(get_db) so the connection is returned to the pool BEFORE the
    # long-lived streaming response begins. With Depends, the dependency's
    # cleanup runs after the StreamingResponse finishes, which can hold the
    # connection for the full generation lifetime and exhaust the pool when
    # multiple sessions stream concurrently.
    db = database.SessionLocal()
    try:
        workspace = get_or_default(db, request.mode)
        chat_session = None

        if request.session_id:
            chat_session = db.query(models.Session).filter(models.Session.id == request.session_id).first()

        if not chat_session:
            generated_title = await ai_engine.generate_title(http_client, request.prompt, request.model)
            chat_session = models.Session(
                title=generated_title,
                workspace_id=workspace.id,
            )
            db.add(chat_session)
            db.commit()
            db.refresh(chat_session)
        elif chat_session.title in ["Document Upload Session", "New Diagnostic Session", "New Diagnostic Chat"]:
            chat_session.title = await ai_engine.generate_title(http_client, request.prompt, request.model)
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

        if not request.skip_db_save:
            user_msg = models.Message(session_id=chat_session.id, role="user", content=request.prompt)
            db.add(user_msg)
            db.commit()

        history = db.query(models.Message).filter(models.Message.session_id == chat_session.id).order_by(models.Message.created_at).all()
        safe_messages = [{"role": msg.role, "content": msg.content} for msg in history]

        # Capture identifiers needed inside the generator so we don't reach into
        # `chat_session` after the local `db` is closed below.
        session_id = chat_session.id
        workspace_id = workspace.id
    finally:
        db.close()

    async def generate():
        yield json.dumps({"status": "started", "session_id": session_id}) + "\n"

        full_response = ""
        completed = False
        disconnected = False

        try:
            async for chunk in ai_engine.stream_chat(
                http_client,
                safe_messages,
                workspace_id=workspace_id,
                session_id=session_id,
                model_name=request.model,
            ):
                if await http_request.is_disconnected():
                    disconnected = True
                    break
                full_response += chunk
                yield json.dumps({"chunk": chunk}) + "\n"

            if not disconnected:
                yield json.dumps({"done": True}) + "\n"
                completed = True

        except Exception as e:
            error_msg = format_error(str(e), "Fatal Stream Error")
            full_response += error_msg
            try:
                yield json.dumps({"chunk": error_msg}) + "\n"
            except Exception:
                # If the client is already gone, we can't yield; still want the
                # finally block to persist what we have.
                pass

        finally:
            if completed:
                status = "complete"
            elif disconnected:
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

                    # Memory condenser only summarises clean (status=complete)
                    # user/assistant exchanges — aborted or failed turns are
                    # noise we don't want to bake into long-term memory.
                    all_msgs = background_db.query(models.Message).filter(
                        models.Message.session_id == session_id
                    ).order_by(models.Message.created_at).all()

                    memory_msg = next((m for m in all_msgs if m.role == "memory"), None)

                    last_id = None
                    old_summary = ""
                    if memory_msg:
                        try:
                            mem_data = json.loads(memory_msg.content)
                            last_id = mem_data.get("last_summarized_id")
                            old_summary = mem_data.get("summary", "")
                        except Exception:
                            old_summary = memory_msg.content

                    active_msgs = [
                        m for m in all_msgs
                        if m.role in ["user", "assistant"] and m.status == "complete"
                    ]

                    start_idx = 0
                    if last_id:
                        for i, m in enumerate(active_msgs):
                            if m.id == last_id:
                                start_idx = i + 1
                                break

                    unsummarized = active_msgs[start_idx:]

                    if len(unsummarized) > settings.MEMORY_CONDENSE_THRESHOLD:
                        retain_count = settings.MEMORY_CONDENSE_RETAIN
                        to_summarize = unsummarized[:-retain_count]
                        new_last_id = to_summarize[-1].id

                        msg_dicts = [{"role": m.role, "content": m.content} for m in to_summarize]
                        new_summary_text = await ai_engine.condense_chat_memory(http_client, old_summary, msg_dicts, request.model)

                        new_mem_data = {
                            "last_summarized_id": new_last_id,
                            "summary": new_summary_text,
                        }

                        if memory_msg:
                            memory_msg.content = json.dumps(new_mem_data)
                        else:
                            background_db.add(models.Message(
                                session_id=session_id,
                                role="memory",
                                content=json.dumps(new_mem_data),
                            ))

                        background_db.commit()

                except Exception as e:
                    background_db.rollback()
                    print(f"Failed to process background memory: {e}")
                finally:
                    background_db.close()

    return StreamingResponse(generate(), media_type="application/x-ndjson")

@router.post("/upload")
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    workspace: str = Form("it_copilot"),
    session_id: Optional[str] = Form(None),
    is_global: bool = Form(False),
    db: Session = Depends(database.get_db),
    http_client: httpx.AsyncClient = Depends(get_http_client),
):
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
    try:
        text_content = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Only UTF-8 text files are currently supported.")

    active_session_id = None
    if session_id and session_id not in ["null", "undefined", "temp_new_chat", ""]:
        existing_session = db.query(models.Session).filter(models.Session.id == session_id).first()
        if existing_session:
            active_session_id = session_id

    result = await knowledge.ingest_document(
        http_client,
        db=db,
        filename=file.filename,
        content=text_content,
        workspace_id=ws.id,
        session_id=active_session_id,
        is_global=is_global,
    )

    return {
        "message": f"Successfully ingested {file.filename}",
        "details": result,
        "session_id": active_session_id,
    }

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
async def get_ollama_models(http_client: httpx.AsyncClient = Depends(get_http_client)):
    try:
        all_models = await ollama.list_models(http_client)
        chat_models = [m for m in all_models if "embed" not in m.lower()]
        return chat_models if chat_models else ["gemma4:e4b"]
    except Exception:
        return ["gemma4:e4b"]

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
