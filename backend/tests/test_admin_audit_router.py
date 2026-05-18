"""Admin audit read endpoints.

Covers GET /api/admin/audit (with filters + cursor pagination),
GET /api/admin/audit/event-types, GET /api/admin/audit/{event_id},
and the require_admin gate.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from core import cookie_auth
from db import database, models
from main import app


def _seed_admin(db_session, username="admin"):
    u = models.User(
        username=username,
        password_hash=cookie_auth.hash_password("admin-pw-12chars"),
        is_admin=True, is_active=True, can_create_workspaces=True,
    )
    db_session.add(u); db_session.commit(); db_session.refresh(u)
    return u


def _seed_user(db_session, username="bob"):
    u = models.User(
        username=username,
        password_hash=cookie_auth.hash_password("bob-pw-12chars"),
        is_admin=False, is_active=True,
    )
    db_session.add(u); db_session.commit(); db_session.refresh(u)
    return u


def _admin_client(db_session, user=None):
    u = user or _seed_admin(db_session)
    sid = cookie_auth.create_session(db_session, u.id)
    app.dependency_overrides[database.get_db] = lambda: db_session
    c = TestClient(app)
    c.cookies.set(cookie_auth.COOKIE_NAME, sid)
    return c, u


def _seed_event(db_session, *, user_id=None, event_type="x.y", workspace_id=None,
                payload=None, created_at=None):
    e = models.AuditEvent(
        user_id=user_id,
        user_display_name_at_event="snap",
        event_type=event_type,
        workspace_id=workspace_id,
        payload=payload or {},
        created_at=created_at or datetime.now(timezone.utc),
    )
    db_session.add(e); db_session.commit(); db_session.refresh(e)
    return e


# -----------------------------------------------------------------------------
# auth gate
# -----------------------------------------------------------------------------

def test_list_requires_admin(db_session):
    try:
        non_admin = _seed_user(db_session)
        sid = cookie_auth.create_session(db_session, non_admin.id)
        app.dependency_overrides[database.get_db] = lambda: db_session
        c = TestClient(app)
        c.cookies.set(cookie_auth.COOKIE_NAME, sid)
        r = c.get("/api/admin/audit")
        assert r.status_code == 403, r.text
    finally:
        app.dependency_overrides.clear()


def test_list_rejects_unauthenticated(db_session):
    try:
        app.dependency_overrides[database.get_db] = lambda: db_session
        c = TestClient(app)
        r = c.get("/api/admin/audit")
        assert r.status_code == 401, r.text
    finally:
        app.dependency_overrides.clear()


# -----------------------------------------------------------------------------
# list filtering
# -----------------------------------------------------------------------------

def test_list_returns_events_newest_first(db_session):
    try:
        c, admin = _admin_client(db_session)
        now = datetime.now(timezone.utc)
        old = _seed_event(db_session, event_type="a.older", created_at=now - timedelta(hours=2))
        new = _seed_event(db_session, event_type="a.newer", created_at=now - timedelta(hours=1))

        r = c.get("/api/admin/audit")
        assert r.status_code == 200, r.text
        body = r.json()
        # Includes the admin's own login event from session creation? No — login
        # events are emitted by the auth router, not by create_session directly.
        # But there's at least our two seeded rows in order.
        event_types = [e["event_type"] for e in body["events"]]
        assert event_types.index("a.newer") < event_types.index("a.older")
    finally:
        app.dependency_overrides.clear()


def test_list_filters_by_user_id(db_session):
    try:
        c, admin = _admin_client(db_session)
        bob = _seed_user(db_session)
        _seed_event(db_session, user_id=admin.id, event_type="x.admin")
        _seed_event(db_session, user_id=bob.id, event_type="x.bob")

        r = c.get(f"/api/admin/audit?user_id={bob.id}")
        assert r.status_code == 200, r.text
        events = r.json()["events"]
        for e in events:
            assert e["user_id"] == bob.id
        assert any(e["event_type"] == "x.bob" for e in events)
        assert not any(e["event_type"] == "x.admin" for e in events)
    finally:
        app.dependency_overrides.clear()


def test_list_filters_by_event_type_exact(db_session):
    try:
        c, admin = _admin_client(db_session)
        _seed_event(db_session, event_type="admin.user.created")
        _seed_event(db_session, event_type="admin.user.edited")

        r = c.get("/api/admin/audit?event_type=admin.user.created")
        assert r.status_code == 200, r.text
        events = r.json()["events"]
        assert all(e["event_type"] == "admin.user.created" for e in events)
        assert any(e["event_type"] == "admin.user.created" for e in events)
    finally:
        app.dependency_overrides.clear()


def test_list_filters_by_event_type_prefix(db_session):
    try:
        c, admin = _admin_client(db_session)
        _seed_event(db_session, event_type="admin.user.created")
        _seed_event(db_session, event_type="admin.user.edited")
        _seed_event(db_session, event_type="admin.template.created")
        _seed_event(db_session, event_type="auth.login_success")

        r = c.get("/api/admin/audit?event_type=prefix:admin.user")
        assert r.status_code == 200, r.text
        events = r.json()["events"]
        types = {e["event_type"] for e in events}
        assert types == {"admin.user.created", "admin.user.edited"}
    finally:
        app.dependency_overrides.clear()


def test_list_filters_by_time_range(db_session):
    try:
        c, admin = _admin_client(db_session)
        now = datetime.now(timezone.utc)
        too_old = _seed_event(db_session, event_type="t.old", created_at=now - timedelta(hours=5))
        in_range = _seed_event(db_session, event_type="t.in", created_at=now - timedelta(hours=2))
        too_new = _seed_event(db_session, event_type="t.new", created_at=now)

        # `params=` URL-encodes properly so the `+00:00` offset doesn't get
        # munged to a space the way it would in an f-string.
        r = c.get("/api/admin/audit", params={
            "from": (now - timedelta(hours=3)).isoformat(),
            "to": (now - timedelta(minutes=30)).isoformat(),
        })
        assert r.status_code == 200, r.text
        types = {e["event_type"] for e in r.json()["events"]}
        assert types == {"t.in"}
    finally:
        app.dependency_overrides.clear()


# -----------------------------------------------------------------------------
# pagination
# -----------------------------------------------------------------------------

def test_cursor_pagination_walks_all_rows(db_session):
    try:
        c, admin = _admin_client(db_session)
        now = datetime.now(timezone.utc)
        # 7 rows, oldest first in seeding
        for i in range(7):
            _seed_event(
                db_session, event_type=f"page.{i}",
                created_at=now - timedelta(minutes=10 - i),
            )

        r = c.get("/api/admin/audit?event_type=prefix:page&limit=3")
        body = r.json()
        assert len(body["events"]) == 3
        assert body["next_cursor"] is not None

        # Verify order: page.6 (newest) → page.5 → page.4 expected first
        first_types = [e["event_type"] for e in body["events"]]
        assert first_types == ["page.6", "page.5", "page.4"]

        # Walk the cursor
        all_types = list(first_types)
        cursor = body["next_cursor"]
        while cursor:
            r2 = c.get(f"/api/admin/audit?event_type=prefix:page&limit=3&cursor={cursor}")
            body2 = r2.json()
            all_types.extend(e["event_type"] for e in body2["events"])
            cursor = body2["next_cursor"]

        assert all_types == [
            "page.6", "page.5", "page.4",
            "page.3", "page.2", "page.1", "page.0",
        ]
    finally:
        app.dependency_overrides.clear()


def test_invalid_cursor_returns_400(db_session):
    try:
        c, admin = _admin_client(db_session)
        r = c.get("/api/admin/audit?cursor=not-base64")
        assert r.status_code == 400, r.text
    finally:
        app.dependency_overrides.clear()


# -----------------------------------------------------------------------------
# payload truncation
# -----------------------------------------------------------------------------

def test_list_truncates_large_payloads(db_session):
    try:
        c, admin = _admin_client(db_session)
        big = {"blob": "x" * 1000}
        _seed_event(db_session, event_type="big.row", payload=big)

        r = c.get("/api/admin/audit?event_type=big.row")
        body = r.json()
        assert len(body["events"]) == 1
        payload = body["events"][0]["payload"]
        assert payload.get("_truncated") is True
        assert "_preview" in payload
    finally:
        app.dependency_overrides.clear()


def test_detail_returns_full_payload(db_session):
    try:
        c, admin = _admin_client(db_session)
        big = {"blob": "x" * 1000}
        e = _seed_event(db_session, event_type="big.detail", payload=big)

        r = c.get(f"/api/admin/audit/{e.id}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["payload"] == big  # untruncated
    finally:
        app.dependency_overrides.clear()


def test_detail_404_on_unknown_id(db_session):
    try:
        c, admin = _admin_client(db_session)
        r = c.get("/api/admin/audit/does-not-exist")
        assert r.status_code == 404, r.text
    finally:
        app.dependency_overrides.clear()


# -----------------------------------------------------------------------------
# event-types
# -----------------------------------------------------------------------------

def test_event_types_lists_known_constants(db_session):
    try:
        c, admin = _admin_client(db_session)
        r = c.get("/api/admin/audit/event-types")
        assert r.status_code == 200, r.text
        types = r.json()["event_types"]
        # Spot-check entries from each prefix group
        assert "auth.login_success" in types
        assert "admin.user.created" in types
        assert "workspace.created" in types
        assert "folder.created" in types
        assert "document.uploaded" in types
        assert "chat.message_sent" in types
        # Sorted alphabetically
        assert types == sorted(types)
    finally:
        app.dependency_overrides.clear()
