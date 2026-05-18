"""Cookie-based authentication: /api/auth/{login,logout,me}."""
import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session as DbSession

from core import cookie_auth
from db import database, models
from schemas import LoginRequest, PasswordChange


router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
async def login(
    payload: LoginRequest,
    response: Response,
    db: DbSession = Depends(database.get_db),
):
    username = payload.username.strip()
    if cookie_auth.login_rate_limiter.is_locked(username):
        await asyncio.sleep(0.25)
        raise HTTPException(status_code=401, detail="Invalid credentials.")

    user = (
        db.query(models.User)
        .filter(models.User.username.ilike(username))
        .filter(models.User.is_active.is_(True))
        .first()
    )
    if user is None or not cookie_auth.verify_password(payload.password, user.password_hash):
        cookie_auth.login_rate_limiter.record_failure(username)
        await asyncio.sleep(0.25)
        raise HTTPException(status_code=401, detail="Invalid credentials.")

    cookie_auth.login_rate_limiter.record_success(username)
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()

    sid = cookie_auth.create_session(db, user.id)
    response.set_cookie(
        cookie_auth.COOKIE_NAME,
        sid,
        max_age=int(cookie_auth.SESSION_IDLE_TIMEOUT.total_seconds()),
        httponly=True,
        secure=False,  # set True behind TLS in production via env/config
        samesite="lax",
        path="/",
    )
    return {
        "id": user.id,
        "username": user.username,
        "is_admin": user.is_admin,
        "can_create_workspaces": user.can_create_workspaces,
    }


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    db: DbSession = Depends(database.get_db),
):
    sid = request.cookies.get(cookie_auth.COOKIE_NAME)
    if sid:
        cookie_auth.invalidate_session(db, sid)
    response.delete_cookie(cookie_auth.COOKIE_NAME, path="/")
    return {"ok": True}


@router.post("/password")
def change_password(
    payload: PasswordChange,
    request: Request,
    db: DbSession = Depends(database.get_db),
    user: models.User = Depends(cookie_auth.current_user),
):
    if not cookie_auth.verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=401, detail="Current password incorrect.")
    if len(payload.new_password) < 12:
        raise HTTPException(status_code=400, detail="Password must be at least 12 characters.")
    current_sid = request.cookies.get(cookie_auth.COOKIE_NAME)
    user.password_hash = cookie_auth.hash_password(payload.new_password)
    user.must_change_password = False
    db.query(models.AuthSession).filter(
        models.AuthSession.user_id == user.id,
        models.AuthSession.id != current_sid,
    ).delete(synchronize_session=False)
    db.commit()
    return {"ok": True}


@router.get("/me")
def me(
    user: models.User = Depends(cookie_auth.current_user),
    db: DbSession = Depends(database.get_db),
):
    workspaces = (
        db.query(models.Workspace)
        .filter(models.Workspace.user_id == user.id)
        .order_by(models.Workspace.position.asc(), models.Workspace.created_at.asc())
        .all()
    )
    return {
        "id": user.id,
        "username": user.username,
        "is_admin": user.is_admin,
        "can_create_workspaces": user.can_create_workspaces,
        "email": user.email,
        "must_change_password": user.must_change_password,
        "workspaces": [
            {
                "id": w.id,
                "slug": w.slug,
                "display_name": w.display_name,
                "color": w.color,
                "owner_can_edit": w.owner_can_edit,
                "template_id": w.template_id,
                "position": w.position,
            }
            for w in workspaces
        ],
    }
