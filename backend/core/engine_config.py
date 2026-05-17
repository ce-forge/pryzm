"""Typed view over workspaces.engine_config JSONB.

The schema lives in db.models.Workspace.engine_config as JSONB. This module
gives the rest of the codebase a typed handle on those values without each
caller re-parsing the dict. Model selection itself is centralised in
`core/llm_server.py`; the JSONB column is reserved for future per-workspace
inference overrides.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from db import models


class EngineConfig(BaseModel):
    """Inference backend choice for a workspace. Today the only value is
    'llama_cpp'; backend-specific overrides can be added here."""
    backend: Literal["llama_cpp"]


def engine_config_for(workspace: models.Workspace) -> EngineConfig:
    """Read the JSONB column on a Workspace row and return the typed model.

    Raises pydantic ValidationError if the stored JSON doesn't match the
    schema — that would mean someone wrote a malformed engine_config (defensive
    check against direct SQL surgery; the migration server-defaults to a valid
    shape)."""
    return EngineConfig.model_validate(workspace.engine_config)
