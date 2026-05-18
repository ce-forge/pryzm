"""Workspace lookup, tool/model resolution, and seed-from-default helpers.

This module is the single owner of "given a workspace, what tools and what
model do we use?" The tools/registry.py module is only the source of the
declared tool registry; this module reads the workspace's stored config
(enabled_tools, engine_config) and resolves it against the live registry
at request time.
"""
import os
import re
from typing import Tuple

from fastapi import HTTPException
from sqlalchemy.orm import Session

from db import models
from tools.registry import AVAILABLE_TOOLS, TOOL_DEFINITIONS


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


def resolve_tools_for_workspace(workspace: models.Workspace) -> Tuple[dict, list]:
    """Given a workspace, return (callable_map, definitions_list) filtered to
    just the tools the workspace has enabled AND that exist in the live
    AVAILABLE_TOOLS registry. Stale names in enabled_tools (e.g. for tools
    that were removed in a later code change) are silently ignored — the
    workspace works with whatever the engineer kept."""
    enabled = set(workspace.enabled_tools or [])
    callables = {name: fn for name, fn in AVAILABLE_TOOLS.items() if name in enabled}
    definitions = [d for d in TOOL_DEFINITIONS if d["function"]["name"] in enabled]
    return callables, definitions


def resolve_model_for_request(workspace: models.Workspace) -> str:
    """Pick the model name to send to Ollama for this chat call.

    Resolution order, most specific first:
      1. workspace.engine_config["model"] (if set)
      2. hardcoded fallback "gemma4:e4b"

    NOTE: this function does NOT verify the chosen model is currently
    installed in Ollama. Validation happens at PATCH /workspaces time so
    the pin is known-good when it's stored. If the model is later
    uninstalled, the Ollama call itself will fail and the request
    logger middleware (main.py) will record the error — we'd rather pay
    that cost on a broken-but-rare configuration than a /api/tags
    round-trip on every chat call.
    """
    if workspace and workspace.engine_config:
        model = workspace.engine_config.get("model")
        if model:
            return model
    return "gemma4:e4b"


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
