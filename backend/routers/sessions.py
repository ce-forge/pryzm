"""Session, message, branch, and truncate endpoints.

Session = the long-lived conversation row. Messages live inside one.
Branching forks the conversation up to a chosen message; truncating
drops everything after a chosen message. Both keep the original
session intact unless the caller explicitly deletes it.

Workspace-scoping: anything that mutates a message looks up the
session-via-workspace and 404s on cross-workspace access (matches the
convention in core.workspace_access).
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import tuple_, func as sqlfunc
from sqlalchemy.orm import Session

from db import database, models
from schemas import (
    BranchRequest,
    MessageHistory,
    MessageUpdate,
    SessionResponse,
    SessionUpdate,
)
from services.workspaces import get_or_default


router = APIRouter(tags=["Sessions"])


def _resolve_workspace_or_404(slug: str, db: Session) -> models.Workspace:
    workspace = db.query(models.Workspace).filter(models.Workspace.slug == slug).first()
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace


def _message_in_workspace_or_404(
    message_id: str,
    workspace_id: str,
    db: Session,
) -> models.Message:
    """Return the message if it belongs to a session in workspace_id, else 404.
    Returns 404 (not 403) on cross-workspace access — info-leak protection
    consistent with the rest of the workspace boundary."""
    msg = (
        db.query(models.Message)
        .join(models.Session, models.Message.session_id == models.Session.id)
        .filter(
            models.Message.id == message_id,
            models.Session.workspace_id == workspace_id,
        )
        .first()
    )
    if msg is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return msg


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

@router.get("/sessions", response_model=List[SessionResponse])
def get_sessions(
    workspace: str = "it_copilot",
    folder_id: Optional[str] = None,
    limit: Optional[int] = None,
    offset: int = 0,
    db: Session = Depends(database.get_db),
):
    """List sessions for a workspace, newest first.

    folder_id filters to one folder (unsorted/null-match is client-side).
    limit/offset are optional; defaults preserve unbounded "load all".
    """
    ws = get_or_default(db, workspace)
    q = db.query(models.Session).filter(models.Session.workspace_id == ws.id)
    if folder_id is not None:
        q = q.filter(models.Session.folder_id == folder_id)
    q = q.order_by(models.Session.created_at.desc())
    if offset:
        q = q.offset(offset)
    if limit is not None:
        q = q.limit(limit)
    return q.all()


@router.get("/sessions/{session_id}", response_model=List[MessageHistory])
def get_session_history(
    session_id: str,
    limit: Optional[int] = None,
    offset: int = 0,
    db: Session = Depends(database.get_db),
):
    """Return user/assistant messages in chronological order."""
    session = db.query(models.Session).filter(models.Session.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    q = db.query(models.Message).filter(
        models.Message.session_id == session_id,
        models.Message.role.in_(["user", "assistant"]),
    ).order_by(models.Message.created_at)
    if offset:
        q = q.offset(offset)
    if limit is not None:
        q = q.limit(limit)
    messages = q.all()

    return [{"id": m.id,
            "role": m.role,
            "content": m.content,
            "status": m.status,
            "timestamp": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
    ]


@router.patch("/sessions/{session_id}")
def update_session(session_id: str, payload: SessionUpdate, db: Session = Depends(database.get_db)):
    db_session = db.query(models.Session).filter(models.Session.id == session_id).first()
    if db_session:
        update_data = payload.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(db_session, key, value)
        db.commit()
        return {"status": "success"}
    return {"status": "error", "message": "Session not found"}


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str, db: Session = Depends(database.get_db)):
    session = db.query(models.Session).filter(models.Session.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    db.delete(session)
    db.commit()
    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

@router.patch("/messages/{message_id}")
def update_message(
    message_id: str,
    payload: MessageUpdate,
    workspace: str = Query(..., description="Slug of the workspace the message belongs to"),
    db: Session = Depends(database.get_db),
):
    """Edit a message's content. Workspace-scoped; cross-workspace → 404."""
    workspace_obj = _resolve_workspace_or_404(workspace, db)
    msg = _message_in_workspace_or_404(message_id, workspace_obj.id, db)

    msg.content = payload.content
    db.commit()
    return {"status": "success"}


