"""add messages.role CHECK constraint

Revision ID: f3ae59ae02f5
Revises: c6bf15460b87
Create Date: 2026-05-14 07:03:38.586118

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f3ae59ae02f5"
down_revision: Union[str, Sequence[str], None] = "c6bf15460b87"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


VALID_ROLES = ("user", "assistant", "tool", "memory")


def upgrade() -> None:
    # Precondition: no existing row violates the new constraint.
    bind = op.get_bind()
    bad = bind.execute(
        sa.text(
            "SELECT count(*) FROM messages WHERE role NOT IN :roles"
        ).bindparams(sa.bindparam("roles", expanding=True)),
        {"roles": list(VALID_ROLES)},
    ).scalar()
    if bad:
        raise RuntimeError(
            f"Cannot add role CHECK: {bad} messages have a role outside "
            f"{VALID_ROLES}. Fix the data and re-run."
        )

    op.create_check_constraint(
        "messages_role_check",
        "messages",
        f"role IN {VALID_ROLES}",
    )


def downgrade() -> None:
    op.drop_constraint("messages_role_check", "messages", type_="check")
