"""add pgvector ivfflat index on document_chunks.embedding

Revision ID: 50d45d7ba8d6
Revises: f3ae59ae02f5
Create Date: 2026-05-14 07:09:21.698291

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "50d45d7ba8d6"
down_revision: Union[str, Sequence[str], None] = "f3ae59ae02f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # CONCURRENTLY avoids locking writes; it can't run inside a transaction,
    # so we use alembic's autocommit_block to escape the migration's tx.
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_chunks_embedding "
            "ON document_chunks USING ivfflat "
            "(embedding vector_cosine_ops) WITH (lists = 100)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_chunks_embedding")
