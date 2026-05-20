"""workspace color length + allowlist CHECK constraint

Revision ID: c7f2e9a1b8d3
Revises: b439e666ffaf
Create Date: 2026-05-21 03:00:00.000000

Brings `workspace_templates.color` in line with `workspaces.color`
(String(32)) and pins both columns to the same allowlist so the model,
schema, and DB agree on what's valid. Mirrors the keys of
WORKSPACE_COLORS in `frontend/src/utils/workspaceColors.ts`.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c7f2e9a1b8d3"
down_revision: Union[str, Sequence[str], None] = "b439e666ffaf"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Kept in sync with backend/utils/constants.py:WORKSPACE_COLORS and
# frontend/src/utils/workspaceColors.ts. Hardcoded here so the
# migration is stable against future edits of those files.
_ALLOWED_COLORS = (
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


def _check_expr(column: str) -> str:
    quoted = ", ".join(f"'{c}'" for c in _ALLOWED_COLORS)
    return f"{column} IS NULL OR {column} IN ({quoted})"


def upgrade() -> None:
    # 1. Bring workspace_templates.color in line with workspaces.color length.
    op.alter_column(
        "workspace_templates",
        "color",
        existing_type=sa.String(),
        type_=sa.String(length=32),
        existing_nullable=True,
    )

    # 2. Allowlist CHECK on both tables. Existing rows have already been
    #    seeded with valid keys from the shared constant; if a row carries
    #    an invalid color the migration fails fast and the operator gets a
    #    clear pointer at the bad row.
    op.create_check_constraint(
        "ck_workspaces_color_allowed",
        "workspaces",
        _check_expr("color"),
    )
    op.create_check_constraint(
        "ck_workspace_templates_color_allowed",
        "workspace_templates",
        _check_expr("color"),
    )


def downgrade() -> None:
    op.drop_constraint("ck_workspace_templates_color_allowed", "workspace_templates", type_="check")
    op.drop_constraint("ck_workspaces_color_allowed", "workspaces", type_="check")
    op.alter_column(
        "workspace_templates",
        "color",
        existing_type=sa.String(length=32),
        type_=sa.String(),
        existing_nullable=True,
    )
