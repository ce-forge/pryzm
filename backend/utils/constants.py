"""Shared constants used across multiple layers (schemas, migrations, models).

Keeping these in one place avoids drift between the Pydantic Literal,
the SQLAlchemy column, the Alembic CHECK constraint, and the frontend
allowlist (which lives at `frontend/src/utils/workspaceColors.ts`).
"""

# Allowed workspace colors. Mirrors the keys of WORKSPACE_COLORS in
# `frontend/src/utils/workspaceColors.ts` — when this list changes,
# update that file too. The Pydantic Literal in `schemas.py` and the
# DB CHECK constraint both derive from this tuple.
WORKSPACE_COLORS: tuple[str, ...] = (
    "blue",
    "orange",
    "emerald",
    "red",
    "amber",
    "violet",
    "cyan",
    "pink",
    "white",
)

# The two color columns are declared with this length. Bumping it
# requires a migration + a re-spread to both `workspaces.color` and
# `workspace_templates.color`.
WORKSPACE_COLOR_MAX_LENGTH: int = 32
