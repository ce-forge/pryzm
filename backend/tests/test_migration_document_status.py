"""Verifies migration 53f0bcb1ae0d: add documents.status + error_message.

Status column carries 'processing' / 'ready' / 'error'; error_message
is populated only on error. Existing rows backfill to 'ready' at upgrade.
"""
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool


def test_upgrade_adds_status_and_error_message(db_at_revision, alembic_cfg):
    engine = db_at_revision("b4fac9a8c30f")
    with engine.connect() as conn:
        before = conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'documents' AND column_name IN ('status', 'error_message')
        """)).fetchall()
    engine.dispose()
    assert not before

    command.upgrade(alembic_cfg, "53f0bcb1ae0d")

    fresh = create_engine(alembic_cfg.get_main_option("sqlalchemy.url"), poolclass=NullPool)
    with fresh.connect() as conn:
        cols = conn.execute(text("""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_name = 'documents' AND column_name IN ('status', 'error_message')
            ORDER BY column_name
        """)).fetchall()
    fresh.dispose()
    by_name = {row.column_name: row for row in cols}
    assert by_name["status"].is_nullable == "NO"
    assert "ready" in (by_name["status"].column_default or "")
    assert by_name["error_message"].is_nullable == "YES"
    assert by_name["error_message"].data_type == "text"


def test_downgrade_drops_status_and_error_message(reset_test_db, alembic_cfg):
    command.downgrade(alembic_cfg, "base")
    command.upgrade(alembic_cfg, "head")
    command.downgrade(alembic_cfg, "b4fac9a8c30f")

    engine = create_engine(reset_test_db, poolclass=NullPool)
    with engine.connect() as conn:
        cols = conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'documents' AND column_name IN ('status', 'error_message')
        """)).fetchall()
    engine.dispose()
    assert not cols, f"columns should be gone after downgrade; got {cols!r}"


def test_existing_rows_backfill_to_ready_on_upgrade(db_at_revision, alembic_cfg):
    """Pre-migration documents (all already ingested) must end up with
    status='ready' so the SSE endpoint and any status-aware queries treat
    them correctly."""
    engine = db_at_revision("b4fac9a8c30f")
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO workspaces (id, slug, display_name, system_prompt, enabled_tools, engine_config, is_builtin) "
            "VALUES ('ws-pre', 'ws-pre', 'Pre', '', '[]'::jsonb, '{}'::jsonb, false)"
        ))
        conn.execute(text(
            "INSERT INTO documents (id, filename, workspace_id, is_global) "
            "VALUES ('doc-pre', 'old.txt', 'ws-pre', false)"
        ))
    engine.dispose()

    command.upgrade(alembic_cfg, "53f0bcb1ae0d")

    fresh = create_engine(alembic_cfg.get_main_option("sqlalchemy.url"), poolclass=NullPool)
    with fresh.connect() as conn:
        row = conn.execute(text(
            "SELECT status, error_message FROM documents WHERE id = 'doc-pre'"
        )).first()
    fresh.dispose()
    assert row.status == "ready"
    assert row.error_message is None


def test_status_check_constraint_rejects_invalid_value(reset_test_db, alembic_cfg):
    """The CHECK constraint must reject anything outside the three known
    states so bad code doesn't silently land bogus values."""
    command.upgrade(alembic_cfg, "head")
    engine = create_engine(reset_test_db, poolclass=NullPool)
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO workspaces (id, slug, display_name, system_prompt, enabled_tools, engine_config) "
            "VALUES ('ws-c', 'ws-c', 'C', '', '[]'::jsonb, '{}'::jsonb)"
        ))
    import sqlalchemy.exc
    with engine.begin() as conn:
        try:
            conn.execute(text(
                "INSERT INTO documents (id, filename, workspace_id, is_global, status) "
                "VALUES ('doc-bad', 'x.txt', 'ws-c', false, 'unknown')"
            ))
            engine.dispose()
            assert False, "expected CHECK constraint to reject unknown status"
        except sqlalchemy.exc.IntegrityError:
            pass
    engine.dispose()
