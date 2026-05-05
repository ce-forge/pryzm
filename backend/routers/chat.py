from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Optional, List
import json

import database
import ai_engine
import models
import knowledge

router = APIRouter(tags=["AI Chat"])

class InferenceRequest(BaseModel):
    session_id: Optional[str] = None
    prompt: str = Field(..., max_length=100000) 
    mode: str = "it_copilot"  

class SessionInfo(BaseModel):
    id: str
    title: str

class MessageHistory(BaseModel):
    role: str
    content: str
    timestamp: Optional[str] = None

@router.get("/sessions", response_model=List[SessionInfo])
def get_all_sessions(workspace: str = "it_copilot", db: Session = Depends(database.get_db)):
    sessions = db.query(models.Session).filter(models.Session.mode == workspace).order_by(models.Session.created_at.desc()).all()
    return [{"id": s.id, "title": s.title} for s in sessions]

@router.get("/sessions/{session_id}", response_model=List[MessageHistory])
def get_session_history(session_id: str, db: Session = Depends(database.get_db)):
    session = db.query(models.Session).filter(models.Session.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    messages = db.query(models.Message).filter(models.Message.session_id == session_id).order_by(models.Message.created_at).all()
    return[{"role": m.role, 
            "content": m.content,
            "timestamp": m.created_at.isoformat() if m.created_at else None
            } 
            for m in messages
    ]

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
    is_new = False
    chat_session = None
    
    if request.session_id:
        chat_session = db.query(models.Session).filter(models.Session.id == request.session_id).first()
        
    if not chat_session:
        chat_session = models.Session(title="New Diagnostic Session", mode=request.mode)
        is_new = True
        db.add(chat_session)
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
            for chunk in ai_engine.stream_chat(safe_messages, request.mode, chat_session.id): 
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
                    
                    if is_new:
                        new_title = ai_engine.generate_title(request.prompt)
                        bg_session = background_db.query(models.Session).filter(models.Session.id == chat_session.id).first()
                        if bg_session:
                            bg_session.title = new_title
                    
                    background_db.commit()
                except Exception as e:
                    background_db.rollback()
                    print(f"Failed to save background message: {e}")
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
    if not session_id:
        print("Warning: Document uploaded without session_id. It will be GLOBAL.")
    content = await file.read()
    try:
        text_content = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Only UTF-8 text files are currently supported.")
        
    result = knowledge.ingest_document(db, file.filename, text_content, workspace, session_id)
    return {"message": f"Successfully ingested {file.filename}", "details": result}