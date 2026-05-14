"""Verifies migration F: drop workspaces.preferred_model.

Phase 4 T5 — all consumers migrated to engine_config.model before this ran.
"""
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool


def test_upgrade_drops_preferred_model_column(db_at_revision, alembic_cfg):
    """After upgrade to bf317b5870ef, preferred_model column must not exist."""
    # Start at the parent revision.
    engine = db_at_revision("a8c69f612a8a")
    # Verify the column exists at the parent revision.
    with engine.connect() as conn:
        col_exists_before = conn.execute(text("""
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'workspaces' AND column_name = 'preferred_model'
        """)).scalar()
    engine.dispose()
    assert col_exists_before == 1, "preferred_model column should exist before migration"

    # Apply our migration.
    command.upgrade(alembic_cfg, "bf317b5870ef")

    fresh = create_engine(alembic_cfg.get_main_option("sqlalchemy.url"), poolclass=NullPool)
    with fresh.connect() as conn:
        col_exists_after = conn.execute(text("""
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'workspaces' AND column_name = 'preferred_model'
        """)).scalar()
    fresh.dispose()
    assert col_exists_after is None, "preferred_model column should be gone after upgrade"


def test_downgrade_restores_preferred_model_column(reset_test_db, alembic_cfg):
    """After downgrade from bf317b5870ef, preferred_model column reappears."""
    command.downgrade(alembic_cfg, "base")
    command.upgrade(alembic_cfg, "head")
    command.downgrade(alembic_cfg, "a8c69f612a8a")

    engine = create_engine(reset_test_db, poolclass=NullPool)
    with engine.connect() as conn:
        col_exists = conn.execute(text("""
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'workspaces' AND column_name = 'preferred_model'
        """)).scalar()
    engine.dispose()
    assert col_exists == 1, "preferred_model column should be restored after downgrade"


def test_downgrade_backfills_preferred_model_from_engine_config(reset_test_db, alembic_cfg):
    """Downgrade's UPDATE backfills preferred_model from engine_config->>'model'."""
    command.downgrade(alembic_cfg, "base")
    command.upgrade(alembic_cfg, "head")

    # Seed a workspace with a specific model in engine_config at head.
    seed_engine = create_engine(reset_test_db, poolclass=NullPool)
    with seed_engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO workspaces (id, slug, display_name, system_prompt,
                                    enabled_tools, engine_config, is_builtin)
            VALUES ('ws-f', 'ws-f', 'WS F', '', '[]'::jsonb,
                    '{"backend": "ollama", "model": "qwen3.6:27b"}'::jsonb, false)
        """))
    seed_engine.dispose()

    command.downgrade(alembic_cfg, "a8c69f612a8a")

    verify_engine = create_engine(reset_test_db, poolclass=NullPool)
    with verify_engine.connect() as conn:
        pm = conn.execute(text(
            "SELECT preferred_model FROM workspaces WHERE id = 'ws-f'"
        )).scalar()
    verify_engine.dispose()
    assert pm == "qwen3.6:27b"
