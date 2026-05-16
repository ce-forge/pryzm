"""Verifies migration e7c2a9f4b8d1: enable web_search on builtin workspaces.

Adds 'web_search' to it_copilot + personal workspaces' enabled_tools JSONB
array if it isn't already present. Idempotent. Non-builtin workspaces are
untouched. Downgrade removes 'web_search' from the same builtins.
"""
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool


_PARENT_REV = "d2f9c4e7a8b1"  # add_messages_tool_calls
_NEW_REV = "e7c2a9f4b8d1"


def _enabled_tools(conn, slug: str) -> list[str]:
    row = conn.execute(text(
        "SELECT enabled_tools FROM workspaces WHERE slug = :s"
    ), {"s": slug}).scalar()
    return list(row) if row is not None else []


def test_upgrade_adds_web_search_to_both_builtins(db_at_revision, alembic_cfg):
    """After upgrade, both it_copilot and personal contain 'web_search'."""
    engine = db_at_revision(_PARENT_REV)
    engine.dispose()

    command.upgrade(alembic_cfg, _NEW_REV)

    fresh = create_engine(alembic_cfg.get_main_option("sqlalchemy.url"), poolclass=NullPool)
    with fresh.connect() as conn:
        it_tools = _enabled_tools(conn, "it_copilot")
        personal_tools = _enabled_tools(conn, "personal")
    fresh.dispose()

    assert "web_search" in it_tools
    assert "web_search" in personal_tools


def test_upgrade_preserves_existing_tools(db_at_revision, alembic_cfg):
    """The existing enabled_tools (e.g. dns_lookup, search_knowledge_base) survive."""
    engine = db_at_revision(_PARENT_REV)
    engine.dispose()

    command.upgrade(alembic_cfg, _NEW_REV)

    fresh = create_engine(alembic_cfg.get_main_option("sqlalchemy.url"), poolclass=NullPool)
    with fresh.connect() as conn:
        it_tools = _enabled_tools(conn, "it_copilot")
        personal_tools = _enabled_tools(conn, "personal")
    fresh.dispose()

    # Sanity: seed migration populated these workspaces with their canonical sets.
    assert "search_knowledge_base" in it_tools
    assert "dns_lookup" in it_tools
    assert "search_knowledge_base" in personal_tools


def test_upgrade_is_idempotent(db_at_revision, alembic_cfg):
    """Pre-existing 'web_search' in enabled_tools does NOT produce a duplicate."""
    engine = db_at_revision(_PARENT_REV)
    with engine.begin() as conn:
        # Simulate a workspace that already had web_search added manually
        conn.execute(text(
            "UPDATE workspaces "
            "SET enabled_tools = enabled_tools || '[\"web_search\"]'::jsonb "
            "WHERE slug = 'it_copilot'"
        ))
    engine.dispose()

    command.upgrade(alembic_cfg, _NEW_REV)

    fresh = create_engine(alembic_cfg.get_main_option("sqlalchemy.url"), poolclass=NullPool)
    with fresh.connect() as conn:
        it_tools = _enabled_tools(conn, "it_copilot")
    fresh.dispose()

    assert it_tools.count("web_search") == 1


def test_upgrade_leaves_non_builtin_untouched(db_at_revision, alembic_cfg):
    """A workspace whose slug is neither it_copilot nor personal is not modified."""
    engine = db_at_revision(_PARENT_REV)
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO workspaces (id, slug, display_name, system_prompt, "
            "enabled_tools, engine_config, is_builtin) "
            "VALUES ('ws-other', 'custom_ws', 'Custom', 'p', "
            "'[\"dns_lookup\"]'::jsonb, '{}'::jsonb, false)"
        ))
    engine.dispose()

    command.upgrade(alembic_cfg, _NEW_REV)

    fresh = create_engine(alembic_cfg.get_main_option("sqlalchemy.url"), poolclass=NullPool)
    with fresh.connect() as conn:
        custom_tools = _enabled_tools(conn, "custom_ws")
    fresh.dispose()

    assert "web_search" not in custom_tools
    assert "dns_lookup" in custom_tools


def test_downgrade_removes_web_search_from_builtins(db_at_revision, alembic_cfg):
    """After upgrade then downgrade, web_search is gone from both builtins
    while other tools remain."""
    engine = db_at_revision(_PARENT_REV)
    engine.dispose()

    command.upgrade(alembic_cfg, _NEW_REV)
    command.downgrade(alembic_cfg, _PARENT_REV)

    fresh = create_engine(alembic_cfg.get_main_option("sqlalchemy.url"), poolclass=NullPool)
    with fresh.connect() as conn:
        it_tools = _enabled_tools(conn, "it_copilot")
        personal_tools = _enabled_tools(conn, "personal")
    fresh.dispose()

    assert "web_search" not in it_tools
    assert "web_search" not in personal_tools
    # Other tools survive
    assert "search_knowledge_base" in it_tools
    assert "search_knowledge_base" in personal_tools
