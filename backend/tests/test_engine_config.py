"""Unit tests for EngineConfig — the typed view over workspaces.engine_config JSONB."""
import pytest
from pydantic import ValidationError

from core.engine_config import EngineConfig, engine_config_for


def test_parse_valid_config():
    cfg = EngineConfig.model_validate({"backend": "ollama", "model": "gemma4:e4b"})
    assert cfg.backend == "ollama"
    assert cfg.model == "gemma4:e4b"


def test_missing_backend_raises():
    with pytest.raises(ValidationError):
        EngineConfig.model_validate({"model": "x"})


def test_missing_model_raises():
    with pytest.raises(ValidationError):
        EngineConfig.model_validate({"backend": "ollama"})


def test_unsupported_backend_raises():
    """Phase 4 ships with Ollama only; llama.cpp lands in a later spec."""
    with pytest.raises(ValidationError):
        EngineConfig.model_validate({"backend": "openai", "model": "gpt-4"})


def test_engine_config_for_workspace_row(db_session):
    """engine_config_for(workspace) reads the JSONB column and returns the model."""
    from db import models
    ws = models.Workspace(
        id="ws-cfg",
        slug="ws-cfg",
        display_name="x",
        system_prompt="",
        enabled_tools=[],
        is_builtin=False,
        engine_config={"backend": "ollama", "model": "qwen3.6:27b"},
    )
    db_session.add(ws)
    db_session.commit()

    cfg = engine_config_for(ws)
    assert cfg.backend == "ollama"
    assert cfg.model == "qwen3.6:27b"
