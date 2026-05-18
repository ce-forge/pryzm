"""audit_events_schema

Revision ID: 9221fabaf142
Revises: 3378c828bea0
Create Date: 2026-05-18 20:56:59.153125

"""
from datetime import datetime, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9221fabaf142'
down_revision: Union[str, Sequence[str], None] = '3378c828bea0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Postgres requires the primary key of a partitioned table to include
    # every partition-key column, so the PK is composite (id, created_at).
    # `id` remains the application-level identifier.
    op.execute(sa.text("""
        CREATE TABLE audit_events (
            id VARCHAR NOT NULL,
            user_id VARCHAR,
            user_display_name_at_event TEXT,
            event_type TEXT NOT NULL,
            workspace_id VARCHAR,
            session_id VARCHAR,
            resource_type TEXT,
            resource_id VARCHAR,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            source_ip TEXT,
            user_agent TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (id, created_at),
            CONSTRAINT fk_audit_user FOREIGN KEY (user_id)
                REFERENCES users(id) ON DELETE SET NULL,
            CONSTRAINT fk_audit_workspace FOREIGN KEY (workspace_id)
                REFERENCES workspaces(id) ON DELETE SET NULL,
            CONSTRAINT fk_audit_session FOREIGN KEY (session_id)
                REFERENCES sessions(id) ON DELETE SET NULL
        ) PARTITION BY RANGE (created_at);
    """))

    op.execute(sa.text(
        "CREATE INDEX ix_audit_events_user_created "
        "ON audit_events (user_id, created_at DESC);"
    ))
    op.execute(sa.text(
        "CREATE INDEX ix_audit_events_event_type_created "
        "ON audit_events (event_type, created_at DESC);"
    ))
    op.execute(sa.text(
        "CREATE INDEX ix_audit_events_workspace_created "
        "ON audit_events (workspace_id, created_at DESC);"
    ))

    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION audit_events_no_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'audit_events is append-only';
        END;
        $$ LANGUAGE plpgsql;
    """))
    op.execute(sa.text("""
        CREATE TRIGGER audit_events_no_update
          BEFORE UPDATE ON audit_events
          FOR EACH ROW EXECUTE FUNCTION audit_events_no_mutation();
    """))
    op.execute(sa.text("""
        CREATE TRIGGER audit_events_no_delete
          BEFORE DELETE ON audit_events
          FOR EACH ROW EXECUTE FUNCTION audit_events_no_mutation();
    """))

    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if now.month == 12:
        next_month_start = month_start.replace(year=now.year + 1, month=1)
    else:
        next_month_start = month_start.replace(month=now.month + 1)
    partition_name = f"audit_events_y{month_start.year}m{month_start.month:02d}"
    op.execute(sa.text(
        f"CREATE TABLE {partition_name} PARTITION OF audit_events "
        f"FOR VALUES FROM ('{month_start.isoformat()}') "
        f"TO ('{next_month_start.isoformat()}');"
    ))


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TRIGGER IF EXISTS audit_events_no_delete ON audit_events;")
    op.execute("DROP TRIGGER IF EXISTS audit_events_no_update ON audit_events;")
    op.execute("DROP FUNCTION IF EXISTS audit_events_no_mutation();")
    # Dropping the parent drops all child partitions too.
    op.execute("DROP TABLE IF EXISTS audit_events CASCADE;")
