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


from tools.registry import ResolvedToolSet, render_tool_directives
from core.ai_engine import _inject_tool_directives
import sys
import types


def _make_module_with_directive(module_name: str, directive: str | None) -> types.ModuleType:
    """Build a throwaway module object with a MODULE_DIRECTIVE constant (or none).
    Registered in sys.modules so callables placed in it report __module__ correctly."""
    mod = types.ModuleType(module_name)
    if directive is not None:
        mod.MODULE_DIRECTIVE = directive
    sys.modules[module_name] = mod
    return mod


def _make_callable(name: str, module: types.ModuleType, directive: str = "") -> callable:
    def _fn():
        return None
    _fn.__name__ = name
    _fn.__module__ = module.__name__
    _fn.system_prompt_directive = directive
    return _fn


def test_render_empty_toolset_returns_empty_string():
    """No enabled tools = no rendered block at all (caller treats empty as 'no header')."""
    result = render_tool_directives(ResolvedToolSet(callables={}, definitions=[], per_tool_config={}))
    assert result == ""


def test_render_tool_with_no_directive_omitted():
    """A tool with empty directive and no MODULE_DIRECTIVE renders nothing."""
    mod = _make_module_with_directive("test_pkg.no_directive_mod", None)
    fn = _make_callable("solo_tool", mod, "")
    result = render_tool_directives(
        ResolvedToolSet(callables={"solo_tool": fn}, definitions=[], per_tool_config={})
    )
    assert result == ""


def test_render_per_tool_directive_no_module():
    """A tool with its own directive renders as a single bullet."""
    mod = _make_module_with_directive("test_pkg.per_tool_mod", None)
    fn = _make_callable("ping_tool", mod, "Use this for ICMP probes.")
    result = render_tool_directives(
        ResolvedToolSet(callables={"ping_tool": fn}, definitions=[], per_tool_config={})
    )
    assert result == (
        "== AVAILABLE TOOLS ==\n\n"
        "- ping_tool: Use this for ICMP probes."
    )


def test_render_module_directive_with_one_member():
    """MODULE_DIRECTIVE renders once above the module's tools, even if only one is enabled."""
    mod = _make_module_with_directive("test_pkg.network_mod", "Network tools only on public hosts.")
    fn = _make_callable("dns_lookup", mod, "")
    result = render_tool_directives(
        ResolvedToolSet(callables={"dns_lookup": fn}, definitions=[], per_tool_config={})
    )
    assert result == (
        "== AVAILABLE TOOLS ==\n\n"
        "[Network tools only on public hosts.]"
    )


def test_render_module_directive_plus_per_tool_bullets():
    """MODULE_DIRECTIVE above; per-tool directives below as bullets."""
    mod = _make_module_with_directive("test_pkg.net2", "Network rule.")
    a = _make_callable("dns_lookup", mod, "")
    b = _make_callable("check_port", mod, "Use after dns_lookup.")
    result = render_tool_directives(
        ResolvedToolSet(callables={"dns_lookup": a, "check_port": b}, definitions=[], per_tool_config={})
    )
    assert result == (
        "== AVAILABLE TOOLS ==\n\n"
        "[Network rule.]\n"
        "- check_port: Use after dns_lookup."
    )


def test_render_two_modules_separated_by_blank_line():
    """Modules render in deterministic order (by module name) separated by blank lines."""
    m_net = _make_module_with_directive("test_pkg.aaa_net", "Net rule.")
    m_sys = _make_module_with_directive("test_pkg.zzz_sys", None)
    a = _make_callable("dns_lookup", m_net, "")
    b = _make_callable("rename_chat_session", m_sys, "Invent a title if none given.")
    result = render_tool_directives(
        ResolvedToolSet(
            callables={"dns_lookup": a, "rename_chat_session": b},
            definitions=[],
            per_tool_config={},
        )
    )
    assert result == (
        "== AVAILABLE TOOLS ==\n\n"
        "[Net rule.]\n"
        "\n"
        "- rename_chat_session: Invent a title if none given."
    )


def test_render_module_import_error_does_not_raise():
    """If sys.modules has no entry for a tool's __module__, render proceeds without it."""
    fn = _make_callable("orphan_tool", types.ModuleType("test_pkg.gone"), "x")
    fn.__module__ = "test_pkg.this_was_unloaded"  # not in sys.modules
    # The tool has no module record AND no MODULE_DIRECTIVE — should still emit its bullet.
    result = render_tool_directives(
        ResolvedToolSet(callables={"orphan_tool": fn}, definitions=[], per_tool_config={})
    )
    assert "orphan_tool: x" in result


def test_placeholder_substitution_inline():
    """When {tool_directives} is present in the prompt, _inject_tool_directives lands the rendered block there."""
    mod = _make_module_with_directive("test_pkg.sub1", None)
    fn = _make_callable("x_tool", mod, "Use for X.")
    rendered = render_tool_directives(
        ResolvedToolSet(callables={"x_tool": fn}, definitions=[], per_tool_config={})
    )
    result = _inject_tool_directives("BEFORE\n\n{tool_directives}\n\nAFTER", rendered)
    assert result == f"BEFORE\n\n{rendered}\n\nAFTER"


def test_missing_placeholder_appends():
    """When {tool_directives} is absent from the prompt, _inject_tool_directives
    appends the rendered block after a blank-line separator. When the rendered
    block is empty, the prompt is returned unchanged."""
    mod = _make_module_with_directive("test_pkg.sub2", None)
    fn = _make_callable("y_tool", mod, "Use for Y.")
    rendered = render_tool_directives(
        ResolvedToolSet(callables={"y_tool": fn}, definitions=[], per_tool_config={})
    )

    out = _inject_tool_directives("PROMPT BODY", rendered)
    assert out == "PROMPT BODY\n\n" + rendered

    empty = _inject_tool_directives("PROMPT BODY", "")
    assert empty == "PROMPT BODY"


def test_inject_empty_rendered_mid_prompt_placeholder():
    """Empty rendered + mid-prompt placeholder should not leave a double blank line."""
    prompt = "SECTION_A_END\n\n{tool_directives}\n\nSECTION_B_START"
    result = _inject_tool_directives(prompt, "")
    assert result == "SECTION_A_END\n\nSECTION_B_START"
