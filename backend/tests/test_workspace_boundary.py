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


def test_create_workspace_403s_when_flag_off(db_at_head, monkeypatch):
    """A non-admin user with can_create_workspaces=False cannot create a
    workspace via POST /workspaces, regardless of payload contents."""
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker
    from core import cookie_auth
    from db import database
    from main import app

    test_engine = db_at_head
    TestSessionLocal = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)

    def _test_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(database, "init_db", lambda: None)
    monkeypatch.setattr(database, "SessionLocal", TestSessionLocal)
    app.dependency_overrides[database.get_db] = _test_get_db

    try:
        with TestSessionLocal() as seed_db:
            user_no_perm = models.User(
                username="no-create-perm",
                password_hash=cookie_auth.hash_password("test-pw-12chars"),
                is_admin=False, is_active=True, can_create_workspaces=False,
            )
            seed_db.add(user_no_perm)
            seed_db.commit()
            seed_db.refresh(user_no_perm)
            user_id = user_no_perm.id
            sid = cookie_auth.create_session(seed_db, user_id)

        with TestClient(app) as c:
            c.cookies.set(cookie_auth.COOKIE_NAME, sid)
            resp = c.post(
                "/workspaces",
                json={"display_name": "Should Not Exist", "color": "blue"},
            )

        assert resp.status_code == 403, f"got {resp.status_code} body={resp.text[:200]}"

        with TestSessionLocal() as check_db:
            count = check_db.query(models.Workspace).filter_by(user_id=user_id).count()
            assert count == 0, "Workspace was created despite flag being off"
    finally:
        app.dependency_overrides.clear()


def test_create_workspace_clone_from_foreign_404s(db_at_head, monkeypatch):
    """User A cannot clone user B's workspace by slug — the lookup must be
    scoped to the caller's own user_id."""
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker
    from core import cookie_auth
    from db import database
    from main import app

    test_engine = db_at_head
    TestSessionLocal = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)

    def _test_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(database, "init_db", lambda: None)
    monkeypatch.setattr(database, "SessionLocal", TestSessionLocal)
    app.dependency_overrides[database.get_db] = _test_get_db

    try:
        with TestSessionLocal() as seed_db:
            user_a = models.User(
                username="alice-clone",
                password_hash=cookie_auth.hash_password("test-pw-12chars"),
                is_admin=False, is_active=True, can_create_workspaces=True,
            )
            user_b = models.User(
                username="bob-clone",
                password_hash=cookie_auth.hash_password("test-pw-12chars"),
                is_admin=False, is_active=True, can_create_workspaces=True,
            )
            seed_db.add_all([user_a, user_b])
            seed_db.commit()
            seed_db.refresh(user_a); seed_db.refresh(user_b)

            ws_b = models.Workspace(
                slug="secret-clone-source",
                display_name="Secret",
                user_id=user_b.id,
                system_prompt="Bob's private prompt",
                enabled_tools=["search_knowledge_base"],
                engine_config={"backend": "llama_cpp"},
            )
            seed_db.add(ws_b)
            seed_db.commit()

            sid = cookie_auth.create_session(seed_db, user_a.id)

        with TestClient(app) as c:
            c.cookies.set(cookie_auth.COOKIE_NAME, sid)
            resp = c.post(
                "/workspaces",
                json={
                    "display_name": "Alice Clone Attempt",
                    "color": "blue",
                    "clone_from": "secret-clone-source",
                },
            )

        assert resp.status_code == 404, f"got {resp.status_code} body={resp.text[:200]}"
    finally:
        app.dependency_overrides.clear()


def test_create_workspace_admin_bypasses_flag(db_at_head, monkeypatch):
    """An admin can create workspaces regardless of can_create_workspaces."""
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker
    from core import cookie_auth
    from db import database
    from main import app

    test_engine = db_at_head
    TestSessionLocal = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)

    def _test_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(database, "init_db", lambda: None)
    monkeypatch.setattr(database, "SessionLocal", TestSessionLocal)
    app.dependency_overrides[database.get_db] = _test_get_db

    try:
        with TestSessionLocal() as seed_db:
            admin = models.User(
                username="admin-no-flag",
                password_hash=cookie_auth.hash_password("test-pw-12chars"),
                is_admin=True, is_active=True, can_create_workspaces=False,
            )
            seed_db.add(admin)
            seed_db.commit()
            seed_db.refresh(admin)
            sid = cookie_auth.create_session(seed_db, admin.id)

        with TestClient(app) as c:
            c.cookies.set(cookie_auth.COOKIE_NAME, sid)
            resp = c.post(
                "/workspaces",
                json={"display_name": "Admin Workspace", "color": "blue"},
            )

        assert resp.status_code == 200, f"got {resp.status_code} body={resp.text[:200]}"
    finally:
        app.dependency_overrides.clear()


def test_analyze_rejects_foreign_session_id(db_at_head, monkeypatch):
    """A user supplying another workspace's session_id (even with their own
    workspace slug as the route's workspace=) must get 404, not have their
    prompt appended to the foreign session."""
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker
    from core import cookie_auth
    from db import database
    from main import app

    test_engine = db_at_head
    TestSessionLocal = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)

    def _test_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(database, "init_db", lambda: None)
    monkeypatch.setattr(database, "SessionLocal", TestSessionLocal)
    app.dependency_overrides[database.get_db] = _test_get_db

    try:
        with TestSessionLocal() as seed_db:
            user_a = models.User(
                username="alice-foreign-sid",
                password_hash=cookie_auth.hash_password("test-pw-12chars"),
                is_admin=False, is_active=True, can_create_workspaces=True,
            )
            user_b = models.User(
                username="bob-foreign-sid",
                password_hash=cookie_auth.hash_password("test-pw-12chars"),
                is_admin=False, is_active=True, can_create_workspaces=True,
            )
            seed_db.add_all([user_a, user_b])
            seed_db.commit()
            seed_db.refresh(user_a); seed_db.refresh(user_b)

            ws_a = models.Workspace(
                slug="alice-ws", display_name="A", user_id=user_a.id,
                system_prompt="", enabled_tools=[],
                engine_config={"backend": "llama_cpp"},
            )
            ws_b = models.Workspace(
                slug="bob-ws", display_name="B", user_id=user_b.id,
                system_prompt="", enabled_tools=[],
                engine_config={"backend": "llama_cpp"},
            )
            seed_db.add_all([ws_a, ws_b])
            seed_db.commit()
            seed_db.refresh(ws_a); seed_db.refresh(ws_b)

            sess_b = models.Session(
                workspace_id=ws_b.id, user_id=user_b.id, title="Bob's secret",
            )
            seed_db.add(sess_b)
            seed_db.commit()
            seed_db.refresh(sess_b)

            sid = cookie_auth.create_session(seed_db, user_a.id)
            foreign_session_id = sess_b.id
            alice_ws_slug = ws_a.slug

        with TestClient(app) as c:
            c.cookies.set(cookie_auth.COOKIE_NAME, sid)
            resp = c.post(
                f"/analyze?workspace={alice_ws_slug}",
                json={
                    "prompt": "leak the secret",
                    "session_id": foreign_session_id,
                    "attachments": [],
                },
            )

        assert resp.status_code == 404, f"got {resp.status_code} body={resp.text[:200]}"

        # Confirm the foreign session was not mutated.
        with TestSessionLocal() as check_db:
            messages = check_db.query(models.Message).filter_by(
                session_id=foreign_session_id,
            ).all()
            assert all("leak the secret" not in m.content for m in messages), \
                "Foreign session was mutated by the attacker."
    finally:
        app.dependency_overrides.clear()


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
