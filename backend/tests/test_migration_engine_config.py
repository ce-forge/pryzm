"""Verifies migration A: workspaces.engine_config (JSONB)."""
import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import NullPool


def _seed_old_row(engine, slug: str, preferred_model: str | None):
    """Insert a workspace row at the pre-migration schema."""
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO workspaces (id, slug, display_name, system_prompt,
                                    enabled_tools, preferred_model, is_builtin)
            VALUES (:id, :slug, :name, '', '[]'::jsonb, :pm, false)
        """), {"id": slug, "slug": slug, "name": slug, "pm": preferred_model})


def test_backfill_populates_engine_config_from_preferred_model(db_at_revision, alembic_cfg):
    # Start at the revision immediately before ours (the direct parent).
    engine = db_at_revision("a3f2c1d4e5b6")
    _seed_old_row(engine, "alpha", "gemma4:e4b")
    _seed_old_row(engine, "beta", None)
    engine.dispose()

    # Apply migration A and open a fresh engine (stale metadata would miss the new column).
    command.upgrade(alembic_cfg, "+1")
    fresh_engine = create_engine(alembic_cfg.get_main_option("sqlalchemy.url"), poolclass=NullPool)

    with fresh_engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT slug, engine_config FROM workspaces ORDER BY slug"
        )).all()
    fresh_engine.dispose()

    alpha_cfg = rows[0][1]
    beta_cfg = rows[1][1]
    assert alpha_cfg == {"backend": "ollama", "model": "gemma4:e4b"}
    assert beta_cfg == {"backend": "ollama", "model": "gemma4:e4b"}


def test_engine_config_server_default_on_insert(db_at_head):
    engine = db_at_head
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO workspaces (id, slug, display_name, system_prompt,
                                    enabled_tools, is_builtin)
            VALUES ('test1', 'test-slug', 'test', '', '[]'::jsonb, false)
        """))
        cfg = conn.execute(text(
            "SELECT engine_config FROM workspaces WHERE id = 'test1'"
        )).scalar()
    assert cfg == {"backend": "ollama", "model": "gemma4:e4b"}


def test_engine_config_rejects_null(db_at_head):
    engine = db_at_head
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO workspaces (id, slug, display_name, system_prompt,
                                        enabled_tools, is_builtin, engine_config)
                VALUES ('test2', 'test-null', 'x', '', '[]'::jsonb, false, NULL)
            """))


def test_downgrade_drops_engine_config_column(reset_test_db, alembic_cfg):
    command.downgrade(alembic_cfg, "base")
    command.upgrade(alembic_cfg, "head")
    command.downgrade(alembic_cfg, "-1")

    engine = create_engine(reset_test_db, poolclass=NullPool)
    with engine.connect() as conn:
        col_exists = conn.execute(text("""
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'workspaces' AND column_name = 'engine_config'
        """)).scalar()
    engine.dispose()
    assert col_exists is None
