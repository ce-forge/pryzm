"""add messages reasoning_content + reasoning_duration_s

Revision ID: e4f1c5a8d72b
Revises: c91578c70205
Create Date: 2026-05-20 02:55:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "e4f1c5a8d72b"
down_revision = "c91578c70205"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("reasoning_content", sa.Text(), nullable=True))
    op.add_column("messages", sa.Column("reasoning_duration_s", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "reasoning_duration_s")
    op.drop_column("messages", "reasoning_content")
