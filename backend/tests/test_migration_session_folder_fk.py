"""Verifies the session_folder_fk migration scrubs cross-workspace folder_id
values and installs the ON DELETE SET NULL FK."""
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool


def _seed_workspace_pre_split(engine, slug: str) -> str:
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO workspaces (id, slug, display_name, system_prompt,
                                    enabled_tools, is_builtin)
            VALUES (:id, :slug, 'x', '', '[]'::jsonb, false)
        """), {"id": slug, "slug": slug})
    return slug


def _seed_workspace(engine, slug: str) -> str:
    """Head-schema seed (no is_builtin column)."""
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO workspaces (id, slug, display_name, system_prompt,
                                    enabled_tools)
            VALUES (:id, :slug, 'x', '', '[]'::jsonb)
        """), {"id": slug, "slug": slug})
    return slug


def _seed_folder(engine, folder_id: str, workspace_id: str, user_id: str | None = None) -> str:
    """Insert a folder. Pass user_id when running at head (Phase B made the
    column NOT NULL); omit for pre-Phase-A revisions where the column doesn't
    exist."""
    if user_id is None:
        sql = "INSERT INTO folders (id, name, workspace_id) VALUES (:id, 'f', :ws)"
        params: dict = {"id": folder_id, "ws": workspace_id}
    else:
        sql = "INSERT INTO folders (id, name, workspace_id, user_id) VALUES (:id, 'f', :ws, :uid)"
        params = {"id": folder_id, "ws": workspace_id, "uid": user_id}
    with engine.begin() as conn:
        conn.execute(text(sql), params)
    return folder_id


def _seed_session(engine, session_id: str, workspace_id: str, folder_id: str | None,
                  user_id: str | None = None) -> str:
    """Insert a session. Pass user_id when running at head; omit for pre-Phase-A."""
    if user_id is None:
        sql = (
            "INSERT INTO sessions (id, title, workspace_id, folder_id) "
            "VALUES (:id, 't', :ws, :folder)"
        )
        params: dict = {"id": session_id, "ws": workspace_id, "folder": folder_id}
    else:
        sql = (
            "INSERT INTO sessions (id, title, workspace_id, folder_id, user_id) "
            "VALUES (:id, 't', :ws, :folder, :uid)"
        )
        params = {"id": session_id, "ws": workspace_id, "folder": folder_id, "uid": user_id}
    with engine.begin() as conn:
        conn.execute(text(sql), params)
    return session_id


def _seed_user(engine, user_id: str) -> str:
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO users (id, username, password_hash, is_admin, is_active,
                               can_create_workspaces)
            VALUES (:id, :id, 'dummy', TRUE, TRUE, TRUE)
        """), {"id": user_id})
    return user_id


def test_cross_workspace_folder_id_scrubbed_to_null(db_at_revision, alembic_cfg):
    # Start at the revision right before ours.
    engine = db_at_revision("f8d3b1c5a2e9")
    ws_a = _seed_workspace_pre_split(engine, "ws-a")
    ws_b = _seed_workspace_pre_split(engine, "ws-b")
    _seed_folder(engine, "f-b", ws_b)
    # Cross-workspace dangling ref: session in ws-a points at folder in ws-b.
    _seed_session(engine, "s-dangling", ws_a, "f-b")
    engine.dispose()

    command.upgrade(alembic_cfg, "+1")

    url = alembic_cfg.get_main_option("sqlalchemy.url")
    engine = create_engine(url, poolclass=NullPool)
    with engine.connect() as conn:
        folder_id = conn.execute(text(
            "SELECT folder_id FROM sessions WHERE id = 's-dangling'"
        )).scalar()
    engine.dispose()
    assert folder_id is None


def test_same_workspace_folder_id_preserved(db_at_revision, alembic_cfg):
    engine = db_at_revision("f8d3b1c5a2e9")
    ws = _seed_workspace_pre_split(engine, "ws-keep")
    _seed_folder(engine, "f-keep", ws)
    _seed_session(engine, "s-keep", ws, "f-keep")
    engine.dispose()

    command.upgrade(alembic_cfg, "+1")

    url = alembic_cfg.get_main_option("sqlalchemy.url")
    engine = create_engine(url, poolclass=NullPool)
    with engine.connect() as conn:
        folder_id = conn.execute(text(
            "SELECT folder_id FROM sessions WHERE id = 's-keep'"
        )).scalar()
    engine.dispose()
    assert folder_id == "f-keep"


def test_fk_sets_folder_id_null_on_folder_delete(db_at_head):
    engine = db_at_head
    user = _seed_user(engine, "u-setnull")
    ws = _seed_workspace(engine, "ws-setnull")
    _seed_folder(engine, "f-setnull", ws, user_id=user)
    _seed_session(engine, "s-setnull", ws, "f-setnull", user_id=user)

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM folders WHERE id = 'f-setnull'"))
        folder_id = conn.execute(text(
            "SELECT folder_id FROM sessions WHERE id = 's-setnull'"
        )).scalar()
    assert folder_id is None
