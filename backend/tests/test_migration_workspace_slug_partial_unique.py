"""Migration a65df9990a35: replace UNIQUE(slug) with two partial indexes."""
from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import NullPool

from tests.conftest import _test_database_url


_MIGRATION_REVISION = "a65df9990a35"


def _index_names(engine, table: str) -> set[str]:
    inspector = inspect(engine)
    return {ix["name"] for ix in inspector.get_indexes(table)}


def _unique_constraint_names(engine, table: str) -> set[str]:
    inspector = inspect(engine)
    return {uc["name"] for uc in inspector.get_unique_constraints(table)}


def test_partial_unique_indexes_present(db_at_revision):
    engine = db_at_revision(_MIGRATION_REVISION)
    names = _index_names(engine, "workspaces")
    assert "ix_workspaces_slug_template_unique" in names
    assert "ix_workspaces_user_slug_unique" in names
    # The global UNIQUE(slug) constraint is gone.
    assert "workspaces_slug_key" not in _unique_constraint_names(engine, "workspaces")


def test_downgrade_restores_global_unique(reset_test_db, alembic_cfg):
    command.downgrade(alembic_cfg, "base")
    command.upgrade(alembic_cfg, _MIGRATION_REVISION)
    command.downgrade(alembic_cfg, "dc1f669b872e")

    engine = create_engine(reset_test_db, poolclass=NullPool)
    try:
        names = _index_names(engine, "workspaces")
        assert "ix_workspaces_slug_template_unique" not in names
        assert "ix_workspaces_user_slug_unique" not in names
        assert "workspaces_slug_key" in _unique_constraint_names(engine, "workspaces")
    finally:
        engine.dispose()


def _clear_workspaces(engine):
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM workspaces"))
        conn.execute(text("DELETE FROM users"))


def test_per_user_slug_uniqueness_enforced_in_db(db_at_revision):
    engine = db_at_revision(_MIGRATION_REVISION)
    _clear_workspaces(engine)
    user_id = "u-1"
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO users (id, username, password_hash)
                VALUES (:id, 'alice', 'x')
            """), {"id": user_id})
            conn.execute(text("""
                INSERT INTO workspaces (id, slug, display_name, system_prompt,
                                        enabled_tools, is_builtin, is_template, user_id)
                VALUES ('w1', 'it_copilot', 'IT', '', '[]'::jsonb, false, false, :uid)
            """), {"uid": user_id})

        import pytest
        from sqlalchemy.exc import IntegrityError
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO workspaces (id, slug, display_name, system_prompt,
                                            enabled_tools, is_builtin, is_template, user_id)
                    VALUES ('w2', 'it_copilot', 'IT', '', '[]'::jsonb, false, false, :uid)
                """), {"uid": user_id})
    finally:
        _clear_workspaces(engine)


def test_cross_user_same_slug_allowed_in_db(db_at_revision):
    engine = db_at_revision(_MIGRATION_REVISION)
    _clear_workspaces(engine)
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO users (id, username, password_hash) VALUES
                    ('u-a', 'alice', 'x'),
                    ('u-b', 'bob', 'x')
            """))
            conn.execute(text("""
                INSERT INTO workspaces (id, slug, display_name, system_prompt,
                                        enabled_tools, is_builtin, is_template, user_id)
                VALUES
                    ('w-a', 'it_copilot', 'IT', '', '[]'::jsonb, false, false, 'u-a'),
                    ('w-b', 'it_copilot', 'IT', '', '[]'::jsonb, false, false, 'u-b')
            """))
            rows = conn.execute(text(
                "SELECT user_id FROM workspaces WHERE slug = 'it_copilot' ORDER BY user_id"
            )).fetchall()
        assert [r[0] for r in rows] == ["u-a", "u-b"]
    finally:
        _clear_workspaces(engine)


def test_template_slug_globally_unique_in_db(db_at_revision):
    engine = db_at_revision(_MIGRATION_REVISION)
    _clear_workspaces(engine)
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO workspaces (id, slug, display_name, system_prompt,
                                        enabled_tools, is_builtin, is_template, user_id)
                VALUES ('t-1', 'shared_tmpl', 'X', '', '[]'::jsonb, true, true, NULL)
            """))

        import pytest
        from sqlalchemy.exc import IntegrityError
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO workspaces (id, slug, display_name, system_prompt,
                                            enabled_tools, is_builtin, is_template, user_id)
                    VALUES ('t-2', 'shared_tmpl', 'X', '', '[]'::jsonb, true, true, NULL)
                """))
    finally:
        _clear_workspaces(engine)
