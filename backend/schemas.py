from pydantic import BaseModel, ConfigDict, Field
from typing import Literal, Optional, List
from datetime import datetime

class InferenceRequest(BaseModel):
    session_id: Optional[str] = None
    prompt: str = Field(..., max_length=100000)
    attachments: Optional[List[str]] = None
    skip_db_save: Optional[bool] = False
    # Per-turn behavior modes (see backend/core/modes.py). Unknown names are
    # dropped server-side, so FE/BE deploys can drift without breaking.
    modes: List[str] = Field(default_factory=list)

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

class ReferencedFile(BaseModel):
    id: str
    filename: str
    mime: str


class ToolCall(BaseModel):
    name: str
    args: dict
    result: str


class MessageHistory(BaseModel):
    id: str
    role: str
    content: str
    status: str = "complete"
    timestamp: Optional[str] = None
    referenced_files: Optional[List[ReferencedFile]] = None
    # Tool calls executed during this assistant turn. NULL on rows with
    # no tool use.
    tool_calls: Optional[List[ToolCall]] = None

class FolderCreate(BaseModel):
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
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    slug: str
    display_name: str
    system_prompt: str
    enabled_tools: List[str]
    color: Optional[str] = None
    created_at: datetime


WORKSPACE_COLOR = Literal["blue", "orange", "emerald", "red", "amber", "violet", "cyan", "pink", "white"]


class WorkspaceCreate(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=80)
    clone_from: Optional[str] = None  # slug of source workspace; None = blank defaults
    color: Optional[WORKSPACE_COLOR] = None


class WorkspaceUpdate(BaseModel):
    display_name: Optional[str] = Field(None, min_length=1, max_length=80)
    system_prompt: Optional[str] = Field(None, max_length=50_000)
    enabled_tools: Optional[List[str]] = None
    color: Optional[WORKSPACE_COLOR] = None


class PositionUpdate(BaseModel):
    position: int


class WorkspaceDeleteResponse(BaseModel):
    deleted: bool
    removed_sessions: int
    removed_folders: int
    removed_documents: int


class LoginRequest(BaseModel):
    username: str
    password: str


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


class StarterTemplate(BaseModel):
    template_id: str
    owner_can_edit: bool = False


class AdminUserCreate(BaseModel):
    username: str
    password: str
    email: Optional[str] = None
    is_admin: bool = False
    can_create_workspaces: bool = False
    allowed_tools: list[str] = []
    starter_templates: list[StarterTemplate] = []


class AdminUserUpdate(BaseModel):
    username: Optional[str] = None
    email: Optional[str] = None
    is_admin: Optional[bool] = None
    is_active: Optional[bool] = None
    can_create_workspaces: Optional[bool] = None
    allowed_tools: Optional[list[str]] = None


class AdminPasswordReset(BaseModel):
    new_password: str


class AdminTemplateCreate(BaseModel):
    slug: str
    display_name: str
    system_prompt: str = ""
    enabled_tools: list[str] = []
    color: Optional[str] = None
    engine_config: dict = {}


class AdminTemplateUpdate(BaseModel):
    slug: Optional[str] = None
    display_name: Optional[str] = None
    system_prompt: Optional[str] = None
    enabled_tools: Optional[list[str]] = None
    color: Optional[str] = None
    engine_config: Optional[dict] = None


class AdminTemplateInstantiate(BaseModel):
    user_id: str
    slug: Optional[str] = None
    owner_can_edit: bool = False


# ---------------------------------------------------------------------------
# Bug reports
# ---------------------------------------------------------------------------

BUG_CATEGORY = Literal[
    "incorrect_info", "vision_wrong", "tool_error", "slow", "ui_bug", "other",
]


class BugReportSubmit(BaseModel):
    category: BUG_CATEGORY
    message: str = Field(..., min_length=1, max_length=10_000)
    include_session: bool = True


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

class AdminNotificationSend(BaseModel):
    user_id: str
    message: str = Field(..., min_length=1, max_length=2_000)
    link_url: Optional[str] = None


class AdminNotificationBroadcast(BaseModel):
    message: str = Field(..., min_length=1, max_length=2_000)
    link_url: Optional[str] = None
