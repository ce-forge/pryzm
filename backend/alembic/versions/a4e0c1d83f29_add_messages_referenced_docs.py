"""add messages.referenced_docs JSONB column

Revision ID: a4e0c1d83f29
Revises: 7a91b3e2d5c1
Create Date: 2026-05-15 20:55:00.000000

Persists the list of image documents the auto-RAG / tool path
retrieved alongside an assistant turn. Lets the chat surface re-render
inline image previews after a page reload — without this, the
files_referenced SSE events only live in volatile frontend state and
disappear on refresh.

Shape: NULL when the assistant turn referenced no files (common case);
otherwise a JSON array of {id, filename, mime} objects mirroring the
SSE event payload. NULL is intentional — the column adds essentially
zero storage cost for turns without referenced files.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a4e0c1d83f29"
down_revision: Union[str, Sequence[str], None] = "7a91b3e2d5c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column(
            "referenced_docs",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("messages", "referenced_docs")
