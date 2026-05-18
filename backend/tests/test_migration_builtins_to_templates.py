"""Builtins-to-templates: it_copilot + personal become templates."""
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from tests.conftest import _test_database_url


def test_builtins_marked_as_templates(db_at_revision, alembic_cfg):
    from alembic import command

    # Upgrade to the schema migration; builtins exist via baseline seed
    engine = db_at_revision("712c74813064")
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT slug, is_template FROM workspaces WHERE slug IN ('it_copilot', 'personal')"
        )).fetchall()
    assert all(row.is_template is False for row in result)
    assert len(result) >= 2
    engine.dispose()

    # Upgrade through this migration
    command.upgrade(alembic_cfg, "8cd618b90038")
    engine = create_engine(_test_database_url(), poolclass=NullPool)
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT slug, is_template, user_id FROM workspaces WHERE slug IN ('it_copilot', 'personal')"
        )).fetchall()
    assert all(row.is_template is True for row in result)
    assert all(row.user_id is None for row in result)
    engine.dispose()
