"""Admin endpoints for user CRUD."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session as DbSession

from core import cookie_auth
from db import database, models
from schemas import AdminUserCreate, AdminUserUpdate, AdminPasswordReset


router = APIRouter(
    prefix="/api/admin/users",
    tags=["admin", "users"],
    dependencies=[Depends(cookie_auth.require_admin)],
)


def _user_dict(u: models.User) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "email": u.email,
        "is_admin": u.is_admin,
        "is_active": u.is_active,
        "can_create_workspaces": u.can_create_workspaces,
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
    }


@router.get("")
def list_users(
    active: Optional[bool] = Query(None),
    db: DbSession = Depends(database.get_db),
):
    q = db.query(models.User)
    if active is not None:
        q = q.filter(models.User.is_active.is_(active))
    return [_user_dict(u) for u in q.order_by(models.User.created_at.asc()).all()]


@router.post("")
def create_user(
    payload: AdminUserCreate,
    db: DbSession = Depends(database.get_db),
):
    existing = db.query(models.User).filter(
        models.User.username.ilike(payload.username)
    ).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Username already exists.")

    if len(payload.password) < 12:
        raise HTTPException(status_code=400, detail="Password must be at least 12 characters.")

    user = models.User(
        username=payload.username,
        password_hash=cookie_auth.hash_password(payload.password),
        email=payload.email,
        is_admin=payload.is_admin,
        can_create_workspaces=payload.can_create_workspaces,
        is_active=True,
    )
    db.add(user); db.commit(); db.refresh(user)

    for starter in payload.starter_templates:
        tmpl = db.query(models.WorkspaceTemplate).filter_by(
            id=starter.template_id,
        ).first()
        if tmpl is None:
            raise HTTPException(status_code=400, detail=f"Template {starter.template_id} not found.")
        instance = models.Workspace(
            slug=tmpl.slug,
            display_name=tmpl.display_name,
            system_prompt=tmpl.system_prompt,
            enabled_tools=list(tmpl.enabled_tools or []),
            template_id=tmpl.id,
            user_id=user.id,
            owner_can_edit=starter.owner_can_edit,
            engine_config=dict(tmpl.engine_config or {}),
        )
        db.add(instance)
    db.commit()

    return _user_dict(user)


@router.get("/{user_id}")
def get_user(user_id: str, db: DbSession = Depends(database.get_db)):
    u = db.query(models.User).filter_by(id=user_id).first()
    if u is None:
        raise HTTPException(status_code=404, detail="User not found.")
    return _user_dict(u)


@router.patch("/{user_id}")
def update_user(
    user_id: str,
    payload: AdminUserUpdate,
    db: DbSession = Depends(database.get_db),
):
    u = db.query(models.User).filter_by(id=user_id).first()
    if u is None:
        raise HTTPException(status_code=404, detail="User not found.")

    changes = payload.model_dump(exclude_unset=True)

    if "is_admin" in changes or "is_active" in changes:
        cookie_auth.assert_not_removing_last_admin(
            db,
            target_user_id=user_id,
            would_be_admin=changes.get("is_admin", u.is_admin),
            would_be_active=changes.get("is_active", u.is_active),
        )

    if "username" in changes and changes["username"] != u.username:
        dup = db.query(models.User).filter(
            models.User.username.ilike(changes["username"]),
            models.User.id != user_id,
        ).first()
        if dup is not None:
            raise HTTPException(status_code=409, detail="Username already exists.")

    for k, v in changes.items():
        setattr(u, k, v)
    db.commit()
    db.refresh(u)
    return _user_dict(u)


@router.post("/{user_id}/password")
def reset_password(
    user_id: str,
    payload: AdminPasswordReset,
    db: DbSession = Depends(database.get_db),
):
    u = db.query(models.User).filter_by(id=user_id).first()
    if u is None:
        raise HTTPException(status_code=404, detail="User not found.")
    if len(payload.new_password) < 12:
        raise HTTPException(status_code=400, detail="Password must be at least 12 characters.")
    u.password_hash = cookie_auth.hash_password(payload.new_password)
    cookie_auth.invalidate_user_sessions(db, user_id)
    db.commit()
    return {"ok": True}


@router.delete("/{user_id}")
def delete_user(
    user_id: str,
    hard: bool = Query(False),
    db: DbSession = Depends(database.get_db),
):
    u = db.query(models.User).filter_by(id=user_id).first()
    if u is None:
        raise HTTPException(status_code=404, detail="User not found.")

    if hard:
        cookie_auth.assert_not_removing_last_admin(
            db, target_user_id=user_id, would_be_admin=False, would_be_active=False,
        )
        db.delete(u)
    else:
        cookie_auth.assert_not_removing_last_admin(
            db, target_user_id=user_id, would_be_admin=u.is_admin, would_be_active=False,
        )
        u.is_active = False
        cookie_auth.invalidate_user_sessions(db, user_id)
    db.commit()
    return {"ok": True}
