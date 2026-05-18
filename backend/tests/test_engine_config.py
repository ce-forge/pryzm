"""Unit tests for EngineConfig — the typed view over workspaces.engine_config JSONB."""
import pytest
from pydantic import ValidationError

from core.engine_config import EngineConfig, engine_config_for


def test_parse_valid_config():
    cfg = EngineConfig.model_validate({"backend": "llama_cpp"})
    assert cfg.backend == "llama_cpp"


def test_missing_backend_raises():
    with pytest.raises(ValidationError):
        EngineConfig.model_validate({})


def test_unsupported_backend_raises():
    """Only llama_cpp is accepted; any other string must fail validation."""
    with pytest.raises(ValidationError):
        EngineConfig.model_validate({"backend": "openai"})


def test_engine_config_for_workspace_row(db_session):
    """engine_config_for(workspace) reads the JSONB column and returns the model."""
    from db import models
    ws = models.Workspace(
        id="ws-cfg",
        slug="ws-cfg",
        display_name="x",
        system_prompt="",
        enabled_tools=[],
        engine_config={"backend": "llama_cpp"},
    )
    db_session.add(ws)
    db_session.commit()

    cfg = engine_config_for(ws)
    assert cfg.backend == "llama_cpp"
