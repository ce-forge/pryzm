"""Admin engine reverse-proxy.

llama-swap isn't running in unit tests, so the proxy's actual upstream
is unreachable. These tests cover the auth gate + the upstream-error
branch (httpx raises RequestError when there's nothing on port 8080) +
the path-rewriting helpers that inject the proxy prefix into upstream
HTML.
"""
import httpx
import pytest
from fastapi.testclient import TestClient

from core import cookie_auth
from db import database, models
from main import app
from routers.admin_engine import _rewrite_body, _rewrite_location


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


# ---------------------------------------------------------------------------
# Path-rewriting helpers
# ---------------------------------------------------------------------------

def test_rewrite_location_prefixes_root_relative():
    assert _rewrite_location("/ui") == "/api/admin/engine/ui"
    assert _rewrite_location("/ui/models") == "/api/admin/engine/ui/models"


def test_rewrite_location_leaves_absolute_and_already_prefixed_alone():
    assert _rewrite_location("https://example.com/ui") == "https://example.com/ui"
    assert _rewrite_location("/api/admin/engine/ui") == "/api/admin/engine/ui"


def test_rewrite_body_injects_prefix_into_html_paths():
    html = (
        b'<link rel="icon" href="/ui/favicon.png" />\n'
        b'<script src="/ui/assets/index.js"></script>\n'
        b'<a href="/api/models">models</a>\n'
        b'fetch("/ui/data.json")'
    )
    out = _rewrite_body(html).decode("utf-8")
    assert '/api/admin/engine/ui/favicon.png' in out
    assert '/api/admin/engine/ui/assets/index.js' in out
    assert '/api/admin/engine/api/models' in out
    assert '/api/admin/engine/ui/data.json' in out


def test_rewrite_body_handles_template_literal_backticks():
    """The minified llama-swap bundle uses template literals for fetch /
    EventSource URLs — `/api/events`, `/api/version`, etc."""
    js = (
        b'new EventSource(`/api/events`);\n'
        b'fetch(`/api/version`);\n'
        b'fetch(`/upstream/${name}/health`);\n'
    )
    out = _rewrite_body(js).decode("utf-8")
    assert '/api/admin/engine/api/events' in out
    assert '/api/admin/engine/api/version' in out
    assert '/api/admin/engine/upstream/' in out


def test_rewrite_body_covers_ui_route_segments():
    """SPA route links like /models, /activity, /performance are top-level
    paths from llama-swap's perspective and need the prefix too."""
    html = (
        b'<a href="/models">Models</a>'
        b'<a href="/activity">Activity</a>'
        b'<a href="/performance">Perf</a>'
        b'<a href="/logs">Logs</a>'
    )
    out = _rewrite_body(html).decode("utf-8")
    assert '/api/admin/engine/models"' in out
    assert '/api/admin/engine/activity"' in out
    assert '/api/admin/engine/performance"' in out
    assert '/api/admin/engine/logs"' in out


def test_rewrite_body_skips_unrelated_paths():
    # Random absolute paths that aren't llama-swap's surface stay untouched.
    html = b'<a href="/something/else">x</a>'
    out = _rewrite_body(html)
    assert b'/api/admin/engine' not in out


def test_rewrite_body_handles_non_utf8_gracefully():
    bin_blob = b'\xff\xfe\x00\x01'
    assert _rewrite_body(bin_blob) == bin_blob
