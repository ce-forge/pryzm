"""POST /folders generates its own id."""
from fastapi.testclient import TestClient

from core import cookie_auth
from db import database, models
from main import app


def _seed_admin_and_ws(db_session, ws_id: str):
    admin = models.User(
        username="admin", password_hash=cookie_auth.hash_password("admin-pw-12chars"),
        is_admin=True, is_active=True,
    )
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)

    ws = models.Workspace(
        id=ws_id, slug=ws_id, display_name=ws_id.upper(),
        system_prompt="", enabled_tools=[],
        user_id=admin.id,
        engine_config={"backend": "llama_cpp"},
    )
    db_session.add(ws)
    db_session.commit()
    return admin


def test_folder_create_does_not_require_client_id(db_session):
    admin = _seed_admin_and_ws(db_session, "ws-fid")
    sid = cookie_auth.create_session(db_session, admin.id)
    app.dependency_overrides[database.get_db] = lambda: db_session
    try:
        c = TestClient(app)
        c.cookies.set(cookie_auth.COOKIE_NAME, sid)
        r = c.post("/folders", json={"name": "Notes", "workspace": "ws-fid"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert "id" in body
        assert len(body["id"]) > 20
        folder = db_session.query(models.Folder).filter_by(id=body["id"]).one()
        assert folder.name == "Notes"
        assert folder.user_id == admin.id
    finally:
        app.dependency_overrides.clear()


def test_folder_create_ignores_client_supplied_id(db_session):
    admin = _seed_admin_and_ws(db_session, "ws-fid2")
    sid = cookie_auth.create_session(db_session, admin.id)
    app.dependency_overrides[database.get_db] = lambda: db_session
    try:
        c = TestClient(app)
        c.cookies.set(cookie_auth.COOKIE_NAME, sid)
        r = c.post("/folders", json={"name": "Notes", "workspace": "ws-fid2", "id": "client-supplied-id"})
        # Either pydantic strips the extra (200 with server id) or rejects (422)
        assert r.status_code in (200, 422)
        if r.status_code == 200:
            body = r.json()
            assert body["id"] != "client-supplied-id"
            folder = db_session.query(models.Folder).filter_by(id=body["id"]).one()
            assert folder.user_id == admin.id
    finally:
        app.dependency_overrides.clear()
