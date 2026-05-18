"""add_users_must_change_password

Revision ID: 3378c828bea0
Revises: 5f645f0d5313
Create Date: 2026-05-18 18:22:06.028074

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3378c828bea0'
down_revision: Union[str, Sequence[str], None] = '5f645f0d5313'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # Existing admins may have been seeded with the weak default "admin"
    # password (see core.bootstrap). Flag every admin as needing a change;
    # operators with their own strong password can clear it via SQL or the
    # password-change endpoint.
    op.execute(
        "UPDATE users SET must_change_password = TRUE WHERE is_admin = TRUE"
    )


def downgrade() -> None:
    op.drop_column("users", "must_change_password")
