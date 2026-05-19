"""Admin endpoints for template CRUD + push + instantiate."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session as DbSession

from core import cookie_auth
from core.audit import EventType, log_event
from core.tool_permissions import enforce_allowed_tools, filter_allowed_tools
from db import database, models
from schemas import AdminTemplateCreate, AdminTemplateUpdate, AdminTemplateInstantiate


router = APIRouter(
    prefix="/api/admin/templates",
    tags=["admin", "templates"],
    dependencies=[Depends(cookie_auth.require_admin)],
)


_SETTINGS_FIELDS = ("system_prompt", "enabled_tools", "color", "engine_config")


def _template_dict(t: models.WorkspaceTemplate) -> dict:
    return {
        "id": t.id,
        "slug": t.slug,
        "display_name": t.display_name,
        "system_prompt": t.system_prompt,
        "enabled_tools": list(t.enabled_tools or []),
        "color": t.color,
        "engine_config": dict(t.engine_config or {}),
    }


@router.get("")
def list_templates(db: DbSession = Depends(database.get_db)):
    templates = db.query(models.WorkspaceTemplate).all()
    return [_template_dict(t) for t in templates]


@router.post("")
def create_template(
    payload: AdminTemplateCreate,
    request: Request,
    db: DbSession = Depends(database.get_db),
    admin: models.User = Depends(cookie_auth.require_admin),
):
    dup = db.query(models.WorkspaceTemplate).filter_by(slug=payload.slug).first()
    if dup is not None:
        raise HTTPException(status_code=409, detail="Template with this slug already exists.")
    t = models.WorkspaceTemplate(
        slug=payload.slug,
        display_name=payload.display_name,
        system_prompt=payload.system_prompt,
        enabled_tools=list(payload.enabled_tools or []),
        engine_config=dict(payload.engine_config or {}),
    )
    if payload.color is not None:
        t.color = payload.color
    db.add(t); db.commit(); db.refresh(t)
    log_event(
        db, EventType.ADMIN_TEMPLATE_CREATED,
        user=admin, request=request,
        payload={
            "template_id": t.id,
            "slug": t.slug,
            "display_name": t.display_name,
        },
    )
    db.commit()
    return _template_dict(t)


@router.get("/{template_id}")
def get_template(template_id: str, db: DbSession = Depends(database.get_db)):
    t = db.query(models.WorkspaceTemplate).filter_by(id=template_id).first()
    if t is None:
        raise HTTPException(status_code=404, detail="Template not found.")
    return _template_dict(t)


@router.put("/{template_id}")
def update_template(
    template_id: str,
    payload: AdminTemplateUpdate,
    request: Request,
    db: DbSession = Depends(database.get_db),
    admin: models.User = Depends(cookie_auth.require_admin),
):
    t = db.query(models.WorkspaceTemplate).filter_by(id=template_id).first()
    if t is None:
        raise HTTPException(status_code=404, detail="Template not found.")
    changes = payload.model_dump(exclude_unset=True)
    changed_fields = [k for k, v in changes.items() if getattr(t, k, None) != v]
    for k, v in changes.items():
        setattr(t, k, v)
    log_event(
        db, EventType.ADMIN_TEMPLATE_EDITED,
        user=admin, request=request,
        payload={
            "template_id": t.id,
            "slug": t.slug,
            "changed_fields": changed_fields,
        },
    )
    db.commit(); db.refresh(t)
    return _template_dict(t)


@router.delete("/{template_id}")
def delete_template(
    template_id: str,
    request: Request,
    db: DbSession = Depends(database.get_db),
    admin: models.User = Depends(cookie_auth.require_admin),
):
    """Delete a template. The FK on workspaces.template_id uses ON DELETE SET NULL,
    so existing instances stay but lose their template link."""
    t = db.query(models.WorkspaceTemplate).filter_by(id=template_id).first()
    if t is None:
        raise HTTPException(status_code=404, detail="Template not found.")
    affected = db.query(models.Workspace).filter(models.Workspace.template_id == t.id).count()
    log_event(
        db, EventType.ADMIN_TEMPLATE_DELETED,
        user=admin, request=request,
        payload={
            "template_id": t.id,
            "slug": t.slug,
            "affected_instances": affected,
        },
    )
    db.delete(t); db.commit()
    return {"ok": True}


@router.post("/{template_id}/instantiate")
def instantiate_template(
    template_id: str,
    payload: AdminTemplateInstantiate,
    request: Request,
    db: DbSession = Depends(database.get_db),
    admin: models.User = Depends(cookie_auth.require_admin),
):
    t = db.query(models.WorkspaceTemplate).filter_by(id=template_id).first()
    if t is None:
        raise HTTPException(status_code=404, detail="Template not found.")
    user = db.query(models.User).filter_by(id=payload.user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    existing = db.query(models.Workspace).filter_by(
        user_id=payload.user_id, template_id=template_id,
    ).first()
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="User already has a workspace from this template. Delete the existing one first to re-instantiate.",
        )
    enforce_allowed_tools(user, list(t.enabled_tools or []))
    instance = models.Workspace(
        slug=payload.slug or t.slug,
        display_name=t.display_name,
        system_prompt=t.system_prompt,
        enabled_tools=list(t.enabled_tools or []),
        color=t.color,
        template_id=t.id,
        user_id=user.id,
        owner_can_edit=payload.owner_can_edit,
        engine_config=dict(t.engine_config or {}),
    )
    db.add(instance); db.commit(); db.refresh(instance)
    log_event(
        db, EventType.ADMIN_TEMPLATE_INSTANTIATED,
        user=admin, request=request,
        payload={
            "template_id": t.id,
            "slug": t.slug,
            "target_user_id": user.id,
            "new_workspace_id": instance.id,
        },
    )
    db.commit()
    return {"id": instance.id, "slug": instance.slug, "user_id": instance.user_id}


@router.post("/{template_id}/push")
def push_template(
    template_id: str,
    request: Request,
    db: DbSession = Depends(database.get_db),
    admin: models.User = Depends(cookie_auth.require_admin),
):
    t = db.query(models.WorkspaceTemplate).filter_by(id=template_id).first()
    if t is None:
        raise HTTPException(status_code=404, detail="Template not found.")
    affected = db.query(models.Workspace).filter(models.Workspace.template_id == t.id).all()
    affected_count = len(affected)
    affected_user_ids = {w.user_id for w in affected}
    template_tools = list(t.enabled_tools or [])

    filtered: list[dict] = []

    for inst in affected:
        owner = inst.user
        if owner is not None:
            kept, dropped = filter_allowed_tools(owner, template_tools)
        else:
            kept, dropped = list(template_tools), []
        for field in _SETTINGS_FIELDS:
            value = getattr(t, field, None)
            if field == "enabled_tools":
                value = kept
            elif field == "engine_config" and value is not None:
                value = dict(value)
            setattr(inst, field, value)
        if dropped:
            filtered.append({
                "user_id": owner.id if owner else None,
                "username": owner.username if owner else None,
                "dropped_tools": dropped,
            })

    log_event(
        db, EventType.ADMIN_TEMPLATE_PUSHED,
        user=admin, request=request,
        payload={
            "template_id": t.id,
            "affected_workspace_count": affected_count,
            "affected_user_count": len(affected_user_ids),
            "had_customizations_count": 0,
            "filtered": filtered,
        },
    )
    db.commit()
    return {
        "ok": True,
        "affected_count": affected_count,
        "filtered": filtered,
    }
