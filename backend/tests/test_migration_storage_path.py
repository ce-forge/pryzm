"""Verifies migration b4fac9a8c30f: add documents.storage_path column.

VLM Milestone 2. The column is nullable; existing rows are unaffected
on upgrade. Downgrade drops the column without backfill.
"""
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool


def test_upgrade_adds_storage_path_column(db_at_revision, alembic_cfg):
    """At the parent revision the column doesn't exist; after the upgrade it does."""
    engine = db_at_revision("de5dfc455310")
    with engine.connect() as conn:
        before = conn.execute(text("""
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'documents' AND column_name = 'storage_path'
        """)).scalar()
    engine.dispose()
    assert before is None

    command.upgrade(alembic_cfg, "b4fac9a8c30f")

    fresh = create_engine(alembic_cfg.get_main_option("sqlalchemy.url"), poolclass=NullPool)
    with fresh.connect() as conn:
        after = conn.execute(text("""
            SELECT data_type, is_nullable, character_maximum_length
            FROM information_schema.columns
            WHERE table_name = 'documents' AND column_name = 'storage_path'
        """)).first()
    fresh.dispose()
    assert after is not None
    assert after.is_nullable == "YES"
    assert after.character_maximum_length == 512


def test_downgrade_removes_storage_path_column(reset_test_db, alembic_cfg):
    """Downgrade from b4fac9a8c30f drops the column cleanly."""
    command.downgrade(alembic_cfg, "base")
    command.upgrade(alembic_cfg, "head")
    command.downgrade(alembic_cfg, "de5dfc455310")

    engine = create_engine(reset_test_db, poolclass=NullPool)
    with engine.connect() as conn:
        col = conn.execute(text("""
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'documents' AND column_name = 'storage_path'
        """)).scalar()
    engine.dispose()
    assert col is None


def test_existing_documents_get_null_storage_path_on_upgrade(db_at_revision, alembic_cfg):
    """Backfill behavior: rows that existed before the upgrade keep storage_path NULL."""
    engine = db_at_revision("de5dfc455310")
    with engine.begin() as conn:
        # Seed a workspace and a document at the parent revision.
        conn.execute(text(
            "INSERT INTO workspaces (id, slug, display_name, system_prompt, enabled_tools, engine_config, is_builtin) "
            "VALUES ('ws-pre', 'ws-pre', 'Pre', '', '[]'::jsonb, '{}'::jsonb, false)"
        ))
        conn.execute(text(
            "INSERT INTO documents (id, filename, workspace_id, is_global) "
            "VALUES ('doc-pre', 'old.txt', 'ws-pre', false)"
        ))
    engine.dispose()

    command.upgrade(alembic_cfg, "b4fac9a8c30f")

    fresh = create_engine(alembic_cfg.get_main_option("sqlalchemy.url"), poolclass=NullPool)
    with fresh.connect() as conn:
        sp = conn.execute(text(
            "SELECT storage_path FROM documents WHERE id = 'doc-pre'"
        )).scalar()
    fresh.dispose()
    assert sp is None
