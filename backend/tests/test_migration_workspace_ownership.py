"""Phase B workspace ownership constraints migration."""
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import NullPool

from tests.conftest import _test_database_url


def test_workspace_ownership_constraints(db_at_revision, alembic_cfg):
    from alembic import command

    # Pre-state: at the previous head, columns are nullable, no FKs.
    engine = db_at_revision("a65df9990a35")
    inspector = inspect(engine)
    session_cols = inspector.get_columns("sessions")
    user_id_col = next(c for c in session_cols if c["name"] == "user_id")
    assert user_id_col["nullable"] is True
    engine.dispose()

    # Seed: one admin + one workspace/session/folder owned by that admin
    # (mimicking Phase A bootstrap backfill). The seed predates Phase B's
    # NOT NULL, so the migration's alter must succeed.
    engine = create_engine(_test_database_url(), poolclass=NullPool)
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO users (id, username, password_hash, is_admin, is_active, can_create_workspaces, created_at)
            VALUES ('u-admin', 'admin', 'dummy', TRUE, TRUE, TRUE, NOW());
        """))
        conn.execute(text("""
            INSERT INTO workspaces (id, slug, display_name, system_prompt, enabled_tools, is_builtin, is_template, user_id, engine_config, created_at)
            VALUES ('ws-x', 'ws-x', 'X', '', '[]'::jsonb, FALSE, FALSE, 'u-admin', '{"backend":"llama_cpp"}'::jsonb, NOW());
        """))
        conn.execute(text("""
            INSERT INTO sessions (id, workspace_id, title, user_id, created_at)
            VALUES ('s-x', 'ws-x', 'session', 'u-admin', NOW());
        """))
        # folders has no created_at column.
        conn.execute(text("""
            INSERT INTO folders (id, workspace_id, name, user_id)
            VALUES ('f-x', 'ws-x', 'folder', 'u-admin');
        """))
    engine.dispose()

    # Upgrade — must succeed because every row has user_id.
    command.upgrade(alembic_cfg, "head")

    engine = create_engine(_test_database_url(), poolclass=NullPool)
    inspector = inspect(engine)

    session_cols = inspector.get_columns("sessions")
    user_id_col = next(c for c in session_cols if c["name"] == "user_id")
    assert user_id_col["nullable"] is False

    folder_cols = inspector.get_columns("folders")
    user_id_col = next(c for c in folder_cols if c["name"] == "user_id")
    assert user_id_col["nullable"] is False

    session_fks = {fk["name"] for fk in inspector.get_foreign_keys("sessions")}
    assert "fk_sessions_user_id" in session_fks

    folder_fks = {fk["name"] for fk in inspector.get_foreign_keys("folders")}
    assert "fk_folders_user_id" in folder_fks

    workspace_fks = {fk["name"] for fk in inspector.get_foreign_keys("workspaces")}
    assert "fk_workspaces_user_id" in workspace_fks
    assert "fk_workspaces_template_id" in workspace_fks

    engine.dispose()

    # Downgrade
    command.downgrade(alembic_cfg, "a65df9990a35")
    engine = create_engine(_test_database_url(), poolclass=NullPool)
    inspector = inspect(engine)
    session_cols = inspector.get_columns("sessions")
    user_id_col = next(c for c in session_cols if c["name"] == "user_id")
    assert user_id_col["nullable"] is True
    engine.dispose()
