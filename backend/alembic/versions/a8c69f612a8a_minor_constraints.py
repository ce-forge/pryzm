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
    # Precondition: no orphan messages.
    bind = op.get_bind()
    bad = bind.execute(
        sa.text("SELECT count(*) FROM messages WHERE session_id IS NULL")
    ).scalar()
    if bad:
        raise RuntimeError(
            f"Cannot set messages.session_id NOT NULL: {bad} rows have NULL. "
            "Delete or fix the orphans and re-run."
        )

    op.alter_column("messages", "session_id", nullable=False)
    op.alter_column(
        "documents", "is_global",
        server_default=sa.text("false"),
    )


def downgrade() -> None:
    op.alter_column("documents", "is_global", server_default=None)
    op.alter_column("messages", "session_id", nullable=True)
