from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from core import cookie_auth
from db import database, models
from schemas import (
    WorkspaceResponse,
    WorkspaceCreate,
    WorkspaceUpdate,
    WorkspaceDeleteResponse,
    PositionUpdate,
)
from services.workspaces import (
    get_by_slug,
    slugify_unique,
)
from tools.registry import AVAILABLE_TOOLS


router = APIRouter(tags=["Workspaces"])


def _validate_enabled_tools(names: List[str]) -> None:
    """Reject names that aren't in the live tool registry."""
    unknown = [n for n in names if n not in AVAILABLE_TOOLS]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown tool name(s): {unknown}",
        )


def _to_response(workspace) -> WorkspaceResponse:
    """Build a WorkspaceResponse from a Workspace row."""
    return WorkspaceResponse(
        id=workspace.id,
        slug=workspace.slug,
        display_name=workspace.display_name,
        system_prompt=workspace.system_prompt,
        enabled_tools=workspace.enabled_tools or [],
        color=workspace.color,
        created_at=workspace.created_at,
    )


@router.get("/workspaces", response_model=List[WorkspaceResponse])
def list_workspaces(
    db: Session = Depends(database.get_db),
    user: models.User = Depends(cookie_auth.current_user),
):
    rows = (
        db.query(models.Workspace)
        .filter(models.Workspace.user_id == user.id)
        .order_by(models.Workspace.position.asc(), models.Workspace.created_at.asc())
        .all()
    )
    return [_to_response(ws) for ws in rows]


@router.get("/workspaces/{slug}", response_model=WorkspaceResponse)
def get_workspace(
    slug: str,
    db: Session = Depends(database.get_db),
    user: models.User = Depends(cookie_auth.current_user),
):
    ws = (
        db.query(models.Workspace)
        .filter(
            models.Workspace.slug == slug,
            models.Workspace.user_id == user.id,
        )
        .first()
    )
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    return _to_response(ws)


@router.post("/workspaces", response_model=WorkspaceResponse)
def create_workspace(
    payload: WorkspaceCreate,
    db: Session = Depends(database.get_db),
):
    try:
        slug = slugify_unique(db, payload.display_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Defaults for a fresh blank workspace.
    system_prompt = "You are a helpful assistant. Answer the user's questions thoughtfully."
    enabled_tools: list[str] = []
    engine_config = {"backend": "llama_cpp"}

    if payload.clone_from:
        source = get_by_slug(db, payload.clone_from)
        system_prompt = source.system_prompt
        enabled_tools = list(source.enabled_tools or [])
        engine_config = dict(source.engine_config or engine_config)

    ws = models.Workspace(
        slug=slug,
        display_name=payload.display_name.strip(),
        system_prompt=system_prompt,
        enabled_tools=enabled_tools,
        engine_config=engine_config,
        color=payload.color,
    )
    db.add(ws)
    db.commit()
    db.refresh(ws)
    return _to_response(ws)


@router.patch("/workspaces/{slug}", response_model=WorkspaceResponse)
def update_workspace(
    slug: str,
    payload: WorkspaceUpdate,
    db: Session = Depends(database.get_db),
):
    ws = get_by_slug(db, slug)

    data = payload.model_dump(exclude_unset=True)

    if "display_name" in data:
        stripped = data["display_name"].strip()
        if not stripped:
            raise HTTPException(
                status_code=400,
                detail="display_name must contain non-whitespace characters",
            )
        ws.display_name = stripped

    if "system_prompt" in data:
        ws.system_prompt = data["system_prompt"]

    if "enabled_tools" in data:
        _validate_enabled_tools(data["enabled_tools"])
        ws.enabled_tools = data["enabled_tools"]

    if "color" in data:
        ws.color = data["color"]

    db.commit()
    db.refresh(ws)
    return _to_response(ws)


@router.delete("/workspaces/{slug}", response_model=WorkspaceDeleteResponse)
def delete_workspace(slug: str, db: Session = Depends(database.get_db)):
    ws = get_by_slug(db, slug)

    # Last-workspace guard.
    total = db.query(models.Workspace).count()
    if total <= 1:
        raise HTTPException(
            status_code=409,
            detail="Cannot delete the only remaining workspace.",
        )

    # Count what's about to cascade so the response can populate the UI
    # confirmation modal. Counts are best-effort: a concurrent request could
    # add/remove rows between these COUNTs and the db.delete below, so the
    # numbers may be slightly off. The actual cascade-delete is authoritative
    # — these counts are display-only.
    removed_sessions = db.query(models.Session).filter(models.Session.workspace_id == ws.id).count()
    removed_folders = db.query(models.Folder).filter(models.Folder.workspace_id == ws.id).count()
    removed_documents = db.query(models.Document).filter(models.Document.workspace_id == ws.id).count()

    db.delete(ws)
    db.commit()

    return WorkspaceDeleteResponse(
        deleted=True,
        removed_sessions=removed_sessions,
        removed_folders=removed_folders,
        removed_documents=removed_documents,
    )


@router.post("/workspaces/{slug}/reset", response_model=WorkspaceResponse)
def reset_workspace(
    slug: str,
    db: Session = Depends(database.get_db),
    user: models.User = Depends(cookie_auth.current_user),
):
    ws = (
        db.query(models.Workspace)
        .filter(
            models.Workspace.slug == slug,
            models.Workspace.user_id == user.id,
        )
        .first()
    )
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    if ws.template_id is None:
        raise HTTPException(
            status_code=400,
            detail="Workspace has no template to reset from.",
        )
    tmpl = db.query(models.WorkspaceTemplate).filter_by(id=ws.template_id).first()
    if tmpl is None:
        raise HTTPException(status_code=404, detail="Template no longer exists.")
    ws.system_prompt = tmpl.system_prompt
    ws.enabled_tools = list(tmpl.enabled_tools or [])
    ws.color = tmpl.color
    ws.engine_config = dict(tmpl.engine_config or {})
    db.commit()
    db.refresh(ws)
    return _to_response(ws)


@router.patch("/workspaces/{slug}/position", response_model=WorkspaceResponse)
def update_workspace_position(
    slug: str,
    payload: PositionUpdate,
    db: Session = Depends(database.get_db),
    user: models.User = Depends(cookie_auth.current_user),
):
    if payload.position < 0:
        raise HTTPException(status_code=400, detail="position must be non-negative")
    ws = (
        db.query(models.Workspace)
        .filter(
            models.Workspace.slug == slug,
            models.Workspace.user_id == user.id,
        )
        .first()
    )
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    new_pos = payload.position
    old_pos = ws.position
    if new_pos == old_pos:
        return _to_response(ws)

    if new_pos < old_pos:
        # Moving up: bump everything in [new_pos, old_pos) down by 1
        db.query(models.Workspace).filter(
            models.Workspace.user_id == user.id,
            models.Workspace.id != ws.id,
            models.Workspace.position >= new_pos,
            models.Workspace.position < old_pos,
        ).update({"position": models.Workspace.position + 1}, synchronize_session=False)
    else:
        # Moving down: bump everything in (old_pos, new_pos] up by 1
        db.query(models.Workspace).filter(
            models.Workspace.user_id == user.id,
            models.Workspace.id != ws.id,
            models.Workspace.position > old_pos,
            models.Workspace.position <= new_pos,
        ).update({"position": models.Workspace.position - 1}, synchronize_session=False)

    ws.position = new_pos
    db.commit()
    db.refresh(ws)
    return _to_response(ws)
