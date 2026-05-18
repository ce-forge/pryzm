"""workspace slug partial unique indexes

Revision ID: a65df9990a35
Revises: dc1f669b872e
Create Date: 2026-05-18 09:00:00.000000

Replaces the global UNIQUE(slug) on workspaces with two partial unique
indexes so that:
  * templates keep a globally unique slug, and
  * each user can own a workspace whose slug matches a template's slug
    (without colliding across users or with the template itself).
"""
from typing import Sequence, Union

from alembic import op


revision: str = "a65df9990a35"
down_revision: Union[str, Sequence[str], None] = "dc1f669b872e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the global UNIQUE(slug) constraint added by the workspaces baseline.
    op.drop_constraint("workspaces_slug_key", "workspaces", type_="unique")

    # Templates: globally unique slug (only one template per slug).
    op.execute(
        "CREATE UNIQUE INDEX ix_workspaces_slug_template_unique "
        "ON workspaces (slug) WHERE is_template = TRUE"
    )
    # Per-user instances: a user can't have two workspaces with the same slug,
    # but different users may each have one (and may share the template slug).
    op.execute(
        "CREATE UNIQUE INDEX ix_workspaces_user_slug_unique "
        "ON workspaces (user_id, slug) "
        "WHERE is_template = FALSE AND user_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_workspaces_user_slug_unique")
    op.execute("DROP INDEX IF EXISTS ix_workspaces_slug_template_unique")
    # Restoring the global UNIQUE(slug) is destructive when a per-user
    # instance shares a slug with another row (template or another user's
    # instance) — there's no schema room for the co-existence the partial
    # indexes allowed. Drop the non-template duplicates so the constraint
    # can be re-applied.
    op.execute("""
        DELETE FROM workspaces w
         WHERE w.is_template = FALSE
           AND EXISTS (
               SELECT 1 FROM workspaces w2
                WHERE w2.slug = w.slug
                  AND w2.id <> w.id
           )
    """)
    op.create_unique_constraint("workspaces_slug_key", "workspaces", ["slug"])
