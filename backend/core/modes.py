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

    Unknown mode names are dropped. Empty requested_modes is a no-op (returns
    the originals untouched).
    """
    if not requested_modes:
        return tool_set, system_prompt, None

    active = [MODES[n] for n in requested_modes if n in MODES]
    if not active:
        return tool_set, system_prompt, None

    # Merge force_tools into the existing tool_set without duplicating.
    callables = dict(tool_set.callables)
    definitions = list(tool_set.definitions)
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


# web_search is mode #1. Force-include the tool; no directive (the tool's own
# system_prompt_directive already tells the LLM when to call it).
register_mode(Mode(name="web_search", force_tools=["web_search"]))
