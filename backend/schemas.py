from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class InferenceRequest(BaseModel):
    session_id: Optional[str] = None
    prompt: str = Field(..., max_length=100000) 
    mode: str = "itCopilot"  
    model: str = "gemma4:e4b"
    attachments: Optional[List[str]] = None

class SessionResponse(BaseModel):
    id: str
    title: str
    mode: str
    folder_id: Optional[str] = None
    is_pinned: Optional[bool] = False
    created_at: datetime

    class Config:
        from_attributes = True

class SessionInfo(BaseModel):
    id: str
    title: str

class SessionUpdate(BaseModel):
    folder_id: Optional[str] = None
    title: Optional[str] = None
    is_pinned: Optional[bool] = None

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

class SystemStatus(BaseModel):
    api: str
    redis: str
    database: str
    inference_engine: str

class HealthResponse(BaseModel):
    status: str
    components: SystemStatus