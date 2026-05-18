"""Tests for verify_workspace_owns dependency and message workspace scoping."""
import pytest
from fastapi import HTTPException

from core.workspace_access import verify_workspace_owns
from db import models
from sqlalchemy.orm import Session


def _seed_two_workspaces_with_one_message(db: Session):
    """Helper: creates two workspaces, each with one session and one message.
    Returns (ws_a, ws_b, msg_in_a)."""
    user = models.User(
        id="user-test", username="test", password_hash="hash", is_admin=False
    )
    ws_a = models.Workspace(
        id="ws-a", slug="ws-a", display_name="A",
        system_prompt="", enabled_tools=[],
        engine_config={"backend": "ollama", "model": "gemma4:e4b"},
        user_id="user-test",
    )
    ws_b = models.Workspace(
        id="ws-b", slug="ws-b", display_name="B",
        system_prompt="", enabled_tools=[],
        engine_config={"backend": "ollama", "model": "gemma4:e4b"},
        user_id="user-test",
    )
    sess_a = models.Session(id="sess-a", workspace_id="ws-a", title="t", user_id="user-test")
    msg_a = models.Message(id="msg-a", session_id="sess-a", role="user", content="x")
    db.add_all([user, ws_a, ws_b, sess_a, msg_a])
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


def test_message_in_workspace_via_session(db_session):
    """Verify the Message helper resolves through Session.workspace_id."""
    from routers.chat import _message_in_workspace_or_404
    ws_a, ws_b, msg = _seed_two_workspaces_with_one_message(db_session)
    # Owner workspace → returns the message.
    result = _message_in_workspace_or_404("msg-a", "ws-a", db_session)
    assert result.id == "msg-a"


def test_message_cross_workspace_404(db_session):
    """Cross-workspace message lookup returns 404."""
    from routers.chat import _message_in_workspace_or_404
    ws_a, ws_b, msg = _seed_two_workspaces_with_one_message(db_session)
    with pytest.raises(HTTPException) as exc:
        _message_in_workspace_or_404("msg-a", "ws-b", db_session)
    assert exc.value.status_code == 404


def test_message_missing_404(db_session):
    """Missing message returns 404 regardless of workspace."""
    from routers.chat import _message_in_workspace_or_404
    ws_a, ws_b, msg = _seed_two_workspaces_with_one_message(db_session)
    with pytest.raises(HTTPException) as exc:
        _message_in_workspace_or_404("nonexistent", "ws-a", db_session)
    assert exc.value.status_code == 404


def test_builtin_workspaces_registry_has_expected_slugs():
    """The two original builtins must be present in the registry."""
    from services.builtins import BUILTIN_WORKSPACES
    slugs = {b.slug for b in BUILTIN_WORKSPACES}
    assert "it_copilot" in slugs
    assert "personal" in slugs


def test_builtin_record_has_required_fields():
    """Each registry entry has all the fields the seed + reset code needs."""
    from services.builtins import BUILTIN_WORKSPACES, BuiltinWorkspace
    for b in BUILTIN_WORKSPACES:
        assert isinstance(b, BuiltinWorkspace)
        assert b.slug
        assert b.display_name
        assert b.system_prompt_file
        assert isinstance(b.enabled_tools, list)
        assert b.engine_config["backend"] == "llama_cpp"
        # engine_config has no 'model' key — model id is set elsewhere.


def test_session_patch_rejects_cross_workspace_folder_id(db_session, monkeypatch):
    """PATCH /sessions/{id} must reject a folder_id from a different workspace."""
    from fastapi.testclient import TestClient
    from core import cookie_auth
    from db import database
    from main import app

    user = models.User(
        id="user-patch", username="patch", password_hash="hash", is_admin=True
    )
    ws_a = models.Workspace(
        id="ws-pa", slug="ws-pa", display_name="A",
        system_prompt="", enabled_tools=[],
        engine_config={"backend": "llama_cpp"},
        user_id="user-patch",
    )
    ws_b = models.Workspace(
        id="ws-pb", slug="ws-pb", display_name="B",
        system_prompt="", enabled_tools=[],
        engine_config={"backend": "llama_cpp"},
        user_id="user-patch",
    )
    sess_a = models.Session(id="sess-pa", workspace_id="ws-pa", title="t", user_id="user-patch")
    folder_b = models.Folder(id="f-pb", workspace_id="ws-pb", name="B folder", user_id="user-patch")
    db_session.add_all([user, ws_a, ws_b, sess_a, folder_b])
    db_session.commit()

    sid = cookie_auth.create_session(db_session, user.id)

    def _get_db_override():
        yield db_session

    monkeypatch.setattr(database, "init_db", lambda: None)
    app.dependency_overrides[database.get_db] = _get_db_override
    try:
        with TestClient(app) as c:
            c.cookies.set(cookie_auth.COOKIE_NAME, sid)
            resp = c.patch(
                "/sessions/sess-pa?workspace=ws-pa",
                json={"folder_id": "f-pb"},
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code in (403, 404), f"got {resp.status_code} body={resp.text}"

    db_session.expire_all()
    sess = db_session.query(models.Session).filter_by(id="sess-pa").one()
    assert sess.folder_id is None
