# Workspace / template table split

## Status

Design ready for implementation. Replaces the shared-table approach used by Pattern B in the auth foundation (`docs/specs/2026-05-17-user-login-and-admin.md`), where workspaces and templates cohabit the `workspaces` row set distinguished by `is_template`. The cohabitation has produced a recurring bug class: every listing endpoint must remember to filter on `is_template`, and forgetting silently leaks templates into user views (caught twice already — once on `GET /workspaces`, once on `GET /sessions`).

## Why

Under Pattern B today:

- Templates and user-owned workspaces are rows in the same `workspaces` table.
- The `is_template` flag distinguishes them.
- Slug uniqueness uses two partial indexes: `UNIQUE(slug) WHERE is_template = TRUE` for templates, `UNIQUE(user_id, slug) WHERE is_template = FALSE AND user_id IS NOT NULL` for instances.
- Every query that lists or resolves a workspace has to filter `is_template = FALSE` (for user views) or `is_template = TRUE` (for admin templates).
- A legacy `get_or_default(slug)` helper exists that does no filtering at all, and several endpoints accidentally still used it post-Pattern-B.

Splitting templates into their own table eliminates the filter requirement entirely. Workspaces are always user-owned and queryable as `WHERE user_id = ?`. Templates live in their own namespace with their own slug uniqueness.

This spec also captures two adjacent cleanups that fall out naturally:

- `workspaces.is_builtin` becomes dead weight. Originally distinguished "shipped with the app" from user-created; under the split, that distinction is owned by templates (a template IS the "shipped" thing; instances are always user-owned).
- A `workspaces.position` integer per user for sidebar ordering, since the question of "which workspace loads first on login" only makes sense per-user.

## Goals

- Two tables: `workspace_templates` (admin-managed blueprints) and `workspaces` (user-owned instances).
- Every workspace listing/resolution endpoint drops its `is_template` filter — impossible to leak templates because they're a different table.
- Drop `workspaces.is_template`, `workspaces.is_builtin`, and the partial unique indexes from Phase A.
- Add `workspaces.position` (per-user sidebar ordering, simple sequence).
- Reset endpoint reworked into "re-copy from your template" (gated by `template_id IS NOT NULL`).

## Non-goals

- Multi-position list-reorder UI in the dashboard — frontend phase, not this spec.
- The user-facing drag-and-drop interaction in the sidebar — frontend phase.
- Template versioning / propagation history — separate concern.
- Cross-user workspace sharing — Pattern B already says no.

## Data model

### New: `workspace_templates`

| column | type | notes |
|---|---|---|
| `id` | UUIDv7 PK | |
| `slug` | text, UNIQUE | globally unique, admin-facing identifier |
| `display_name` | text | |
| `system_prompt` | text | |
| `enabled_tools` | jsonb | array of tool names |
| `color` | text, nullable | per-workspace UI accent |
| `engine_config` | jsonb | model selection etc. |
| `created_at` | timestamptz | |

### Modified: `workspaces`

Removed:
- `is_template` (column gone)
- `is_builtin` (column gone)
- The two partial unique indexes from Phase A's slug-uniqueness migration

Added:
- `position` integer NOT NULL default 0 — per-user ordering for sidebar and login-default. Simple sequence (0, 1, 2, …); reorder UPDATEs rows after the change point.

Kept (now simpler since templates are elsewhere):
- `id`, `user_id` (NOT NULL FK), `slug`, `template_id` (now FK → `workspace_templates`, ON DELETE SET NULL), `display_name`, `system_prompt`, `enabled_tools`, `color`, `engine_config`, `owner_can_edit`, `created_at`

Unique constraint: simple `UNIQUE(user_id, slug)` — no partial-index dance.

Index: `(user_id, position)` for the sorted sidebar query.

## Migration shape

Single alembic revision, four steps:

1. **Create `workspace_templates` table** with the column shape above.

2. **Copy template rows out.** For every row in `workspaces` where `is_template = TRUE`, INSERT a corresponding row into `workspace_templates` preserving the `id`. The existing `workspaces.template_id` FK already references those ids — keeping them stable means no FK repointing on instance rows.

3. **Drop template rows from `workspaces`.** `DELETE FROM workspaces WHERE is_template = TRUE`.

4. **Drop columns + indexes + repoint FK.**
   - Drop the partial unique indexes from Phase A.
   - Drop `is_template` and `is_builtin` columns.
   - Drop the existing `fk_workspaces_template_id` (which pointed to `workspaces.id`).
   - Re-create `template_id` FK pointing to `workspace_templates.id` ON DELETE SET NULL.
   - Add `UNIQUE(user_id, slug)` constraint on `workspaces`.
   - Add `position` column (INT NOT NULL DEFAULT 0) with index on `(user_id, position)`.

Down-migration reverses (recreate columns, copy rows back, restore partial indexes, drop position).

