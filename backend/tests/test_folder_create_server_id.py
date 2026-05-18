"""POST /folders generates its own id."""
from fastapi.testclient import TestClient

from db import database, models
from main import app


def test_folder_create_does_not_require_client_id(db_session, monkeypatch):
    ws = models.Workspace(
        id="ws-fid", slug="ws-fid", display_name="FID",
        system_prompt="", enabled_tools=[], is_builtin=False,
        engine_config={"backend": "llama_cpp"},
    )
    db_session.add(ws)
    db_session.commit()

    monkeypatch.setattr("config.settings.PRYZM_API_TOKEN", "test-token")
    app.dependency_overrides[database.get_db] = lambda: db_session
    try:
        c = TestClient(app)
        c.headers.update({"Authorization": "Bearer test-token"})
        r = c.post("/folders", json={"name": "Notes", "workspace": "ws-fid"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert "id" in body
        assert len(body["id"]) > 20
        folder = db_session.query(models.Folder).filter_by(id=body["id"]).one()
        assert folder.name == "Notes"
    finally:
        app.dependency_overrides.clear()


def test_folder_create_ignores_client_supplied_id(db_session, monkeypatch):
    ws = models.Workspace(
        id="ws-fid2", slug="ws-fid2", display_name="FID2",
        system_prompt="", enabled_tools=[], is_builtin=False,
        engine_config={"backend": "llama_cpp"},
    )
    db_session.add(ws)
    db_session.commit()

    monkeypatch.setattr("config.settings.PRYZM_API_TOKEN", "test-token")
    app.dependency_overrides[database.get_db] = lambda: db_session
    try:
        c = TestClient(app)
        c.headers.update({"Authorization": "Bearer test-token"})
        r = c.post("/folders", json={"name": "Notes", "workspace": "ws-fid2", "id": "client-supplied-id"})
        # Either pydantic strips the extra (200 with server id) or rejects (422)
        assert r.status_code in (200, 422)
        if r.status_code == 200:
            body = r.json()
            assert body["id"] != "client-supplied-id"
    finally:
        app.dependency_overrides.clear()
