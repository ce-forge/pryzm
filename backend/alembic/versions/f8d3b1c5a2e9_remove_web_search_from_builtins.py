"""remove web_search from it_copilot + personal builtin workspaces

Revision ID: f8d3b1c5a2e9
Revises: e7c2a9f4b8d1
Create Date: 2026-05-16 10:15:00.000000

Reverses the data effect of e7c2a9f4b8d1 for the two builtin slugs. After
in-demo testing, web_search is moving from "default-on per workspace" to
"only-on via the per-turn globe toggle" — the toggle's force_tools layer
is the single source of truth. Non-builtin workspaces are untouched
(their admins explicitly opted in; respect that).

Idempotent — re-runs and pre-absent entries don't error. Downgrade
re-appends web_search.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f8d3b1c5a2e9"
down_revision: Union[str, Sequence[str], None] = "e7c2a9f4b8d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_BUILTIN_SLUGS = ("it_copilot", "personal")


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE workspaces SET enabled_tools = COALESCE("
            "  (SELECT jsonb_agg(elem) "
            "   FROM jsonb_array_elements(enabled_tools) elem "
            "   WHERE elem <> '\"web_search\"'::jsonb), "
            "  '[]'::jsonb"
            ") "
            "WHERE slug = ANY(:slugs)"
        ),
        {"slugs": list(_BUILTIN_SLUGS)},
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE workspaces "
            "SET enabled_tools = enabled_tools || '[\"web_search\"]'::jsonb "
            "WHERE slug = ANY(:slugs) "
            "AND NOT (enabled_tools @> '[\"web_search\"]'::jsonb)"
        ),
        {"slugs": list(_BUILTIN_SLUGS)},
    )
