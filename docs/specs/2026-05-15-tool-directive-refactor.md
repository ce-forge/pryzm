# Tool-directive refactor — design spec

**Status:** Brainstorm complete, awaiting implementation plan.
**Filed:** 2026-05-15
**Tracks:** task #50 (first half — SearxNG is a separate spec)
**Related memory:** `feedback_tool_guidance_lives_on_tools.md`

## Problem

The workspace `system_prompt` (stored in `workspaces.system_prompt`, defaulted from `core/prompts/{slug}.txt`) currently mixes two kinds of content:

1. **Workspace-level concerns** — persona, output formatting, authorization policy, generic tool-use principles.
2. **Tool-specific behavior guidance** — "when to call `search_knowledge_base`", "network tools require a valid TLD", "if the user doesn't name the chat, invent a title".

Mixing them creates three concrete problems already observed:

- **Duplication across workspaces.** `personal.txt` and `it_copilot.txt` both carry the same `search_knowledge_base` and `rename_chat_session` rules, slightly worded differently. Drift is inevitable as they're edited independently.
- **Tokens wasted on workspaces that don't enable the tool.** A workspace that doesn't enable network tools still ships the network rule to the LLM.
- **Coupling.** The workspace prompt has to know which tools exist and how they behave. Adding a tool means editing every workspace's prompt that should describe it.

This was flagged in-session on 2026-05-15 when an image-display directive added to `it_copilot.txt` to fix a refusal was correctly called out as belonging on the tool itself.

## Goal

Tool-specific behavior guidance lives next to the tool that owns it. The workspace prompt stays tool-agnostic. When a workspace's enabled toolset changes, the rendered system message the LLM sees updates automatically — no prompt edit required.

## Scope

**In scope:**
- New `system_prompt_directive` kwarg on the `@tool()` decorator.
- New module-level `MODULE_DIRECTIVE` constant convention for shared guidance across tools in the same file.
- New `{tool_directives}` placeholder substitution in `core/ai_engine.py`.
- Migrate tool-specific lines out of both `core/prompts/it_copilot.txt` and `core/prompts/personal.txt` onto the appropriate tools.
- Alembic migration that force-resets the `it_copilot` and `personal` workspaces' `system_prompt` DB column to the new on-disk defaults.
- Unit tests for the renderer, a migration test, autotest probes for both workspaces.

**Out of scope:**
- SearxNG container, `tools/web.py`, web-search tool — separate spec.
- Per-workspace directive overrides — deferred to the workspace-roadmap's `tool_config` JSONB column.
- Migrating `search_knowledge_base`'s `queries` / `filenames` parameter descriptions out of the JSON schema — parameter-scoped guidance stays where it is.
- Settings-UI "rendered prompt preview" — flagged as a half-day follow-up, not blocking.

## Architecture

Three new surface elements, all in the existing tools layer. No DB schema change. No new files except the new test file.

### 1. `system_prompt_directive` kwarg on `@tool()`

Optional string, defaults to `""`. A tool fills this when it has a per-tool quirk worth telling the LLM about: when to reach for it, what the UI does with its output, refusal-prevention specific to its outputs.

```python
@tool(
    properties={...},
    required=[...],
    system_prompt_directive="When the user references a specific file by name or display request, pass it in the `filenames` argument so retrieval scopes to that file.",
)
def search_knowledge_base(...): ...
```

Discipline: directives describe **WHEN/HOW**, not WHAT. The tool's docstring (which becomes the JSON-schema `description` the LLM sees per-call) already covers WHAT. Directives should be **descriptive, not commanding** ("Avoid responses like X" beats "NEVER X"). Cap at ~3 lines per tool; longer is a smell that the tool is doing too much.

### 2. `MODULE_DIRECTIVE` module-level constant

Optional. When present at the top of a tool module (e.g. `tools/network.py`), the renderer emits it once above the module's tools — but only if at least one of that module's tools is enabled in the active workspace. The file IS the group.

```python
# tools/network.py
MODULE_DIRECTIVE = "Network tools only run when the user provides a valid TLD (e.g. \"reddit.com\") or an explicit IPv4/IPv6 address."

@tool(...)
def execute_ping(...): ...
```

Rationale: the file layout already groups tools de facto (`network.py`, `retrieval.py`, `system.py`). Making the group explicit costs one optional module constant and no new decorator argument. New module → drop in the constant; the renderer picks it up via `getattr(module, "MODULE_DIRECTIVE", "")` on the next request.

