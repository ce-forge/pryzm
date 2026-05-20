"""Folder CRUD for organising sessions inside a workspace.

Folders live under a workspace; deleting a folder nulls out folder_id on
any sessions that lived in it (they reappear in "Unsorted Logs") rather
than cascade-deleting the sessions themselves.

All mutating routes scope by `?workspace={slug}` — cross-workspace
attempts 404, matching the convention in core.workspace_access.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core import cookie_auth
from core.audit import EventType, log_event
from core.workspace_access import verify_workspace_owns, workspace_query_dep
from db import database, models
from schemas import FolderCreate, FolderResponse, FolderUpdate


router = APIRouter(tags=["Folders"])


@router.get("/folders", response_model=list[FolderResponse])
def get_folders(
    workspace: models.Workspace = Depends(workspace_query_dep),
    db: Session = Depends(database.get_db),
):
    return db.query(models.Folder).filter(models.Folder.workspace_id == workspace.id).all()


@router.post("/folders")
def create_folder(
    folder: FolderCreate,
    request: Request,
    db: Session = Depends(database.get_db),
    user: models.User = Depends(cookie_auth.current_user),
):
    ws = (
        db.query(models.Workspace)
        .filter(
            models.Workspace.slug == folder.workspace,
            models.Workspace.user_id == user.id,
        )
        .first()
    )
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    new_folder = models.Folder(name=folder.name, workspace_id=ws.id, user_id=user.id)
    db.add(new_folder)
    db.commit()

    log_event(
        db,
        EventType.FOLDER_CREATED,
        user=user,
        workspace=ws,
        resource_type="folder",
        resource_id=new_folder.id,
        payload={
            "folder_id": new_folder.id,
            "name": new_folder.name,
        },
        request=request,
    )
    db.commit()
    return {"status": "success", "id": new_folder.id}


@router.patch("/folders/{folder_id}")
def update_folder(
    folder_id: str,
    payload: FolderUpdate,
    request: Request,
    workspace: models.Workspace = Depends(workspace_query_dep),
    db: Session = Depends(database.get_db),
    user: models.User = Depends(cookie_auth.current_user),
):
    db_folder = verify_workspace_owns(folder_id, models.Folder, workspace.id, db)
    previous_name = db_folder.name
    db_folder.name = payload.name
    db.commit()

    if previous_name != payload.name:
        log_event(
            db,
            EventType.FOLDER_EDITED,
            user=user,
            workspace=workspace,
            resource_type="folder",
            resource_id=folder_id,
            payload={
                "folder_id": folder_id,
                "previous_name": previous_name,
                "new_name": payload.name,
            },
            request=request,
        )
        db.commit()

    return {"status": "success"}


@router.delete("/folders/{folder_id}")
def delete_folder(
    folder_id: str,
    request: Request,
    workspace: models.Workspace = Depends(workspace_query_dep),
    db: Session = Depends(database.get_db),
    user: models.User = Depends(cookie_auth.current_user),
):
    db_folder = verify_workspace_owns(folder_id, models.Folder, workspace.id, db)
    deleted_name = db_folder.name

    orphaned_session_count = db.query(models.Session).filter(
        models.Session.folder_id == folder_id
    ).count()

    # Null out folder_id on any sessions that lived in this folder so they
    # show up in "Unsorted Logs" rather than carrying a dangling reference.
    db.query(models.Session).filter(models.Session.folder_id == folder_id).update(
        {"folder_id": None}, synchronize_session=False,
    )
    db.query(models.Folder).filter(models.Folder.id == folder_id).delete()

    log_event(
        db,
        EventType.FOLDER_DELETED,
        user=user,
        workspace=workspace,
        resource_type="folder",
        resource_id=folder_id,
        payload={
            "folder_id": folder_id,
            "name": deleted_name,
            "orphaned_session_count": orphaned_session_count,
        },
        request=request,
    )
    db.commit()
    return {"status": "success"}
