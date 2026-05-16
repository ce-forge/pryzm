"""enable web_search on it_copilot + personal builtin workspaces

Revision ID: e7c2a9f4b8d1
Revises: d2f9c4e7a8b1
Create Date: 2026-05-16 00:00:00.000000

The seed migration only runs on fresh DBs; existing workspaces need a
backfill to pick up `web_search` (added in PR-A of the SearxNG rollout).
Idempotent — re-runs and pre-existing entries don't duplicate.

User-customised workspaces (non-builtin) are intentionally NOT touched.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e7c2a9f4b8d1"
down_revision: Union[str, Sequence[str], None] = "d2f9c4e7a8b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_BUILTIN_SLUGS = ("it_copilot", "personal")


def upgrade() -> None:
    conn = op.get_bind()
    # Append "web_search" to enabled_tools where it's not already present.
    conn.execute(
        sa.text(
            "UPDATE workspaces "
            "SET enabled_tools = enabled_tools || '[\"web_search\"]'::jsonb "
            "WHERE slug = ANY(:slugs) "
            "AND NOT (enabled_tools @> '[\"web_search\"]'::jsonb)"
        ),
        {"slugs": list(_BUILTIN_SLUGS)},
    )


def downgrade() -> None:
    conn = op.get_bind()
    # Filter "web_search" out of the JSONB array. jsonb_agg(NULL) returns NULL,
    # so coalesce to '[]' for the all-elements-removed case.
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