@router.delete("/messages/{message_id}")
def delete_message(
    message_id: str,
    workspace: str = Query(..., description="Slug of the workspace the message belongs to"),
    db: Session = Depends(database.get_db),
):
    workspace_obj = _resolve_workspace_or_404(workspace, db)
    msg = _message_in_workspace_or_404(message_id, workspace_obj.id, db)

    session_id_resp = msg.session_id
    db.delete(msg)
    db.commit()
    return {"status": "success", "session_id": session_id_resp}


# ---------------------------------------------------------------------------
# Branch + truncate
# ---------------------------------------------------------------------------

@router.post("/sessions/{session_id}/branch")
def branch_session(session_id: str, body: BranchRequest, db: Session = Depends(database.get_db)):
    old_session = db.query(models.Session).filter(models.Session.id == session_id).first()
    if not old_session:
        raise HTTPException(status_code=404, detail="Source session not found")

    target = db.query(models.Message).filter(
        models.Message.id == body.up_to_message_id,
        models.Message.session_id == session_id,
    ).first()
    if not target:
        raise HTTPException(status_code=404, detail="up_to_message_id does not belong to this session")

    # Avoid stacking "(Branch) (Branch) ..." when re-branching a branch.
    branched_title = old_session.title if old_session.title.endswith("(Branch)") else f"{old_session.title} (Branch)"
    new_session = models.Session(title=branched_title, workspace_id=old_session.workspace_id)
    db.add(new_session)
    db.commit()
    db.refresh(new_session)

    # Skip memory rows: their JSON payload references message IDs that
    # won't exist in the new branch and would corrupt the condenser.
    messages = db.query(models.Message).filter(
        models.Message.session_id == session_id,
        models.Message.role.in_(["user", "assistant"]),
    ).order_by(models.Message.created_at, models.Message.id).all()

    for m in messages:
        # clock_timestamp() gives each copy a distinct wall-clock time.
        # The default `now()` makes every row in this transaction share
        # one timestamp, which breaks later truncates ordered by created_at.
        new_msg = models.Message(
            session_id=new_session.id,
            role=m.role,
            content=m.content,
            status=m.status,
            created_at=sqlfunc.clock_timestamp(),
        )
        db.add(new_msg)
        if m.id == body.up_to_message_id:
            break

    db.commit()
    return {"new_session_id": new_session.id}


@router.delete("/sessions/{session_id}/truncate/{message_id}")
def truncate_session(
    session_id: str,
    message_id: str,
    workspace: str = Query(..., description="Slug of the workspace the session belongs to"),
    db: Session = Depends(database.get_db),
):
    """Delete all messages AFTER the specified message_id.

    Uses (created_at, id) for deterministic ordering when two rows share
    a created_at (which happens after branch_session — see comment there).
    """
    workspace_obj = _resolve_workspace_or_404(workspace, db)

    target_msg = (
        db.query(models.Message)
        .join(models.Session, models.Message.session_id == models.Session.id)
        .filter(
            models.Message.id == message_id,
            models.Message.session_id == session_id,
            models.Session.workspace_id == workspace_obj.id,
        )
        .first()
    )
    if not target_msg:
        raise HTTPException(status_code=404, detail="Target message not found")

    deleted_count = db.query(models.Message).filter(
        models.Message.session_id == session_id,
        tuple_(models.Message.created_at, models.Message.id) >
            (target_msg.created_at, target_msg.id),
    ).delete(synchronize_session=False)

    # Drop the memory row too. If it references a now-deleted message
    # the condenser would silently restart from index 0 and re-summarize
    # content already baked into the summary. Cheaper to rebuild.
    db.query(models.Message).filter(
        models.Message.session_id == session_id,
        models.Message.role == "memory",
    ).delete(synchronize_session=False)

    db.commit()
    return {"status": "success", "deleted_count": deleted_count}
