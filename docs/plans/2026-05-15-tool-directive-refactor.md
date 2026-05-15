# Tool-directive refactor — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move tool-specific behavior guidance out of workspace system prompts onto each tool, with `{tool_directives}` substituted into the workspace prompt at chat time.

**Architecture:** New optional `system_prompt_directive` kwarg on `@tool()` stores per-tool guidance as a function attribute. New optional `MODULE_DIRECTIVE` module constant carries shared guidance for tools in the same file. A renderer in `tools/registry.py` walks the enabled toolset, groups by module, and produces the rendered block. The block lands at the `{tool_directives}` placeholder in the workspace prompt (fallback: append). An Alembic migration force-resets the two builtin workspaces' DB-stored `system_prompt` to the new on-disk defaults.

**Tech Stack:** FastAPI (Python), SQLAlchemy, Alembic, pytest. No new dependencies.

**Spec:** `docs/specs/2026-05-15-tool-directive-refactor.md`

---

## File structure

**Modified:**
- `backend/tools/registry.py` — add `system_prompt_directive` kwarg to `@tool()`, add `render_tool_directives()` function
- `backend/tools/network.py` — add `MODULE_DIRECTIVE` constant, add directive on `check_port`
- `backend/tools/retrieval.py` — add directive on `search_knowledge_base`
- `backend/tools/system.py` — add directive on `rename_chat_session`
- `backend/core/ai_engine.py` — substitute `{tool_directives}` after the existing `{tool_names}` substitution at line 212
- `backend/core/prompts/it_copilot.txt` — remove tool-specific lines, add `{tool_directives}` placeholder
- `backend/core/prompts/personal.txt` — remove tool-specific lines, add `{tool_directives}` placeholder

**Created:**
- `backend/tests/test_tool_directive_render.py` — unit tests for the renderer
- `backend/tests/test_migration_force_reset_prompts.py` — migration test
- `backend/alembic/versions/c1f8b27a4d56_force_reset_builtin_prompts.py` — Alembic migration

(The Alembic revision string `c1f8b27a4d56` is a placeholder — the engineer regenerates with `alembic revision --autogenerate=false -m "force_reset_builtin_prompts"` if preferred. The downstream test reads the version from the file, so any valid 12-char hex works.)

---

## Task 1: Add `system_prompt_directive` kwarg to `@tool()`

**Files:**
- Modify: `backend/tools/registry.py`
- Test: `backend/tests/test_tool_directive_render.py` (new)

- [ ] **Step 1: Write the failing test for kwarg storage**

Create `backend/tests/test_tool_directive_render.py`:

