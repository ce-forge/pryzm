# Per-user allowed_tools cap

## Status

Design ready for implementation. Builds on the workspace/template split (`docs/specs/2026-05-18-workspace-template-split.md`) and the admin-managed template tool list shipped in PR #109. Adds a per-user upper bound that constrains what tools can land on any workspace a user owns.

## Why

Today the trust model is per-workspace. Each workspace has its own `enabled_tools` list plus an `owner_can_edit` flag. There is no per-user upper bound:

- A user with `can_create_workspaces=True` can create a fresh workspace and put any registry tool on it. The only gate is the existence of the tool in `AVAILABLE_TOOLS`.
- An admin instantiating a template for a user, or pushing a template, can hand the user any tool the template enables. The recipient inherits whatever the template carries.
- Reset re-copies the template's tool list back onto the user's instance with no filter.

For a local-LAN install with a trusted pool, this is fine. For Pryzm as a distributable product reaching less-trusted user populations, every tool an admin grants becomes a capability that user holds across every workspace they own — and there is no single column the admin can set to cap that.

`users.allowed_tools` introduces that cap. Empty list = no cap (current behavior, backwards compatible). Non-empty list = the user's workspaces can only carry tools that are a subset of this list. Admins bypass entirely.

## Goals

- Single column on `users` that defines the per-user tool cap.
- Every write path that sets `enabled_tools` on a user-owned workspace respects the cap.
- Admin UI exposes the cap in the create-user form and the edit-user modal.
- Existing data is grandfathered — tightening the cap does not silently mutate workspaces a user already owns.
- Bulk admin operations (template push, user reset) keep the rest of the field set propagating; tool caps clamp per-recipient instead of aborting the whole operation.

## Non-goals

- Frontend pre-flight warning in `WorkspaceSettings` when a user hits their cap. Server-side enforcement is authoritative; a frontend hint is a UX polish for a follow-up PR.
- Per-workspace caps that further restrict what the owner can do beyond `owner_can_edit`. Existing flag already covers the "lock down a specific workspace" case.
- Per-tool granular permissions (allowed only with these args, allowed only in these workspaces, etc.). The cap is binary per tool name.
- Migration of the existing trust model. Default `[]` means existing installs see zero behavioral change until the admin sets a cap on a specific user.

## Data model

### Add to `users`

| column | type | notes |
|---|---|---|
| `allowed_tools` | `jsonb NOT NULL DEFAULT '[]'` | Array of tool names from `AVAILABLE_TOOLS`. Empty = no cap. |

Mirrors the shape of `workspaces.enabled_tools` and `workspace_templates.enabled_tools`. No referential integrity to the tool registry — that registry lives in Python, not the DB. Unknown tool names are rejected at the API boundary on writes.

Alembic migration adds the column with a server default so existing rows backfill to `[]` without code changes. SQLAlchemy model adds `allowed_tools = Column(JSONB, nullable=False, server_default="[]")`.

## Enforcement

A single helper covers every write site. Lives in `backend/core/tool_permissions.py`:

```python
def enforce_allowed_tools(
    target_user: models.User,
    requested: list[str],
) -> None:
    """Raise 400 if any requested tool is outside target_user's cap.
    Admins always bypass. Empty cap means no restriction."""
    if target_user.is_admin:
        return
    cap = target_user.allowed_tools or []
    if not cap:
        return
    disallowed = [t for t in requested if t not in cap]
    if disallowed:
        raise HTTPException(
            status_code=400,
            detail=f"User is not allowed to use tools: {', '.join(disallowed)}",
        )


def filter_allowed_tools(
    target_user: models.User,
    requested: list[str],
) -> tuple[list[str], list[str]]:
    """Return (kept, dropped). Used by push + reset where bulk
    field propagation is more valuable than failing on one tool."""
    if target_user.is_admin:
        return list(requested), []
    cap = target_user.allowed_tools or []
    if not cap:
        return list(requested), []
    kept = [t for t in requested if t in cap]
    dropped = [t for t in requested if t not in cap]
    return kept, dropped
```

`target_user` is always the *workspace owner*, never the actor. Admin acting on someone else's workspace passes that recipient's user row.

## Write sites

The earlier `POST /admin/templates/{id}/instantiate` and `POST /admin/templates/{id}/push` endpoints have since merged into a single `POST /admin/templates/{id}/apply` with per-target action verbs (`create`, `update`, `adopt`). The cap behavior per verb is what matters here, not the route shape.

| Endpoint | Action verb | Target user | Behavior |
|---|---|---|---|
| `POST /workspaces` | — | current_user | `enforce_allowed_tools` after computing `enabled_tools` (default `[]` or from `clone_from`). Hard error on disallowed. |
| `PATCH /workspaces/{slug}` | — | `ws.user` | When payload includes `enabled_tools`, run `enforce_allowed_tools` on the new list. Stored value untouched if request omits the field — that is how grandfathering works. |
| `POST /workspaces/{slug}/reset` | — | `ws.user` | `filter_allowed_tools` on the template's tool list. Other fields (system_prompt, color, engine_config) propagate unconditionally. Response carries `dropped_tools` so the frontend can show a notice. |
| `POST /admin/templates/{id}/apply` | `create` (instantiate) | `target_user_id` | **Strict.** `enforce_allowed_tools(target_user, template.enabled_tools)`. Hard error on disallowed — create is one-shot, admin gets a clear actionable failure. |
| `POST /admin/templates/{id}/apply` | `update` (push) | each instance's `ws.user` | **Filter.** Per-recipient `filter_allowed_tools` against the template's tool list silently drops disallowed tools. Other fields propagate unconditionally. Response carries `filtered: [{ user_id, username, dropped_tools }]`. |
| `POST /admin/templates/{id}/apply` | `adopt` | `ws.user` | **Filter.** Same as `update` — bulk re-alignment, `filter_allowed_tools` quietly clamps. |
| `PUT /admin/workspaces/{id}` | — | `ws.user` | When payload includes `enabled_tools`, run `enforce_allowed_tools`. Admin sees the same error a user would; explicit lists are explicit intent. |

