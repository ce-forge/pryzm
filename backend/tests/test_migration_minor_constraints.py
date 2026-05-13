"""Verifies migration E: messages.session_id NOT NULL + documents.is_global server_default."""
import pytest
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import NullPool


def _seed_workspace(engine, slug: str = "ws-e") -> str:
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO workspaces (id, slug, display_name, system_prompt,
                                    enabled_tools, is_builtin)
            VALUES (:id, :slug, 'x', '', '[]'::jsonb, false)
        """), {"id": slug, "slug": slug})
    return slug


def test_messages_session_id_not_null(db_at_head):
    engine = db_at_head
    _seed_workspace(engine)
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO messages (id, role, content)
                VALUES ('m-orphan', 'user', 'x')
            """))


def test_documents_is_global_defaults_to_false_in_db(db_at_head):
    engine = db_at_head
    ws = _seed_workspace(engine)
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO documents (id, filename, workspace_id)
            VALUES ('doc-e', 'f.txt', :ws)
        """), {"ws": ws})
        val = conn.execute(text(
            "SELECT is_global FROM documents WHERE id = 'doc-e'"
        )).scalar()
    assert val is False


def test_downgrade_restores_nullable_session_id(reset_test_db, alembic_cfg):
    command.downgrade(alembic_cfg, "base")
    command.upgrade(alembic_cfg, "head")
    command.downgrade(alembic_cfg, "50d45d7ba8d6")  # T5's down_revision

    engine = create_engine(reset_test_db, poolclass=NullPool)
    with engine.connect() as conn:
        is_nullable = conn.execute(text("""
            SELECT is_nullable FROM information_schema.columns
            WHERE table_name = 'messages' AND column_name = 'session_id'
        """)).scalar()
    engine.dispose()
    assert is_nullable == "YES"
