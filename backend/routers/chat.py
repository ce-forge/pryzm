from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import Optional, List
import json

from db import database, models
from core import ai_engine
from core.prompt_manager import MICRO_PROMPTS
from services import knowledge
from schemas import (InferenceRequest, SessionResponse, SessionUpdate, 
                     FolderUpdate, MessageHistory, FolderCreate)
from config import settings
from utils.formatters import format_error
import requests



router = APIRouter(tags=["AI Chat"])

@router.get("/sessions", response_model=List[SessionResponse])
def get_sessions(workspace: str = "it_copilot", db: Session = Depends(database.get_db)):
    return db.query(models.Session).filter(models.Session.mode == workspace).order_by(models.Session.created_at.desc()).all()

@router.get("/sessions/{session_id}", response_model=List[MessageHistory])
def get_session_history(session_id: str, db: Session = Depends(database.get_db)):
    session = db.query(models.Session).filter(models.Session.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    messages = db.query(models.Message).filter(
        models.Message.session_id == session_id,
        models.Message.role.in_(["user", "assistant"]) 
    ).order_by(models.Message.created_at).all()
    
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
        update_data = payload.dict(exclude_unset=True) 
        print(f"\n--- DEBUG UPDATE --- payload received: {update_data}\n")
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
def analyze_data(
    http_request: Request,
    request: InferenceRequest,
):
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
            generated_title = ai_engine.generate_title(request.prompt, request.model)
            chat_session = models.Session(title=generated_title, mode=request.mode)
            db.add(chat_session)
            db.commit()
            db.refresh(chat_session)
        elif chat_session.title in ["Document Upload Session", "New Diagnostic Session", "New Diagnostic Chat"]:
            chat_session.title = ai_engine.generate_title(request.prompt, request.model)
            db.commit()
            db.refresh(chat_session)

        if request.attachments:
            db.query(models.Document).filter(
                models.Document.id.in_(request.attachments)
            ).update({"session_id": chat_session.id}, synchronize_session=False)
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
        mode = request.mode
        model_name = request.model
    finally:
        db.close()

    async def generate():
        yield json.dumps({"status": "started", "session_id": session_id}) + "\n"

        full_response = ""
        completed = False
        disconnected = False

        try:
            for chunk in ai_engine.stream_chat(safe_messages, mode, session_id, model_name):
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
                        new_summary_text = ai_engine.condense_chat_memory(old_summary, msg_dicts, model_name)

                        new_mem_data = {
                            "last_summarized_id": new_last_id,
                            "summary": new_summary_text,
                        }

                        if memory_msg:
                            memory_msg.content = json.dumps(new_mem_data)
                        else:
                            new_mem = models.Message(
                                session_id=session_id,
                                role="memory",
                                content=json.dumps(new_mem_data),
                            )
                            background_db.add(new_mem)

                        background_db.commit()

                except Exception as e:
                    background_db.rollback()
                    print(f"Failed to process background memory: {e}")
                finally:
                    background_db.close()

    return StreamingResponse(generate(), media_type="application/x-ndjson")

@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...), 
    workspace: str = Form("it_copilot"),
    session_id: Optional[str] = Form(None), 
    is_global: bool = Form(False),  # <-- ADDED
    db: Session = Depends(database.get_db)
):
    content = await file.read()
    try:
        text_content = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Only UTF-8 text files are currently supported.")
        
    active_session_id = None
    if session_id and session_id not in ["null", "undefined", "temp_new_chat", ""]:
        existing_session = db.query(models.Session).filter(models.Session.id == session_id).first()
        if existing_session:
            active_session_id = session_id

    # Passed to knowledge.ingest_document
    result = knowledge.ingest_document(
        db=db, 
        filename=file.filename, 
        content=text_content, 
        workspace=workspace, 
        session_id=active_session_id, 
        is_global=is_global 
    )
    
    return {
        "message": f"Successfully ingested {file.filename}", 
        "details": result,
        "session_id": active_session_id 
    }

@router.get("/folders")
def get_folders(workspace: str = "it_copilot", db: Session = Depends(database.get_db)):
    return db.query(models.Folder).filter(models.Folder.workspace == workspace).all()

@router.post("/folders")
def create_folder(folder: FolderCreate, db: Session = Depends(database.get_db)):
    new_folder = models.Folder(id=folder.id, name=folder.name, workspace=folder.workspace)
    db.add(new_folder)
    db.commit()
    return {"status": "success"}

@router.delete("/folders/{folder_id}")
def delete_folder(folder_id: str, db: Session = Depends(database.get_db)):
    db.query(models.Folder).filter(models.Folder.id == folder_id).delete()
    db.commit()
    return {"status": "success"}

@router.get("/api/models")
def get_ollama_models():
    try:
        r = requests.get(f"{settings.OLLAMA_URL.strip().rstrip('/')}/api/tags", timeout=3)
        r.raise_for_status()
        models = [m["name"] for m in r.json().get("models", []) if "embed" not in m["name"].lower()]
        return models if models else["gemma4:e4b"]
    except Exception as e:
        return["gemma4:e4b"] 

@router.get("/api/prompts")
def get_prompts():
    return MICRO_PROMPTS.get_all()

@router.patch("/api/prompts")
def update_prompts(payload: dict):
    MICRO_PROMPTS.save_prompts(payload)
    return {"status": "success"}

@router.patch("/messages/{message_id}")
def update_message(message_id: str, payload: dict, db: Session = Depends(database.get_db)):
    msg = db.query(models.Message).filter(models.Message.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    
    msg.content = payload.get("content", msg.content)
    db.commit()
    return {"status": "success"}

@router.delete("/messages/{message_id}")
def delete_message(message_id: str, db: Session = Depends(database.get_db)):
    msg = db.query(models.Message).filter(models.Message.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    
    session_id = msg.session_id
    db.delete(msg)
    db.commit()
    return {"status": "success", "session_id": session_id}

@router.post("/sessions/{session_id}/branch")
def branch_session(session_id: str, up_to_message_id: str, db: Session = Depends(database.get_db)):
    # 1. Get original session
    old_session = db.query(models.Session).filter(models.Session.id == session_id).first()
    
    # 2. Create new session
    new_session = models.Session(
        title=f"{old_session.title} (Branch)",
        mode=old_session.mode
    )
    db.add(new_session)
    db.commit()
    db.refresh(new_session)
    
    # 3. Copy messages up to the specific one
    messages = db.query(models.Message).filter(
        models.Message.session_id == session_id
    ).order_by(models.Message.created_at).all()
    
    for m in messages:
        new_msg = models.Message(
            session_id=new_session.id,
            role=m.role,
            content=m.content
        )
        db.add(new_msg)
        if m.id == up_to_message_id:
            break
            
    db.commit()
    return {"new_session_id": new_session.id}

@router.delete("/sessions/{session_id}/truncate/{message_id}")
def truncate_session(session_id: str, message_id: str, db: Session = Depends(database.get_db)):
    """Deletes all messages in a session that occurred AFTER the specified message_id."""
    target_msg = db.query(models.Message).filter(models.Message.id == message_id).first()
    if not target_msg:
        raise HTTPException(status_code=404, detail="Target message not found")

    # Delete everything created after the target message's timestamp in this session
    deleted_count = db.query(models.Message).filter(
        models.Message.session_id == session_id,
        models.Message.created_at > target_msg.created_at
    ).delete(synchronize_session=False)
    
    db.commit()
    return {"status": "success", "deleted_count": deleted_count}