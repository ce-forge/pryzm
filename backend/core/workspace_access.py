"""Workspace boundary verification.

Reusable helpers + a FastAPI dependency that look up resources scoped to
a workspace. Returning 404 (not 403) on cross-workspace access avoids
leaking whether the resource exists in another workspace.

`verify_workspace_owns` works for any model with a direct `workspace_id`
column (Session, Folder, Document, DocumentChunk). Message is scoped via
Session.workspace_id and uses a separate helper in routers/chat.py.
"""
from typing import Optional, Type, TypeVar

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy.orm import Session as SqlSession

from db import database, models
from db.models import Base


T = TypeVar("T", bound=Base)


def resolve_workspace_or_404(slug: str, db: SqlSession) -> models.Workspace:
    """Resolve a workspace slug to its ORM row; 404 if not found."""
    ws = db.query(models.Workspace).filter(models.Workspace.slug == slug).first()
    if ws is None:
        raise HTTPException(status_code=404, detail=f"Workspace not found: {slug}")
    return ws


def workspace_query_dep(
    workspace: Optional[str] = Query(
        None, description="Slug of the workspace the resource belongs to"
    ),
    db: SqlSession = Depends(database.get_db),
) -> models.Workspace:
    """FastAPI dep: read `?workspace={slug}` and resolve to a Workspace row.

    422 if the query param is missing, 404 if the slug does not exist. This
    is the single boundary where slug → id resolution happens for routes
    that need workspace context.
    """
    if not workspace:
        raise HTTPException(status_code=422, detail="workspace query parameter is required")
    return resolve_workspace_or_404(workspace, db)


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
