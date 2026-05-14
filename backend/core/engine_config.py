"""Typed view over workspaces.engine_config JSONB.

The schema lives in db.models.Workspace.engine_config as JSONB. This module
gives the rest of the codebase a typed handle on those values without each
caller re-parsing the dict.

Today only the ollama backend is supported. The future llama.cpp swap will
extend the `backend` Literal here — that's a one-line change at that point,
which is the whole reason we have this seam.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from db import models


class EngineConfig(BaseModel):
    """Inference backend choice + model name for a workspace.

    Future llama.cpp swap will add sampling/context params (n_ctx,
    n_gpu_layers, temperature, etc.) here. For now: backend + model is the
    minimum.
    """
    backend: Literal["ollama"]
    model: str


def engine_config_for(workspace: models.Workspace) -> EngineConfig:
    """Read the JSONB column on a Workspace row and return the typed model.

    Raises pydantic ValidationError if the stored JSON doesn't match the schema —
    that would mean someone wrote a malformed engine_config (defensive check
    against direct SQL surgery; the migration in Phase 1 server-defaults to a
    valid shape).
    """
    return EngineConfig.model_validate(workspace.engine_config)
