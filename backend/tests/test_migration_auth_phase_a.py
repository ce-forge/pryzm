"""Phase A schema migration: tables + columns + indexes."""
from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import NullPool

from tests.conftest import _test_database_url


def test_auth_phase_a_schema_upgrades_and_downgrades(db_at_revision, alembic_cfg):
    from alembic import command

    # Upgrade to the migration just before ours
    engine = db_at_revision("eb3a1f1e91ba")
    inspector = inspect(engine)
    assert "users" not in inspector.get_table_names()
    engine.dispose()

    # Upgrade through our migration
    command.upgrade(alembic_cfg, "head")
    engine = create_engine(_test_database_url(), poolclass=NullPool)
    inspector = inspect(engine)

    assert "users" in inspector.get_table_names()
    assert "auth_sessions" in inspector.get_table_names()

    user_cols = {c["name"] for c in inspector.get_columns("users")}
    assert {"id", "username", "password_hash", "email", "is_admin",
            "is_active", "can_create_workspaces", "created_at", "last_login_at"} <= user_cols

    auth_session_cols = {c["name"] for c in inspector.get_columns("auth_sessions")}
    assert {"id", "user_id", "created_at", "expires_at", "last_seen_at"} <= auth_session_cols

    workspace_cols = {c["name"] for c in inspector.get_columns("workspaces")}
    assert {"user_id", "is_template", "template_id", "owner_can_edit"} <= workspace_cols

    session_cols = {c["name"] for c in inspector.get_columns("sessions")}
    assert "user_id" in session_cols

    folder_cols = {c["name"] for c in inspector.get_columns("folders")}
    assert "user_id" in folder_cols
    engine.dispose()

    # Downgrade
    command.downgrade(alembic_cfg, "-1")
    engine = create_engine(_test_database_url(), poolclass=NullPool)
    inspector = inspect(engine)
    assert "users" not in inspector.get_table_names()
    assert "auth_sessions" not in inspector.get_table_names()
    workspace_cols = {c["name"] for c in inspector.get_columns("workspaces")}
    assert "user_id" not in workspace_cols
    engine.dispose()
