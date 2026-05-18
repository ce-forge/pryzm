"""Admin engine reverse-proxy.

llama-swap isn't running in unit tests, so the proxy's actual upstream
is unreachable. These tests cover the auth gate + the upstream-error
branch (httpx raises RequestError when there's nothing on port 8080).
"""
import httpx
import pytest
from fastapi.testclient import TestClient

from core import cookie_auth
from db import database, models
from main import app


def _seed_admin(db_session, username="admin"):
    u = models.User(
        username=username,
        password_hash=cookie_auth.hash_password("p" * 12),
        is_admin=True, is_active=True,
    )
    db_session.add(u); db_session.commit(); db_session.refresh(u)
    return u


def _seed_user(db_session, username="bob"):
    u = models.User(
        username=username,
        password_hash=cookie_auth.hash_password("p" * 12),
        is_admin=False, is_active=True,
    )
    db_session.add(u); db_session.commit(); db_session.refresh(u)
    return u


def _client_for(db_session, user):
    sid = cookie_auth.create_session(db_session, user.id)
    app.dependency_overrides[database.get_db] = lambda: db_session
    c = TestClient(app)
    c.cookies.set(cookie_auth.COOKIE_NAME, sid)
    return c


def test_engine_proxy_requires_admin(db_session):
    """Non-admin users get 403 — they don't reach the proxy at all."""
    try:
        bob = _seed_user(db_session)
        c = _client_for(db_session, bob)
        r = c.get("/api/admin/engine/")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_engine_proxy_unauthenticated_is_401(db_session):
    try:
        app.dependency_overrides[database.get_db] = lambda: db_session
        c = TestClient(app)
        r = c.get("/api/admin/engine/anything")
        assert r.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_engine_proxy_502_when_upstream_unreachable(db_session, monkeypatch):
    """With llama-swap not running (its 127.0.0.1:8080 binding) the proxy
    surfaces httpx.RequestError as a 502."""
    try:
        admin = _seed_admin(db_session)
        c = _client_for(db_session, admin)

        # Force the upstream client to raise RequestError on send.
        class _BoomClient:
            def build_request(self, **kwargs):
                return httpx.Request(
                    method=kwargs["method"], url=kwargs["url"],
                )
            async def send(self, _req, stream=True):
                raise httpx.ConnectError("simulated upstream down")

        # The proxy reads app.state.http_client. Override via TestClient
        # lifespan: since lifespan doesn't run in TestClient by default,
        # set the attribute directly on the app object.
        app.state.http_client = _BoomClient()  # type: ignore[assignment]
        try:
            r = c.get("/api/admin/engine/anywhere")
            assert r.status_code == 502
            assert "upstream" in r.json()["detail"].lower()
        finally:
            # Restore to whatever the next test expects (None is fine —
            # subsequent tests that need the client mock it themselves).
            if hasattr(app.state, "http_client"):
                delattr(app.state, "http_client")
    finally:
        app.dependency_overrides.clear()
