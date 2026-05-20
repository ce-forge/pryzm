"""partial indices on SET NULL FK columns (D3)

Revision ID: d4f1e8a9c2b5
Revises: c7f2e9a1b8d3
Create Date: 2026-05-21 03:30:00.000000

Adds partial indices on `bug_reports.resolved_by` and
`audit_events.session_id`. Both have ON DELETE SET NULL FKs to users
and sessions respectively; without these indices, hard-deleting an
admin user or a chat session triggers a full table scan to find rows
needing the NULL update. Partial-only (WHERE … IS NOT NULL) keeps the
index small since the vast majority of audit_events rows have NULL
session_id.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "d4f1e8a9c2b5"
down_revision: Union[str, Sequence[str], None] = "c7f2e9a1b8d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # bug_reports is a plain table → CONCURRENTLY is preferred so admin
    # browsing doesn't block while the index builds.
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_bug_reports_resolved_by ON bug_reports(resolved_by) "
            "WHERE resolved_by IS NOT NULL"
        )
    # audit_events is a RANGE-partitioned table. Postgres refuses
    # CREATE INDEX CONCURRENTLY on partitioned parents — the partitioned
    # index needs a single atomic step to register the child indices.
    # Per-partition data volumes are small (monthly buckets, retention
    # cap = 90 days), so the brief AccessExclusiveLock is acceptable.
    op.execute(
        "CREATE INDEX IF NOT EXISTS "
        "ix_audit_events_session_id ON audit_events(session_id) "
        "WHERE session_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_audit_events_session_id")
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_bug_reports_resolved_by")