### Grandfathering

A workspace can persist `enabled_tools` that no longer satisfies the owner's current cap. This happens when the admin tightens `allowed_tools` after the workspace already existed, or when the admin grants a tool, the user uses it, and the admin later revokes.

Reads are untouched — the workspace runs with whatever it has. The next PATCH or admin direct-edit that re-sends `enabled_tools` is when the cap kicks in. The grandfathered state is observable in `/admin/users/[id]` (lists the user's workspaces with their tool sets, so admin can spot drift).

Reset and push, being bulk operations, will eventually scrub the violation via `filter_allowed_tools`. That is acceptable — the admin chose to push or the user chose to reset, both of which signal "re-align to template."

### Admin bypass

`is_admin=True` causes both helpers to return early. An admin's own workspaces can carry any tool regardless of what their own `allowed_tools` column contains. The column is still stored on admin rows so that demoting an admin to a regular user makes the cap meaningful immediately — no rewrite needed at demotion time.

## UI

### `/admin/users` create form

Add a tool multi-select between `can_create_workspaces` and the starter-templates picker. Same `ToolPicker`-style render as PR #109 (`/api/tools` source, checkbox per tool with name + description). Submitted as `allowed_tools: string[]` in `AdminUserCreate`.

### `EditUserModal`

Add the same multi-select. PATCH only sends `allowed_tools` when the list actually changed, matching the existing changed-fields pattern.

### `/admin/users/[id]` detail page

Add a small "Allowed tools" row near the top showing the current cap. If the cap is non-empty, list each tool. If empty, show "No restriction." A separate "Workspaces" section already lists the user's workspaces — for each, render an inline indicator next to any tool name that is currently in the workspace's `enabled_tools` but outside the cap (grandfathered violation marker).

### Push modal

The existing modal in `/admin/workspaces` (templates view) shows the pre-push count. After the push request returns, render the filtered list:

> Pushed to 7 workspaces. Filtered tools for 2 users:
> - alice — dropped `code_run`
> - bob — dropped `code_run`, `web_search`

Click-to-expand if the list is long.

### Reset

`POST /workspaces/{slug}/reset` response gains `{ ..., dropped_tools: ["code_run"] }`. Frontend renders a one-time inline notice in the workspace settings panel: "Some tools weren't restored because your admin restricts your tool list: code_run." No need for a separate dismiss flow — the notice goes away when the modal closes.

## Audit

No new `EventType`. Existing flows already cover the surface:

- `ADMIN_USER_CREATED` and `ADMIN_USER_EDITED` capture `allowed_tools` changes via the existing `changed_fields` / `previous_values` / `new_values` payload pattern. No code change needed beyond surfacing the field in the admin_users router's diff logic (already generic over `AdminUserUpdate.model_dump`).
- `ADMIN_TEMPLATE_PUSHED` payload (currently `affected_workspace_count`, `affected_user_count`, `had_customizations_count`) extends with `filtered: [{ user_id, dropped_tools }]` so the audit trail reflects what the admin actually delivered, not just what they intended.
- `WORKSPACE_EDITED` covers PATCH rejections via HTTP 400; no audit row is written on a rejected write (existing pattern).

## Tests

Backend (`backend/tests/test_allowed_tools.py`):

- Migration: existing users backfill to `[]`.
- `enforce_allowed_tools`: empty cap allows any list; non-empty rejects on disallowed; admin always passes regardless of cap shape.
- `filter_allowed_tools`: returns kept + dropped correctly across all cap shapes.
- Each strict write site (POST workspaces, PATCH workspaces, instantiate, admin PUT workspaces): positive case + 400 on disallowed.
- Reset: filter applied, dropped_tools surfaced in response, other fields propagate.
- Push: one recipient violates → push succeeds for all, filtered list in response, audit payload carries per-user dropped lists.
- Grandfathering: workspace has `enabled_tools=["A", "C"]` and owner's cap tightens to `["A"]`. PATCH that touches only `display_name` succeeds. PATCH that re-sends `enabled_tools=["A", "C"]` fails. PATCH that sends `enabled_tools=["A"]` succeeds.
- Admin self-cap: admin user with non-empty `allowed_tools` can still PATCH their own workspace to any tool. Demotion makes the cap take effect immediately on the next write.

Frontend: manual walkthrough on the same posture as PR #109. No formal frontend test framework yet.

## Out of scope

- Frontend pre-flight indicator in `WorkspaceSettings` when the user is at their cap. Server-side error message is the source of truth.
- Bulk admin tooling for sweeping grandfathered workspaces into compliance. Admin can edit them one by one if needed; no automation pressure yet.
- Audit-trail UI for the new `filtered` payload on push events. The data lands in `audit_events.payload`; the audit log viewer already renders JSON.

## Open questions

None. Decisions resolved during brainstorm:
- Storage shape: JSON column on `users`.
- Empty semantics: no restriction.
- Strict sites: POST/PATCH workspaces, instantiate, admin PUT workspaces.
- Filter sites: push, reset.
- Tightening behavior: grandfather + block at next write.
- Admin bypass: always unrestricted regardless of column value.
