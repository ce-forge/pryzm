"""add documents.status and documents.error_message

Async-ingestion PR 1 (docs/specs/2026-05-15-async-ingestion.md):
`/upload` will return early with status='processing' and run the
captioning pipeline in a background task. The two new columns track
that state on the row itself, so the SSE endpoint can answer "what
is the current state?" without depending on the broker for state
that may have already fired.

Existing rows are all already ingested → server_default 'ready'
backfills them correctly at upgrade time.

Revision ID: 53f0bcb1ae0d
Revises: b4fac9a8c30f
Create Date: 2026-05-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "53f0bcb1ae0d"
down_revision: Union[str, Sequence[str], None] = "b4fac9a8c30f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="ready",
        ),
    )
    op.add_column(
        "documents",
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_check_constraint(
        "documents_status_check",
        "documents",
        "status IN ('processing', 'ready', 'error')",
    )


def downgrade() -> None:
    op.drop_constraint("documents_status_check", "documents", type_="check")
    op.drop_column("documents", "error_message")
    op.drop_column("documents", "status")
