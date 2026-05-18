"""Bug-report submission + admin triage endpoints."""
from fastapi.testclient import TestClient

from core import cookie_auth
from db import database, models
from main import app


def _seed_user(db_session, username="alice", is_admin=False):
    u = models.User(
        username=username,
        password_hash=cookie_auth.hash_password("alice-pw-12chars"),
        is_admin=is_admin, is_active=True, can_create_workspaces=True,
    )
    db_session.add(u); db_session.commit(); db_session.refresh(u)
    return u


def _client_for(db_session, user):
    sid = cookie_auth.create_session(db_session, user.id)
    app.dependency_overrides[database.get_db] = lambda: db_session
    c = TestClient(app)
    c.cookies.set(cookie_auth.COOKIE_NAME, sid)
    return c


def test_submit_creates_row_and_audit_event(db_session):
    try:
        alice = _seed_user(db_session)
        c = _client_for(db_session, alice)
        r = c.post(
            "/api/bug-reports",
            json={
                "category": "ui_bug",
                "message": "Sidebar overflows on small screens",
                "include_session": False,
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["category"] == "ui_bug"
        assert body["status"] == "open"
        assert body["user_display_name"] == "alice"

        events = db_session.query(models.AuditEvent).filter_by(
            event_type="bugreport.submitted", user_id=alice.id,
        ).all()
        assert len(events) == 1
        assert events[0].payload["bug_report_id"] == body["id"]
    finally:
        app.dependency_overrides.clear()


def test_submit_rejects_invalid_category(db_session):
    try:
        alice = _seed_user(db_session)
        c = _client_for(db_session, alice)
        r = c.post(
            "/api/bug-reports",
            json={"category": "not_a_real_category", "message": "x"},
        )
        assert r.status_code == 422, r.text
    finally:
        app.dependency_overrides.clear()


def test_admin_list_filters_by_status(db_session):
    try:
        alice = _seed_user(db_session)
        admin = _seed_user(db_session, "admin1", is_admin=True)
        for status in ("open", "resolved", "open"):
            db_session.add(models.BugReport(
                user_id=alice.id, user_display_name="alice",
                category="other", message="m", status=status,
            ))
        db_session.commit()

        c = _client_for(db_session, admin)
        r_open = c.get("/api/admin/bug-reports?status=open")
        assert r_open.status_code == 200, r_open.text
        assert len(r_open.json()) == 2

        r_resolved = c.get("/api/admin/bug-reports?status=resolved")
        assert len(r_resolved.json()) == 1
    finally:
        app.dependency_overrides.clear()


def test_acknowledge_flips_status(db_session):
    try:
        alice = _seed_user(db_session)
        admin = _seed_user(db_session, "admin1", is_admin=True)
        bug = models.BugReport(
            user_id=alice.id, user_display_name="alice",
            category="other", message="x", status="open",
        )
        db_session.add(bug); db_session.commit(); db_session.refresh(bug)

        c = _client_for(db_session, admin)
        r = c.post(f"/api/admin/bug-reports/{bug.id}/acknowledge")
        assert r.status_code == 200
        assert r.json()["status"] == "acknowledged"
    finally:
        app.dependency_overrides.clear()


def test_resolve_queues_notification_for_reporter(db_session):
    try:
        alice = _seed_user(db_session)
        admin = _seed_user(db_session, "admin1", is_admin=True)
        bug = models.BugReport(
            user_id=alice.id, user_display_name="alice",
            category="other",
            message="Something went wrong while uploading a PDF",
            status="open",
        )
        db_session.add(bug); db_session.commit(); db_session.refresh(bug)

        c = _client_for(db_session, admin)
        r = c.post(f"/api/admin/bug-reports/{bug.id}/resolve")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "resolved"
        assert body["resolved_by"] == admin.id
        assert body["resolved_at"] is not None

        # Notification queued for the reporter
        notifs = db_session.query(models.Notification).filter_by(user_id=alice.id).all()
        assert len(notifs) == 1
        assert notifs[0].source == "bugreport.resolved"
        assert notifs[0].source_id == bug.id
        assert "Something went wrong" in notifs[0].message
    finally:
        app.dependency_overrides.clear()


def test_resolve_without_reporter_skips_notification(db_session):
    try:
        admin = _seed_user(db_session, "admin1", is_admin=True)
        # Reporter was hard-deleted (FK SET NULL).
        bug = models.BugReport(
            user_id=None, user_display_name="ghost",
            category="other", message="m", status="open",
        )
        db_session.add(bug); db_session.commit(); db_session.refresh(bug)

        c = _client_for(db_session, admin)
        r = c.post(f"/api/admin/bug-reports/{bug.id}/resolve")
        assert r.status_code == 200
        assert db_session.query(models.Notification).count() == 0
    finally:
        app.dependency_overrides.clear()


def test_dismiss_does_not_notify(db_session):
    try:
        alice = _seed_user(db_session)
        admin = _seed_user(db_session, "admin1", is_admin=True)
        bug = models.BugReport(
            user_id=alice.id, user_display_name="alice",
            category="other", message="m", status="open",
        )
        db_session.add(bug); db_session.commit(); db_session.refresh(bug)

        c = _client_for(db_session, admin)
        r = c.post(f"/api/admin/bug-reports/{bug.id}/dismiss")
        assert r.status_code == 200
        assert r.json()["status"] == "dismissed"
        assert db_session.query(models.Notification).count() == 0
    finally:
        app.dependency_overrides.clear()


def test_delete_removes_row_and_audits(db_session):
    try:
        alice = _seed_user(db_session)
        admin = _seed_user(db_session, "admin1", is_admin=True)
        bug = models.BugReport(
            user_id=alice.id, user_display_name="alice",
            category="other", message="m", status="resolved",
        )
        db_session.add(bug); db_session.commit(); db_session.refresh(bug)

        c = _client_for(db_session, admin)
        r = c.delete(f"/api/admin/bug-reports/{bug.id}")
        assert r.status_code == 200

        assert db_session.query(models.BugReport).filter_by(id=bug.id).first() is None
        events = db_session.query(models.AuditEvent).filter_by(
            event_type="bugreport.deleted",
        ).all()
        assert len(events) == 1
    finally:
        app.dependency_overrides.clear()


def test_non_admin_cannot_triage(db_session):
    try:
        alice = _seed_user(db_session)
        bug = models.BugReport(
            user_id=alice.id, user_display_name="alice",
            category="other", message="m", status="open",
        )
        db_session.add(bug); db_session.commit(); db_session.refresh(bug)

        c = _client_for(db_session, alice)
        r = c.post(f"/api/admin/bug-reports/{bug.id}/resolve")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.clear()
