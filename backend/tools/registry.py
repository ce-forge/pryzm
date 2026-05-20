from __future__ import annotations

import sys as _sys
from dataclasses import dataclass
from typing import Callable

AVAILABLE_TOOLS = {}
TOOL_DEFINITIONS = []

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


def render_tool_directives(tool_set: "ResolvedToolSet") -> str:
    """Produce the `== AVAILABLE TOOLS ==` block for the workspace prompt.

    Walks the enabled tools, groups by `__module__`, and emits:
      - one optional `[MODULE_DIRECTIVE]` line per module that defines one and has
        at least one enabled tool;
      - one `- <name>: <directive>` line per tool with a non-empty
        `system_prompt_directive`.

    Tools with neither a module rule nor a per-tool directive are omitted. If
    the resulting block has zero content lines, returns an empty string (caller
    treats empty as 'no section at all').

    Modules render in deterministic order (by module name) separated by blank
    lines. Within a module, per-tool bullets render in deterministic order
    (by tool name).
    """
    if not tool_set.callables:
        return ""

    # Group tools by __module__.
    by_module: dict[str, list[tuple[str, callable]]] = {}
    for name, fn in tool_set.callables.items():
        mod_name = getattr(fn, "__module__", "")
        by_module.setdefault(mod_name, []).append((name, fn))

    blocks: list[str] = []
    for mod_name in sorted(by_module.keys()):
        members = sorted(by_module[mod_name], key=lambda pair: pair[0])
        mod = _sys.modules.get(mod_name)
        module_directive = getattr(mod, "MODULE_DIRECTIVE", "") if mod is not None else ""

        lines: list[str] = []
        if module_directive:
            lines.append(f"[{module_directive}]")
        for tool_name, fn in members:
            directive = getattr(fn, "system_prompt_directive", "") or ""
            if directive:
                lines.append(f"- {tool_name}: {directive}")

        if lines:
            blocks.append("\n".join(lines))

    if not blocks:
        return ""

    body = "\n\n".join(blocks)
    return f"== AVAILABLE TOOLS ==\n\n{body}"


def tool(properties, required=None, system_prompt_directive=""):
    """A decorator that turns a Python function into an LLM-callable tool.

    Per-workspace gating happens via `Workspace.enabled_tools` (the JSONB
    column on the row) resolved by `services.workspaces.resolve_tools_for_workspace`.
    The registry knows which tools EXIST, not which workspaces may call them.

    system_prompt_directive: short text injected into the workspace's rendered
    system prompt under the `== AVAILABLE TOOLS ==` block. Describes WHEN/HOW
    to call the tool (NOT what it does — that's the JSON-schema description).
    Empty string = the tool gets no per-tool line in the rendered block (it
    still gets listed in {tool_names} as today).
    """
    if required is None:
        required = []

    def decorator(func):
        name = func.__name__
        if name in AVAILABLE_TOOLS:
            raise ToolRegistrationError(
                f"Tool name {name!r} already registered "
                f"(was: {getattr(AVAILABLE_TOOLS[name], '__qualname__', AVAILABLE_TOOLS[name])}). "
                "Each tool name must be unique across the registry."
            )
        AVAILABLE_TOOLS[name] = func
        func.system_prompt_directive = system_prompt_directive

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


