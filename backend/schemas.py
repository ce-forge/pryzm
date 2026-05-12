from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List
from datetime import datetime

class InferenceRequest(BaseModel):
    session_id: Optional[str] = None
    prompt: str = Field(..., max_length=100000) 
    mode: str = "itCopilot"  
    model: str = "gemma4:e4b"
    attachments: Optional[List[str]] = None
    skip_db_save: Optional[bool] = False

class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    workspace_id: str
    folder_id: Optional[str] = None
    is_pinned: Optional[bool] = False
    created_at: datetime

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
    id: str
    role: str
    content: str
    status: str = "complete"
    timestamp: Optional[str] = None

class FolderCreate(BaseModel):
    id: str
    name: str
    workspace: str

class BranchRequest(BaseModel):
    up_to_message_id: str

class MessageUpdate(BaseModel):
    content: str

class SystemStatus(BaseModel):
    api: str
    redis: str
    database: str
    inference_engine: str

class HealthResponse(BaseModel):
    status: str
    components: SystemStatus


class WorkspaceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    slug: str
    display_name: str
    system_prompt: str
    enabled_tools: List[str]
    preferred_model: Optional[str] = None
    is_builtin: bool
    created_at: datetime


class WorkspaceCreate(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=80)
    clone_from: Optional[str] = None  # slug of source workspace; None = blank defaults


class WorkspaceUpdate(BaseModel):
    display_name: Optional[str] = Field(None, min_length=1, max_length=80)
    system_prompt: Optional[str] = Field(None, max_length=50_000)
    enabled_tools: Optional[List[str]] = None
    preferred_model: Optional[str] = None  # explicit null = clear the pin


class WorkspaceDeleteResponse(BaseModel):
    deleted: bool
    removed_sessions: int
    removed_folders: int
    removed_documents: int
