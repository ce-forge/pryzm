"""Unit tests for the tool-directive system: decorator kwarg + renderer."""
import pytest

from tools.registry import (
    AVAILABLE_TOOLS,
    TOOL_DEFINITIONS,
    TOOL_WORKSPACES,
    tool,
)


@pytest.fixture(autouse=True)
def _restore_registry():
    """Snapshot + restore the global registry around each test so registrations
    inside tests don't bleed across cases."""
    saved_tools = dict(AVAILABLE_TOOLS)
    saved_defs = list(TOOL_DEFINITIONS)
    saved_ws = dict(TOOL_WORKSPACES)
    yield
    AVAILABLE_TOOLS.clear()
    AVAILABLE_TOOLS.update(saved_tools)
    TOOL_DEFINITIONS.clear()
    TOOL_DEFINITIONS.extend(saved_defs)
    TOOL_WORKSPACES.clear()
    TOOL_WORKSPACES.update(saved_ws)


def test_decorator_stores_directive_on_function():
    """@tool(system_prompt_directive=...) stashes the string on the callable."""

    @tool(properties={}, required=[], system_prompt_directive="Call me when X.")
    def _probe_directive_stored() -> str:
        return "ok"

    assert _probe_directive_stored.system_prompt_directive == "Call me when X."


def test_decorator_default_directive_is_empty():
    """A tool that omits the kwarg has an empty directive attribute."""

    @tool(properties={}, required=[])
    def _probe_directive_default() -> str:
        return "ok"

    assert _probe_directive_default.system_prompt_directive == ""
