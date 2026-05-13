"""Workspace boundary verification.

A reusable dependency that looks up an id-keyed resource and 404s if it
belongs to another workspace. Returning 404 rather than 403 avoids leaking
whether the resource exists in another workspace.

Only works for models that have a `workspace_id` column directly (Session,
Folder, Document, DocumentChunk). Message is scoped via Session.workspace_id
and uses a separate helper in routers/chat.py (Phase 2 Task 2).
"""
from typing import Type, TypeVar

from fastapi import HTTPException, status
from sqlalchemy.orm import Session as SqlSession

from db.models import Base


T = TypeVar("T", bound=Base)


def verify_workspace_owns(
    resource_id: str,
    model: Type[T],
    workspace_id: str,
    db: SqlSession,
) -> T:
    """Return the resource if it exists AND belongs to workspace_id.
    Raise 404 otherwise (not 403 — see module docstring).
    """
    resource = db.query(model).filter(model.id == resource_id).first()
    if resource is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if getattr(resource, "workspace_id", None) != workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return resource
