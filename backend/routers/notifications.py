"""Notification endpoints.

User-facing reads + acknowledgement at `/api/notifications/*`. Admin
sends at `/api/admin/notifications/*` for direct and broadcast.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session as DbSession

from core import cookie_auth
from core.audit import EventType, log_event
from db import database, models
from schemas import AdminNotificationBroadcast, AdminNotificationSend


user_router = APIRouter(
    prefix="/api/notifications",
    tags=["notifications"],
    dependencies=[Depends(cookie_auth.current_user)],
)

admin_router = APIRouter(
    prefix="/api/admin/notifications",
    tags=["admin", "notifications"],
    dependencies=[Depends(cookie_auth.require_admin)],
)


def _notification_dict(n: models.Notification) -> dict:
    return {
        "id": n.id,
        "user_id": n.user_id,
        "message": n.message,
        "source": n.source,
        "source_id": n.source_id,
        "link_url": n.link_url,
        "created_at": n.created_at.isoformat() if n.created_at else None,
        "seen_at": n.seen_at.isoformat() if n.seen_at else None,
    }


# ---------------------------------------------------------------------------
# User reads + acks
# ---------------------------------------------------------------------------

@user_router.get("/unseen")
def list_unseen(
    db: DbSession = Depends(database.get_db),
    user: models.User = Depends(cookie_auth.current_user),
):
    rows = (
        db.query(models.Notification)
        .filter(
            models.Notification.user_id == user.id,
            models.Notification.seen_at.is_(None),
        )
        .order_by(models.Notification.created_at.desc())
        .all()
    )
    return {
        "unseen_count": len(rows),
        "notifications": [_notification_dict(n) for n in rows],
    }


@user_router.post("/{notification_id}/seen")
def mark_seen(
    notification_id: str,
    db: DbSession = Depends(database.get_db),
    user: models.User = Depends(cookie_auth.current_user),
):
    n = db.query(models.Notification).filter_by(id=notification_id).first()
    if n is None or n.user_id != user.id:
        # Treat "not yours" as 404 — don't leak that an id exists for someone else.
        raise HTTPException(status_code=404, detail="Notification not found.")
    if n.seen_at is None:
        n.seen_at = datetime.now(timezone.utc)
        db.commit()
    return {"ok": True}


@user_router.post("/seen-all")
def mark_all_seen(
    db: DbSession = Depends(database.get_db),
    user: models.User = Depends(cookie_auth.current_user),
):
    now = datetime.now(timezone.utc)
    updated = (
        db.query(models.Notification)
        .filter(
            models.Notification.user_id == user.id,
            models.Notification.seen_at.is_(None),
        )
        .update({"seen_at": now}, synchronize_session=False)
    )
    db.commit()
    return {"ok": True, "marked_seen": updated}


# ---------------------------------------------------------------------------
# Admin sends
# ---------------------------------------------------------------------------

@admin_router.post("")
def admin_send_notification(
    payload: AdminNotificationSend,
    request: Request,
    db: DbSession = Depends(database.get_db),
    admin: models.User = Depends(cookie_auth.require_admin),
):
    target = db.query(models.User).filter_by(id=payload.user_id).first()
    if target is None:
        raise HTTPException(status_code=404, detail="Target user not found.")
    n = models.Notification(
        user_id=target.id,
        message=payload.message,
        source="admin.direct",
        link_url=payload.link_url,
    )
    db.add(n)
    db.commit()
    db.refresh(n)
    log_event(
        db, EventType.NOTIFICATION_SENT,
        user=admin, request=request,
        resource_type="notification", resource_id=n.id,
        payload={
            "notification_id": n.id,
            "target_user_id": target.id,
            "target_username": target.username,
            "message_preview": payload.message[:200],
        },
    )
    db.commit()
    return _notification_dict(n)


@admin_router.post("/broadcast")
def admin_broadcast(
    payload: AdminNotificationBroadcast,
    request: Request,
    db: DbSession = Depends(database.get_db),
    admin: models.User = Depends(cookie_auth.require_admin),
):
    recipients = (
        db.query(models.User)
        .filter(models.User.is_active.is_(True))
        .all()
    )
    for u in recipients:
        db.add(
            models.Notification(
                user_id=u.id,
                message=payload.message,
                source="admin.broadcast",
                link_url=payload.link_url,
            )
        )
    db.flush()
    log_event(
        db, EventType.NOTIFICATION_BROADCAST_SENT,
        user=admin, request=request,
        resource_type="notification",
        payload={
            "recipient_count": len(recipients),
            "message_preview": payload.message[:200],
        },
    )
    db.commit()
    return {"recipient_count": len(recipients)}