## Endpoint changes

**Simplified (filter goes away):**
- `GET /workspaces` — `WHERE user_id = ?` is enough; no `is_template = FALSE` filter
- `GET /workspaces/{slug}` — same
- `workspace_query_dep` — `(slug, user_id)` filter only
- Every endpoint using `Depends(workspace_query_dep)`

**Renamed table reference (functional shape unchanged):**
- `GET /api/admin/templates` — queries `workspace_templates` directly
- `POST /api/admin/templates` — INSERTs into `workspace_templates`
- `PUT /api/admin/templates/{id}` — UPDATEs in `workspace_templates`
- `DELETE /api/admin/templates/{id}` — DELETEs from `workspace_templates`; FK ON DELETE SET NULL handles instance `template_id` cleanup
- `POST /api/admin/templates/{id}/instantiate` — looks up template, INSERTs into `workspaces`
- `POST /api/admin/templates/{id}/push` — updates `workspaces` rows where `template_id = ?`

**New / reworked:**
- `POST /workspaces/{slug}/reset` — was `_validate_resettable` (gated on `is_builtin`). Now: looks up the workspace's `template_id`; if null, 400 ("workspace has no template to reset to"); otherwise re-copies settings from the template (same logic as admin push, but for the single workspace by its owner). Self-service version of admin push, gated by `owner_can_edit` or admin.
- `PATCH /workspaces/{slug}/position` — accepts `{position: int}`, updates the workspace's position and shifts other rows in the user's set as needed. Used by the eventual sidebar drag-and-drop UI (frontend phase).
- `GET /workspaces` returns rows ordered by `position ASC, created_at ASC` so the sidebar shows them in the right order.

## Code cleanup falling out of the split

- `services/workspaces.py::get_or_default` — delete entirely. Every caller has been migrated to either `workspace_query_dep` or an inline user-scoped filter (post-PR #80). The legacy helper is now dead code.
- `routers/workspaces.py::_validate_resettable` — deleted; reset now gates on `template_id`.
- `core/bootstrap.py` — `_instantiate_templates_for` reads from `workspace_templates`, INSERTs into `workspaces`. No more copying of `is_builtin` (column gone).
- `routers/admin_templates.py` — switches all queries to `workspace_templates` model; the existing API shape stays the same so frontend (when it lands) doesn't change.
- Phase A's `workspace_slug_partial_unique` alembic migration is no longer needed for future fresh installs, but it's already in the history and that's fine — this new migration drops the partial indexes it created.

## Test impact

- Existing tests that seed `models.Workspace(is_template=True, ...)` move to `models.WorkspaceTemplate(...)`.
- Tests that assert `is_template=False` on instances — assertions go away.
- Tests that exercised the partial unique indexes can either be updated to the new constraint shape or deleted if they were only validating the partial-index behavior.
- The bootstrap admin test verifies templates land in `workspace_templates` and the admin's instance lands in `workspaces`.
- A new test verifies workspace ordering: seed 3 workspaces, set positions, GET /workspaces returns them in `position` order.

## Decisions (resolved)

1. **Reset endpoint:** kept; reworked as "re-copy from template" (gated by `template_id IS NOT NULL`). Self-service equivalent of admin push.
2. **Table name:** `workspace_templates`. Explicit, no collision with future generic templates concept.
3. **Position semantics:** simple sequence (0, 1, 2, …). Reorder UPDATEs the affected rows; per-user lists are small enough that the cost is irrelevant.

## Phased plan

Single PR. Phases here are internal commit boundaries, not separate releases.

- **F.1** — alembic migration (new table, data copy, column/index drops, position column).
- **F.2** — SQLAlchemy models: add `WorkspaceTemplate`, drop `is_template`/`is_builtin` from `Workspace`, add `position`. Re-point `template_id` FK reference in `Workspace`.
- **F.3** — `core/bootstrap.py` updated to read from `WorkspaceTemplate`.
- **F.4** — `core/workspace_access.py::workspace_query_dep` simplified.
- **F.5** — admin templates router (`routers/admin_templates.py`) switched to the new model.
- **F.6** — user workspaces router (`routers/workspaces.py`): drop `_validate_resettable`, rework reset endpoint, add `PATCH /workspaces/{slug}/position`. Listing endpoint orders by position.
- **F.7** — delete `services/workspaces.py::get_or_default` and audit imports.
- **F.8** — test fixture updates across the board.
- **F.9** — full test sweep + manual smoke.
- **F.10** — push + PR.

## What this unblocks

- Sidebar drag-and-drop reordering (frontend phase, after backend lands).
- Login default workspace = the one with `position = 0` for that user (frontend phase).
- Cleaner mental model for future work — every reference to "workspace" unambiguously means a user-owned instance.
- Removal of the dead `is_builtin` accumulating noise across the codebase.
