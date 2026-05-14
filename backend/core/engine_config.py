"""Typed view over workspaces.engine_config JSONB.

The schema lives in db.models.Workspace.engine_config as JSONB. This module
gives the rest of the codebase a typed handle on those values without each
caller re-parsing the dict.

Phase B1 dropped the `model` field — the backend hardcodes its model id in
`core/llm_server.py`. The column stays as JSONB so future per-workspace
overrides (e.g. council members forcing a specific model) can plug in
without a migration.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from db import models


class EngineConfig(BaseModel):
    """Inference backend choice for a workspace. Today the only value is
    'llama_cpp'; Phase B2 may add backend-specific overrides here."""
    backend: Literal["llama_cpp"]


def engine_config_for(workspace: models.Workspace) -> EngineConfig:
    """Read the JSONB column on a Workspace row and return the typed model.

    Raises pydantic ValidationError if the stored JSON doesn't match the
    schema — that would mean someone wrote a malformed engine_config (defensive
    check against direct SQL surgery; the migration server-defaults to a valid
    shape)."""
    return EngineConfig.model_validate(workspace.engine_config)
