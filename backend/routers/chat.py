from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
import database
import ai_engine
import models

router = APIRouter(tags=["AI Chat"])

class InferenceRequest(BaseModel):
    session_id: Optional[str] = None
    prompt: str

class InferenceResponse(BaseModel):
    session_id: str
    response: str

class SessionInfo(BaseModel):
    id: str
    title: str

class MessageHistory(BaseModel):
    role: str
    content: str

@router.post("/analyze", response_model=InferenceResponse)
def analyze_data(request: InferenceRequest, db: Session = Depends(database.get_db)): # Removed 'async'
    if request.session_id:
        chat_session = db.query(models.Session).filter(models.Session.id == request.session_id).first()
    else:
        chat_session = models.Session(title="New Diagnostic Session")
        db.add(chat_session)
        db.commit()
        db.refresh(chat_session)
    
    user_msg = models.Message(session_id=chat_session.id, role="user", content=request.prompt)
    db.add(user_msg)
    db.commit()

    history = db.query(models.Message).filter(models.Message.session_id == chat_session.id).order_by(models.Message.created_at).all()
    safe_messages =[{"role": msg.role, "content": msg.content} for msg in history]

    answer = ai_engine.analyze_chat(safe_messages)

    ai_msg = models.Message(session_id=chat_session.id, role="assistant", content=answer)
    db.add(ai_msg)
    db.commit()

    return InferenceResponse(session_id=chat_session.id, response=answer)

@router.get("/sessions", response_model=List[SessionInfo])
def get_all_sessions(db: Session = Depends(database.get_db)):
    """Fetches all chat sessions to display in the frontend sidebar."""
    # Order by newest first
    sessions = db.query(models.Session).order_by(models.Session.created_at.desc()).all()
    return[{"id": s.id, "title": s.title} for s in sessions]

@router.get("/sessions/{session_id}", response_model=List[MessageHistory])
def get_session_history(session_id: str, db: Session = Depends(database.get_db)):
    """Fetches the message history for a specific chat session."""
    session = db.query(models.Session).filter(models.Session.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    messages = db.query(models.Message).filter(models.Message.session_id == session_id).order_by(models.Message.created_at).all()
    return[{"role": m.role, "content": m.content} for m in messages]