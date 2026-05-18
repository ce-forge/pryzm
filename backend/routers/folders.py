"""Folder CRUD for organising sessions inside a workspace.

Folders live under a workspace; deleting a folder nulls out folder_id on
any sessions that lived in it (they reappear in "Unsorted Logs") rather
than cascade-deleting the sessions themselves.

All mutating routes scope by `?workspace={slug}` — cross-workspace
attempts 404, matching the convention in core.workspace_access.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core import cookie_auth
from core.workspace_access import verify_workspace_owns, workspace_query_dep
from db import database, models
from schemas import FolderCreate, FolderUpdate
from services.workspaces import get_or_default


router = APIRouter(tags=["Folders"])


@router.get("/folders")
def get_folders(workspace: str = "it_copilot", db: Session = Depends(database.get_db)):
    ws = get_or_default(db, workspace)
    return db.query(models.Folder).filter(models.Folder.workspace_id == ws.id).all()


@router.post("/folders")
def create_folder(
    folder: FolderCreate,
    db: Session = Depends(database.get_db),
    user: models.User = Depends(cookie_auth.current_user),
):
    ws = get_or_default(db, folder.workspace)
    new_folder = models.Folder(name=folder.name, workspace_id=ws.id, user_id=user.id)
    db.add(new_folder)
    db.commit()
    return {"status": "success", "id": new_folder.id}


@router.patch("/folders/{folder_id}")
def update_folder(
    folder_id: str,
    payload: FolderUpdate,
    workspace: models.Workspace = Depends(workspace_query_dep),
    db: Session = Depends(database.get_db),
):
    db_folder = verify_workspace_owns(folder_id, models.Folder, workspace.id, db)
    db_folder.name = payload.name
    db.commit()
    return {"status": "success"}


@router.delete("/folders/{folder_id}")
def delete_folder(
    folder_id: str,
    workspace: models.Workspace = Depends(workspace_query_dep),
    db: Session = Depends(database.get_db),
):
    verify_workspace_owns(folder_id, models.Folder, workspace.id, db)
    # Null out folder_id on any sessions that lived in this folder so they
    # show up in "Unsorted Logs" rather than carrying a dangling reference.
    db.query(models.Session).filter(models.Session.folder_id == folder_id).update(
        {"folder_id": None}, synchronize_session=False,
    )
    db.query(models.Folder).filter(models.Folder.id == folder_id).delete()
    db.commit()
    return {"status": "success"}
