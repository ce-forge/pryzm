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

    # admin.user.*
    ADMIN_USER_CREATED = "admin.user.created"
    ADMIN_USER_EDITED = "admin.user.edited"
    ADMIN_USER_ACTIVATED = "admin.user.activated"
    ADMIN_USER_DEACTIVATED = "admin.user.deactivated"
    ADMIN_USER_PROMOTED_TO_ADMIN = "admin.user.promoted_to_admin"
    ADMIN_USER_DEMOTED_FROM_ADMIN = "admin.user.demoted_from_admin"
    ADMIN_USER_DELETED = "admin.user.deleted"

    # admin.template.*
    ADMIN_TEMPLATE_CREATED = "admin.template.created"
    ADMIN_TEMPLATE_EDITED = "admin.template.edited"
    ADMIN_TEMPLATE_DELETED = "admin.template.deleted"
    ADMIN_TEMPLATE_INSTANTIATED = "admin.template.instantiated"
    ADMIN_TEMPLATE_PUSHED = "admin.template.pushed"

    # admin.workspace.*
    ADMIN_WORKSPACE_EDITED = "admin.workspace.edited"
    ADMIN_WORKSPACE_DELETED = "admin.workspace.deleted"

    # admin.system.*
    ADMIN_SYSTEM_MODEL_ADDED = "admin.system.model_added"
    ADMIN_SYSTEM_MODEL_EDITED = "admin.system.model_edited"
    ADMIN_SYSTEM_MODEL_REMOVED = "admin.system.model_removed"
    ADMIN_SYSTEM_MICRO_PROMPT_EDITED = "admin.system.micro_prompt_edited"

    # workspace.*
    WORKSPACE_CREATED = "workspace.created"
    WORKSPACE_EDITED = "workspace.edited"

    # folder.*
    FOLDER_CREATED = "folder.created"
    FOLDER_EDITED = "folder.edited"
    FOLDER_DELETED = "folder.deleted"

    # document.*
    DOCUMENT_UPLOADED = "document.uploaded"
    DOCUMENT_DELETED = "document.deleted"
    DOCUMENT_PROCESSING_FAILED = "document.processing_failed"

    # chat.*
    CHAT_SESSION_CREATED = "chat.session_created"
    CHAT_SESSION_DELETED = "chat.session_deleted"
    CHAT_MESSAGE_SENT = "chat.message_sent"
    CHAT_MESSAGE_RECEIVED = "chat.message_received"
    CHAT_TOOL_INVOKED = "chat.tool_invoked"
    CHAT_RAG_RETRIEVED = "chat.rag_retrieved"
    CHAT_WEB_SEARCH = "chat.web_search"

    # bugreport.*
    BUGREPORT_SUBMITTED = "bugreport.submitted"
    BUGREPORT_ACKNOWLEDGED = "bugreport.acknowledged"
    BUGREPORT_RESOLVED = "bugreport.resolved"
    BUGREPORT_DISMISSED = "bugreport.dismissed"
    BUGREPORT_DELETED = "bugreport.deleted"

    # notification.*
    NOTIFICATION_SENT = "notification.sent"
    NOTIFICATION_BROADCAST_SENT = "notification.broadcast_sent"


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
