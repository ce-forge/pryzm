"""Verifies migration d2f9c4e7a8b1: add messages.tool_calls JSONB column."""
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool


def test_upgrade_adds_tool_calls_column(db_at_revision, alembic_cfg):
    """At parent revision the column doesn't exist; after upgrade it does."""
    engine = db_at_revision("c1f8b27a4d56")
    with engine.connect() as conn:
        before = conn.execute(text("""
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'messages' AND column_name = 'tool_calls'
        """)).scalar()
    engine.dispose()
    assert before is None

    command.upgrade(alembic_cfg, "d2f9c4e7a8b1")

    fresh = create_engine(alembic_cfg.get_main_option("sqlalchemy.url"), poolclass=NullPool)
    with fresh.connect() as conn:
        col = conn.execute(text("""
            SELECT data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'messages' AND column_name = 'tool_calls'
        """)).first()
    fresh.dispose()
    assert col is not None
    assert col.data_type == "jsonb"
    assert col.is_nullable == "YES"


def test_downgrade_removes_tool_calls_column(reset_test_db, alembic_cfg):
    """Downgrade from d2f9c4e7a8b1 drops the column cleanly."""
    command.downgrade(alembic_cfg, "base")
    command.upgrade(alembic_cfg, "head")
    command.downgrade(alembic_cfg, "c1f8b27a4d56")

    engine = create_engine(reset_test_db, poolclass=NullPool)
    with engine.connect() as conn:
        col = conn.execute(text("""
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'messages' AND column_name = 'tool_calls'
        """)).scalar()
    engine.dispose()
    assert col is None