```python
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
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `cd backend && ./venv/bin/pytest tests/test_tool_directive_render.py -v`
Expected: FAIL with `TypeError: tool() got an unexpected keyword argument 'system_prompt_directive'`

- [ ] **Step 3: Implement the kwarg in `tools/registry.py`**

Modify the signature and body of `tool()` in `backend/tools/registry.py`:

```python
def tool(properties, required=None, workspaces=None, system_prompt_directive=""):
    """A decorator that turns a Python function into an LLM-callable tool.

    workspaces: list of workspace names in which the tool is exposed. Defaults
    to ["it_copilot"] to preserve historical behavior — every existing tool was
    only available in the IT Copilot workspace. Pass a longer list to opt a
    tool into additional workspaces (e.g. rename_chat_session is allowed in
    "personal" too because users like that affordance everywhere).

    system_prompt_directive: short text injected into the workspace's rendered
    system prompt under the `== AVAILABLE TOOLS ==` block. Describes WHEN/HOW
    to call the tool (NOT what it does — that's the JSON-schema description).
    Empty string = the tool gets no per-tool line in the rendered block (it
    still gets listed in {tool_names} as today).
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
```

- [ ] **Step 4: Run the test and verify it passes**

Run: `cd backend && ./venv/bin/pytest tests/test_tool_directive_render.py -v`
Expected: 2 passed

- [ ] **Step 5: Run the existing tool-set tests to confirm no regression**

Run: `cd backend && ./venv/bin/pytest tests/test_tool_set.py -v`
Expected: all tests still pass

- [ ] **Step 6: Commit**

```bash
cd /home/orbital/projects/pryzm
git add backend/tools/registry.py backend/tests/test_tool_directive_render.py
git commit -m "feat(tools): @tool gains optional system_prompt_directive kwarg"
```

---

## Task 2: Implement `render_tool_directives()` in `tools/registry.py`

**Files:**
- Modify: `backend/tools/registry.py` (add new function below `build_tool_set`)
- Modify: `backend/tests/test_tool_directive_render.py` (extend with renderer tests)

- [ ] **Step 1: Write the failing tests for the renderer**

Append to `backend/tests/test_tool_directive_render.py`:

```python
from tools.registry import ResolvedToolSet, render_tool_directives
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
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `cd backend && ./venv/bin/pytest tests/test_tool_directive_render.py -v`
Expected: FAIL with `ImportError: cannot import name 'render_tool_directives' from 'tools.registry'`

- [ ] **Step 3: Implement `render_tool_directives` in `tools/registry.py`**

Append to `backend/tools/registry.py`:

```python
import sys as _sys


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
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `cd backend && ./venv/bin/pytest tests/test_tool_directive_render.py -v`
Expected: 8 passed (2 from Task 1 + 6 new)

- [ ] **Step 5: Commit**

```bash
cd /home/orbital/projects/pryzm
git add backend/tools/registry.py backend/tests/test_tool_directive_render.py
git commit -m "feat(tools): add render_tool_directives() with module-as-group grouping"
```

---

## Task 3: Wire `{tool_directives}` substitution into ai_engine

**Files:**
- Modify: `backend/core/ai_engine.py` (line 211–215)
- Modify: `backend/tests/test_tool_directive_render.py` (add substitution-flow test)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_tool_directive_render.py`:

```python
def test_placeholder_substitution_inline():
    """When {tool_directives} is present in the prompt, the rendered block lands there."""
    mod = _make_module_with_directive("test_pkg.sub1", None)
    fn = _make_callable("x_tool", mod, "Use for X.")
    rendered = render_tool_directives(
        ResolvedToolSet(callables={"x_tool": fn}, definitions=[], per_tool_config={})
    )
    prompt = "BEFORE\n\n{tool_directives}\n\nAFTER"
    assert "{tool_directives}" in prompt
    substituted = prompt.replace("{tool_directives}", rendered)
    assert substituted == f"BEFORE\n\n{rendered}\n\nAFTER"


def test_missing_placeholder_appends():
    """When {tool_directives} is missing, ai_engine's fallback appends the rendered block.
    (Behavior tested at the engine level in Task 3's wiring; this test pins the contract.)"""
    mod = _make_module_with_directive("test_pkg.sub2", None)
    fn = _make_callable("y_tool", mod, "Use for Y.")
    rendered = render_tool_directives(
        ResolvedToolSet(callables={"y_tool": fn}, definitions=[], per_tool_config={})
    )

    from core.ai_engine import _inject_tool_directives  # introduced in this task

    out = _inject_tool_directives("PROMPT BODY", rendered)
    assert out == "PROMPT BODY\n\n" + rendered

    inline = _inject_tool_directives("BEFORE {tool_directives} AFTER", rendered)
    assert inline == f"BEFORE {rendered} AFTER"

    empty = _inject_tool_directives("PROMPT BODY", "")
    assert empty == "PROMPT BODY"
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `cd backend && ./venv/bin/pytest tests/test_tool_directive_render.py::test_missing_placeholder_appends -v`
Expected: FAIL with `ImportError: cannot import name '_inject_tool_directives' from 'core.ai_engine'`

- [ ] **Step 3: Add `_inject_tool_directives` helper and wire substitution into stream_chat**

In `backend/core/ai_engine.py`, find the substitution at lines 211-212:

```python
    tool_names = ", ".join(workspace_tools.keys())
    system_content = system_prompt_raw.replace("{tool_names}", tool_names)
```

Replace those two lines with:

```python
    from tools.registry import render_tool_directives
    tool_names = ", ".join(workspace_tools.keys())
    system_content = system_prompt_raw.replace("{tool_names}", tool_names)
    rendered_directives = render_tool_directives(tool_set)
    system_content = _inject_tool_directives(system_content, rendered_directives)
```

Then, at the top of `core/ai_engine.py` after the other module-level functions (e.g. near `_image_document_refs`), add:

```python
def _inject_tool_directives(prompt: str, rendered: str) -> str:
    """Substitute {tool_directives} in the prompt with the rendered block.

    If the placeholder is missing, append the block after the prompt with a
    blank line separator — keeps hand-edited workspace prompts (that forgot the
    placeholder) functional. If the rendered block is empty (no tool has any
    directive AND no module has a MODULE_DIRECTIVE), the prompt is returned
    unchanged regardless of whether the placeholder is present.
    """
    if not rendered:
        # Strip a lonely placeholder so the prompt doesn't leak it to the LLM.
        return prompt.replace("{tool_directives}", "").rstrip()
    if "{tool_directives}" in prompt:
        return prompt.replace("{tool_directives}", rendered)
    return f"{prompt}\n\n{rendered}"
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `cd backend && ./venv/bin/pytest tests/test_tool_directive_render.py -v`
Expected: 10 passed

- [ ] **Step 5: Run the full ai_engine smoke test**

Run: `cd backend && ./venv/bin/pytest tests/ -k "ai_engine or stream_chat" -v` (existing tests in the area)
Expected: all pass (no regression — substitution is opt-in via the placeholder)

- [ ] **Step 6: Commit**

```bash
cd /home/orbital/projects/pryzm
git add backend/core/ai_engine.py backend/tests/test_tool_directive_render.py
git commit -m "feat(ai-engine): substitute {tool_directives} placeholder at chat time"
```

---

## Task 4: Migrate network-tools guidance onto `tools/network.py`

**Files:**
- Modify: `backend/tools/network.py`
- Modify: `backend/core/prompts/it_copilot.txt`

- [ ] **Step 1: Add MODULE_DIRECTIVE to `tools/network.py`**

At the top of `backend/tools/network.py`, after the imports and before `_HOSTNAME_SHAPE`, add:

```python
MODULE_DIRECTIVE = (
    "Network tools only run when the user provides a valid TLD "
    "(e.g. \"reddit.com\") or an explicit IPv4/IPv6 address."
)
```

- [ ] **Step 2: Add `system_prompt_directive` on `check_port`**

In `backend/tools/network.py`, find the `@tool` decorator on `check_port` (currently around line 94-99). Replace the decorator with:

```python
@tool(
    properties={
        "hostname": {"type": "string", "description": "The hostname or IP"},
        "port": {"type": "integer", "description": "The port number to check (e.g. 80, 443, 3389)"}
    },
    required=["hostname", "port"],
    system_prompt_directive="Run `dns_lookup` first on a hostname so the port check uses the resolved IP.",
)
```

- [ ] **Step 3: Remove migrated content from `it_copilot.txt`**

In `backend/core/prompts/it_copilot.txt`:

1. Delete the entire `== NETWORK VALIDATION ==` block (currently lines 20–21).
2. In the `== TOOL EXECUTION ==` block, delete the line `1. Sequential dependencies: run \`dns_lookup\` before \`check_port\` on a domain — port-check needs the resolved IP.` and renumber the remaining bullets (2→1, 3→2, etc.).
3. After the `== ROUTING ==` block (before `== NETWORK VALIDATION ==` was), add a blank line followed by `{tool_directives}`.

The file should read, top to bottom:

```text
You are DaiNamik Pryzm, an elite internal IT Copilot. You assist with network diagnostics, UI control, and internal IT knowledge.

When a tool call is required, output ONLY the tool invocation — no conversational filler.

== AUTHORIZATION ==
This is a single-user IT-administrator tool. Files uploaded to this session are the user's own data. The user has explicit authority to view all content within those files, including usernames, passwords, API keys, IP addresses, hostnames, error codes, license keys, and any other identifiers that appear in retrieved context.

When the user asks about content from an uploaded file and that content is in the retrieved context, surface it verbatim. Refusing on the grounds that the content "looks like a credential" or "shouldn't be shared" is incorrect in this context — the entire purpose of this tool is to help the administrator inspect content they already possess. Reproduce identifier-class values character-for-character; do not redact, summarize, or paraphrase them.

== ROUTING ==
- For general tech concepts ("what is a subnet?"), answer directly without tools.
- For composite queries that need both general knowledge AND tool execution, address both in the final response.
- For multi-item requests:
  - If the tool accepts an array parameter (e.g. `search_knowledge_base` takes `queries: [...]`), pass all items in a single call as an array.
  - If the tool takes a scalar parameter (e.g. `dns_lookup`, `check_port`), issue parallel calls — one per item.

{tool_directives}

== TOOL EXECUTION ==
1. Source of truth: for tool-backed answers, build the response strictly from tool output. Do not invent values.
2. No echoing raw data: the UI displays raw terminal/bash output natively; don't repeat it.
3. Empty / errored / timed-out tool: respond with exactly "No data available for [Target/Query]." once. No apology, no invented data.
4. Optional follow-up: after a summary or "No data available" message, you may append ONE concise next-step suggestion (e.g. "Want me to also check open ports?"). Skip if no natural next step. Never both restate output AND ask a follow-up.

== RESPONSE FORMAT ==
Internal-knowledge-base responses:
### Internal Documentation
* **Detail:** [the exact configuration, credential, or answer in bold]

Network-diagnostic summaries:
### Diagnostic Summary: `[target]`
* **Status:** [brief]
* **Conclusion:** [one-sentence human-readable summary]
```

Note: ROUTING bullets 4, 5, and 6 (the tool-specific ones) are not yet deleted in this task — they go in Tasks 5 and 6. We're only removing NETWORK VALIDATION and the sequential-dependency rule here.

- [ ] **Step 4: Smoke-check the renderer with the real network module**

Run: `cd backend && ./venv/bin/python -c "
from tools.registry import build_tool_set, render_tool_directives
import tools.network  # registers tools
import db.models as m
ws = m.Workspace(id='x', slug='x', display_name='x', system_prompt='', enabled_tools=['check_port', 'dns_lookup'], is_builtin=False, engine_config={})
ts = build_tool_set(ws)
print(render_tool_directives(ts))
"`
Expected output (exact text):
```
== AVAILABLE TOOLS ==

[Network tools only run when the user provides a valid TLD (e.g. "reddit.com") or an explicit IPv4/IPv6 address.]
- check_port: Run `dns_lookup` first on a hostname so the port check uses the resolved IP.
```

- [ ] **Step 5: Commit**

```bash
cd /home/orbital/projects/pryzm
git add backend/tools/network.py backend/core/prompts/it_copilot.txt
git commit -m "refactor(prompts): move network-tools guidance onto network module"
```

---

## Task 5: Migrate `search_knowledge_base` guidance

**Files:**
- Modify: `backend/tools/retrieval.py`
- Modify: `backend/core/prompts/it_copilot.txt`
- Modify: `backend/core/prompts/personal.txt`

- [ ] **Step 1: Add `system_prompt_directive` on `search_knowledge_base`**

In `backend/tools/retrieval.py`, replace the `@tool` decorator on `search_knowledge_base` with:

```python
@tool(
    properties={
        "queries": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "One or more distinct search terms, topics, or filenames. "
                "Pass ALL items the user asks about in a single call as an array — "
                "e.g. [\"rocket\", \"water\"] for a request like \"search for rocket and water\". "
                "Do NOT issue separate tool calls for each item; this tool batches multiple "
                "queries internally and labels the results by query."
            ),
        },
        "filenames": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "OPTIONAL. When the user references specific files by name (e.g., "
                "'what's in screenshot.png' or 'check runbook.pdf'), pass those "
                "filenames here. Retrieval will be scoped to those documents only, "
                "so unrelated content in the workspace doesn't compete in the results. "
                "Omit when the user is asking a general question across the knowledge base."
            ),
        },
    },
    required=["queries"],
    workspaces=["it_copilot", "personal"],
    system_prompt_directive=(
        "Call this for internal documentation or content from uploaded files; base your "
        "answer on the tool's output. If the user references a specific file — by name, "
        "by description, or by display request — pass it in the `filenames` argument so "
        "retrieval scopes to that file."
    ),
)
```

- [ ] **Step 2: Remove migrated lines from `it_copilot.txt`**

In `backend/core/prompts/it_copilot.txt`, remove the following two bullets from the `== ROUTING ==` block (they currently appear as bullets 4 and 5, after the multi-item bullet):

```
- For internal documentation or content from uploaded files, use `search_knowledge_base`. Base your answer on the tool's output.
- If the user references a previously attached file or image — by name ("what's in screenshot.png"), by description ("the file from earlier"), or by display request ("show me the image") — call `search_knowledge_base` before responding. When the user names a specific file, pass it in the `filenames` argument so retrieval scopes to that file.
```

- [ ] **Step 3: Remove migrated line from `personal.txt`**

In `backend/core/prompts/personal.txt`, in the `== TOOL USE ==` block, remove the line:

```
- For past uploads: call `search_knowledge_base` with the document's name or topic. Don't guess at content of files you can't see in this conversation.
```

- [ ] **Step 4: Smoke-check rendering**

Run: `cd backend && ./venv/bin/python -c "
from tools.registry import build_tool_set, render_tool_directives
import tools.retrieval
import db.models as m
ws = m.Workspace(id='x', slug='x', display_name='x', system_prompt='', enabled_tools=['search_knowledge_base'], is_builtin=False, engine_config={})
print(render_tool_directives(build_tool_set(ws)))
"`
Expected: rendered block includes `- search_knowledge_base: Call this for internal documentation…`

- [ ] **Step 5: Commit**

```bash
cd /home/orbital/projects/pryzm
git add backend/tools/retrieval.py backend/core/prompts/it_copilot.txt backend/core/prompts/personal.txt
git commit -m "refactor(prompts): move search_knowledge_base guidance onto the tool"
```

---

## Task 6: Migrate `rename_chat_session` guidance + add placeholder to `personal.txt`

**Files:**
- Modify: `backend/tools/system.py`
- Modify: `backend/core/prompts/it_copilot.txt`
- Modify: `backend/core/prompts/personal.txt`

- [ ] **Step 1: Add `system_prompt_directive` on `rename_chat_session`**

In `backend/tools/system.py`, replace the `@tool` decorator with:

```python
@tool(
    properties={
        "new_title": {
            "type": "string",
            "description": "The new title. If the user asks you to rename the chat but doesn't provide a specific name, you MUST invent a concise, context-aware title based on the current conversation yourself."
        }
    },
    required=["new_title"],
    workspaces=["it_copilot", "personal"],
    system_prompt_directive=(
        "If the user asks to rename the chat but doesn't supply a title, "
        "invent a concise, context-aware one rather than asking back."
    ),
)
```

- [ ] **Step 2: Remove the UI-control bullet from `it_copilot.txt`**

In `backend/core/prompts/it_copilot.txt`, remove the last bullet from the `== ROUTING ==` block:

```
- For UI control (e.g. renaming a chat), execute the matching tool (`rename_chat_session` etc.).
```

- [ ] **Step 3: Remove the rename line from `personal.txt`**

In `backend/core/prompts/personal.txt`, in the `== TOOL USE ==` block, remove the line:

```
- For UI control (e.g. renaming the chat), execute the matching tool (`rename_chat_session`). If the user doesn't give a title, invent a concise, context-aware one.
```

- [ ] **Step 4: Add `{tool_directives}` placeholder to `personal.txt`**

In `backend/core/prompts/personal.txt`, after the `== TOOL USE ==` section's remaining content (just the "array vs scalar" multi-item bullet and the in-message-attachment line), add a blank line followed by `{tool_directives}`.

The final `personal.txt` should read:

```text
You are a helpful, creative personal AI assistant. Answer the user's questions thoughtfully and conversationally.

Avoid em-dashes and en-dashes in your output — they're a common AI-text giveaway. Use regular punctuation.

== TOOL USE ==
Only call a tool if the user's request matches its purpose.

- For multi-item requests:
  - If the tool accepts an array parameter (e.g. `queries: [...]`), pass all items in a single call as an array.
  - If the tool takes a scalar parameter, issue parallel calls — one per item.
- For attached files in the current message: excerpts are injected above; read them directly, no tool needed.

{tool_directives}

== RESPONSE FORMAT ==
- When a tool's output already answers the request directly (a confirmation, a status, a "no results" message), don't restate it — the UI shows the result block above your response. Ask ONE concise follow-up suggesting a useful next step instead.
- When a tool's output needs interpretation (multi-line hits, raw data), provide a brief synthesis.
```

- [ ] **Step 5: Verify the final it_copilot.txt and personal.txt match the spec**

Run: `cd backend && grep -c "{tool_directives}" core/prompts/it_copilot.txt core/prompts/personal.txt`
Expected: each file shows count `1`.

Run: `cd backend && grep -F "rename_chat_session" core/prompts/it_copilot.txt core/prompts/personal.txt`
Expected: no output (the tool name no longer appears in either workspace prompt).

Run: `cd backend && grep -F "NETWORK VALIDATION" core/prompts/it_copilot.txt`
Expected: no output (section removed).

- [ ] **Step 6: Commit**

```bash
cd /home/orbital/projects/pryzm
git add backend/tools/system.py backend/core/prompts/it_copilot.txt backend/core/prompts/personal.txt
git commit -m "refactor(prompts): move rename_chat_session guidance + finish personal.txt migration"
```

---

## Task 7: Alembic migration force-resetting builtin workspace prompts

**Files:**
- Create: `backend/alembic/versions/c1f8b27a4d56_force_reset_builtin_prompts.py`
- Create: `backend/tests/test_migration_force_reset_prompts.py`

- [ ] **Step 1: Capture the OLD prompt text from the current DB (for the downgrade path)**

Run:

```bash
cd /home/orbital/projects/pryzm
PGPASSWORD=postgres psql -h localhost -U pryzm_admin -d pryzm_core -c "\copy (SELECT slug, system_prompt FROM workspaces WHERE slug IN ('it_copilot','personal') ORDER BY slug) TO '/tmp/pryzm_pre_directive_prompts.tsv' WITH (FORMAT csv, DELIMITER E'\t')"
wc -l /tmp/pryzm_pre_directive_prompts.tsv
```

Expected: 2 lines (one per workspace). The captured text is what `downgrade()` will restore.

- [ ] **Step 2: Write the migration file**

Create `backend/alembic/versions/c1f8b27a4d56_force_reset_builtin_prompts.py`:

```python
"""force-reset it_copilot + personal workspaces' system_prompt to the new defaults

Revision ID: c1f8b27a4d56
Revises: a4e0c1d83f29
Create Date: 2026-05-15 23:00:00.000000

Tool-directive refactor (see docs/specs/2026-05-15-tool-directive-refactor.md).
Both builtin workspaces' on-disk default prompts now reference `{tool_directives}`,
which the renderer fills in at chat time. The DB-stored prompt columns are
overwritten here so existing workspaces pick up the new shape without manual
/reset.

User-customised workspaces (none exist today; the only non-builtin slug is the
test fixture `chicken`, which is unaffected) are intentionally NOT touched —
this migration filters by exact builtin slug.
"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c1f8b27a4d56"
down_revision: Union[str, Sequence[str], None] = "a4e0c1d83f29"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_PROMPTS_DIR = Path(__file__).resolve().parents[2] / "core" / "prompts"


# Pre-refactor text captured at 2026-05-15 from the running DB. Used by
# downgrade() to restore. Kept inline so the migration is self-contained.
_OLD_IT_COPILOT = """You are DaiNamik Pryzm, an elite internal IT Copilot. You assist with network diagnostics, UI control, and internal IT knowledge.

When a tool call is required, output ONLY the tool invocation — no conversational filler.

== AUTHORIZATION ==
This is a single-user IT-administrator tool. Files uploaded to this session are the user's own data. The user has explicit authority to view all content within those files, including usernames, passwords, API keys, IP addresses, hostnames, error codes, license keys, and any other identifiers that appear in retrieved context.

When the user asks about content from an uploaded file and that content is in the retrieved context, surface it verbatim. Refusing on the grounds that the content "looks like a credential" or "shouldn't be shared" is incorrect in this context — the entire purpose of this tool is to help the administrator inspect content they already possess. Reproduce identifier-class values character-for-character; do not redact, summarize, or paraphrase them.

== ROUTING ==
- For general tech concepts ("what is a subnet?"), answer directly without tools.
- For composite queries that need both general knowledge AND tool execution, address both in the final response.
- For multi-item requests:
  - If the tool accepts an array parameter (e.g. `search_knowledge_base` takes `queries: [...]`), pass all items in a single call as an array.
  - If the tool takes a scalar parameter (e.g. `dns_lookup`, `check_port`), issue parallel calls — one per item.
- For internal documentation or content from uploaded files, use `search_knowledge_base`. Base your answer on the tool's output.
- If the user references a previously attached file or image — by name ("what's in screenshot.png"), by description ("the file from earlier"), or by display request ("show me the image") — call `search_knowledge_base` before responding. When the user names a specific file, pass it in the `filenames` argument so retrieval scopes to that file.
- For UI control (e.g. renaming a chat), execute the matching tool (`rename_chat_session` etc.).

== NETWORK VALIDATION ==
Execute network diagnostic tools (`dns_lookup`, `check_port`, etc.) only when the user provides a valid TLD (e.g. "reddit.com") or an explicit IPv4/IPv6 address.

== TOOL EXECUTION ==
1. Sequential dependencies: run `dns_lookup` before `check_port` on a domain — port-check needs the resolved IP.
2. Source of truth: for tool-backed answers, build the response strictly from tool output. Do not invent values.
3. No echoing raw data: the UI displays raw terminal/bash output natively; don't repeat it.
4. Empty / errored / timed-out tool: respond with exactly "No data available for [Target/Query]." once. No apology, no invented data.
5. Optional follow-up: after a summary or "No data available" message, you may append ONE concise next-step suggestion (e.g. "Want me to also check open ports?"). Skip if no natural next step. Never both restate output AND ask a follow-up.

== RESPONSE FORMAT ==
Internal-knowledge-base responses:
### Internal Documentation
* **Detail:** [the exact configuration, credential, or answer in bold]

Network-diagnostic summaries:
### Diagnostic Summary: `[target]`
* **Status:** [brief]
* **Conclusion:** [one-sentence human-readable summary]"""


_OLD_PERSONAL = """You are a helpful, creative personal AI assistant. Answer the user's questions thoughtfully and conversationally.

Avoid em-dashes and en-dashes in your output — they're a common AI-text giveaway. Use regular punctuation.

== TOOL USE ==
Only call a tool if the user's request matches its purpose.

- For multi-item requests:
  - If the tool accepts an array parameter (e.g. `queries: [...]`), pass all items in a single call as an array.
  - If the tool takes a scalar parameter, issue parallel calls — one per item.
- For UI control (e.g. renaming the chat), execute the matching tool (`rename_chat_session`). If the user doesn't give a title, invent a concise, context-aware one.
- For attached files in the current message: excerpts are injected above; read them directly, no tool needed.
- For past uploads: call `search_knowledge_base` with the document's name or topic. Don't guess at content of files you can't see in this conversation.

== RESPONSE FORMAT ==
- When a tool's output already answers the request directly (a confirmation, a status, a "no results" message), don't restate it — the UI shows the result block above your response. Ask ONE concise follow-up suggesting a useful next step instead.
- When a tool's output needs interpretation (multi-line hits, raw data), provide a brief synthesis."""


def _read_new(slug: str) -> str:
    return (_PROMPTS_DIR / f"{slug}.txt").read_text().strip()


def upgrade() -> None:
    conn = op.get_bind()
    for slug in ("it_copilot", "personal"):
        new_text = _read_new(slug)
        conn.execute(
            sa.text("UPDATE workspaces SET system_prompt = :p WHERE slug = :s"),
            {"p": new_text, "s": slug},
        )


def downgrade() -> None:
    conn = op.get_bind()
    for slug, old_text in (("it_copilot", _OLD_IT_COPILOT), ("personal", _OLD_PERSONAL)):
        conn.execute(
            sa.text("UPDATE workspaces SET system_prompt = :p WHERE slug = :s"),
            {"p": old_text, "s": slug},
        )
```

- [ ] **Step 3: Write the migration test**

Create `backend/tests/test_migration_force_reset_prompts.py`:

```python
"""Verifies migration c1f8b27a4d56: force-reset builtin workspaces' system_prompt.

Upgrade overwrites it_copilot + personal rows with the new on-disk defaults
(which contain {tool_directives}). Downgrade restores the captured prior text.
Non-builtin workspaces and rows with other slugs are unaffected.
"""
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool


def test_upgrade_overwrites_builtin_prompts(db_at_revision, alembic_cfg):
    """At the parent revision, the two builtins have their pre-refactor text;
    after the upgrade, both prompts contain {tool_directives}."""
    engine = db_at_revision("a4e0c1d83f29")
    with engine.begin() as conn:
        # Seed the two builtins with the pre-refactor text. (The dev DB had them;
        # the test DB starts empty and we seed deterministically here.)
        for slug in ("it_copilot", "personal"):
            conn.execute(text(
                "INSERT INTO workspaces (id, slug, display_name, system_prompt, "
                "enabled_tools, engine_config, is_builtin) "
                "VALUES (:id, :slug, :slug, 'OLD TEXT', '[]'::jsonb, '{}'::jsonb, true)"
            ), {"id": f"ws-{slug}", "slug": slug})
    engine.dispose()

    command.upgrade(alembic_cfg, "c1f8b27a4d56")

    fresh = create_engine(alembic_cfg.get_main_option("sqlalchemy.url"), poolclass=NullPool)
    with fresh.connect() as conn:
        rows = conn.execute(text(
            "SELECT slug, system_prompt FROM workspaces WHERE slug IN ('it_copilot','personal') ORDER BY slug"
        )).fetchall()
    fresh.dispose()

    assert len(rows) == 2
    for slug, prompt in rows:
        assert "{tool_directives}" in prompt, f"{slug} missing placeholder after upgrade"
        assert "OLD TEXT" not in prompt


def test_upgrade_leaves_non_builtin_untouched(db_at_revision, alembic_cfg):
    """A workspace with a slug NOT in ('it_copilot','personal') keeps its prompt."""
    engine = db_at_revision("a4e0c1d83f29")
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO workspaces (id, slug, display_name, system_prompt, "
            "enabled_tools, engine_config, is_builtin) "
            "VALUES ('ws-custom', 'my_custom_ws', 'Custom', 'KEEP ME', '[]'::jsonb, '{}'::jsonb, false)"
        ))
    engine.dispose()

    command.upgrade(alembic_cfg, "c1f8b27a4d56")

    fresh = create_engine(alembic_cfg.get_main_option("sqlalchemy.url"), poolclass=NullPool)
    with fresh.connect() as conn:
        prompt = conn.execute(text(
            "SELECT system_prompt FROM workspaces WHERE slug = 'my_custom_ws'"
        )).scalar()
    fresh.dispose()

    assert prompt == "KEEP ME"


def test_downgrade_restores_pre_refactor_text(db_at_revision, alembic_cfg):
    """Downgrade puts back the captured pre-refactor text."""
    engine = db_at_revision("a4e0c1d83f29")
    with engine.begin() as conn:
        for slug in ("it_copilot", "personal"):
            conn.execute(text(
                "INSERT INTO workspaces (id, slug, display_name, system_prompt, "
                "enabled_tools, engine_config, is_builtin) "
                "VALUES (:id, :slug, :slug, 'OLD TEXT', '[]'::jsonb, '{}'::jsonb, true)"
            ), {"id": f"ws-{slug}", "slug": slug})
    engine.dispose()

    command.upgrade(alembic_cfg, "c1f8b27a4d56")
    command.downgrade(alembic_cfg, "a4e0c1d83f29")

    fresh = create_engine(alembic_cfg.get_main_option("sqlalchemy.url"), poolclass=NullPool)
    with fresh.connect() as conn:
        rows = conn.execute(text(
            "SELECT slug, system_prompt FROM workspaces WHERE slug IN ('it_copilot','personal') ORDER BY slug"
        )).fetchall()
    fresh.dispose()

    by_slug = {slug: prompt for slug, prompt in rows}
    assert "{tool_directives}" not in by_slug["it_copilot"]
    assert "{tool_directives}" not in by_slug["personal"]
    assert "NETWORK VALIDATION" in by_slug["it_copilot"]
    assert "rename_chat_session" in by_slug["personal"]
```

- [ ] **Step 4: Run the migration test**

Run: `cd backend && ./venv/bin/pytest tests/test_migration_force_reset_prompts.py -v`
Expected: 3 passed

- [ ] **Step 5: Apply the migration to the dev DB**

Run: `cd backend && ./venv/bin/alembic upgrade head`
Expected: revision `c1f8b27a4d56` applied; no errors.

- [ ] **Step 6: Verify the dev DB row matches the on-disk default**

Run:
```bash
PGPASSWORD=postgres psql -h localhost -U pryzm_admin -d pryzm_core -c "SELECT slug, length(system_prompt) FROM workspaces WHERE slug IN ('it_copilot','personal') ORDER BY slug;"
diff <(PGPASSWORD=postgres psql -h localhost -U pryzm_admin -d pryzm_core -tA -c "SELECT system_prompt FROM workspaces WHERE slug = 'it_copilot';") <(cat /home/orbital/projects/pryzm/backend/core/prompts/it_copilot.txt)
```
Expected: lengths are non-zero, `diff` shows no differences (or only trailing-newline noise).

- [ ] **Step 7: Commit**

```bash
cd /home/orbital/projects/pryzm
git add backend/alembic/versions/c1f8b27a4d56_force_reset_builtin_prompts.py backend/tests/test_migration_force_reset_prompts.py
git commit -m "feat(migrate): force-reset builtin workspace prompts for tool-directive refactor"
```

---

## Task 8: End-to-end autotest probes

**Files:**
- Modify: `/tmp/pryzm_autotest.py` (the local probe helper — not in repo, per `reference_debug_tools.md` memory)

Goal: verify that the four behavioral expectations in the spec still fire after the refactor.

- [ ] **Step 1: Ensure backend + frontend are running**

If not already up, start them per `reference_stack_commands.md`:
```bash
cd /home/orbital/projects/pryzm/backend && uvicorn main:app --host 0.0.0.0 --reload --reload-delay 2 &
```

- [ ] **Step 2: Create or refresh the autotest helper**

Write `/tmp/pryzm_autotest.py` with the following contents (if a newer version already exists from a prior session, prefer that; otherwise use this minimal version):

```python
"""Minimal end-to-end probe for /analyze. Sends a prompt, streams the SSE, and
verifies that one or more expected tools were called (by parsing the
`> **Tool:** \`name\`` markdown markers the engine emits in chunks). Exits
0 on match, 1 on miss."""
import argparse
import json
import os
import re
import sys
import urllib.request


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--workspace", required=True)
    p.add_argument("--prompt", required=True)
    p.add_argument("--session", default=None,
                   help="Existing session id; omit to create a new chat")
    p.add_argument("--expect-tool", default=None,
                   help="Single tool name that must appear in the response")
    p.add_argument("--expect-tool-any", default=None,
                   help="Comma-separated tool names; any one passing counts")
    p.add_argument("--expect-arg", default=None,
                   help="Substring that must appear in the tool-args text")
    p.add_argument("--base", default="http://127.0.0.1:8000")
    args = p.parse_args()

    token = os.environ.get("PRYZM_API_TOKEN") or _read_env_token()
    body = json.dumps({
        "prompt": args.prompt,
        "session_id": args.session,
        "attachments": [],
        "skip_db_save": False,
    }).encode()

    req = urllib.request.Request(
        f"{args.base}/analyze?workspace={args.workspace}",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    response_text = ""
    with urllib.request.urlopen(req, timeout=120) as resp:
        for raw in resp:
            line = raw.decode().strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            chunk = obj.get("chunk") or ""
            response_text += chunk

    tool_calls = re.findall(r"> \*\*Tool:\*\* `([^`]+)`", response_text)
    args_block = response_text

    if args.expect_tool:
        if args.expect_tool not in tool_calls:
            print(f"FAIL: expected tool {args.expect_tool!r}, saw {tool_calls}", file=sys.stderr)
            return 1
    if args.expect_tool_any:
        wanted = set(args.expect_tool_any.split(","))
        if not (set(tool_calls) & wanted):
            print(f"FAIL: expected any of {wanted}, saw {tool_calls}", file=sys.stderr)
            return 1
    if args.expect_arg:
        if args.expect_arg not in args_block:
            print(f"FAIL: expected arg substring {args.expect_arg!r} not found in response", file=sys.stderr)
            return 1

    print(f"OK: tool_calls={tool_calls}")
    return 0


def _read_env_token() -> str:
    path = "/home/orbital/projects/pryzm/.env"
    with open(path) as f:
        for line in f:
            if line.startswith("PRYZM_API_TOKEN="):
                return line.split("=", 1)[1].strip()
    raise SystemExit("PRYZM_API_TOKEN not set in env or .env")


if __name__ == "__main__":
    sys.exit(main())
```

Make executable: `chmod +x /tmp/pryzm_autotest.py`

- [ ] **Step 3: Run the four probes**

Probe 1 — it_copilot network workflow still fires:
```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/python /tmp/pryzm_autotest.py --workspace it_copilot \
    --prompt "Check if reddit.com is up" \
    --expect-tool-any "dns_lookup,check_port,execute_ping"
```

Probe 2 — it_copilot filename-scoped retrieval. Requires a session that has an uploaded file; find one:
```bash
PGPASSWORD=postgres psql -h localhost -U pryzm_admin -d pryzm_core -tA -c "SELECT s.id, d.filename FROM sessions s JOIN documents d ON d.session_id = s.id WHERE d.storage_path IS NOT NULL LIMIT 1"
```
Take the returned `<session>` and `<filename>`, then:
```bash
./venv/bin/python /tmp/pryzm_autotest.py --workspace it_copilot \
    --session <session> \
    --prompt "Show me <filename>" \
    --expect-tool search_knowledge_base \
    --expect-arg "filenames"
```

Probe 3 — personal rename without title:
```bash
./venv/bin/python /tmp/pryzm_autotest.py --workspace personal \
    --prompt "Rename this chat to project-alpha" \
    --expect-tool rename_chat_session \
    --expect-arg "project-alpha"
```

Probe 4 — personal past-upload retrieval. Use the same `<session>` from probe 2:
```bash
./venv/bin/python /tmp/pryzm_autotest.py --workspace personal \
    --session <session> \
    --prompt "What was in that file I uploaded earlier?" \
    --expect-tool search_knowledge_base
```

Expected: all four return exit 0 and print `OK: tool_calls=[...]`.

- [ ] **Step 4: If any probe fails, diagnose and fix the relevant directive wording**

The most likely failure modes:
- **Probe 1 fails to call a network tool.** The model didn't pick up that reddit.com is a valid TLD trigger. Check the rendered prompt: `./venv/bin/python -c "import tools.network; from tools.registry import build_tool_set, render_tool_directives; ..."` and confirm the MODULE_DIRECTIVE wording matches the old NETWORK VALIDATION wording.
- **Probe 2 calls search_knowledge_base without `filenames`.** Tighten the `search_knowledge_base` directive: add a more explicit "when the user names a file, use filenames" cue.
- **Probe 3 asks back for a title instead of inventing one.** Tighten the `rename_chat_session` directive.
- **Probe 4 doesn't fire.** Same as 2 but for the conversational form.

Fix in the tool's `system_prompt_directive`, re-run the probe, commit if behavior is back.

- [ ] **Step 5: Commit any fix-up directive changes (if Step 4 was needed)**

```bash
cd /home/orbital/projects/pryzm
git add backend/tools/<changed>.py
git commit -m "tune(tools): tighten <tool> directive after autotest probe"
```

- [ ] **Step 6: Final verification — run the whole test suite**

Run: `cd backend && ./venv/bin/pytest tests/ -x --ignore=tests/e2e --ignore=tests/perf -q`
Expected: no failures introduced by the refactor. (The e2e + perf folders are skipped because they require additional setup not in scope here.)

---

## Done state

- Two builtin workspaces store prompts that contain `{tool_directives}` and no tool-specific text.
- The `@tool()` decorator supports `system_prompt_directive=`.
- `tools/network.py` has `MODULE_DIRECTIVE`; `check_port`, `search_knowledge_base`, and `rename_chat_session` each carry a directive.
- The renderer assembles the `== AVAILABLE TOOLS ==` block at chat time.
- Unit, migration, and end-to-end probes all pass.
