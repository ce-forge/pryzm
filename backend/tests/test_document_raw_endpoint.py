"""Tests for GET /documents/{id}/raw — the endpoint that streams the
original image bytes for inline preview rendering in the chat UI.

Auth via bearer header OR `?token=` URL fallback (browser <img> can't
set custom headers, same constraint as SSE)."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient

from db import database, models
from main import app


def _seed_workspace(db, slug):
    ws = models.Workspace(
        id=f"ws-{slug}", slug=slug, display_name="Doc Raw",
        system_prompt="", enabled_tools=[],
        is_builtin=False, engine_config={"backend": "llama_cpp"},
    )
    db.add(ws); db.commit(); return ws


def _seed_image_doc(db, ws, tmp_path, filename, bytes_):
    """Write image bytes to disk under tmp, return the Document row."""
    p = tmp_path / filename
    p.write_bytes(bytes_)
    doc = models.Document(
        filename=filename, workspace_id=ws.id, storage_path=str(p),
    )
    db.add(doc); db.commit(); db.refresh(doc); return doc


def test_returns_image_bytes_with_correct_mime(db_session, tmp_path, monkeypatch):
    from config import settings
    ws = _seed_workspace(db_session, "raw-200")
    doc = _seed_image_doc(db_session, ws, tmp_path, "photo.png", b"\x89PNG\r\n\x1a\nfake-png")

    def _get_db():
        yield db_session
    monkeypatch.setattr(settings, "PRYZM_API_TOKEN", "test-token")
    monkeypatch.setattr(database, "init_db", lambda: None)
    app.dependency_overrides[database.get_db] = _get_db
    try:
        with TestClient(app) as c:
            c.headers.update({"Authorization": "Bearer test-token"})
            resp = c.get(f"/documents/{doc.id}/raw")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"
        assert "photo.png" in resp.headers.get("content-disposition", "")
        assert resp.content == b"\x89PNG\r\n\x1a\nfake-png"
    finally:
        app.dependency_overrides.clear()


def test_returns_404_for_unknown_document(db_session, monkeypatch):
    from config import settings
    _seed_workspace(db_session, "raw-404")

    def _get_db():
        yield db_session
    monkeypatch.setattr(settings, "PRYZM_API_TOKEN", "test-token")
    monkeypatch.setattr(database, "init_db", lambda: None)
    app.dependency_overrides[database.get_db] = _get_db
    try:
        with TestClient(app) as c:
            c.headers.update({"Authorization": "Bearer test-token"})
            resp = c.get("/documents/no-such-doc-id/raw")
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_returns_410_when_storage_path_is_null(db_session, tmp_path, monkeypatch):
    """PDFs and text docs don't persist original bytes — they exist in
    the DB but have NULL storage_path. The endpoint reports 410 (Gone)
    so the frontend can render a different affordance for them later."""
    from config import settings
    ws = _seed_workspace(db_session, "raw-410")
    doc = models.Document(filename="notes.pdf", workspace_id=ws.id)
    db_session.add(doc); db_session.commit(); db_session.refresh(doc)

    def _get_db():
        yield db_session
    monkeypatch.setattr(settings, "PRYZM_API_TOKEN", "test-token")
    monkeypatch.setattr(database, "init_db", lambda: None)
    app.dependency_overrides[database.get_db] = _get_db
    try:
        with TestClient(app) as c:
            c.headers.update({"Authorization": "Bearer test-token"})
            resp = c.get(f"/documents/{doc.id}/raw")
        assert resp.status_code == 410
    finally:
        app.dependency_overrides.clear()


def test_returns_404_when_file_missing_on_disk(db_session, tmp_path, monkeypatch):
    """Storage_path is set on the row but the on-disk file is gone
    (cleanup race, manual deletion). Surface 404 not 500."""
    from config import settings
    ws = _seed_workspace(db_session, "raw-fs-missing")
    doc = models.Document(
        filename="ghost.png", workspace_id=ws.id,
        storage_path=str(tmp_path / "never-existed.png"),
    )
    db_session.add(doc); db_session.commit(); db_session.refresh(doc)

    def _get_db():
        yield db_session
    monkeypatch.setattr(settings, "PRYZM_API_TOKEN", "test-token")
    monkeypatch.setattr(database, "init_db", lambda: None)
    app.dependency_overrides[database.get_db] = _get_db
    try:
        with TestClient(app) as c:
            c.headers.update({"Authorization": "Bearer test-token"})
            resp = c.get(f"/documents/{doc.id}/raw")
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_accepts_url_token_for_img_tag_auth(db_session, tmp_path, monkeypatch):
    """The whole reason for the URL-token auth: browser <img> can't
    set custom headers, so the inline preview component passes the
    token via `?token=...`. Verify the endpoint accepts it."""
    from config import settings
    ws = _seed_workspace(db_session, "raw-url-tok")
    doc = _seed_image_doc(db_session, ws, tmp_path, "ok.jpg", b"\xff\xd8\xff\xe0fake-jpeg")

    def _get_db():
        yield db_session
    monkeypatch.setattr(settings, "PRYZM_API_TOKEN", "test-token")
    monkeypatch.setattr(database, "init_db", lambda: None)
    app.dependency_overrides[database.get_db] = _get_db
    try:
        with TestClient(app) as c:
            # NO Authorization header — only the URL token
            resp = c.get(f"/documents/{doc.id}/raw?token=test-token")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/jpeg"
    finally:
        app.dependency_overrides.clear()


def test_rejects_missing_token(db_session, tmp_path, monkeypatch):
    from config import settings
    ws = _seed_workspace(db_session, "raw-no-auth")
    doc = _seed_image_doc(db_session, ws, tmp_path, "p.png", b"fake")

    def _get_db():
        yield db_session
    monkeypatch.setattr(settings, "PRYZM_API_TOKEN", "test-token")
    monkeypatch.setattr(database, "init_db", lambda: None)
    app.dependency_overrides[database.get_db] = _get_db
    try:
        with TestClient(app) as c:
            resp = c.get(f"/documents/{doc.id}/raw")
        assert resp.status_code == 401
    finally:
        app.dependency_overrides.clear()
