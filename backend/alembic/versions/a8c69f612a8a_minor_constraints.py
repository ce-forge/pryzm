"""minor constraint fixes

Revision ID: a8c69f612a8a
Revises: 50d45d7ba8d6
Create Date: 2026-05-14 07:15:05.142229

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a8c69f612a8a"
down_revision: Union[str, Sequence[str], None] = "50d45d7ba8d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # Preconditions: no orphan rows that would violate the new constraints.
    orphan_messages = bind.execute(
        sa.text("SELECT count(*) FROM messages WHERE session_id IS NULL")
    ).scalar()
    if orphan_messages:
        raise RuntimeError(
            f"Cannot set messages.session_id NOT NULL: {orphan_messages} rows have NULL. "
            "Delete or fix the orphans and re-run."
        )

    null_is_global = bind.execute(
        sa.text("SELECT count(*) FROM documents WHERE is_global IS NULL")
    ).scalar()
    if null_is_global:
        raise RuntimeError(
            f"Cannot set documents.is_global NOT NULL: {null_is_global} rows have NULL. "
            "Backfill with UPDATE documents SET is_global = false WHERE is_global IS NULL."
        )

    op.alter_column("messages", "session_id", nullable=False)
    op.alter_column(
        "documents", "is_global",
        server_default=sa.text("false"),
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column("documents", "is_global", server_default=None, nullable=True)
    op.alter_column("messages", "session_id", nullable=True)