Trade-off vs an explicit `directive_group=` kwarg: cannot group two tools that live in different files. In this codebase that case is currently hypothetical. If it ever stops being hypothetical, the kwarg can be added without removing the module convention.

### 3. `{tool_directives}` placeholder

The workspace's `system_prompt` opts into where the rendered tools section lands by including `{tool_directives}`. This matches the existing `{tool_names}` substitution pattern at `core/ai_engine.py:212`.

**Fallback:** if the placeholder is missing, the renderer appends the block after the existing prompt content with one blank line separator. A `DEBUG` log entry surfaces the fallback so it's visible in dev.

## Render flow

In `ai_engine.stream_chat`, after the existing `{tool_names}` substitution:

```
workspace.system_prompt (loaded from DB)
         │
         ▼
   substitute {tool_names}             ← existing
         │
         ▼
   substitute {tool_directives}        ← new
         │
         ▼
   final system message → LLM
```

The `{tool_directives}` substitution:

1. Walks each enabled tool from `tool_set.callables`.
2. Groups by `tool.__module__`.
3. For each module that has a `MODULE_DIRECTIVE` AND at least one enabled tool: emits the module directive once.
4. For each enabled tool in that module: if it has a non-empty `system_prompt_directive`, emit `- <tool_name>: <directive>`.
5. Tools with neither a module directive nor a per-tool directive are omitted (no bare bullet).
6. If the resulting block is empty (no enabled tool has any directive), no section header is emitted at all.

Rendered example for `it_copilot` with all current tools enabled:

```
== AVAILABLE TOOLS ==

[Network tools only run when the user provides a valid TLD (e.g. "reddit.com") or an explicit IPv4/IPv6 address.]
- check_port: Run dns_lookup first on a hostname so the port check uses the resolved IP.

- search_knowledge_base: When the user references a specific file by name or display request, pass it in the `filenames` argument so retrieval scopes to that file.

- rename_chat_session: If the user asks to rename the chat but doesn't supply a title, invent a concise, context-aware one rather than asking back.
```

Section header `== AVAILABLE TOOLS ==` mirrors the existing `== AUTHORIZATION ==`, `== ROUTING ==` shape in the workspace prompts.

## Content migration

Every tool-specific line moves out of the workspace prompts onto the appropriate tool. Wording stays as close to existing as possible — this is a relocation, not a rewrite, so the LLM's behavior doesn't shift.

### `tools/network.py`

- **`MODULE_DIRECTIVE`** (new):
  > Network tools only run when the user provides a valid TLD (e.g. "reddit.com") or an explicit IPv4/IPv6 address.
- **`check_port.system_prompt_directive`** (new):
  > Run `dns_lookup` first on a hostname so the port check uses the resolved IP.
- Other network tools: no per-tool directive — the module rule plus their JSON-schema `description` carries them.

### `tools/retrieval.py`

- **`search_knowledge_base.system_prompt_directive`** (new):
  > Call this for internal documentation or content from uploaded files; base your answer on the tool's output. If the user references a specific file — by name, by description, or by display request — pass it in the `filenames` argument so retrieval scopes to that file.

### `tools/system.py`

- **`rename_chat_session.system_prompt_directive`** (new):
  > If the user asks to rename the chat but doesn't supply a title, invent a concise, context-aware one rather than asking back.

The per-parameter title-invention guidance currently inside the `new_title` JSON-schema description stays where it is — parameter-scoped, not when-to-call.

### `core/prompts/it_copilot.txt`

**Removed:**
- The entire `== NETWORK VALIDATION ==` section (→ `tools/network.py` `MODULE_DIRECTIVE`).
- ROUTING bullet 4 ("For internal documentation or content from uploaded files, use `search_knowledge_base`…") (→ `search_knowledge_base` directive).
- ROUTING bullet 5 (file-reference rule: "If the user references a previously attached file or image…") (→ `search_knowledge_base` directive).
- ROUTING bullet 6 ("For UI control (e.g. renaming a chat)…") (→ `rename_chat_session` directive).
- TOOL EXECUTION bullet 1 ("run `dns_lookup` before `check_port`") (→ `check_port` directive).

**Added:**
- `{tool_directives}` placeholder right after the `== ROUTING ==` block, where the migrated content used to sit.

