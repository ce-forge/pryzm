"""Audit logging helper.

The single entry point for emitting audit events. Inserts are sync and
participate in the surrounding request transaction — if the audit write
fails, the entire request rolls back. This is deliberate; silent audit
failure is worse than a visible 500 because it creates a false sense of
observability.

Event_type strings follow `domain.verb` shape. Add new constants here
as new domains land.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import Request
from sqlalchemy.orm import Session

from db import models


class EventType:
    """Canonical event-type strings. Add new entries here, not inline."""

    # auth.*
    AUTH_LOGIN_SUCCESS = "auth.login_success"
    AUTH_LOGIN_FAILURE = "auth.login_failure"
    AUTH_LOGOUT = "auth.logout"
    AUTH_PASSWORD_CHANGED = "auth.password_changed"
    AUTH_PASSWORD_RESET_BY_ADMIN = "auth.password_reset_by_admin"
    AUTH_SESSION_EXPIRED = "auth.session_expired"


def log_event(
    db: Session,
    event_type: str,
    *,
    user: Optional[models.User] = None,
    workspace: Optional[models.Workspace] = None,
    session: Optional[models.Session] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    payload: Optional[dict[str, Any]] = None,
    source_ip: Optional[str] = None,
    user_agent: Optional[str] = None,
    request: Optional[Request] = None,
) -> models.AuditEvent:
    """Append one row to audit_events using the caller's db session."""
    if request is not None:
        if source_ip is None:
            source_ip = request.client.host if request.client else None
        if user_agent is None:
            user_agent = request.headers.get("user-agent")

    event = models.AuditEvent(
        user_id=user.id if user else None,
        user_display_name_at_event=user.username if user else None,
        event_type=event_type,
        workspace_id=workspace.id if workspace else None,
        session_id=session.id if session else None,
        resource_type=resource_type,
        resource_id=resource_id,
        payload=payload or {},
        source_ip=source_ip,
        user_agent=user_agent,
    )
    db.add(event)
    return event
