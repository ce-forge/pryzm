"""Admin read endpoints for audit_events.

Read-only — events are emitted by application code via core.audit.log_event.
The list endpoint cursor-paginates so the dashboard's Audit tab can stably
scroll across rows that continue to append while the user is paging.

`event_type` filter supports a `prefix:` syntax (e.g., `prefix:admin.user`)
which matches `event_type LIKE 'admin.user.%'` — useful for the dashboard
dropdown that groups by domain.
"""
from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, or_, tuple_
from sqlalchemy.orm import Session as DbSession

from core import cookie_auth
from core.audit import EventType
from db import database, models


router = APIRouter(
    prefix="/api/admin/audit",
    tags=["admin", "audit"],
    dependencies=[Depends(cookie_auth.require_admin)],
)


# Truncate the payload in list responses to keep the wire small. The
# detail endpoint returns the full payload.
_LIST_PAYLOAD_PREVIEW_CHARS = 500


def _encode_cursor(created_at: datetime, event_id: str) -> str:
    raw = json.dumps({"c": created_at.isoformat(), "i": event_id})
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    """Returns (created_at, id). Raises HTTPException(400) on malformed input."""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded).decode())
        return datetime.fromisoformat(data["c"]), data["i"]
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid cursor.")


def _event_to_dict(e: models.AuditEvent, truncate_payload: bool) -> dict:
    payload = e.payload or {}
    if truncate_payload:
        # Cheap, deterministic truncation: stringify then slice. The frontend
        # never needs to deserialize the preview as structured data — it just
        # shows it as a short summary in the list row.
        serialized = json.dumps(payload)
        if len(serialized) > _LIST_PAYLOAD_PREVIEW_CHARS:
            payload = {
                "_preview": serialized[:_LIST_PAYLOAD_PREVIEW_CHARS] + "...",
                "_truncated": True,
            }
    return {
        "id": e.id,
        "user_id": e.user_id,
        "user_display_name_at_event": e.user_display_name_at_event,
        "event_type": e.event_type,
        "workspace_id": e.workspace_id,
        "session_id": e.session_id,
        "resource_type": e.resource_type,
        "resource_id": e.resource_id,
        "payload": payload,
        "source_ip": e.source_ip,
        "user_agent": e.user_agent,
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }


@router.get("")
def list_events(
    user_id: Optional[str] = Query(None),
    event_type: Optional[str] = Query(
        None,
        description="Exact event_type, or `prefix:foo.bar` to match `foo.bar.*`.",
    ),
    workspace_id: Optional[str] = Query(None),
    from_: Optional[datetime] = Query(None, alias="from"),
    to: Optional[datetime] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    cursor: Optional[str] = Query(None),
    db: DbSession = Depends(database.get_db),
):
    q = db.query(models.AuditEvent)

    if user_id:
        q = q.filter(models.AuditEvent.user_id == user_id)
    if workspace_id:
        q = q.filter(models.AuditEvent.workspace_id == workspace_id)
    if event_type:
        if event_type.startswith("prefix:"):
            prefix = event_type[len("prefix:"):]
            q = q.filter(models.AuditEvent.event_type.like(f"{prefix}.%"))
        else:
            q = q.filter(models.AuditEvent.event_type == event_type)
    if from_:
        q = q.filter(models.AuditEvent.created_at >= from_)
    if to:
        q = q.filter(models.AuditEvent.created_at < to)

    if cursor:
        cur_created_at, cur_id = _decode_cursor(cursor)
        # (created_at, id) < (cursor_created_at, cursor_id) gives strict
        # ordering across the natural insertion sequence.
        q = q.filter(
            or_(
                models.AuditEvent.created_at < cur_created_at,
                and_(
                    models.AuditEvent.created_at == cur_created_at,
                    models.AuditEvent.id < cur_id,
                ),
            )
        )

    q = q.order_by(
        models.AuditEvent.created_at.desc(),
        models.AuditEvent.id.desc(),
    ).limit(limit + 1)

    rows = q.all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = _encode_cursor(last.created_at, last.id)

    return {
        "events": [_event_to_dict(e, truncate_payload=True) for e in rows],
        "next_cursor": next_cursor,
    }


@router.get("/event-types")
def list_event_types():
    """Return the canonical list of known event-type strings.

    Sourced from `core/audit.py::EventType` via attribute introspection so
    new constants automatically show up in the dashboard dropdown.
    """
    types = sorted(
        v for k, v in vars(EventType).items()
        if not k.startswith("_") and isinstance(v, str)
    )
    return {"event_types": types}


@router.get("/{event_id}")
def get_event(
    event_id: str,
    db: DbSession = Depends(database.get_db),
):
    event = db.query(models.AuditEvent).filter(
        models.AuditEvent.id == event_id
    ).first()
    if event is None:
        raise HTTPException(status_code=404, detail="Audit event not found.")
    return _event_to_dict(event, truncate_payload=False)
