"""GET /documents/{id}/raw must return private cache headers + ETag.

`public` would let intermediate caches store the response keyed on URL
(which carries the auth token in `?token=`). Restrict to the end user's
browser with `private`, and add an ETag so the browser can revalidate.
"""
import os
import tempfile

from fastapi.testclient import TestClient

from config import settings
from core.cookie_auth import hash_password
from db import database, models
from main import app


def test_document_raw_has_private_cache_and_etag(db_session, monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".png")
    os.write(fd, b"\x89PNG\r\n\x1a\n")
    os.close(fd)

    # Phase B: bearer token resolves to the bootstrap admin via the dual-mode
    # current_user dep, and workspace_query_dep scopes by (slug, user.id).
    admin = models.User(
        username="admin", password_hash=hash_password("test-pw-12chars"),
        is_admin=True, is_active=True, can_create_workspaces=True,
    )
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)

    ws = models.Workspace(
        id="ws-h",
        slug="ws-h",
        display_name="H",
        system_prompt="",
        enabled_tools=[],
        is_builtin=False,
        engine_config={"backend": "llama_cpp"},
        user_id=admin.id,
        is_template=False,
    )
    doc = models.Document(
        id="doc-h",
        workspace_id="ws-h",
        session_id=None,
        is_global=True,
        filename="a.png",
        status="ready",
        storage_path=path,
    )
    db_session.add_all([ws, doc])
    db_session.commit()

    def _get_db_override():
        yield db_session

    monkeypatch.setattr(settings, "PRYZM_API_TOKEN", "test-token")
    monkeypatch.setattr(database, "init_db", lambda: None)
    app.dependency_overrides[database.get_db] = _get_db_override
    try:
        with TestClient(app) as c:
            c.headers.update({"Authorization": "Bearer test-token"})
            resp = c.get("/documents/doc-h/raw?workspace=ws-h")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    cache = resp.headers["cache-control"]
    assert "private" in cache
    assert "public" not in cache
    assert "immutable" not in cache
    assert "etag" in {k.lower() for k in resp.headers.keys()}
    assert resp.headers["etag"] == '"doc-h"'
