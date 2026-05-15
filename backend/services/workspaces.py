"""Workspace lookup, tool/model resolution, and seed-from-default helpers.

This module is the single owner of "given a workspace, what tools and what
model do we use?" The tools/registry.py module is only the source of the
declared tool registry; this module reads the workspace's stored config
(enabled_tools, engine_config) and resolves it against the live registry
at request time.
"""
import os
import re
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from db import models


PROMPTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "core", "prompts",
)


def get_by_slug(db: Session, slug: str) -> models.Workspace:
    """Resolve a slug to a Workspace, 404 if missing."""
    ws = db.query(models.Workspace).filter(models.Workspace.slug == slug).first()
    if not ws:
        raise HTTPException(status_code=404, detail=f"Workspace not found: {slug}")
    return ws


def get_or_default(db: Session, slug: Optional[str]) -> models.Workspace:
    """Resolve a slug to its Workspace. Behavior depends on the input:

      - slug is None or empty: fall back to the oldest workspace
        (typically it_copilot post-migration). This preserves the
        historical default for endpoints whose `workspace` query
        parameter was optional with a built-in default.
      - slug is provided but does NOT exist: 404. We deliberately do
        NOT silently reroute to the default — that would mask stale
        URLs and let user-visible operations land in the wrong
        workspace without notice.
    """
    if slug:
        ws = db.query(models.Workspace).filter(models.Workspace.slug == slug).first()
        if ws:
            return ws
        raise HTTPException(status_code=404, detail=f"Workspace not found: {slug}")
    ws = db.query(models.Workspace).order_by(models.Workspace.created_at.asc()).first()
    if not ws:
        raise HTTPException(status_code=500, detail="No workspaces exist. Database is empty.")
    return ws


def slugify(display_name: str) -> str:
    """Convert a display name to a URL/identifier-safe slug. Lowercase,
    replace non-alphanumeric with hyphens, collapse runs, trim leading
    and trailing hyphens. Raises ValueError if the result is empty
    (caller should respond 400)."""
    s = re.sub(r"[^a-z0-9]+", "-", display_name.lower()).strip("-")
    if not s:
        raise ValueError("Display name must contain at least one alphanumeric character")
    return s


def slugify_unique(db: Session, display_name: str) -> str:
    """Slugify the display name, then append -2, -3, ... until unique."""
    base = slugify(display_name)
    candidate = base
    n = 2
    while db.query(models.Workspace).filter(models.Workspace.slug == candidate).first():
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def read_default_prompt(slug: str) -> str:
    """Read the on-disk default prompt for a built-in workspace. Used by the
    /reset endpoint. Raises FileNotFoundError if the slug has no default."""
    path = os.path.join(PROMPTS_DIR, f"{slug}.txt")
    with open(path, "r") as f:
        return f.read().strip()
