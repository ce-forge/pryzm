# Workspace Expansion — Design Spec

- **Date**: 2026-05-12
- **Status**: Approved, ready for implementation plan
- **Branch context**: builds on top of `feature/dynamic-tool-creator` (post Group G)

## Context

Today the app has two hardcoded workspaces — `it_copilot` and `personal` — represented as a free-form string column (`Session.mode`, `Folder.workspace`, `Document.workspace`) and a binary mode check in `core/ai_engine.py`. The per-tool workspace allowlist landed during Group C (`@tool(workspaces=[...])`) gives us a *capability* declaration but not user-driven *policy* — there is no way to add, remove, rename, or reconfigure a workspace at runtime.

This spec covers **Project A**: introducing user-created workspaces and per-workspace tool/prompt configuration. Each workspace becomes an **agent bound to a data scope**: it owns its own system prompt, its own enabled tool set, and its own sessions/folders/documents. Built-in workspaces become first-class editable rows.

### Explicitly out of scope

- **User accounts, authentication, admin permissions** — deferred to a separate "Project B" spec. The data model in this spec does NOT bake in user ownership; that layer will overlay later via permission middleware and a `users` + `workspace_users` table.
- **The "council" orchestrator workspace** — covered architecturally (a future `delegate_to_workspace(slug)` tool can be added without schema changes) but not implemented here.
- **Visual node-graph editor for system prompts** — current spec stores prompts as `TEXT`. The future graph editor can add a `prompt_graph JSONB` column and a `prompt_source` enum without touching this design.
- **Workspace icons / colors / visual customization** — deferred.
- **Workspace export / import / templates beyond clone-on-create**.

## Goals

1. Users can create, rename, edit, clone, and delete workspaces from the UI.
2. Each workspace has its own editable system prompt and its own enabled tool list.
3. The existing `it_copilot` and `personal` workspaces become editable rows with `is_builtin=true`, preserving their current behavior and gaining a "Reset to default" affordance.
4. URLs and tool calls reference workspaces by a stable human-readable **slug**; foreign keys reference a stable **UUID** primary key.
5. Existing `/?workspace=it_copilot`-style URLs continue to work — the slugs match the historical mode strings, so external links don't break.
6. The data model leaves a clean seam for the future council pattern (cross-workspace delegation) and Project B (user/admin permissions).

## Data Model

### New table: `workspaces`

```
workspaces
  id             UUID         PRIMARY KEY
  slug           VARCHAR      UNIQUE NOT NULL   -- "it_copilot", "research-bot"; immutable
  display_name   VARCHAR      NOT NULL          -- "IT Copilot", "Research Bot"; editable
  system_prompt  TEXT         NOT NULL          -- assistant instructions; editable
  enabled_tools  JSONB        NOT NULL DEFAULT '[]'::jsonb
                                                -- list of tool name strings;
                                                -- e.g. ["rename_chat_session", "check_port"]
  is_builtin     BOOLEAN      NOT NULL DEFAULT FALSE
                                                -- powers "Reset to default" affordance
  created_at     TIMESTAMPTZ  NOT NULL DEFAULT clock_timestamp()
```

**Notes**:
- `id` is the foreign-key target on sessions/folders/documents. Stable through any rename.
- `slug` is human-readable, used in URL query params (`?workspace=research-bot`) and as the identifier the LLM emits in cross-workspace tool calls (future `delegate_to_workspace("research-bot")`). Immutable in this version — slug mutability with redirect handling can come later without schema changes.
- `display_name` is what the user sees in the switcher and chat header. Edit-friendly.
- `enabled_tools` is canonical at runtime. The `@tool(workspaces=[...])` decorator is *seed data only* — its only job is to populate the built-ins' `enabled_tools` during the initial migration.
- `is_builtin` flags `it_copilot` and `personal` so the UI can render a "Reset to default" button that re-seeds `display_name`, `system_prompt`, and `enabled_tools` from the on-disk defaults. User-created workspaces have `is_builtin=false` and no reset (delete is the equivalent).
- `created_at` uses `clock_timestamp()` (real wall time, see Group B fix on `branch_session`) so concurrent creates don't share a timestamp.

### FK changes on existing tables

