"""Verifies migration f8d3b1c5a2e9: remove web_search from builtin workspaces.

After in-demo testing, web_search is moving from default-on per workspace
to only-on via the per-turn globe toggle. This migration reverses the data
effect of e7c2a9f4b8d1 for the two builtin slugs. Non-builtin workspaces
are untouched. Downgrade puts it back.
"""
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool


_PARENT_REV = "e7c2a9f4b8d1"  # enable_web_search_on_builtins
_NEW_REV = "f8d3b1c5a2e9"


def _enabled_tools(conn, slug: str) -> list[str]:
    row = conn.execute(text(
        "SELECT enabled_tools FROM workspaces WHERE slug = :s"
    ), {"s": slug}).scalar()
    return list(row) if row is not None else []


def test_upgrade_removes_web_search_from_both_builtins(db_at_revision, alembic_cfg):
    """At the parent revision, web_search is in both builtins (per the prior
    migration). After upgrade, it's gone from both — and the rest survives."""
    engine = db_at_revision(_PARENT_REV)
    engine.dispose()

    command.upgrade(alembic_cfg, _NEW_REV)

    fresh = create_engine(alembic_cfg.get_main_option("sqlalchemy.url"), poolclass=NullPool)
    with fresh.connect() as conn:
        it_tools = _enabled_tools(conn, "it_copilot")
        personal_tools = _enabled_tools(conn, "personal")
    fresh.dispose()

    assert "web_search" not in it_tools
    assert "web_search" not in personal_tools
    # Sanity: other tools survive
    assert "search_knowledge_base" in it_tools
    assert "dns_lookup" in it_tools


def test_upgrade_leaves_non_builtin_untouched(db_at_revision, alembic_cfg):
    """A non-builtin workspace that had web_search enabled keeps it — admins
    of those workspaces opted in explicitly."""
    engine = db_at_revision(_PARENT_REV)
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO workspaces (id, slug, display_name, system_prompt, "
            "enabled_tools, engine_config, is_builtin) "
            "VALUES ('ws-cust', 'custom_ws', 'Custom', 'p', "
            "'[\"web_search\",\"dns_lookup\"]'::jsonb, '{}'::jsonb, false)"
        ))
    engine.dispose()

    command.upgrade(alembic_cfg, _NEW_REV)

    fresh = create_engine(alembic_cfg.get_main_option("sqlalchemy.url"), poolclass=NullPool)
    with fresh.connect() as conn:
        custom_tools = _enabled_tools(conn, "custom_ws")
    fresh.dispose()

    assert "web_search" in custom_tools
    assert "dns_lookup" in custom_tools


def test_upgrade_is_idempotent(db_at_revision, alembic_cfg):
    """If web_search is already absent (e.g. someone manually removed it before
    the migration ran), upgrade is a no-op."""
    engine = db_at_revision(_PARENT_REV)
    # Pre-remove web_search to simulate already-absent state
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE workspaces SET enabled_tools = ( "
            "  SELECT jsonb_agg(elem) "
            "  FROM jsonb_array_elements(enabled_tools) elem "
            "  WHERE elem <> '\"web_search\"'::jsonb) "
            "WHERE slug = 'it_copilot'"
        ))
    engine.dispose()

    command.upgrade(alembic_cfg, _NEW_REV)

    fresh = create_engine(alembic_cfg.get_main_option("sqlalchemy.url"), poolclass=NullPool)
    with fresh.connect() as conn:
        it_tools = _enabled_tools(conn, "it_copilot")
    fresh.dispose()

    assert "web_search" not in it_tools
    # Other tools intact
    assert "dns_lookup" in it_tools


def test_downgrade_restores_web_search(db_at_revision, alembic_cfg):
    """Downgrade re-adds web_search to both builtins."""
    engine = db_at_revision(_PARENT_REV)
    engine.dispose()

    command.upgrade(alembic_cfg, _NEW_REV)
    command.downgrade(alembic_cfg, _PARENT_REV)

    fresh = create_engine(alembic_cfg.get_main_option("sqlalchemy.url"), poolclass=NullPool)
    with fresh.connect() as conn:
        it_tools = _enabled_tools(conn, "it_copilot")
        personal_tools = _enabled_tools(conn, "personal")
    fresh.dispose()

    assert "web_search" in it_tools
    assert "web_search" in personal_tools
