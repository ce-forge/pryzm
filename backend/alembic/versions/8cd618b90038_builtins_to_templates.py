"""builtins_to_templates

Revision ID: 8cd618b90038
Revises: 712c74813064
Create Date: 2026-05-18 05:15:54.329067

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8cd618b90038'
down_revision: Union[str, Sequence[str], None] = '712c74813064'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        UPDATE workspaces
           SET is_template = TRUE,
               user_id = NULL
         WHERE slug IN ('it_copilot', 'personal')
           AND is_builtin = TRUE;
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE workspaces
           SET is_template = FALSE
         WHERE slug IN ('it_copilot', 'personal')
           AND is_builtin = TRUE;
    """)
