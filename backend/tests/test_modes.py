"""Unit tests for the per-turn modes registry (backend/core/modes.py).

A `Mode` is a small declarative bundle: which tools to force-include in the
turn's tool set, an optional directive string appended to the system prompt,
and an optional tier override for the router (unused by web_search v1).
`apply_modes(tool_set, system_prompt, requested_modes)` returns a transformed
(tool_set, system_prompt, tier_hint) tuple.
"""
from __future__ import annotations

import pytest

from core.modes import MODES, Mode, apply_modes, register_mode
from tools.registry import (
    AVAILABLE_TOOLS,
    TOOL_DEFINITIONS,
    ResolvedToolSet,
    tool,
)


@pytest.fixture(autouse=True)
def _restore_registries():
    """Snapshot + restore the tool registry and the modes registry around
    each test so registrations don't bleed across cases."""
    saved_tools = dict(AVAILABLE_TOOLS)
    saved_defs = list(TOOL_DEFINITIONS)
    saved_modes = dict(MODES)
    yield
    AVAILABLE_TOOLS.clear()
    AVAILABLE_TOOLS.update(saved_tools)
    TOOL_DEFINITIONS.clear()
    TOOL_DEFINITIONS.extend(saved_defs)
    MODES.clear()
    MODES.update(saved_modes)


def _make_tool_set(tool_names: list[str]) -> ResolvedToolSet:
    callables = {n: AVAILABLE_TOOLS[n] for n in tool_names if n in AVAILABLE_TOOLS}
    definitions = [d for d in TOOL_DEFINITIONS if d["function"]["name"] in tool_names]
    return ResolvedToolSet(callables=callables, definitions=definitions, per_tool_config={})


def test_register_and_lookup_mode():
    """register_mode adds a Mode to the MODES dict; lookup returns the same object."""
    m = Mode(name="testmode", force_tools=["x"], directive="hint", tier_override=None)
    register_mode(m)
    assert MODES["testmode"] is m


def test_apply_no_modes_is_no_op():
    """Empty modes list returns the tool_set and system_prompt unchanged."""
    @tool(properties={}, required=[])
    def _t() -> str:
        return ""
    ts = _make_tool_set(["_t"])
    out_ts, out_sp, tier = apply_modes(ts, "PROMPT", [])
    assert out_ts is ts
    assert out_sp == "PROMPT"
    assert tier is None


def test_apply_force_tools_injects_missing_tool():
    """A mode with force_tools=['_target'] adds it to the per-turn set even if
    it wasn't enabled on the workspace."""
    @tool(properties={}, required=[])
    def _enabled_tool() -> str:
        return ""

    @tool(properties={}, required=[])
    def _forced_tool() -> str:
        return ""

    register_mode(Mode(name="injects", force_tools=["_forced_tool"]))
    ts = _make_tool_set(["_enabled_tool"])  # workspace has only _enabled_tool

    out_ts, _, _ = apply_modes(ts, "PROMPT", ["injects"])
    assert "_enabled_tool" in out_ts.callables
    assert "_forced_tool" in out_ts.callables
    assert any(d["function"]["name"] == "_forced_tool" for d in out_ts.definitions)


def test_apply_force_tools_does_not_duplicate_already_enabled_tool():
    """If the workspace already has the force_tools target, no duplicate entry."""
    @tool(properties={}, required=[])
    def _shared_tool() -> str:
        return ""

    register_mode(Mode(name="dup", force_tools=["_shared_tool"]))
    ts = _make_tool_set(["_shared_tool"])

    out_ts, _, _ = apply_modes(ts, "PROMPT", ["dup"])
    assert list(out_ts.callables.keys()).count("_shared_tool") == 1
    assert sum(1 for d in out_ts.definitions if d["function"]["name"] == "_shared_tool") == 1


def test_apply_directive_is_appended_to_system_prompt():
    """A mode's directive is appended (with separator) to the system prompt."""
    register_mode(Mode(name="hints", directive="Be terse."))
    ts = _make_tool_set([])
    _, out_sp, _ = apply_modes(ts, "PROMPT", ["hints"])
    assert "PROMPT" in out_sp
    assert "Be terse." in out_sp


def test_apply_unknown_mode_is_silently_ignored():
    """An unknown mode name does not raise; tool_set and prompt are unchanged."""
    ts = _make_tool_set([])
    out_ts, out_sp, tier = apply_modes(ts, "PROMPT", ["this_does_not_exist"])
    assert list(out_ts.callables.keys()) == []
    assert out_sp == "PROMPT"
    assert tier is None


def test_apply_multiple_modes_compose():
    """Two modes both apply: tools merge, directives concatenate."""
    @tool(properties={}, required=[])
    def _t_a() -> str:
        return ""

    @tool(properties={}, required=[])
    def _t_b() -> str:
        return ""

    register_mode(Mode(name="ma", force_tools=["_t_a"], directive="A says hi."))
    register_mode(Mode(name="mb", force_tools=["_t_b"], directive="B says hi."))

    ts = _make_tool_set([])
    out_ts, out_sp, _ = apply_modes(ts, "PROMPT", ["ma", "mb"])
    assert "_t_a" in out_ts.callables
    assert "_t_b" in out_ts.callables
    assert "A says hi." in out_sp
    assert "B says hi." in out_sp


def test_apply_tier_override_is_returned():
    """A mode with tier_override returns that hint for the router."""
    register_mode(Mode(name="big", tier_override="LARGE"))
    ts = _make_tool_set([])
    _, _, tier = apply_modes(ts, "PROMPT", ["big"])
    assert tier == "LARGE"


def test_gated_tool_is_hidden_when_its_mode_is_not_active():
    """A tool listed in a mode's gates_tools is filtered out of the
    per-turn tool_set unless that mode is in requested_modes — even if
    the workspace has it enabled. This is how the globe toggle gates
    web_search end-to-end."""
    @tool(properties={}, required=[])
    def _gated_tool() -> str:
        return ""

    register_mode(Mode(name="gate", gates_tools=["_gated_tool"]))
    ts = _make_tool_set(["_gated_tool"])  # workspace HAS the tool enabled

    out_ts, _, _ = apply_modes(ts, "PROMPT", [])
    assert "_gated_tool" not in out_ts.callables
    assert not any(d["function"]["name"] == "_gated_tool" for d in out_ts.definitions)


def test_gated_tool_is_visible_when_its_mode_is_active():
    """The same tool is included when the gating mode is in requested_modes."""
    @tool(properties={}, required=[])
    def _gated_tool() -> str:
        return ""

    register_mode(Mode(name="gate", gates_tools=["_gated_tool"]))
    ts = _make_tool_set(["_gated_tool"])

    out_ts, _, _ = apply_modes(ts, "PROMPT", ["gate"])
    assert "_gated_tool" in out_ts.callables
    assert any(d["function"]["name"] == "_gated_tool" for d in out_ts.definitions)


def test_web_search_mode_is_registered_when_module_imports():
    """Importing core.modes (and indirectly tools.web) registers a 'web_search' mode
    whose only effect is force_tools=['web_search']."""
    import core.modes  # noqa: F401  (registration happens at import time)

    assert "web_search" in MODES
    m = MODES["web_search"]
    assert "web_search" in m.force_tools
