"""auth_phase_a_schema

Revision ID: 712c74813064
Revises: eb3a1f1e91ba
Create Date: 2026-05-18 05:13:23.442433

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '712c74813064'
down_revision: Union[str, Sequence[str], None] = 'eb3a1f1e91ba'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("can_create_workspaces", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_users_username_lower",
        "users",
        [sa.text("lower(username)")],
        unique=True,
    )

    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])

    op.add_column("workspaces", sa.Column("user_id", sa.String(), nullable=True))
    op.add_column("workspaces", sa.Column("is_template", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("workspaces", sa.Column("template_id", sa.String(), nullable=True))
    op.add_column("workspaces", sa.Column("owner_can_edit", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.create_index("ix_workspaces_user_id", "workspaces", ["user_id"])
    op.create_index("ix_workspaces_template_id", "workspaces", ["template_id"])

    op.add_column("sessions", sa.Column("user_id", sa.String(), nullable=True))
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])

    op.add_column("folders", sa.Column("user_id", sa.String(), nullable=True))
    op.create_index("ix_folders_user_id", "folders", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_folders_user_id", "folders")
    op.drop_column("folders", "user_id")
    op.drop_index("ix_sessions_user_id", "sessions")
    op.drop_column("sessions", "user_id")
    op.drop_index("ix_workspaces_template_id", "workspaces")
    op.drop_index("ix_workspaces_user_id", "workspaces")
    op.drop_column("workspaces", "owner_can_edit")
    op.drop_column("workspaces", "template_id")
    op.drop_column("workspaces", "is_template")
    op.drop_column("workspaces", "user_id")
    op.drop_index("ix_auth_sessions_user_id", "auth_sessions")
    op.drop_index("ix_auth_sessions_expires_at", "auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_index("ix_users_username_lower", "users")
    op.drop_table("users")
