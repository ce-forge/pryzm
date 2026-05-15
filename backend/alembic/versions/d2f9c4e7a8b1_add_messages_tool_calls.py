"""add messages.tool_calls JSONB column

Revision ID: d2f9c4e7a8b1
Revises: c1f8b27a4d56
Create Date: 2026-05-15 23:30:00.000000

Stores the list of tool calls executed during an assistant turn as a
structured JSONB array of {name, args, result} objects. Lets us re-emit
proper OpenAI-style {role: "assistant", tool_calls: ...} + {role: "tool"}
messages to the LLM on subsequent turns, instead of flattening tool
markdown into the assistant's content blob.

Shape: NULL when the assistant turn made no tool calls (the common case);
otherwise a JSON array. NULL is also the legacy shape — pre-migration
rows keep using the single-content blob and history-rebuild handles them.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d2f9c4e7a8b1"
down_revision: Union[str, Sequence[str], None] = "c1f8b27a4d56"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column(
            "tool_calls",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("messages", "tool_calls")
