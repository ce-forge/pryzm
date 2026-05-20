from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from typing import List
from core import cookie_auth
from core.audit import EventType, log_event
from core.tool_permissions import enforce_allowed_tools, filter_allowed_tools, validate_tool_names
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


router = APIRouter(tags=["Workspaces"])


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
    request: Request,
    db: Session = Depends(database.get_db),
    user: models.User = Depends(cookie_auth.current_user),
):
    if not user.is_admin and not user.can_create_workspaces:
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to create workspaces.",
        )

    stripped_display_name = payload.display_name.strip()

    # Reject if this user already has a workspace with the same display name.
    # The sidebar surfaces display_name (not slug), so allowing duplicates
    # produces visually-identical entries the user can't tell apart.
    dup = (
        db.query(models.Workspace)
        .filter(
            models.Workspace.user_id == user.id,
            models.Workspace.display_name == stripped_display_name,
        )
        .first()
    )
    if dup is not None:
        raise HTTPException(
            status_code=409,
            detail=f"You already have a workspace named {stripped_display_name!r}.",
        )

    try:
        slug = slugify_unique(db, stripped_display_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Defaults for a fresh blank workspace.
    system_prompt = "You are a helpful assistant. Answer the user's questions thoughtfully."
    enabled_tools: list[str] = []
    engine_config = {"backend": "llama_cpp"}

    if payload.clone_from:
        source = get_by_slug(db, payload.clone_from, user_id=user.id)
        system_prompt = source.system_prompt
        enabled_tools = list(source.enabled_tools or [])
        engine_config = dict(source.engine_config or engine_config)

    enforce_allowed_tools(user, enabled_tools)

    ws = models.Workspace(
        slug=slug,
        display_name=stripped_display_name,
        system_prompt=system_prompt,
        enabled_tools=enabled_tools,
        engine_config=engine_config,
        color=payload.color,
        user_id=user.id,
        # User created this themselves — they own the editing rights.
        # owner_can_edit=False is reserved for admin-instantiated
        # templates the admin wants to lock down.
        owner_can_edit=True,
    )
    db.add(ws)
    db.commit()
    db.refresh(ws)

    log_event(
        db,
        EventType.WORKSPACE_CREATED,
        user=user,
        workspace=ws,
        resource_type="workspace",
        resource_id=ws.id,
        payload={
            "slug": ws.slug,
            "display_name": ws.display_name,
            "color": ws.color,
            "cloned_from_slug": payload.clone_from,
        },
        request=request,
    )
    db.commit()

    return _to_response(ws)


@router.patch("/workspaces/{slug}", response_model=WorkspaceResponse)
def update_workspace(
    slug: str,
    payload: WorkspaceUpdate,
    request: Request,
    db: Session = Depends(database.get_db),
    user: models.User = Depends(cookie_auth.current_user),
):
    # Scope to the caller's own workspace — slugs aren't unique per user.
    ws = get_by_slug(db, slug, user_id=user.id)

    # Locked workspaces (admin-instantiated templates with owner_can_edit
    # cleared) reject edits from the recipient. Admins bypass — they have
    # the admin endpoint at /api/admin/workspaces/{id} that's gated by
    # require_admin and never checks this flag.
    if not ws.owner_can_edit and not user.is_admin:
        raise HTTPException(
            status_code=403,
            detail=(
                "This workspace is locked. Ask your admin to enable editing "
                "or to push template changes."
            ),
        )

    data = payload.model_dump(exclude_unset=True)

    changed_fields: list[str] = []
    previous_values: dict = {}
    new_values: dict = {}

    if "display_name" in data:
        stripped = data["display_name"].strip()
        if not stripped:
            raise HTTPException(
                status_code=400,
                detail="display_name must contain non-whitespace characters",
            )
        if stripped != ws.display_name:
            previous_values["display_name"] = ws.display_name
            new_values["display_name"] = stripped
            changed_fields.append("display_name")
        ws.display_name = stripped

    if "system_prompt" in data:
        if data["system_prompt"] != ws.system_prompt:
            previous_values["system_prompt"] = ws.system_prompt
            new_values["system_prompt"] = data["system_prompt"]
            changed_fields.append("system_prompt")
        ws.system_prompt = data["system_prompt"]

    if "enabled_tools" in data:
        validate_tool_names(data["enabled_tools"])
        enforce_allowed_tools(ws.user, data["enabled_tools"])
        if list(ws.enabled_tools or []) != list(data["enabled_tools"]):
            previous_values["enabled_tools"] = list(ws.enabled_tools or [])
            new_values["enabled_tools"] = list(data["enabled_tools"])
            changed_fields.append("enabled_tools")
        ws.enabled_tools = data["enabled_tools"]

    if "color" in data:
        if data["color"] != ws.color:
            previous_values["color"] = ws.color
            new_values["color"] = data["color"]
            changed_fields.append("color")
        ws.color = data["color"]

    db.commit()
    db.refresh(ws)

    if changed_fields:
        log_event(
            db,
            EventType.WORKSPACE_EDITED,
            user=user,
            workspace=ws,
            resource_type="workspace",
            resource_id=ws.id,
            payload={
                "changed_fields": changed_fields,
                "previous_values": previous_values,
                "new_values": new_values,
            },
            request=request,
        )
        db.commit()

    return _to_response(ws)


@router.delete("/workspaces/{slug}", response_model=WorkspaceDeleteResponse)
def delete_workspace(
    slug: str,
    db: Session = Depends(database.get_db),
    user: models.User = Depends(cookie_auth.current_user),
):
    # Scope to the caller's own workspace — without this any authed user
    # could DELETE the first row in the DB matching the slug regardless
    # of owner. Slugs are not unique per-user.
    ws = get_by_slug(db, slug, user_id=user.id)

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


@router.post("/workspaces/{slug}/reset")
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

    template_tools = list(tmpl.enabled_tools or [])
    kept, dropped = filter_allowed_tools(user, template_tools)

    ws.system_prompt = tmpl.system_prompt
    ws.enabled_tools = kept
    ws.color = tmpl.color
    ws.engine_config = dict(tmpl.engine_config or {})
    db.commit()
    db.refresh(ws)
    return {
        "workspace": _to_response(ws).model_dump(),
        "dropped_tools": dropped,
    }


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
