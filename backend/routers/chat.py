from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
import json
import database
import ai_engine
import models

router = APIRouter(tags=["AI Chat"])

class InferenceRequest(BaseModel):
    session_id: Optional[str] = None
    prompt: str

class SessionInfo(BaseModel):
    id: str
    title: str

class MessageHistory(BaseModel):
    role: str
    content: str

@router.get("/sessions", response_model=List[SessionInfo])
def get_all_sessions(db: Session = Depends(database.get_db)):
    sessions = db.query(models.Session).order_by(models.Session.created_at.desc()).all()
    return [{"id": s.id, "title": s.title} for s in sessions]

@router.get("/sessions/{session_id}", response_model=List[MessageHistory])
def get_session_history(session_id: str, db: Session = Depends(database.get_db)):
    session = db.query(models.Session).filter(models.Session.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    messages = db.query(models.Message).filter(models.Message.session_id == session_id).order_by(models.Message.created_at).all()
    return[{"role": m.role, "content": m.content} for m in messages]

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
        chat_session = models.Session(title="New Diagnostic Session")
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
        full_response = ""
        for chunk in ai_engine.stream_chat(safe_messages):
            full_response += chunk
            yield json.dumps({"chunk": chunk}) + "\n"
            
        ai_msg = models.Message(session_id=chat_session.id, role="assistant", content=full_response)
        db.add(ai_msg)
        
        if is_new:
            new_title = ai_engine.generate_title(request.prompt)
            chat_session.title = new_title
            
        db.commit()
        
        yield json.dumps({"done": True, "session_id": chat_session.id}) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")