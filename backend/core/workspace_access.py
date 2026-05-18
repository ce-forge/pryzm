"""Workspace boundary verification.

Reusable helpers + a FastAPI dependency that look up resources scoped to
a workspace. Returning 404 (not 403) on cross-workspace access avoids
leaking whether the resource exists in another workspace.

`verify_workspace_owns` works for any model with a direct `workspace_id`
column (Session, Folder, Document, DocumentChunk). Message is scoped via
Session.workspace_id and uses a separate helper in routers/chat.py.
"""
from typing import Type, TypeVar

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy.orm import Session as SqlSession

from core.cookie_auth import current_user
from db import database, models
from db.models import Base


T = TypeVar("T", bound=Base)


def workspace_query_dep(
    workspace: str = Query(..., description="Slug of the workspace the resource belongs to"),
    user: models.User = Depends(current_user),
    db: SqlSession = Depends(database.get_db),
) -> models.Workspace:
    """FastAPI dep: resolve `?workspace={slug}` to the caller's own,
    non-template workspace. 404 on any miss (wrong owner, template, or
    nonexistent slug) — 404 not 403 to avoid leaking existence across users.
    """
    ws = (
        db.query(models.Workspace)
        .filter(
            models.Workspace.slug == workspace,
            models.Workspace.user_id == user.id,
            models.Workspace.is_template.is_(False),
        )
        .first()
    )
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    return ws


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
