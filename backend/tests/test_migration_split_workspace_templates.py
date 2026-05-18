"""Workspace/template split migration: schema + data preservation."""
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import NullPool

from tests.conftest import _test_database_url


def test_split_workspace_templates(db_at_revision, alembic_cfg):
    from alembic import command

    # Pre-state: at the previous head, no workspace_templates table,
    # workspaces still carries is_template / is_builtin.
    engine = db_at_revision("f0d03905ddc4")
    inspector = inspect(engine)
    assert "workspace_templates" not in inspector.get_table_names()
    workspace_cols = {c["name"] for c in inspector.get_columns("workspaces")}
    assert "is_template" in workspace_cols
    assert "is_builtin" in workspace_cols
    engine.dispose()

    # Seed: one admin, one template, one user-owned instance pointing at it.
    engine = create_engine(_test_database_url(), poolclass=NullPool)
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO users (id, username, password_hash, is_admin, is_active, can_create_workspaces, created_at)
            VALUES ('u-1', 'admin', 'dummy', TRUE, TRUE, TRUE, NOW());
        """))
        conn.execute(text("""
            INSERT INTO workspaces (id, slug, display_name, system_prompt, enabled_tools, color, engine_config, is_builtin, is_template, user_id, template_id, owner_can_edit, created_at)
            VALUES ('t-1', 'tmpl-x', 'Tmpl X', 'tmpl prompt', '[]'::jsonb, NULL, '{"backend":"llama_cpp"}'::jsonb, TRUE, TRUE, NULL, NULL, FALSE, NOW()),
                   ('w-1', 'tmpl-x', 'Inst X', 'inst prompt', '[]'::jsonb, NULL, '{"backend":"llama_cpp"}'::jsonb, FALSE, FALSE, 'u-1', 't-1', TRUE, NOW());
        """))
    engine.dispose()

    # Upgrade
    command.upgrade(alembic_cfg, "head")

    engine = create_engine(_test_database_url(), poolclass=NullPool)
    inspector = inspect(engine)

    # workspace_templates exists; seeded template was migrated (id + slug preserved).
    assert "workspace_templates" in inspector.get_table_names()
    with engine.connect() as conn:
        seeded = conn.execute(text(
            "SELECT id, slug, display_name FROM workspace_templates WHERE id = 't-1'"
        )).fetchone()
    assert seeded is not None and seeded.slug == "tmpl-x" and seeded.display_name == "Tmpl X"

    # is_template / is_builtin gone from workspaces; position added.
    workspace_cols = {c["name"] for c in inspector.get_columns("workspaces")}
    assert "is_template" not in workspace_cols
    assert "is_builtin" not in workspace_cols
    assert "position" in workspace_cols

    # Instance row survives in workspaces with template_id intact.
    with engine.connect() as conn:
        instance = conn.execute(text(
            "SELECT id, slug, template_id FROM workspaces WHERE id = 'w-1'"
        )).fetchone()
    assert instance is not None and instance.slug == "tmpl-x" and instance.template_id == "t-1"

    # FK now points to workspace_templates.
    fks = inspector.get_foreign_keys("workspaces")
    template_fk = next(fk for fk in fks if "template_id" in fk["constrained_columns"])
    assert template_fk["referred_table"] == "workspace_templates"

    engine.dispose()

    # Downgrade restores prior shape.
    command.downgrade(alembic_cfg, "f0d03905ddc4")
    engine = create_engine(_test_database_url(), poolclass=NullPool)
    inspector = inspect(engine)
    assert "workspace_templates" not in inspector.get_table_names()
    workspace_cols = {c["name"] for c in inspector.get_columns("workspaces")}
    assert "is_template" in workspace_cols
    assert "is_builtin" in workspace_cols
    engine.dispose()