| Table | Old column | New column | Behavior |
|---|---|---|---|
| `sessions` | `mode VARCHAR` | `workspace_id UUID NOT NULL` | FK → `workspaces.id` ON DELETE CASCADE |
| `folders` | `workspace VARCHAR` | `workspace_id UUID NOT NULL` | FK → `workspaces.id` ON DELETE CASCADE |
| `documents` | `workspace VARCHAR` | `workspace_id UUID NOT NULL` | FK → `workspaces.id` ON DELETE CASCADE |

All three get an index on `workspace_id` for the existing "list by workspace" queries.

### Migrations (two-step, alembic)

**Migration `add_workspaces_table`**:

1. `CREATE TABLE workspaces (...)`.
2. Seed two rows:
   - `(slug='it_copilot', display_name='IT Copilot', system_prompt=<contents of core/prompts/it_copilot.txt>, enabled_tools=<every tool whose @tool decorator lists "it_copilot">, is_builtin=true)`
   - `(slug='personal', display_name='Personal', system_prompt=<contents of core/prompts/personal.txt>, enabled_tools=<every tool whose decorator lists "personal">, is_builtin=true)`
3. Add `workspace_id UUID` columns to `sessions`/`folders`/`documents` (nullable for now).
4. Backfill: for each row, set `workspace_id` to the workspace whose `slug` matches the existing `mode`/`workspace` string. Rows whose string doesn't match a seeded slug — none should exist in practice, but defensively: assign to `it_copilot`.
5. Add indexes on `workspace_id`.

**Migration `enforce_workspace_id_nonnull`** (separate revision so the first is reversible):

1. `ALTER TABLE ... ALTER COLUMN workspace_id SET NOT NULL`.
2. Add the FK constraints (`ON DELETE CASCADE`).
3. Drop the old `mode` / `workspace` string columns.

The two-revision split lets us roll back after step 1 without losing data; once step 2 lands, the old columns are gone.

### Seed-data plumbing

To keep the migration's seed values in sync with what the running code expects (system prompts and decorator's `workspaces=[...]` lists), the migration imports `core.prompt_manager.PromptManager` only to *read* the default prompt file paths, and `tools.registry.TOOL_WORKSPACES` to read the decorator-declared allowlists. The migration is therefore self-contained (no live HTTP / Ollama calls) but uses live module state.

`is_builtin=true` workspaces have a corresponding `core/prompts/<slug>.txt` file on disk. The "Reset to default" endpoint re-reads that file and rewrites the workspace's `system_prompt` + `enabled_tools` from the seed logic. **User-created workspaces have no on-disk counterpart and no reset.**

## API Surface

### New endpoints

| Method | Path | Body / Query | Returns |
|---|---|---|---|
| `GET` | `/workspaces` | — | `[{id, slug, display_name, system_prompt, enabled_tools, is_builtin, created_at}, ...]` |
| `GET` | `/workspaces/{slug}` | — | single workspace |
| `POST` | `/workspaces` | `{display_name: str, clone_from: Optional[str]}` | created workspace |
| `PATCH` | `/workspaces/{slug}` | `{display_name?, system_prompt?, enabled_tools?}` | updated workspace |
| `DELETE` | `/workspaces/{slug}` | — | `{deleted: true, removed_sessions: N, removed_folders: M, removed_documents: K}` |
| `POST` | `/workspaces/{slug}/reset` | — | re-seeded workspace (only valid when `is_builtin=true`; returns 409 otherwise) |

### Behavior details

- **Slug generation**: `POST /workspaces` derives `slug` from `display_name` via a slugify pass (lowercase, replace non-alphanumeric with `-`, collapse runs, trim). If the result collides with an existing slug, append `-2`, `-3`, … until unique. Reject if the display_name slugifies to empty.
- **Clone**: if `clone_from` is provided, the new workspace's `system_prompt` and `enabled_tools` are copied from that source workspace. `display_name`/`slug` come from the new body. Blank (default) = sensible defaults: `system_prompt="You are a helpful assistant. Answer the user's questions thoughtfully."`, `enabled_tools=[]`.
- **Last-workspace guard**: `DELETE /workspaces/{slug}` returns `409` with `{"detail": "Cannot delete the only remaining workspace"}` if it would leave zero rows.
- **PATCH validation**:
  - `enabled_tools` values must all be present in the live `AVAILABLE_TOOLS` registry; unknown names → 400.
  - `system_prompt` length capped at some reasonable bound (e.g. 50 KB) to prevent unbounded growth.
