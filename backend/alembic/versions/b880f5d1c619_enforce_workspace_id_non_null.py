"""enforce workspace_id non-null and drop old string columns

Revision ID: b880f5d1c619
Revises: 58c8b7524030
Create Date: 2026-05-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b880f5d1c619"
down_revision: Union[str, Sequence[str], None] = "58c8b7524030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NOT NULL + FK constraints on the new workspace_id columns.
    op.alter_column("sessions", "workspace_id", nullable=False)
    op.alter_column("folders", "workspace_id", nullable=False)
    op.alter_column("documents", "workspace_id", nullable=False)

    op.create_foreign_key(
        "fk_sessions_workspace_id",
        "sessions", "workspaces",
        ["workspace_id"], ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_folders_workspace_id",
        "folders", "workspaces",
        ["workspace_id"], ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_documents_workspace_id",
        "documents", "workspaces",
        ["workspace_id"], ["id"],
        ondelete="CASCADE",
    )

    # Drop the old string columns.
    op.drop_column("sessions", "mode")
    op.drop_column("folders", "workspace")
    op.drop_column("documents", "workspace")


def downgrade() -> None:
    # NOTE: this downgrade is lossy — the old string columns are recreated with
    # NULL, which means the second migration cannot be rolled back without
    # losing the mode/workspace classification. Only roll back if the data
    # loss is acceptable (it's also why we split into two migrations).
    op.add_column("sessions", sa.Column("mode", sa.String(), nullable=True))
    op.add_column("folders", sa.Column("workspace", sa.String(), nullable=True))
    op.add_column("documents", sa.Column("workspace", sa.String(), nullable=True))

    op.drop_constraint("fk_documents_workspace_id", "documents", type_="foreignkey")
    op.drop_constraint("fk_folders_workspace_id", "folders", type_="foreignkey")
    op.drop_constraint("fk_sessions_workspace_id", "sessions", type_="foreignkey")

    op.alter_column("documents", "workspace_id", nullable=True)
    op.alter_column("folders", "workspace_id", nullable=True)
    op.alter_column("sessions", "workspace_id", nullable=True)
