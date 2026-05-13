"""add document_chunks.workspace_id

Revision ID: c6bf15460b87
Revises: 78445f9618d3
Create Date: 2026-05-14 06:56:05.431695

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c6bf15460b87"
down_revision: Union[str, Sequence[str], None] = "78445f9618d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Nullable column so backfill can populate it.
    op.add_column(
        "document_chunks",
        sa.Column("workspace_id", sa.String(), nullable=True),
    )

    # 2. Backfill from parent document.
    op.execute(
        """
        UPDATE document_chunks dc
        SET workspace_id = d.workspace_id
        FROM documents d
        WHERE dc.document_id = d.id
        """
    )

    # 3. NOT NULL.
    op.alter_column("document_chunks", "workspace_id", nullable=False)

    # 4. FK with CASCADE delete.
    op.create_foreign_key(
        "fk_chunks_workspace_id",
        "document_chunks", "workspaces",
        ["workspace_id"], ["id"],
        ondelete="CASCADE",
    )

    # 5. Composite index for (workspace_id, document_id) lookups.
    op.create_index(
        "ix_chunks_workspace_document",
        "document_chunks",
        ["workspace_id", "document_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_chunks_workspace_document", table_name="document_chunks")
    op.drop_constraint("fk_chunks_workspace_id", "document_chunks", type_="foreignkey")
    op.drop_column("document_chunks", "workspace_id")