- **Reset**: only valid for `is_builtin=true`. Reads `core/prompts/<slug>.txt` and the decorator-declared `workspaces=[...]` lists, rewrites the workspace's `system_prompt` and `enabled_tools` accordingly. `display_name` is also reset (in case the user renamed it).

### Modified endpoints

The existing `/sessions`, `/folders`, `/upload`, `/analyze` and friends currently take a `workspace` query / body param as a free-form string. After this change:

- They still accept `workspace=<slug>`. The backend resolves slug → workspace_id at the start of each handler and uses the UUID for DB ops.
- Unknown slugs return `404` (`{"detail": "Workspace not found: foo"}`).
- The default value falls back to `it_copilot` when omitted (existing behavior).

### Backward compatibility

- Existing URLs (`?workspace=it_copilot`, `?workspace=personal`) keep working: the slugs match the historical strings.
- Frontend code paths that read `session.mode` change to read `session.workspace.slug` (or `session.workspace_id` for FK comparisons). Group D already typed `ChatContextValue` from a hook, so adding `workspace` to the session shape is type-safe and TypeScript will surface missed call sites.

## UI Structure

### New components

```
frontend/src/components/
  WorkspaceSwitcher.tsx       — top-of-sidebar trigger + dropdown panel
  WorkspaceSettings.tsx       — modal: display name, prompt, tools, delete
  InlineCreateForm.tsx        — shared with + Folder (small refactor of SessionDirectory)
```

### `WorkspaceSwitcher.tsx`

Replaces the current `IT Copilot | Personal` tab toggle in `Sidebar.tsx`.

Structure:
- Trigger button: `[active workspace display_name] ▾`
- Dropdown panel (opens on click):
  - List of workspaces (active one highlighted)
  - Divider
  - `+ New workspace` (opens an `InlineCreateForm` styled to fit the dropdown, with the "Start from..." dropdown next to the name input)
  - `⚙ Workspace settings` (opens `WorkspaceSettings` modal scoped to the active workspace)

Reaches into `ChatContext` for the active workspace + the full workspace list. Switching workspace calls `session.navigateToSession` with the new slug in the URL.

### `WorkspaceSettings.tsx`

Modal, parallel pattern to existing `ConfirmModal` and `Settings`.

Fields:
- **Display name** — text input, debounced PATCH on blur.
- **System prompt** — textarea, debounced PATCH on blur. Sized for comfortable editing (multi-line, resizable).
- **Enabled tools** — list of checkboxes, one per tool in `AVAILABLE_TOOLS`. Toggle = PATCH `{enabled_tools: [...]}`. Each row shows the tool name + its decorator-declared description as a hint.
- **Reset to default** — button, only visible when `is_builtin=true`. Opens a confirm modal then POSTs `/workspaces/{slug}/reset`.
- **Delete workspace** — danger button. Opens a confirm modal showing the destructive count: "Delete `Research Bot` and its 12 sessions, 3 folders, 2 documents? This cannot be undone." On confirm, DELETE the workspace and navigate to the next remaining one.

### `InlineCreateForm.tsx` (shared)

Tiny component, refactored out of the existing folder-create flow in `SessionDirectory.tsx`. Owns the input + submit/cancel/blur/Escape behavior. Both `+ Folder` and `+ Workspace` use it.

```tsx
<InlineCreateForm
  placeholder="Folder name"
  onSubmit={(name) => createFolder(name)}
  onCancel={() => setIsCreatingFolder(false)}
/>
```

### Changes to existing components

- `Sidebar.tsx` — replace the tab toggle with `<WorkspaceSwitcher />`. The "+ New chat" button and rest of the sidebar stay.
- `SessionDirectory.tsx` — refactor its inline create-folder JSX to use the new `InlineCreateForm`. Behavior unchanged.
- `ChatHeader.tsx` — currently has a hardcoded `IT COPILOT` / `PERSONAL` badge based on a `workspace?.toLowerCase().includes('copilot')` check. Change to use the active workspace's `display_name` directly.
- `useSession.ts` — `workspace` URL param semantics unchanged (still a slug). The hook gains a `workspace` object (resolved from the slug) for the rest of the app to consume.

