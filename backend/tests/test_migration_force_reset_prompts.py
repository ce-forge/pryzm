"""Verifies migration c1f8b27a4d56: force-reset builtin workspaces' system_prompt.

Upgrade overwrites it_copilot + personal rows with the new on-disk defaults
(which contain {tool_directives}). Downgrade restores the captured prior text.
Non-builtin workspaces and rows with other slugs are unaffected.
"""
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool


def test_upgrade_overwrites_builtin_prompts(db_at_revision, alembic_cfg):
    """At the parent revision, the two builtins have their pre-refactor text;
    after the upgrade, both prompts contain {tool_directives}."""
    engine = db_at_revision("a4e0c1d83f29")
    with engine.begin() as conn:
        # The workspaces migration (58c8b7524030) already seeded the two builtins
        # with the current on-disk prompts. We overwrite with OLD TEXT here to
        # simulate the pre-refactor state that c1f8b27a4d56 is designed to fix.
        for slug in ("it_copilot", "personal"):
            conn.execute(text(
                "UPDATE workspaces SET system_prompt = 'OLD TEXT' WHERE slug = :slug"
            ), {"slug": slug})
    engine.dispose()

    command.upgrade(alembic_cfg, "c1f8b27a4d56")

    fresh = create_engine(alembic_cfg.get_main_option("sqlalchemy.url"), poolclass=NullPool)
    with fresh.connect() as conn:
        rows = conn.execute(text(
            "SELECT slug, system_prompt FROM workspaces WHERE slug IN ('it_copilot','personal') ORDER BY slug"
        )).fetchall()
    fresh.dispose()

    assert len(rows) == 2
    for slug, prompt in rows:
        assert "{tool_directives}" in prompt, f"{slug} missing placeholder after upgrade"
        assert "OLD TEXT" not in prompt


def test_upgrade_leaves_non_builtin_untouched(db_at_revision, alembic_cfg):
    """A workspace with a slug NOT in ('it_copilot','personal') keeps its prompt."""
    engine = db_at_revision("a4e0c1d83f29")
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO workspaces (id, slug, display_name, system_prompt, "
            "enabled_tools, engine_config, is_builtin) "
            "VALUES ('ws-custom', 'my_custom_ws', 'Custom', 'KEEP ME', '[]'::jsonb, '{}'::jsonb, false)"
        ))
    engine.dispose()

    command.upgrade(alembic_cfg, "c1f8b27a4d56")

    fresh = create_engine(alembic_cfg.get_main_option("sqlalchemy.url"), poolclass=NullPool)
    with fresh.connect() as conn:
        prompt = conn.execute(text(
            "SELECT system_prompt FROM workspaces WHERE slug = 'my_custom_ws'"
        )).scalar()
    fresh.dispose()

    assert prompt == "KEEP ME"


def test_downgrade_restores_pre_refactor_text(db_at_revision, alembic_cfg):
    """Downgrade puts back the captured pre-refactor text."""
    engine = db_at_revision("a4e0c1d83f29")
    with engine.begin() as conn:
        # Overwrite the already-seeded rows with OLD TEXT to simulate pre-refactor state.
        for slug in ("it_copilot", "personal"):
            conn.execute(text(
                "UPDATE workspaces SET system_prompt = 'OLD TEXT' WHERE slug = :slug"
            ), {"slug": slug})
    engine.dispose()

    command.upgrade(alembic_cfg, "c1f8b27a4d56")
    command.downgrade(alembic_cfg, "a4e0c1d83f29")

    fresh = create_engine(alembic_cfg.get_main_option("sqlalchemy.url"), poolclass=NullPool)
    with fresh.connect() as conn:
        rows = conn.execute(text(
            "SELECT slug, system_prompt FROM workspaces WHERE slug IN ('it_copilot','personal') ORDER BY slug"
        )).fetchall()
    fresh.dispose()

    by_slug = {slug: prompt for slug, prompt in rows}
    assert "{tool_directives}" not in by_slug["it_copilot"]
    assert "{tool_directives}" not in by_slug["personal"]
    assert "NETWORK VALIDATION" in by_slug["it_copilot"]
    assert "rename_chat_session" in by_slug["personal"]
