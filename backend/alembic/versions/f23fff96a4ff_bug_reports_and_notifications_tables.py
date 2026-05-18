"""bug_reports and notifications tables

Revision ID: f23fff96a4ff
Revises: 9221fabaf142
Create Date: 2026-05-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'f23fff96a4ff'
down_revision: Union[str, Sequence[str], None] = '9221fabaf142'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bug_reports",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "user_id", sa.String(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True, index=True,
        ),
        # Snapshot — survives a hard delete of the reporter.
        sa.Column("user_display_name", sa.Text(), nullable=False),
        sa.Column(
            "workspace_id", sa.String(),
            sa.ForeignKey("workspaces.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "session_id", sa.String(),
            sa.ForeignKey("sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "payload", postgresql.JSONB(),
            nullable=False, server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "status", sa.Text(),
            nullable=False, server_default=sa.text("'open'"),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "resolved_by", sa.String(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "category IN ('incorrect_info','vision_wrong','tool_error',"
            "'slow','ui_bug','other')",
            name="bug_reports_category_check",
        ),
        sa.CheckConstraint(
            "status IN ('open','acknowledged','resolved','dismissed')",
            name="bug_reports_status_check",
        ),
    )
    op.create_index(
        "ix_bug_reports_status_created",
        "bug_reports",
        ["status", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_bug_reports_user_created",
        "bug_reports",
        ["user_id", sa.text("created_at DESC")],
    )

    op.create_table(
        "notifications",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "user_id", sa.String(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=True),
        sa.Column("link_url", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_notifications_user_seen",
        "notifications",
        ["user_id", "seen_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_user_seen", table_name="notifications")
    op.drop_table("notifications")
    op.drop_index("ix_bug_reports_user_created", table_name="bug_reports")
    op.drop_index("ix_bug_reports_status_created", table_name="bug_reports")
    op.drop_table("bug_reports")
