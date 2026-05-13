"""Smoke test for the test-DB fixture infrastructure.

This test passes as soon as the conftest can spin up an ephemeral test DB,
run alembic to head, and hand back a working SQLAlchemy connection.
"""
from sqlalchemy import text


def test_db_at_head_exposes_workspaces_table(db_at_head):
    engine = db_at_head
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'workspaces'"
        ))
        assert result.scalar() == "workspaces"


def test_db_at_revision_can_walk_history(db_at_revision):
    engine = db_at_revision("b880f5d1c619")
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT version_num FROM alembic_version"
        ))
        assert result.scalar() == "b880f5d1c619"
