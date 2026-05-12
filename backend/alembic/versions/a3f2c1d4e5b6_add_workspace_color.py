"""add workspace color

Revision ID: a3f2c1d4e5b6
Revises: b880f5d1c619
Create Date: 2026-05-12 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a3f2c1d4e5b6"
down_revision: Union[str, Sequence[str], None] = "b880f5d1c619"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("workspaces", sa.Column("color", sa.String(length=32), nullable=True))

    conn = op.get_bind()
    conn.execute(sa.text("UPDATE workspaces SET color = 'orange' WHERE slug = 'personal' AND color IS NULL"))
    conn.execute(sa.text("UPDATE workspaces SET color = 'blue' WHERE slug = 'it_copilot' AND color IS NULL"))


def downgrade() -> None:
    op.drop_column("workspaces", "color")