## Tool Capability vs Policy

Decision: **option A** — DB is the sole runtime source of truth.

- `@tool(workspaces=[...])` in source code is **seed data only**. The alembic migration reads it once to populate the built-ins' `enabled_tools`. After migration, it's never read at runtime.
- `core/ai_engine.py:get_tools_for_workspace(workspace)` is renamed/rewritten to look up the workspace's `enabled_tools` column from the DB and intersect it with the live `AVAILABLE_TOOLS` registry (so disabled or removed tool names are ignored gracefully).
- New tools added by an engineer (`@tool(...)` decorator added to a Python file) are NOT auto-enabled in any workspace. The engineer or user explicitly toggles them on in `WorkspaceSettings`. This matches the user-facing model where "what tools this workspace has" is configuration, not code.
- The decorator's `workspaces=[...]` field is kept for documentation/intent in source — it tells a reader "this tool was originally designed for these workspaces" — but the runtime ignores it.

## Edge cases

- **Last-workspace deletion**: API returns 409 (see API Surface).
- **Deleting the workspace you're currently in**: frontend handles the redirect — after the DELETE response, navigate to the first remaining workspace.
- **URL points at a deleted/unknown slug**: backend returns 404 from any endpoint with that slug. Frontend silently navigates to the first available workspace (sorted by `created_at` ascending — i.e. `it_copilot` if it still exists) and updates the URL. No user-facing toast; the redirect is silent because this only happens when something off-flow has happened (manual URL edit, stale bookmark after a delete in another tab).
- **Slug collision on create**: append `-2`, `-3`, … until unique. The chosen final slug is returned in the response so the frontend can navigate to it.
- **Empty slug after slugify** (e.g. user enters only emojis): 400 with `{"detail": "Display name must contain at least one alphanumeric character"}`.
- **Tool name in `enabled_tools` no longer exists in code**: the engine ignores it at request time (warns to stdout via the request logger). PATCH endpoint refuses to *add* unknown names — only stale ones persist.
- **Reset on a non-builtin workspace**: 409.
- **PATCH `display_name` to empty / whitespace**: 400.

## Forward compatibility

- **Council pattern**: when ready, add a new tool to `tools/system.py`:
  ```python
  @tool(properties={...}, required=["target_workspace_slug", "query"])
  def delegate_to_workspace(target_workspace_slug, query, workspace, session_id):
      # Look up target by slug, run its chat pipeline, return result.
  ```
  Then create a `council` workspace (via the same `POST /workspaces`) and toggle this tool on. No schema changes needed.

- **Project B (users + admin gating)**: layered on top, never below. The plan:
  - Add `users`, `workspace_users` (assignments with role enum), `sessions` (auth sessions, not chat sessions) tables.
  - Add an auth dependency to every API endpoint.
  - The workspace CRUD endpoints gain permission checks; non-admin users can only `GET` workspaces they're assigned to.
  - Frontend conditionally renders the `WorkspaceSettings` modal as read-only for non-admin users.
  - The workspace data model stays exactly as designed here. None of the columns above change.

- **Prompt node graph**: add `prompt_graph JSONB` and `prompt_source` (`'text' | 'graph'`) columns to `workspaces`. The agent loop checks `prompt_source` and either uses the existing `system_prompt` text or compiles the graph at request time. Additive migration.

## Verification

Autotest probes to add in `/tmp/pryzm_autotest.py`:

