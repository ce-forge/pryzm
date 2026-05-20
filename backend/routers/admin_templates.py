"""Admin endpoints for template CRUD + unified preview/apply.

A single `/apply` endpoint replaces the older `/push` + `/instantiate` split.
Each call carries a list of per-user targets with explicit actions
(update / adopt / create); the modal that drives it first hits `/preview`
to learn each user's current state."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session as DbSession

from core import cookie_auth
from core.audit import EventType, log_event
from db import database, models
from schemas import (
    AdminTemplateCreate,
    AdminTemplateUpdate,
    AdminTemplateApplyRequest,
)
from services.template_apply import apply_targets, build_preview


router = APIRouter(
    prefix="/api/admin/templates",
    tags=["admin", "templates"],
    dependencies=[Depends(cookie_auth.require_admin)],
)


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


@router.get("/{template_id}/preview")
def preview_template(
    template_id: str,
    db: DbSession = Depends(database.get_db),
):
    t = db.query(models.WorkspaceTemplate).filter_by(id=template_id).first()
    if t is None:
        raise HTTPException(status_code=404, detail="Template not found.")
    rows = build_preview(db, t)
    return {
        "template": {"id": t.id, "slug": t.slug, "display_name": t.display_name},
        "rows": [
            {
                "user_id": r.user_id,
                "username": r.username,
                "state": r.state,
                "workspace_id": r.workspace_id,
                "owner_can_edit": r.owner_can_edit,
                "diff_fields": r.diff_fields,
            }
            for r in rows
        ],
    }


@router.post("/{template_id}/apply")
def apply_template(
    template_id: str,
    payload: AdminTemplateApplyRequest,
    request: Request,
    db: DbSession = Depends(database.get_db),
    admin: models.User = Depends(cookie_auth.require_admin),
):
    t = db.query(models.WorkspaceTemplate).filter_by(id=template_id).first()
    if t is None:
        raise HTTPException(status_code=404, detail="Template not found.")

    target_tuples = [(tg.user_id, tg.action, tg.owner_can_edit) for tg in payload.targets]
    outcomes, rejections = apply_targets(db, t, target_tuples)

    # Emit one audit event per created workspace (matches the old
    # per-call instantiate semantics — easy to grep for).
    created = [o for o in outcomes if o.action == "create"]
    updated = [o for o in outcomes if o.action in ("update", "adopt")]
    for o in created:
        log_event(
            db, EventType.ADMIN_TEMPLATE_INSTANTIATED,
            user=admin, request=request,
            payload={
                "template_id": t.id,
                "slug": t.slug,
                "target_user_id": o.user_id,
                "new_workspace_id": o.workspace_id,
            },
        )

    # One aggregate push event covers all update + adopt rows. Keeps the
    # audit feed readable when the admin pushes to dozens of users.
    if updated:
        filtered = [
            {"user_id": o.user_id, "dropped_tools": o.dropped_tools}
            for o in updated if o.dropped_tools
        ]
        log_event(
            db, EventType.ADMIN_TEMPLATE_PUSHED,
            user=admin, request=request,
            payload={
                "template_id": t.id,
                "slug": t.slug,
                "affected_workspace_count": len(updated),
                "adopted_count": sum(1 for o in updated if o.action == "adopt"),
                "filtered": filtered,
            },
        )

    db.commit()
    return {
        "ok": True,
        "outcomes": [
            {
                "user_id": o.user_id,
                "action": o.action,
                "workspace_id": o.workspace_id,
                "dropped_tools": o.dropped_tools,
            }
            for o in outcomes
        ],
        "rejections": rejections,
    }
