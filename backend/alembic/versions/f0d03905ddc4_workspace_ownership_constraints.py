"""workspace_ownership_constraints

Revision ID: f0d03905ddc4
Revises: a65df9990a35
Create Date: 2026-05-18 10:35:18.348576

Locks in workspace ownership wiring added in Phase A:
  * sessions.user_id and folders.user_id become NOT NULL.
  * FK sessions.user_id  -> users.id           (ON DELETE CASCADE)
  * FK folders.user_id   -> users.id           (ON DELETE CASCADE)
  * FK workspaces.user_id    -> users.id       (ON DELETE CASCADE; nullable
    so templates can keep a NULL owner)
  * FK workspaces.template_id -> workspaces.id (ON DELETE SET NULL)

Assumes Phase A's bootstrap backfilled user_id on every non-template
workspace/session/folder. Any orphan row will trip the NOT NULL alter.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'f0d03905ddc4'
down_revision: Union[str, Sequence[str], None] = 'a65df9990a35'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("sessions", "user_id", nullable=False)
    op.alter_column("folders", "user_id", nullable=False)

    op.create_foreign_key(
        "fk_sessions_user_id",
        "sessions", "users",
        ["user_id"], ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_folders_user_id",
        "folders", "users",
        ["user_id"], ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_workspaces_user_id",
        "workspaces", "users",
        ["user_id"], ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_workspaces_template_id",
        "workspaces", "workspaces",
        ["template_id"], ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_workspaces_template_id", "workspaces", type_="foreignkey")
    op.drop_constraint("fk_workspaces_user_id", "workspaces", type_="foreignkey")
    op.drop_constraint("fk_folders_user_id", "folders", type_="foreignkey")
    op.drop_constraint("fk_sessions_user_id", "sessions", type_="foreignkey")
    op.alter_column("folders", "user_id", nullable=True)
    op.alter_column("sessions", "user_id", nullable=True)
