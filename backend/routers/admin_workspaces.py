"""Admin endpoints for per-user workspace management."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core import cookie_auth
from core.audit import EventType, log_event
from db import database, models


router = APIRouter(
    prefix="/api/admin",
    tags=["admin", "workspaces"],
    dependencies=[Depends(cookie_auth.require_admin)],
)


class AdminWorkspaceUpdate(BaseModel):
    display_name: Optional[str] = None
    system_prompt: Optional[str] = None
    enabled_tools: Optional[list[str]] = None
    color: Optional[str] = None
    engine_config: Optional[dict] = None
    owner_can_edit: Optional[bool] = None
    slug: Optional[str] = None


def _ws_dict(w: models.Workspace) -> dict:
    return {
        "id": w.id,
        "slug": w.slug,
        "display_name": w.display_name,
        "system_prompt": w.system_prompt,
        "enabled_tools": list(w.enabled_tools or []),
        "color": getattr(w, "color", None),
        "engine_config": dict(w.engine_config or {}),
        "user_id": w.user_id,
        "template_id": w.template_id,
        "owner_can_edit": w.owner_can_edit,
    }


@router.get("/users/{user_id}/workspaces")
def list_user_workspaces(user_id: str, db: DbSession = Depends(database.get_db)):
    user = db.query(models.User).filter_by(id=user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    workspaces = db.query(models.Workspace).filter_by(
        user_id=user_id,
    ).all()
    return [_ws_dict(w) for w in workspaces]


@router.get("/workspaces/{workspace_id}")
def get_workspace(workspace_id: str, db: DbSession = Depends(database.get_db)):
    w = db.query(models.Workspace).filter_by(id=workspace_id).first()
    if w is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    return _ws_dict(w)


@router.put("/workspaces/{workspace_id}")
def update_workspace(
    workspace_id: str,
    payload: AdminWorkspaceUpdate,
    request: Request,
    db: DbSession = Depends(database.get_db),
    admin: models.User = Depends(cookie_auth.require_admin),
):
    w = db.query(models.Workspace).filter_by(id=workspace_id).first()
    if w is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    changes = payload.model_dump(exclude_unset=True)
    changed_fields = [k for k, v in changes.items() if getattr(w, k, None) != v]
    for k, v in changes.items():
        if k == "color" and not hasattr(models.Workspace, "color"):
            continue
        setattr(w, k, v)
    log_event(
        db, EventType.ADMIN_WORKSPACE_EDITED,
        user=admin, request=request,
        workspace=w,
        payload={
            "workspace_id": w.id,
            "owner_user_id": w.user_id,
            "slug": w.slug,
            "changed_fields": changed_fields,
        },
    )
    db.commit(); db.refresh(w)
    return _ws_dict(w)


@router.delete("/workspaces/{workspace_id}")
def delete_workspace(
    workspace_id: str,
    request: Request,
    db: DbSession = Depends(database.get_db),
    admin: models.User = Depends(cookie_auth.require_admin),
):
    w = db.query(models.Workspace).filter_by(id=workspace_id).first()
    if w is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    session_count = db.query(models.Session).filter(models.Session.workspace_id == w.id).count()
    folder_count = db.query(models.Folder).filter(models.Folder.workspace_id == w.id).count()
    document_count = db.query(models.Document).filter(models.Document.workspace_id == w.id).count()
    log_event(
        db, EventType.ADMIN_WORKSPACE_DELETED,
        user=admin, request=request,
        payload={
            "workspace_id": w.id,
            "owner_user_id": w.user_id,
            "slug": w.slug,
            "removed_session_count": session_count,
            "removed_folder_count": folder_count,
            "removed_document_count": document_count,
        },
    )
    db.delete(w); db.commit()
    return {"ok": True}
