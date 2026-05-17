"""drop deprecated workspaces.preferred_model

engine_config.model is the single source of truth; this drops the
redundant column.

Revision ID: bf317b5870ef
Revises: a8c69f612a8a
Create Date: 2026-05-14 11:50:24.424200

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "bf317b5870ef"
down_revision: Union[str, Sequence[str], None] = "a8c69f612a8a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("workspaces", "preferred_model")


def downgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column("preferred_model", sa.String(), nullable=True),
    )
    op.execute("""
        UPDATE workspaces
        SET preferred_model = engine_config->>'model'
        WHERE engine_config IS NOT NULL
    """)
