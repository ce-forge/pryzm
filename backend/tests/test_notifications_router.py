"""Notification endpoints: user reads/acks + admin sends."""
from fastapi.testclient import TestClient

from core import cookie_auth
from db import database, models
from main import app


def _seed_user(db_session, username="alice", is_admin=False):
    u = models.User(
        username=username,
        password_hash=cookie_auth.hash_password("alice-pw-12chars"),
        is_admin=is_admin, is_active=True,
    )
    db_session.add(u); db_session.commit(); db_session.refresh(u)
    return u


def _client_for(db_session, user):
    sid = cookie_auth.create_session(db_session, user.id)
    app.dependency_overrides[database.get_db] = lambda: db_session
    c = TestClient(app)
    c.cookies.set(cookie_auth.COOKIE_NAME, sid)
    return c


def _add_notification(db_session, user_id, message="hi", seen=False):
    from datetime import datetime, timezone
    n = models.Notification(
        user_id=user_id, message=message,
        source="admin.direct",
        seen_at=datetime.now(timezone.utc) if seen else None,
    )
    db_session.add(n); db_session.commit(); db_session.refresh(n)
    return n


def test_unseen_returns_only_unseen(db_session):
    try:
        alice = _seed_user(db_session)
        _add_notification(db_session, alice.id, "unseen one")
        _add_notification(db_session, alice.id, "already seen", seen=True)

        c = _client_for(db_session, alice)
        r = c.get("/api/notifications/unseen")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["unseen_count"] == 1
        assert body["notifications"][0]["message"] == "unseen one"
    finally:
        app.dependency_overrides.clear()


def test_mark_single_seen(db_session):
    try:
        alice = _seed_user(db_session)
        n = _add_notification(db_session, alice.id)
        c = _client_for(db_session, alice)
        r = c.post(f"/api/notifications/{n.id}/seen")
        assert r.status_code == 200
        db_session.refresh(n)
        assert n.seen_at is not None
    finally:
        app.dependency_overrides.clear()


def test_mark_other_users_notification_404(db_session):
    try:
        alice = _seed_user(db_session)
        bob = _seed_user(db_session, "bob")
        bobs = _add_notification(db_session, bob.id)
        c = _client_for(db_session, alice)
        r = c.post(f"/api/notifications/{bobs.id}/seen")
        assert r.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_seen_all_clears_unseen_for_caller_only(db_session):
    try:
        alice = _seed_user(db_session)
        bob = _seed_user(db_session, "bob")
        _add_notification(db_session, alice.id)
        _add_notification(db_session, alice.id)
        _add_notification(db_session, bob.id)

        c = _client_for(db_session, alice)
        r = c.post("/api/notifications/seen-all")
        assert r.status_code == 200
        assert r.json()["marked_seen"] == 2

        alice_unseen = db_session.query(models.Notification).filter(
            models.Notification.user_id == alice.id,
            models.Notification.seen_at.is_(None),
        ).count()
        assert alice_unseen == 0

        bob_unseen = db_session.query(models.Notification).filter(
            models.Notification.user_id == bob.id,
            models.Notification.seen_at.is_(None),
        ).count()
        assert bob_unseen == 1
    finally:
        app.dependency_overrides.clear()


def test_admin_send_direct(db_session):
    try:
        admin = _seed_user(db_session, "admin1", is_admin=True)
        alice = _seed_user(db_session)
        c = _client_for(db_session, admin)
        r = c.post(
            "/api/admin/notifications",
            json={"user_id": alice.id, "message": "Welcome aboard"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["user_id"] == alice.id
        assert body["source"] == "admin.direct"

        events = db_session.query(models.AuditEvent).filter_by(
            event_type="notification.sent",
        ).all()
        assert len(events) == 1
    finally:
        app.dependency_overrides.clear()


def test_admin_broadcast_active_users_only(db_session):
    try:
        admin = _seed_user(db_session, "admin1", is_admin=True)
        active = _seed_user(db_session, "active1")
        inactive = models.User(
            username="inactive1",
            password_hash=cookie_auth.hash_password("p" * 12),
            is_active=False,
        )
        db_session.add(inactive); db_session.commit(); db_session.refresh(inactive)

        c = _client_for(db_session, admin)
        r = c.post(
            "/api/admin/notifications/broadcast",
            json={"message": "System maintenance tonight."},
        )
        assert r.status_code == 200
        # admin + active user are both is_active=True; inactive user excluded.
        assert r.json()["recipient_count"] == 2

        # No row went to the inactive user.
        assert db_session.query(models.Notification).filter_by(
            user_id=inactive.id,
        ).count() == 0
    finally:
        app.dependency_overrides.clear()
