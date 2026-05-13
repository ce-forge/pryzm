"""Verifies migration C: messages.role CHECK constraint."""
import pytest
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import NullPool


def _seed_session(engine) -> str:
    """Create the minimum scaffold (workspace + session) for a message insert."""
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO workspaces (id, slug, display_name, system_prompt,
                                    enabled_tools, is_builtin)
            VALUES ('ws-c', 'ws-c', 'x', '', '[]'::jsonb, false)
        """))
        conn.execute(text("""
            INSERT INTO sessions (id, title, workspace_id)
            VALUES ('sess-c', 't', 'ws-c')
        """))
    return "sess-c"


def test_each_valid_role_inserts(db_at_head):
    engine = db_at_head
    sess = _seed_session(engine)
    for role in ("user", "assistant", "tool", "memory"):
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO messages (id, session_id, role, content)
                VALUES (:id, :sess, :role, 'x')
            """), {"id": f"m-{role}", "sess": sess, "role": role})


def test_invalid_role_rejected(db_at_head):
    engine = db_at_head
    sess = _seed_session(engine)
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO messages (id, session_id, role, content)
                VALUES ('m-bad', :sess, 'garbage', 'x')
            """), {"sess": sess})


def test_downgrade_drops_constraint(reset_test_db, alembic_cfg):
    command.downgrade(alembic_cfg, "base")
    command.upgrade(alembic_cfg, "head")
    command.downgrade(alembic_cfg, "c6bf15460b87")  # T3's down_revision

    engine = create_engine(reset_test_db, poolclass=NullPool)
    with engine.connect() as conn:
        constraint = conn.execute(text("""
            SELECT 1 FROM information_schema.table_constraints
            WHERE table_name = 'messages' AND constraint_name = 'messages_role_check'
        """)).scalar()
    engine.dispose()
    assert constraint is None
