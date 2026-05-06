from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
import json

import database
import ai_engine
import models
import knowledge
from prompt_manager import MICRO_PROMPTS
import requests
from config import settings

router = APIRouter(tags=["AI Chat"])

class InferenceRequest(BaseModel):
    session_id: Optional[str] = None
    prompt: str = Field(..., max_length=100000) 
    mode: str = "it_copilot"  
    model: str = "gemma4:e4b"

class SessionResponse(BaseModel):
    id: str
    title: str
    mode: str
    folder_id: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

class SessionInfo(BaseModel):
    id: str
    title: str

class SessionUpdate(BaseModel):
    folder_id: Optional[str] = None
    title: Optional[str] = None

class FolderUpdate(BaseModel):
    name: str

class MessageHistory(BaseModel):
    role: str
    content: str
    timestamp: Optional[str] = None

class FolderCreate(BaseModel):
    id: str
    name: str
    workspace: str

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
    
    return[{"role": m.role, 
            "content": m.content,
            "timestamp": m.created_at.isoformat() if m.created_at else None
            } 
            for m in messages
    ]

@router.patch("/sessions/{session_id}")
def update_session(session_id: str, payload: SessionUpdate, db: Session = Depends(database.get_db)):
    db_session = db.query(models.Session).filter(models.Session.id == session_id).first()
    if db_session:
        update_data = payload.dict(exclude_unset=True) 
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
def analyze_data(request: InferenceRequest, db: Session = Depends(database.get_db)):
    chat_session = None
    
    if request.session_id:
        chat_session = db.query(models.Session).filter(models.Session.id == request.session_id).first()
        
    if not chat_session:
        generated_title = ai_engine.generate_title(request.prompt, request.model)
        chat_session = models.Session(title=generated_title, mode=request.mode)
        db.add(chat_session)
        db.commit()
        db.refresh(chat_session)
    elif chat_session.title in["Document Upload Session", "New Diagnostic Session", "New Diagnostic Chat"]:
        chat_session.title = ai_engine.generate_title(request.prompt, request.model)
        db.commit()
        db.refresh(chat_session)
        
    user_msg = models.Message(session_id=chat_session.id, role="user", content=request.prompt)
    db.add(user_msg)
    db.commit()

    history = db.query(models.Message).filter(models.Message.session_id == chat_session.id).order_by(models.Message.created_at).all()
    safe_messages =[{"role": msg.role, "content": msg.content} for msg in history]

    def generate():
        yield json.dumps({"status": "started", "session_id": chat_session.id}) + "\n"
        
        full_response = ""
        try:
            for chunk in ai_engine.stream_chat(safe_messages, request.mode, chat_session.id, request.model): 
                full_response += chunk
                yield json.dumps({"chunk": chunk}) + "\n"
                
            yield json.dumps({"done": True}) + "\n"
            
        except Exception as e:
            error_msg = f"\n\n**[Fatal Stream Error]**\n`{str(e)}`"
            full_response += error_msg
            yield json.dumps({"chunk": error_msg}) + "\n"

        finally:
            if full_response.strip():
                background_db = database.SessionLocal()
                try:
                    ai_msg = models.Message(session_id=chat_session.id, role="assistant", content=full_response)
                    background_db.add(ai_msg)
                    background_db.commit()
                    
                    all_msgs = background_db.query(models.Message).filter(models.Message.session_id == chat_session.id).order_by(models.Message.created_at).all()
                    
                    memory_msg = next((m for m in all_msgs if m.role == "memory"), None)
                    
                    last_id = None
                    old_summary = ""
                    if memory_msg:
                        try:
                            mem_data = json.loads(memory_msg.content)
                            last_id = mem_data.get("last_summarized_id")
                            old_summary = mem_data.get("summary", "")
                        except:
                            old_summary = memory_msg.content

                    active_msgs = [m for m in all_msgs if m.role in ["user", "assistant"]]
                    
                    start_idx = 0
                    if last_id:
                        for i, m in enumerate(active_msgs):
                            if m.id == last_id:
                                start_idx = i + 1
                                break

                    unsummarized = active_msgs[start_idx:]
                    
                    if len(unsummarized) > 30:
                        to_summarize = unsummarized[:-10] 
                        new_last_id = to_summarize[-1].id
                        
                        msg_dicts =[{"role": m.role, "content": m.content} for m in to_summarize]
                        new_summary_text = ai_engine.condense_chat_memory(old_summary, msg_dicts, request.model)
                        
                        new_mem_data = {
                            "last_summarized_id": new_last_id,
                            "summary": new_summary_text
                        }
                        
                        if memory_msg:
                            memory_msg.content = json.dumps(new_mem_data)
                        else:
                            new_mem = models.Message(session_id=chat_session.id, role="memory", content=json.dumps(new_mem_data))
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
    db: Session = Depends(database.get_db)
):
    content = await file.read()
    try:
        text_content = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Only UTF-8 text files are currently supported.")
        
    active_session_id = session_id
    
    if active_session_id and active_session_id not in ["null", "undefined"]:
        existing_session = db.query(models.Session).filter(models.Session.id == active_session_id).first()
        
        if not existing_session:
            new_session = models.Session(id=active_session_id, title="Document Upload Session", mode=workspace)
            db.add(new_session)
            db.commit()
    else:
        new_session = models.Session(title="Document Upload Session", mode=workspace)
        db.add(new_session)
        db.commit()
        db.refresh(new_session)
        active_session_id = new_session.id

    result = knowledge.ingest_document(db, file.filename, text_content, workspace, active_session_id)
    
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