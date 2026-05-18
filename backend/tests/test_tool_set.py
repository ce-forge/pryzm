"""Unit tests for build_tool_set + duplicate-name guard."""
import pytest

from tools.registry import build_tool_set, ResolvedToolSet, AVAILABLE_TOOLS, ToolRegistrationError


def _make_workspace(enabled_tools: list[str]):
    """Helper: returns an object with the .enabled_tools attribute the resolver expects.
    Doesn't need to be a real ORM row — duck-typed."""
    from db import models
    return models.Workspace(
        id="ws-test",
        slug="ws-test",
        display_name="x",
        system_prompt="",
        enabled_tools=enabled_tools,
        engine_config={"backend": "ollama", "model": "gemma4:e4b"},
    )


def test_resolved_tool_set_shape():
    """ResolvedToolSet exposes callables, definitions, per_tool_config."""
    ws = _make_workspace([])
    result = build_tool_set(ws)
    assert isinstance(result, ResolvedToolSet)
    assert isinstance(result.callables, dict)
    assert isinstance(result.definitions, list)
    assert isinstance(result.per_tool_config, dict)


def test_tool_set_filters_by_enabled_tools():
    """Only tools listed in workspace.enabled_tools appear in the resolved set."""
    # Use a known-real tool — search_knowledge_base is enabled for both builtins.
    ws = _make_workspace(["search_knowledge_base"])
    result = build_tool_set(ws)
    assert "search_knowledge_base" in result.callables
    # Should NOT include other registered tools.
    assert "check_port" not in result.callables  # disabled for this workspace


def test_tool_set_empty_when_no_enabled_tools():
    """A workspace with no enabled tools gets an empty resolved set."""
    ws = _make_workspace([])
    result = build_tool_set(ws)
    assert result.callables == {}
    assert result.definitions == []


def test_per_tool_config_defaults_to_empty():
    """workspace.tool_config doesn't exist as a column yet; per_tool_config is empty."""
    ws = _make_workspace(["search_knowledge_base"])
    result = build_tool_set(ws)
    assert result.per_tool_config == {}


def test_duplicate_tool_name_raises():
    """Two @tool decorators with the same name should raise ToolRegistrationError."""
    from tools.registry import tool

    # Use a unique name that won't collide with existing tools across test runs.
    unique = "phase4_test_unique_xyz"

    @tool(
        properties={},
        required=[],
    )
    def phase4_test_unique_xyz():
        """Test tool for duplicate-name guard."""
        pass

    try:
        with pytest.raises(ToolRegistrationError):
            @tool(
                properties={},
                required=[],
            )
            def phase4_test_unique_xyz():  # noqa: F811
                """Duplicate — should raise."""
                pass
    finally:
        # Cleanup: remove from the global registry so future test runs aren't polluted.
        AVAILABLE_TOOLS.pop(unique, None)
        # Also remove from TOOL_DEFINITIONS to keep the registry clean.
        from tools.registry import TOOL_DEFINITIONS
        to_remove = [
            d for d in TOOL_DEFINITIONS
            if d.get("function", {}).get("name") == unique
        ]
        for item in to_remove:
            TOOL_DEFINITIONS.remove(item)
