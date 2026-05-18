"""Admin read-only access to any chat session.

Bypasses the workspace-ownership scoping the user-facing
`/sessions/{id}` endpoint enforces, so admins can read conversations
referenced from bug reports and audit events. No write endpoints —
admin can observe but cannot impersonate.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DbSession

from core import cookie_auth
from db import database, models


router = APIRouter(
    prefix="/api/admin/sessions",
    tags=["admin", "sessions"],
    dependencies=[Depends(cookie_auth.require_admin)],
)


@router.get("/{session_id}")
def get_session_for_admin(
    session_id: str,
    db: DbSession = Depends(database.get_db),
):
    s = db.query(models.Session).filter_by(id=session_id).first()
    if s is None:
        raise HTTPException(status_code=404, detail="Session not found.")

    workspace = (
        db.query(models.Workspace).filter_by(id=s.workspace_id).first()
        if s.workspace_id
        else None
    )
    owner = (
        db.query(models.User).filter_by(id=s.user_id).first()
        if s.user_id
        else None
    )

    messages = (
        db.query(models.Message)
        .filter(
            models.Message.session_id == session_id,
            models.Message.role.in_(["user", "assistant"]),
        )
        .order_by(models.Message.created_at)
        .all()
    )

    return {
        "id": s.id,
        "title": s.title,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "owner": {"id": owner.id, "username": owner.username} if owner else None,
        "workspace": (
            {
                "id": workspace.id,
                "slug": workspace.slug,
                "display_name": workspace.display_name,
            }
            if workspace
            else None
        ),
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "status": m.status,
                "created_at": m.created_at.isoformat() if m.created_at else None,
                "tool_calls": m.tool_calls or None,
                "referenced_docs": m.referenced_docs or None,
            }
            for m in messages
        ],
    }
