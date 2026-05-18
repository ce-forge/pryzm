"""split_workspace_templates

Splits workspace blueprints out of the workspaces table:
  * Creates workspace_templates (admin-managed blueprints) with its own slug
    uniqueness.
  * Migrates template rows out of workspaces, preserving ids so
    workspaces.template_id FK refs remain valid.
  * Drops is_template, is_builtin, and the Phase A partial unique indexes
    from workspaces.
  * Adds UNIQUE(user_id, slug) on workspaces.
  * Repoints fk_workspaces_template_id at workspace_templates.id.
  * Adds workspaces.position (per-user ordering) and an index on
    (user_id, position).

Revision ID: 5f645f0d5313
Revises: f0d03905ddc4
Create Date: 2026-05-18 14:32:13.789922

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5f645f0d5313'
down_revision: Union[str, Sequence[str], None] = 'f0d03905ddc4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create workspace_templates
    op.create_table(
        "workspace_templates",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("enabled_tools", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("color", sa.String(), nullable=True),
        sa.Column("engine_config", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_unique_constraint("uq_workspace_templates_slug", "workspace_templates", ["slug"])

    # 2. Copy template rows out (preserve id so existing FK refs stay valid)
    op.execute("""
        INSERT INTO workspace_templates (id, slug, display_name, system_prompt, enabled_tools, color, engine_config, created_at)
        SELECT id, slug, display_name, system_prompt, enabled_tools, color, engine_config, created_at
        FROM workspaces
        WHERE is_template = TRUE;
    """)

    # 3. Drop existing template_id FK so it can be repointed
    op.drop_constraint("fk_workspaces_template_id", "workspaces", type_="foreignkey")

    # 4. Delete template rows from workspaces
    op.execute("DELETE FROM workspaces WHERE is_template = TRUE;")

    # 5. Drop Phase A partial unique indexes
    op.execute("DROP INDEX IF EXISTS ix_workspaces_slug_template_unique;")
    op.execute("DROP INDEX IF EXISTS ix_workspaces_user_slug_unique;")

    # 6. Drop is_template and is_builtin columns
    op.drop_column("workspaces", "is_template")
    op.drop_column("workspaces", "is_builtin")

    # 7. New simple unique constraint: a user can't reuse a slug across their workspaces
    op.create_unique_constraint("uq_workspaces_user_slug", "workspaces", ["user_id", "slug"])

    # 8. Re-create template_id FK pointing at workspace_templates
    op.create_foreign_key(
        "fk_workspaces_template_id",
        "workspaces", "workspace_templates",
        ["template_id"], ["id"],
        ondelete="SET NULL",
    )

    # 9. Per-user ordering column
    op.add_column("workspaces", sa.Column("position", sa.Integer(), nullable=False, server_default="0"))
    op.create_index("ix_workspaces_user_position", "workspaces", ["user_id", "position"])


def downgrade() -> None:
    # Drop position
    op.drop_index("ix_workspaces_user_position", "workspaces")
    op.drop_column("workspaces", "position")

    # Drop the simple unique
    op.drop_constraint("uq_workspaces_user_slug", "workspaces", type_="unique")

    # Drop the FK so it can be repointed
    op.drop_constraint("fk_workspaces_template_id", "workspaces", type_="foreignkey")

    # Re-add columns
    op.add_column("workspaces", sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("workspaces", sa.Column("is_template", sa.Boolean(), nullable=False, server_default=sa.text("false")))

    # Copy templates back into workspaces
    op.execute("""
        INSERT INTO workspaces (id, slug, display_name, system_prompt, enabled_tools, color, engine_config, created_at, is_template, is_builtin, user_id, template_id, owner_can_edit)
        SELECT id, slug, display_name, system_prompt, enabled_tools, color, engine_config, created_at, TRUE, TRUE, NULL, NULL, FALSE
        FROM workspace_templates;
    """)

    # Repoint FK back to workspaces.id
    op.create_foreign_key(
        "fk_workspaces_template_id",
        "workspaces", "workspaces",
        ["template_id"], ["id"],
        ondelete="SET NULL",
    )

    # Restore Phase A partial unique indexes
    op.execute(
        "CREATE UNIQUE INDEX ix_workspaces_slug_template_unique "
        "ON workspaces (slug) WHERE is_template = TRUE;"
    )
    op.execute(
        "CREATE UNIQUE INDEX ix_workspaces_user_slug_unique "
        "ON workspaces (user_id, slug) "
        "WHERE is_template = FALSE AND user_id IS NOT NULL;"
    )

    # Drop workspace_templates
    op.drop_constraint("uq_workspace_templates_slug", "workspace_templates", type_="unique")
    op.drop_table("workspace_templates")
