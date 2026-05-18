"""Bug-report endpoints.

User-facing submission lives at `POST /api/bug-reports`. Admin triage
endpoints live at `/api/admin/bug-reports`. Lifecycle events
(submitted / acknowledged / resolved / dismissed / deleted) all emit
`bugreport.*` audit rows. Resolving also queues a notification for the
reporter.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session as DbSession

from core import cookie_auth
from core.audit import EventType, log_event
from db import database, models
from schemas import BugReportSubmit


user_router = APIRouter(
    prefix="/api/bug-reports",
    tags=["bug-reports"],
    dependencies=[Depends(cookie_auth.current_user)],
)

admin_router = APIRouter(
    prefix="/api/admin/bug-reports",
    tags=["admin", "bug-reports"],
    dependencies=[Depends(cookie_auth.require_admin)],
)


_NOTIFICATION_PREVIEW_CHARS = 60


def _bug_dict(b: models.BugReport) -> dict:
    return {
        "id": b.id,
        "user_id": b.user_id,
        "user_display_name": b.user_display_name,
        "workspace_id": b.workspace_id,
        "session_id": b.session_id,
        "category": b.category,
        "message": b.message,
        "payload": b.payload or {},
        "status": b.status,
        "resolved_at": b.resolved_at.isoformat() if b.resolved_at else None,
        "resolved_by": b.resolved_by,
        "created_at": b.created_at.isoformat() if b.created_at else None,
    }


def _get_or_404(db: DbSession, bug_id: str) -> models.BugReport:
    b = db.query(models.BugReport).filter_by(id=bug_id).first()
    if b is None:
        raise HTTPException(status_code=404, detail="Bug report not found.")
    return b


# ---------------------------------------------------------------------------
# User-facing submit
# ---------------------------------------------------------------------------

@user_router.post("")
def submit_bug_report(
    payload: BugReportSubmit,
    request: Request,
    db: DbSession = Depends(database.get_db),
    user: models.User = Depends(cookie_auth.current_user),
):
    workspace_id = request.query_params.get("workspace_id") or None
    session_id_param = request.query_params.get("session_id") or None
    session_id = session_id_param if payload.include_session else None

    # Validate workspace ownership softly — non-owner submissions just get
    # workspace_id=NULL rather than 403, because users browsing other
    # workspaces (templates view, etc.) should still be able to file bugs.
    if workspace_id:
        ws = db.query(models.Workspace).filter_by(id=workspace_id).first()
        if ws is None or ws.user_id != user.id:
            workspace_id = None
    if session_id:
        s = db.query(models.Session).filter_by(id=session_id).first()
        if s is None or s.user_id != user.id:
            session_id = None

    bug = models.BugReport(
        user_id=user.id,
        user_display_name=user.username,
        workspace_id=workspace_id,
        session_id=session_id,
        category=payload.category,
        message=payload.message,
        payload={
            "url": request.headers.get("referer"),
            "user_agent": request.headers.get("user-agent"),
        },
    )
    db.add(bug)
    db.commit()
    db.refresh(bug)

    log_event(
        db,
        EventType.BUGREPORT_SUBMITTED,
        user=user,
        request=request,
        resource_type="bug_report",
        resource_id=bug.id,
        payload={
            "bug_report_id": bug.id,
            "category": bug.category,
            "message_preview": bug.message[:200],
            "current_workspace_id": workspace_id,
            "current_session_id": session_id,
        },
    )
    db.commit()
    return _bug_dict(bug)


# ---------------------------------------------------------------------------
# Admin list + detail
# ---------------------------------------------------------------------------

@admin_router.get("")
def list_bug_reports(
    status: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    db: DbSession = Depends(database.get_db),
):
    q = db.query(models.BugReport)
    if status:
        q = q.filter(models.BugReport.status == status)
    if user_id:
        q = q.filter(models.BugReport.user_id == user_id)
    if category:
        q = q.filter(models.BugReport.category == category)
    rows = q.order_by(models.BugReport.created_at.desc()).all()
    return [_bug_dict(b) for b in rows]


@admin_router.get("/{bug_id}")
def get_bug_report(bug_id: str, db: DbSession = Depends(database.get_db)):
    return _bug_dict(_get_or_404(db, bug_id))


# ---------------------------------------------------------------------------
# Admin lifecycle transitions
# ---------------------------------------------------------------------------

@admin_router.post("/{bug_id}/acknowledge")
def acknowledge_bug_report(
    bug_id: str,
    request: Request,
    db: DbSession = Depends(database.get_db),
    admin: models.User = Depends(cookie_auth.require_admin),
):
    b = _get_or_404(db, bug_id)
    if b.status not in ("open", "acknowledged"):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot acknowledge bug in status {b.status!r}.",
        )
    b.status = "acknowledged"
    log_event(
        db, EventType.BUGREPORT_ACKNOWLEDGED,
        user=admin, request=request,
        resource_type="bug_report", resource_id=b.id,
        payload={"bug_report_id": b.id},
    )
    db.commit()
    db.refresh(b)
    return _bug_dict(b)


@admin_router.post("/{bug_id}/resolve")
def resolve_bug_report(
    bug_id: str,
    request: Request,
    db: DbSession = Depends(database.get_db),
    admin: models.User = Depends(cookie_auth.require_admin),
):
    b = _get_or_404(db, bug_id)
    if b.status == "resolved":
        raise HTTPException(status_code=409, detail="Bug report already resolved.")

    b.status = "resolved"
    b.resolved_at = datetime.now(timezone.utc)
    b.resolved_by = admin.id

    # Queue a notification for the reporter — only when the reporter row
    # still exists. Hard-deleted users (user_id=NULL) get no notification.
    if b.user_id:
        preview = b.message[:_NOTIFICATION_PREVIEW_CHARS]
        if len(b.message) > _NOTIFICATION_PREVIEW_CHARS:
            preview += "…"
        notif = models.Notification(
            user_id=b.user_id,
            message=f"Your bug report has been resolved: {preview}",
            source="bugreport.resolved",
            source_id=b.id,
        )
        db.add(notif)

    log_event(
        db, EventType.BUGREPORT_RESOLVED,
        user=admin, request=request,
        resource_type="bug_report", resource_id=b.id,
        payload={
            "bug_report_id": b.id,
            "reporter_user_id": b.user_id,
        },
    )
    db.commit()
    db.refresh(b)
    return _bug_dict(b)


@admin_router.post("/{bug_id}/dismiss")
def dismiss_bug_report(
    bug_id: str,
    request: Request,
    db: DbSession = Depends(database.get_db),
    admin: models.User = Depends(cookie_auth.require_admin),
):
    b = _get_or_404(db, bug_id)
    if b.status == "dismissed":
        raise HTTPException(status_code=409, detail="Bug report already dismissed.")
    b.status = "dismissed"
    log_event(
        db, EventType.BUGREPORT_DISMISSED,
        user=admin, request=request,
        resource_type="bug_report", resource_id=b.id,
        payload={"bug_report_id": b.id},
    )
    db.commit()
    db.refresh(b)
    return _bug_dict(b)


@admin_router.delete("/{bug_id}")
def delete_bug_report(
    bug_id: str,
    request: Request,
    db: DbSession = Depends(database.get_db),
    admin: models.User = Depends(cookie_auth.require_admin),
):
    b = _get_or_404(db, bug_id)
    bug_summary = {
        "bug_report_id": b.id,
        "category": b.category,
        "status_at_delete": b.status,
        "reporter_user_id": b.user_id,
    }
    db.delete(b)
    log_event(
        db, EventType.BUGREPORT_DELETED,
        user=admin, request=request,
        resource_type="bug_report", resource_id=bug_id,
        payload=bug_summary,
    )
    db.commit()
    return {"ok": True}
