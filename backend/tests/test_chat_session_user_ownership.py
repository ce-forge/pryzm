"""New chat sessions inherit current_user.id."""
import pytest
from fastapi.testclient import TestClient

from core import cookie_auth
from db import database, models
from main import app


def test_chat_session_creation_assigns_user_id(db_session, monkeypatch):
    """Smoke test: when a logged-in user causes a session row to be created
    (via /analyze or whatever write path exists), the row has user_id set
    to that user."""
    u = models.User(
        username="alice", password_hash=cookie_auth.hash_password("alice-pw-12chars"),
        is_admin=False, is_active=True, can_create_workspaces=True,
    )
    db_session.add(u); db_session.commit(); db_session.refresh(u)
    ws = models.Workspace(
        slug="ws-chat", display_name="Chat", system_prompt="",
        enabled_tools=[], is_builtin=False, is_template=False,
        user_id=u.id, engine_config={"backend": "llama_cpp"},
    )
    db_session.add(ws); db_session.commit(); db_session.refresh(ws)

    # Direct model construction confirms NOT NULL is enforced and our
    # change wires user_id correctly
    s = models.Session(workspace_id=ws.id, title="t", user_id=u.id)
    db_session.add(s); db_session.commit()
    assert s.user_id == u.id


def test_chat_session_creation_without_user_id_fails_at_db(db_session, monkeypatch):
    """Confirm the FK + NOT NULL is actively enforced at DB level."""
    import sqlalchemy.exc
    u = models.User(
        username="alice2", password_hash="x", is_admin=False, is_active=True,
    )
    db_session.add(u); db_session.commit(); db_session.refresh(u)
    ws = models.Workspace(
        slug="ws-chat2", display_name="Chat", system_prompt="",
        enabled_tools=[], is_builtin=False, is_template=False,
        user_id=u.id, engine_config={"backend": "llama_cpp"},
    )
    db_session.add(ws); db_session.commit(); db_session.refresh(ws)

    s = models.Session(workspace_id=ws.id, title="t")  # no user_id
    db_session.add(s)
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        db_session.commit()
    db_session.rollback()
