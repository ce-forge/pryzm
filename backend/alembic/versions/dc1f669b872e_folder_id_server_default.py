"""folder_id_server_default

Revision ID: dc1f669b872e
Revises: 8cd618b90038
Create Date: 2026-05-18 05:17:31.729179

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'dc1f669b872e'
down_revision: Union[str, Sequence[str], None] = '8cd618b90038'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # folders.id is already PK NOT NULL. This migration confirms/documents
    # the constraint; the actual server-side default is the SQLAlchemy
    # column's default=generate_uuid (added in a model-update task).
    op.alter_column("folders", "id", nullable=False)


def downgrade() -> None:
    # No-op; column was already NOT NULL as a PK.
    pass
