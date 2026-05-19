"""Per-turn behavior modes.

A `Mode` is a small declarative override that the frontend can request for a
single turn via `InferenceRequest.modes`. It can:

  - force-include tools (add to the per-turn tool set even if the workspace
    hasn't enabled them)
  - append a directive to the system prompt for the turn only
  - hint a tier to the heuristic router (used by future code-mode, etc.)

`web_search` is the first mode and is registered alongside the tool itself.
Future neighbors (deep-research, strict-RAG, code-mode, brainstorm) drop in
by calling `register_mode(...)`.

Unknown mode names are silently ignored — keeps frontend/backend deploys
decoupled when the FE knows about a mode the BE hasn't shipped yet.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from tools.registry import AVAILABLE_TOOLS, TOOL_DEFINITIONS, ResolvedToolSet


@dataclass(frozen=True)
class Mode:
    name: str
    force_tools: list[str] = field(default_factory=list)
    # Tools that are HIDDEN from the LLM unless this mode is active for
    # the turn — even if the workspace has them in enabled_tools. Lets the
    # workspace flag express "this workspace is *allowed* to web-search"
    # while the per-turn toggle decides "but is it available right now."
    # The globe icon in the chat input is the user-facing surface for
    # web_search's gate.
    gates_tools: list[str] = field(default_factory=list)
    directive: str = ""
    tier_override: Optional[str] = None


MODES: dict[str, Mode] = {}


def register_mode(mode: Mode) -> None:
    """Add a Mode to the registry. Idempotent — re-registering with the same
    name overwrites the prior entry (matches the @tool decorator's behavior of
    'last-definition-wins' for hot reloads in dev, while raising in production
    would be too brittle for the modes use case)."""
    MODES[mode.name] = mode


def apply_modes(
    tool_set: ResolvedToolSet,
    system_prompt: str,
    requested_modes: list[str],
) -> tuple[ResolvedToolSet, str, Optional[str]]:
    """Apply the requested modes to a (tool_set, system_prompt) pair.

    Returns the (possibly transformed) tool_set, the (possibly augmented)
    system_prompt, and an optional tier hint for the router.

    Unknown mode names are dropped. Empty requested_modes is a no-op modulo
    the gating pass — tools registered as gated by any mode are removed if
    no mode that unlocks them is active.
    """
    active = [MODES[n] for n in requested_modes if n in MODES] if requested_modes else []

    # Gating pass — always runs, even for empty requested_modes. Any tool
    # listed in a mode's `gates_tools` is hidden from the LLM unless that
    # mode is active. Keeps web_search invisible whenever the globe
    # toggle is off, regardless of whether the workspace technically
    # has the tool enabled.
    all_gated: set[str] = set()
    for mode in MODES.values():
        all_gated.update(mode.gates_tools)
    unlocked: set[str] = set()
    for mode in active:
        unlocked.update(mode.gates_tools)
    hidden = all_gated - unlocked

    # Identity-preserving no-op when no modes are active AND no hidden
    # tool is actually present in the workspace's tool_set — there's
    # nothing to filter or augment, so return the original references.
    workspace_tool_names = set(tool_set.callables)
    if not active and not (hidden & workspace_tool_names):
        return tool_set, system_prompt, None

    callables = {n: c for n, c in tool_set.callables.items() if n not in hidden}
    definitions = [d for d in tool_set.definitions if d["function"]["name"] not in hidden]

    if not active:
        return (
            ResolvedToolSet(
                callables=callables,
                definitions=definitions,
                per_tool_config=tool_set.per_tool_config,
            ),
            system_prompt,
            None,
        )

    # Merge force_tools into the (gating-filtered) tool_set without duplicating.
    have = set(callables)
    for mode in active:
        for tname in mode.force_tools:
            if tname in have or tname not in AVAILABLE_TOOLS:
                continue
            callables[tname] = AVAILABLE_TOOLS[tname]
            defn = next((d for d in TOOL_DEFINITIONS if d["function"]["name"] == tname), None)
            if defn is not None:
                definitions.append(defn)
            have.add(tname)

    # Append directives in deterministic order.
    directives = [m.directive for m in active if m.directive]
    new_prompt = system_prompt
    if directives:
        new_prompt = system_prompt + "\n\n" + "\n".join(directives)

    # Tier hint: last-mode-wins if multiple modes request one. (No mode in v1
    # uses this; reserved for code-mode etc.)
    tier_hint: Optional[str] = None
    for m in active:
        if m.tier_override:
            tier_hint = m.tier_override

    new_tool_set = ResolvedToolSet(
        callables=callables,
        definitions=definitions,
        per_tool_config=tool_set.per_tool_config,
    )
    return new_tool_set, new_prompt, tier_hint


# web_search is mode #1.
#   force_tools: include the tool when the mode IS active (even if the
#     workspace hasn't enabled it).
#   gates_tools: hide the tool when the mode is NOT active (even if the
#     workspace HAS enabled it). The globe toggle is the only path the
#     LLM ever sees web_search through.
register_mode(Mode(
    name="web_search",
    force_tools=["web_search"],
    gates_tools=["web_search"],
))