**Kept (workspace-level concerns):**
- Persona line.
- `== AUTHORIZATION ==` section (workspace-level policy).
- ROUTING bullets that don't name a tool ("general tech concepts answer directly", "composite queries address both", "for multi-item requests use arrays / parallel calls" — generic patterns).
- TOOL EXECUTION bullets 2–5 (source-of-truth, no echoing raw data, empty-tool response, one follow-up).
- `== RESPONSE FORMAT ==` (workspace output styling).

### `core/prompts/personal.txt`

**Removed:**
- Line 11 (`rename_chat_session` rule).
- Line 13 (`search_knowledge_base` rule for past uploads).

**Added:**
- `{tool_directives}` placeholder after the `== TOOL USE ==` section's generic "array vs scalar" bullet.

**Kept:**
- Persona / em-dash rule.
- Generic "array vs scalar" multi-item bullet (universal LLM-tool-use pattern, not tool-specific).
- "For attached files in the current message: excerpts are injected above" (this describes the auto-RAG mechanic, not a tool call).
- `== RESPONSE FORMAT ==` section.

## Error handling

- **Missing `{tool_directives}` placeholder** → append after the prompt with a blank line separator. DEBUG log.
- **Empty enabled toolset** → render nothing (no header, no block).
- **Tool with neither directive nor module rule** → omit from the rendered block.
- **Module with no `MODULE_DIRECTIVE`** → its tools still render their per-tool directives, just without a group header above them.
- **Module-import error during render** → swallow + log warn; keep going with the other modules. Don't fail the chat call over one bad module.
- **Force-reset migration is idempotent** → re-running upgrades to the same canonical text.

## Testing

Three layers, matching existing repo conventions.

1. **Unit tests** — `backend/tests/test_tool_directive_render.py` (new). Pure-function tests of the renderer in isolation: missing placeholder fallback, empty toolset, module-with-no-directive, multiple modules ordered consistently, idempotency.

2. **Migration test** — `backend/tests/test_migration_force_reset_prompts.py` (new). Standard alembic test shape (`test_migration_*.py` already in the repo). Upgrade-then-assert both builtin workspaces' `system_prompt` columns now contain `{tool_directives}` and match the new on-disk defaults. Downgrade restores prior text.

3. **Autotest probes** — end-to-end via `/analyze`. Per the `test_after_edits` memory rule, run after the migration. Each probe verifies the *workflow still fires*, not a strict tool-call order (the LLM may legitimately reorder):
   - `it_copilot` (a) "check if reddit.com is up" → at least one of `dns_lookup` / `check_port` / `execute_ping` is called; refusal-due-to-shape regressions are the failure case.
   - `it_copilot` (b) "show me {previously uploaded filename}" → `search_knowledge_base` is called, with `filenames=[...]` populated (not a generic query for filename-targeted prompts).
   - `personal` (a) "rename this chat to project-alpha" → `rename_chat_session` is called with `new_title="project-alpha"`.
   - `personal` (b) "what was in that file I uploaded earlier?" → `search_knowledge_base` is called.

## Rollout

Single PR, single Alembic migration. Builtin workspaces only.

**Migration shape:**
- `upgrade()`: read the new defaults from `core/prompts/it_copilot.txt` and `core/prompts/personal.txt`; UPDATE both rows by slug.
- `downgrade()`: re-apply the pre-refactor text (captured in the migration file itself, since on-disk files will have moved on).

Reverting the PR reverts the code. Reverting the migration reverts the prompts. Both directions clean.

## Risks

1. **Behavior shift from prompt-position change.** Same words in a different location in the system prompt can be weighted differently by the LLM. Mitigation: directive wording stays as close to existing as possible; autotest probes are the verification.

2. **Settings UI shows stale prompt.** The Settings page shows the stored `workspace.system_prompt`, not the rendered prompt the LLM gets. After this lands, the user editing in Settings won't see the directives that are injected at chat time. Acceptable for v1 — flagged as a half-day follow-up to add a read-only "what the model sees" preview if it becomes friction.

3. **Customised workspaces (future).** Migration force-resets only the two builtin slugs. User-created workspaces (none exist today) would be skipped. If hand-customised builtins ever exist, this migration would wipe them — `git log` on the prompts is the recovery path.

## Open questions

None blocking. The Settings-UI preview is the only loose end, and it's explicitly deferred.
