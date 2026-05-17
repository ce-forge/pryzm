"""session_folder_fk

Revision ID: eb3a1f1e91ba
Revises: f8d3b1c5a2e9
Create Date: 2026-05-18 02:32:27.853994

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'eb3a1f1e91ba'
down_revision: Union[str, Sequence[str], None] = 'f8d3b1c5a2e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        UPDATE sessions
           SET folder_id = NULL
         WHERE folder_id IS NOT NULL
           AND folder_id NOT IN (
               SELECT id FROM folders
                WHERE folders.workspace_id = sessions.workspace_id
           );
    """)
    op.create_foreign_key(
        "fk_sessions_folder_id",
        "sessions", "folders",
        ["folder_id"], ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_sessions_folder_id", "sessions", type_="foreignkey")
