"""add users.allowed_tools

Revision ID: c91578c70205
Revises: f23fff96a4ff
Create Date: 2026-05-19 17:49:37.825315

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "c91578c70205"
down_revision = "f23fff96a4ff"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "allowed_tools",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "allowed_tools")
