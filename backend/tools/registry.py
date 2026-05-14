from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

AVAILABLE_TOOLS = {}
TOOL_DEFINITIONS = []

# Per-tool workspace allowlist. Maps tool name -> list of workspace names
# (e.g. "it_copilot", "personal") in which the tool is exposed to the LLM.
# Populated by the @tool decorator. The eventual UI-driven workspace tool
# config (see project_workspace_roadmap memory) will overlay this default.
TOOL_WORKSPACES: dict[str, list[str]] = {}


class ToolRegistrationError(Exception):
    """Raised when @tool registers a name that is already taken."""


@dataclass(frozen=True)
class ResolvedToolSet:
    """Per-request snapshot of which tools a workspace gets, plus their schemas.

    callables: dict mapping tool name -> function (for execution by the engine).
    definitions: list of OpenAI-style function schemas (sent to the LLM).
    per_tool_config: dict mapping tool name -> per-tool config (empty today; the
        seam for future per-workspace tool tuning — see [[project-workspace-roadmap]]).
    """
    callables: dict[str, Callable]
    definitions: list[dict]
    per_tool_config: dict[str, dict]


def build_tool_set(workspace) -> ResolvedToolSet:
    """Filter the global registry to just this workspace's enabled tools.

    Today: filters AVAILABLE_TOOLS + TOOL_DEFINITIONS by the names in
    workspace.enabled_tools. Future per-workspace tool config will land in a
    workspace.tool_config JSONB column; the per_tool_config field exposes it
    here (empty until then).
    """
    enabled = set(workspace.enabled_tools or [])
    callables = {n: AVAILABLE_TOOLS[n] for n in enabled if n in AVAILABLE_TOOLS}
    definitions = [d for d in TOOL_DEFINITIONS if d["function"]["name"] in enabled]
    per_tool_config = getattr(workspace, "tool_config", None) or {}
    return ResolvedToolSet(
        callables=callables,
        definitions=definitions,
        per_tool_config=per_tool_config,
    )


def tool(properties, required=None, workspaces=None):
    """A decorator that turns a Python function into an LLM-callable tool.

    workspaces: list of workspace names in which the tool is exposed. Defaults
    to ["it_copilot"] to preserve historical behavior — every existing tool was
    only available in the IT Copilot workspace. Pass a longer list to opt a
    tool into additional workspaces (e.g. rename_chat_session is allowed in
    "personal" too because users like that affordance everywhere).
    """
    if required is None:
        required = []
    if workspaces is None:
        workspaces = ["it_copilot"]

    def decorator(func):
        name = func.__name__
        if name in AVAILABLE_TOOLS:
            raise ToolRegistrationError(
                f"Tool name {name!r} already registered "
                f"(was: {getattr(AVAILABLE_TOOLS[name], '__qualname__', AVAILABLE_TOOLS[name])}). "
                "Each tool name must be unique across the registry."
            )
        AVAILABLE_TOOLS[name] = func
        TOOL_WORKSPACES[name] = list(workspaces)

        TOOL_DEFINITIONS.append({
            "type": "function",
            "function": {
                "name": name,
                "description": func.__doc__.strip() if func.__doc__ else "No description.",
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        })
        return func
    return decorator


