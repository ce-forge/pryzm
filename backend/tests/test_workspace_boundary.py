"""Tests for verify_workspace_owns dependency."""
import pytest
from fastapi import HTTPException

from core.workspace_access import verify_workspace_owns
from db import models
from sqlalchemy.orm import Session


def _seed_two_workspaces_with_one_message(db: Session):
    """Helper: creates two workspaces, each with one session and one message.
    Returns (ws_a, ws_b, msg_in_a)."""
    ws_a = models.Workspace(
        id="ws-a", slug="ws-a", display_name="A",
        system_prompt="", enabled_tools=[], is_builtin=False,
        engine_config={"backend": "ollama", "model": "gemma4:e4b"},
    )
    ws_b = models.Workspace(
        id="ws-b", slug="ws-b", display_name="B",
        system_prompt="", enabled_tools=[], is_builtin=False,
        engine_config={"backend": "ollama", "model": "gemma4:e4b"},
    )
    sess_a = models.Session(id="sess-a", workspace_id="ws-a", title="t")
    msg_a = models.Message(id="msg-a", session_id="sess-a", role="user", content="x")
    db.add_all([ws_a, ws_b, sess_a, msg_a])
    db.commit()
    return ws_a, ws_b, msg_a


def test_owns_returns_resource_when_workspace_matches(db_session):
    ws_a, ws_b, msg = _seed_two_workspaces_with_one_message(db_session)
    sess = db_session.query(models.Session).filter_by(id="sess-a").one()
    result = verify_workspace_owns(
        resource_id=sess.id, model=models.Session, workspace_id="ws-a", db=db_session,
    )
    assert result.id == "sess-a"


def test_owns_404s_when_cross_workspace(db_session):
    ws_a, ws_b, msg = _seed_two_workspaces_with_one_message(db_session)
    # Session sess-a belongs to ws-a; query as ws-b → 404.
    with pytest.raises(HTTPException) as exc:
        verify_workspace_owns(
            resource_id="sess-a", model=models.Session, workspace_id="ws-b", db=db_session,
        )
    assert exc.value.status_code == 404


def test_owns_404s_when_resource_missing(db_session):
    ws_a, ws_b, msg = _seed_two_workspaces_with_one_message(db_session)
    with pytest.raises(HTTPException) as exc:
        verify_workspace_owns(
            resource_id="nope", model=models.Session, workspace_id="ws-a", db=db_session,
        )
    assert exc.value.status_code == 404
