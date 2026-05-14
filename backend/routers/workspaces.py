from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from typing import List

import httpx

from config import settings
from core import ollama
from core.deps import get_http_client
from db import database, models
from schemas import (
    WorkspaceResponse,
    WorkspaceCreate,
    WorkspaceUpdate,
    WorkspaceDeleteResponse,
)
from services.builtins import get_builtin
from services.workspaces import (
    get_by_slug,
    slugify_unique,
    read_default_prompt,
)
from tools.registry import AVAILABLE_TOOLS


router = APIRouter(tags=["Workspaces"])


def _validate_resettable(workspace: models.Workspace) -> None:
    """Raise 400 if the workspace is not a builtin.

    Reset re-seeds display_name, system_prompt, enabled_tools, etc. from the
    BUILTIN_WORKSPACES registry — only meaningful for rows we own the source
    of truth for. User-created workspaces have no canonical defaults to reset
    to, so we reject the operation.
    """
    if not workspace.is_builtin:
        raise HTTPException(
            status_code=400,
            detail="Reset is only allowed for builtin workspaces.",
        )


def _validate_enabled_tools(names: List[str]) -> None:
    """Reject names that aren't in the live tool registry."""
    unknown = [n for n in names if n not in AVAILABLE_TOOLS]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown tool name(s): {unknown}",
        )


async def _validate_preferred_model(client: httpx.AsyncClient, model: str) -> None:
    """Confirm the model exists in the Ollama /api/tags response AND is a
    chat-capable model (embedding-only models like nomic-embed-text are
    filtered out, matching chat.py:get_ollama_models). Done at PATCH time
    so we fail loudly on misconfiguration; chat-time resolution in
    services/workspaces.py tolerates a stale value with a warning."""
    if model is None:
        return
    try:
        all_models = await ollama.list_models(client)
        # Filter out embedding-only models; they're not usable as chat models.
        names = [m for m in all_models if "embed" not in m.lower()]
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Could not reach Ollama to validate model: {e}",
        )
    if model not in names:
        raise HTTPException(
            status_code=400,
            detail=f"Model not installed (or is embedding-only) in Ollama: {model}. Available: {names}",
        )


@router.get("/workspaces", response_model=List[WorkspaceResponse])
def list_workspaces(db: Session = Depends(database.get_db)):
    return db.query(models.Workspace).order_by(models.Workspace.created_at.asc()).all()


@router.get("/workspaces/{slug}", response_model=WorkspaceResponse)
def get_workspace(slug: str, db: Session = Depends(database.get_db)):
    return get_by_slug(db, slug)


@router.post("/workspaces", response_model=WorkspaceResponse)
def create_workspace(
    payload: WorkspaceCreate,
    db: Session = Depends(database.get_db),
):
    try:
        slug = slugify_unique(db, payload.display_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Defaults for a fresh blank workspace.
    system_prompt = "You are a helpful assistant. Answer the user's questions thoughtfully."
    enabled_tools: list[str] = []
    preferred_model = None

    if payload.clone_from:
        source = get_by_slug(db, payload.clone_from)
        system_prompt = source.system_prompt
        enabled_tools = list(source.enabled_tools or [])
        preferred_model = source.preferred_model

    ws = models.Workspace(
        slug=slug,
        display_name=payload.display_name.strip(),
        system_prompt=system_prompt,
        enabled_tools=enabled_tools,
        preferred_model=preferred_model,
        color=payload.color,
        is_builtin=False,
    )
    db.add(ws)
    db.commit()
    db.refresh(ws)
    return ws


@router.patch("/workspaces/{slug}", response_model=WorkspaceResponse)
async def update_workspace(
    slug: str,
    payload: WorkspaceUpdate,
    db: Session = Depends(database.get_db),
    http_client: httpx.AsyncClient = Depends(get_http_client),
):
    ws = get_by_slug(db, slug)

    data = payload.model_dump(exclude_unset=True)

    if "display_name" in data:
        stripped = data["display_name"].strip()
        if not stripped:
            raise HTTPException(
                status_code=400,
                detail="display_name must contain non-whitespace characters",
            )
        ws.display_name = stripped

    if "system_prompt" in data:
        ws.system_prompt = data["system_prompt"]

    if "enabled_tools" in data:
        _validate_enabled_tools(data["enabled_tools"])
        ws.enabled_tools = data["enabled_tools"]

    if "preferred_model" in data:
        # Explicit null clears the pin; non-null is validated against Ollama.
        if data["preferred_model"] is not None:
            await _validate_preferred_model(http_client, data["preferred_model"])
        ws.preferred_model = data["preferred_model"]

    if "color" in data:
        ws.color = data["color"]

    db.commit()
    db.refresh(ws)
    return ws


@router.delete("/workspaces/{slug}", response_model=WorkspaceDeleteResponse)
def delete_workspace(slug: str, db: Session = Depends(database.get_db)):
    ws = get_by_slug(db, slug)

    # Last-workspace guard.
    total = db.query(models.Workspace).count()
    if total <= 1:
        raise HTTPException(
            status_code=409,
            detail="Cannot delete the only remaining workspace.",
        )

    # Count what's about to cascade so the response can populate the UI
    # confirmation modal. Counts are best-effort: a concurrent request could
    # add/remove rows between these COUNTs and the db.delete below, so the
    # numbers may be slightly off. The actual cascade-delete is authoritative
    # — these counts are display-only.
    removed_sessions = db.query(models.Session).filter(models.Session.workspace_id == ws.id).count()
    removed_folders = db.query(models.Folder).filter(models.Folder.workspace_id == ws.id).count()
    removed_documents = db.query(models.Document).filter(models.Document.workspace_id == ws.id).count()

    db.delete(ws)
    db.commit()

    return WorkspaceDeleteResponse(
        deleted=True,
        removed_sessions=removed_sessions,
        removed_folders=removed_folders,
        removed_documents=removed_documents,
    )


@router.post("/workspaces/{slug}/reset", response_model=WorkspaceResponse)
def reset_workspace(slug: str, db: Session = Depends(database.get_db)):
    ws = get_by_slug(db, slug)
    _validate_resettable(ws)
    builtin = get_builtin(slug)
    if builtin is None:
        raise HTTPException(
            status_code=500,
            detail=f"Builtin registry entry missing for: {slug}",
        )
    try:
        ws.system_prompt = read_default_prompt(slug)
    except FileNotFoundError:
        raise HTTPException(
            status_code=500,
            detail=f"Default prompt file missing for builtin: core/prompts/{slug}.txt",
        )
    ws.enabled_tools = list(builtin.enabled_tools)
    ws.preferred_model = None
    ws.display_name = builtin.display_name
    ws.color = builtin.color
    db.commit()
    db.refresh(ws)
    return ws