- `workspaces/list-after-migration` — exactly 2 workspaces present with slugs `it_copilot` and `personal`, both `is_builtin=true`.
- `workspaces/create-blank` — POST with name only; verify slug auto-generation, default prompt, empty tools.
- `workspaces/create-clone` — POST with `clone_from=it_copilot`; verify prompt + tools copied.
- `workspaces/create-slug-collision` — POST same name twice; verify second gets `-2` suffix.
- `workspaces/patch-display-name` — PATCH; verify slug unchanged, display_name updated.
- `workspaces/patch-system-prompt` — PATCH; verify persistence.
- `workspaces/patch-enabled-tools-unknown-name` — PATCH with `["definitely_not_a_real_tool"]`; verify 400.
- `workspaces/delete-cascade-counts` — create a workspace with a session/folder/doc, DELETE, verify response counts and DB cascade.
- `workspaces/delete-last-blocked` — try to delete when only one remains; verify 409.
- `workspaces/reset-builtin` — PATCH `it_copilot.system_prompt` to something custom, POST `/workspaces/it_copilot/reset`, verify the prompt matches `core/prompts/it_copilot.txt`.
- `workspaces/reset-user-workspace-blocked` — try to reset a non-builtin; verify 409.
- `workspaces/url-backward-compat` — `GET /sessions?workspace=it_copilot` still works post-migration.

UI verification (manual / screenshot):

- Switch workspace via the dropdown → URL updates, chat header reflects the new display_name.
- Create a workspace → it appears in the dropdown immediately.
- Settings modal: rename → reflected everywhere. Prompt edit → persisted. Tool toggle → tool used by the LLM matches.
- Reset built-in → prompt + tools return to defaults.
- Delete → confirm dialog shows counts; deletion redirects to first remaining workspace.

## Critical files

### New
- `backend/alembic/versions/<rev>_add_workspaces_table.py`
- `backend/alembic/versions/<rev>_enforce_workspace_id_nonnull.py`
- `frontend/src/components/WorkspaceSwitcher.tsx`
- `frontend/src/components/WorkspaceSettings.tsx`
- `frontend/src/components/InlineCreateForm.tsx`
- `frontend/src/hooks/useWorkspaces.ts` (CRUD + list state)

### Modified
- `backend/db/models.py` — new `Workspace` model; FK changes on `Session` / `Folder` / `Document`.
- `backend/schemas.py` — `WorkspaceResponse`, `WorkspaceCreate`, `WorkspaceUpdate`.
- `backend/routers/chat.py` — slug → workspace_id resolution at the start of any handler that takes `workspace=`; new workspace CRUD endpoints (or split into `backend/routers/workspaces.py` if `chat.py` gets too dense).
- `backend/services/workspaces.py` (new) — owns workspace DB operations, including a `resolve_tools_for_workspace(db, workspace_id) -> (callable_map, definitions_list)` function that intersects the workspace's stored `enabled_tools` with the live `AVAILABLE_TOOLS` registry.
- `backend/core/ai_engine.py` — `stream_chat` now calls `services.workspaces.resolve_tools_for_workspace(db, workspace_id)` instead of `tools.registry.get_tools_for_workspace(name)`.
- `backend/tools/registry.py` — `TOOL_WORKSPACES` is kept as seed-only metadata. The existing `get_tools_for_workspace(name)` helper is removed; its only caller was `ai_engine.stream_chat`, which now resolves via the DB.
- `frontend/src/components/Sidebar.tsx` — replace tab toggle with `<WorkspaceSwitcher />`.
- `frontend/src/components/SessionDirectory.tsx` — refactor inline folder-create to use `<InlineCreateForm />`.
- `frontend/src/components/ChatHeader.tsx` — read active workspace's display_name instead of hardcoded copilot/personal logic.
- `frontend/src/hooks/useSession.ts` — workspace slug → workspace object resolution.
- `frontend/src/context/ChatContext.tsx` — include workspaces list in the value.

## Implementation phases (rough sketch — full plan comes next)

1. **Backend foundation**: model + migration (two-step) + workspace CRUD endpoints + slug resolution layer + autotest probes. App still uses the old tab toggle.
2. **Tool model switch**: rewire `ai_engine.get_tools_for_workspace` to read from DB. Verify existing tool behavior in `it_copilot` and `personal` unchanged.
3. **Frontend foundation**: `WorkspaceSwitcher` + `WorkspaceSettings` + `InlineCreateForm` + ChatContext updates. Old tab toggle removed.
4. **End-to-end manual verification**: create / edit / clone / delete a workspace from the UI; exercise tool toggling and prompt editing; confirm Reset to default works.

These phases ARE implementation order, not separate commits — the implementation plan (next step) will divide them into commit-shaped chunks.
