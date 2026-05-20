"""GET /documents/{id}/raw must return private cache headers + ETag.

`public` would let intermediate caches store the response keyed on URL
(which carries the auth token in `?token=`). Restrict to the end user's
browser with `private`, and add an ETag so the browser can revalidate.
"""
import os
import tempfile

from fastapi.testclient import TestClient

from core import cookie_auth
from core.cookie_auth import hash_password
from db import database, models
from main import app


def test_document_raw_has_private_cache_and_etag(db_session, monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".png")
    os.write(fd, b"\x89PNG\r\n\x1a\n")
    os.close(fd)

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
        engine_config={"backend": "llama_cpp"},
        user_id=admin.id,
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

    sid = cookie_auth.create_session(db_session, admin.id)

    def _get_db_override():
        yield db_session

    monkeypatch.setattr(database, "init_db", lambda: None)
    app.dependency_overrides[database.get_db] = _get_db_override
    try:
        with TestClient(app) as c:
            c.cookies.set(cookie_auth.COOKIE_NAME, sid)
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
    # RFC 5987: header carries both ASCII-safe and percent-encoded forms.
    cd = resp.headers["content-disposition"]
    assert cd.startswith("inline; filename=")
    assert "filename*=UTF-8''" in cd


def test_document_raw_disposition_quotes_unsafe_filename(db_session, monkeypatch):
    """A filename containing a quote character must not break the header.
    The ASCII-safe form is stripped and the original survives in filename*=."""
    fd, path = tempfile.mkstemp(suffix=".png")
    os.write(fd, b"\x89PNG\r\n\x1a\n")
    os.close(fd)

    admin = models.User(
        username="admin-cd", password_hash=hash_password("test-pw-12chars"),
        is_admin=True, is_active=True, can_create_workspaces=True,
    )
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)

    ws = models.Workspace(
        id="ws-cd", slug="ws-cd", display_name="CD",
        system_prompt="", enabled_tools=[],
        engine_config={"backend": "llama_cpp"},
        user_id=admin.id,
    )
    doc = models.Document(
        id="doc-cd",
        workspace_id="ws-cd",
        session_id=None,
        is_global=True,
        filename='weird";name.png',
        status="ready",
        storage_path=path,
    )
    db_session.add_all([ws, doc])
    db_session.commit()

    sid = cookie_auth.create_session(db_session, admin.id)

    def _get_db_override():
        yield db_session

    monkeypatch.setattr(database, "init_db", lambda: None)
    app.dependency_overrides[database.get_db] = _get_db_override
    try:
        with TestClient(app) as c:
            c.cookies.set(cookie_auth.COOKIE_NAME, sid)
            resp = c.get("/documents/doc-cd/raw?workspace=ws-cd")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    cd = resp.headers["content-disposition"]
    # ASCII-safe form must not contain raw quote chars from the filename.
    # The encoded form (filename*=) carries the original through percent-encoding.
    assert '"' not in cd.split("filename*=")[0].split('filename="')[1].split('"')[0]
    assert "filename*=UTF-8''" in cd
    assert "%22" in cd  # the original quote, percent-encoded
