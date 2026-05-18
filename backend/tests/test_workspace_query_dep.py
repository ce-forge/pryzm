"""workspace_query_dep enforces per-user ownership."""
import pytest
from fastapi import HTTPException

from core.workspace_access import workspace_query_dep
from db import models


def _seed(db_session):
    alice = models.User(
        username="alice", password_hash="x", is_admin=False, is_active=True,
    )
    bob = models.User(
        username="bob", password_hash="x", is_admin=False, is_active=True,
    )
    db_session.add_all([alice, bob])
    db_session.commit()
    db_session.refresh(alice); db_session.refresh(bob)

    alice_ws = models.Workspace(
        slug="ws-shared", display_name="A's WS",
        system_prompt="", enabled_tools=[],
        is_builtin=False, is_template=False, user_id=alice.id,
        engine_config={"backend": "llama_cpp"},
    )
    bob_ws = models.Workspace(
        slug="ws-shared", display_name="B's WS",
        system_prompt="", enabled_tools=[],
        is_builtin=False, is_template=False, user_id=bob.id,
        engine_config={"backend": "llama_cpp"},
    )
    db_session.add_all([alice_ws, bob_ws])
    db_session.commit()
    db_session.refresh(alice_ws); db_session.refresh(bob_ws)
    return alice, bob, alice_ws, bob_ws


def test_workspace_query_dep_returns_users_own_workspace(db_session):
    alice, bob, alice_ws, bob_ws = _seed(db_session)
    result = workspace_query_dep(workspace="ws-shared", user=alice, db=db_session)
    assert result.id == alice_ws.id


def test_workspace_query_dep_404_for_other_users_workspace(db_session):
    alice, bob, alice_ws, bob_ws = _seed(db_session)
    charlie = models.User(username="charlie", password_hash="x", is_admin=False, is_active=True)
    db_session.add(charlie); db_session.commit(); db_session.refresh(charlie)

    with pytest.raises(HTTPException) as exc:
        workspace_query_dep(workspace="ws-shared", user=charlie, db=db_session)
    assert exc.value.status_code == 404


def test_workspace_query_dep_skips_templates(db_session):
    alice, _, _, _ = _seed(db_session)
    tmpl = models.Workspace(
        slug="ws-shared", display_name="Template",
        system_prompt="", enabled_tools=[],
        is_builtin=False, is_template=True, user_id=None,
        engine_config={"backend": "llama_cpp"},
    )
    db_session.add(tmpl); db_session.commit()
    result = workspace_query_dep(workspace="ws-shared", user=alice, db=db_session)
    assert result.is_template is False
