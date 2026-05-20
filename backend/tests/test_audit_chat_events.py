"""Chat audit events.

Lifecycle events (session_created via branch, session_deleted) are
tested by invoking the routers via TestClient. The agentic-loop events
(tool_invoked / rag_retrieved / web_search) are tested by calling the
private `_audit_chat_event` helper directly — testing the full
streaming + LLM dispatch path is brittle and slow, and the helper IS
the boundary that writes the row.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from core import cookie_auth
from core.audit import EventType
from db import database, models
from main import app


@pytest.fixture
def redirect_session_local(db_session, monkeypatch):
    """Point `database.SessionLocal` at the test DB engine.

    The audit helper opens its own session via `database.SessionLocal()`
    which is normally bound to the production DB. For tests that exercise
    that helper directly, redirect it to the test engine so the audit
    row lands somewhere `db_session` can read it back."""
    test_engine = db_session.bind
    test_session_local = sessionmaker(
        bind=test_engine, autoflush=False, autocommit=False
    )
    monkeypatch.setattr(database, "SessionLocal", test_session_local)
    return test_session_local


def _seed_user(db_session, username="alice"):
    u = models.User(
        username=username,
        password_hash=cookie_auth.hash_password("alice-pw-12chars"),
        is_admin=False, is_active=True, can_create_workspaces=True,
    )
    db_session.add(u); db_session.commit(); db_session.refresh(u)
    return u


def _seed_workspace(db_session, user_id, slug="ws-test"):
    ws = models.Workspace(
        slug=slug, display_name=slug, system_prompt="x",
        enabled_tools=[], engine_config={"backend": "llama_cpp"},
        color="blue", user_id=user_id, owner_can_edit=True,
    )
    db_session.add(ws); db_session.commit(); db_session.refresh(ws)
    return ws


def _seed_session(db_session, user_id, workspace_id, title="Existing"):
    s = models.Session(title=title, workspace_id=workspace_id, user_id=user_id)
    db_session.add(s); db_session.commit(); db_session.refresh(s)
    return s


def _user_client(db_session, user=None):
    u = user or _seed_user(db_session)
    sid = cookie_auth.create_session(db_session, u.id)
    app.dependency_overrides[database.get_db] = lambda: db_session
    c = TestClient(app)
    c.cookies.set(cookie_auth.COOKIE_NAME, sid)
    return c, u


# --- session_deleted ---

def test_session_deleted_emits_event(db_session):
    try:
        c, user = _user_client(db_session)
        ws = _seed_workspace(db_session, user.id)
        s = _seed_session(db_session, user.id, ws.id, title="To delete")
        r = c.delete(f"/sessions/{s.id}?workspace={ws.slug}")
        assert r.status_code == 200, r.text
        events = db_session.query(models.AuditEvent).filter_by(
            event_type="chat.session_deleted", user_id=user.id,
        ).all()
        assert len(events) == 1
        assert events[0].payload["title"] == "To delete"
        assert events[0].resource_id == s.id
    finally:
        app.dependency_overrides.clear()


# --- session_created via branch ---

def test_session_created_via_branch_emits_event(db_session):
    try:
        c, user = _user_client(db_session)
        ws = _seed_workspace(db_session, user.id)
        src = _seed_session(db_session, user.id, ws.id, title="Source")
        m = models.Message(session_id=src.id, role="user", content="hello")
        db_session.add(m); db_session.commit(); db_session.refresh(m)

        r = c.post(
            f"/sessions/{src.id}/branch?workspace={ws.slug}",
            json={"up_to_message_id": m.id},
        )
        assert r.status_code == 200, r.text

        events = db_session.query(models.AuditEvent).filter_by(
            event_type="chat.session_created", user_id=user.id,
        ).all()
        assert len(events) == 1
        payload = events[0].payload
        assert payload["source"] == "branch"
        assert payload["branched_from_session_id"] == src.id
        assert payload["branched_from_message_id"] == m.id
    finally:
        app.dependency_overrides.clear()


# --- _audit_chat_event helper direct calls ---

def test_audit_chat_event_writes_rag_retrieved(db_session, redirect_session_local):
    from core.ai_engine import _audit_chat_event
    user = _seed_user(db_session)
    ws = _seed_workspace(db_session, user.id)
    s = _seed_session(db_session, user.id, ws.id)

    _audit_chat_event(
        user.id, ws.id, s.id,
        EventType.CHAT_RAG_RETRIEVED,
        {
            "query_preview": "what is x",
            "num_results": 2,
            "source_filenames": ["a.pdf", "b.png"],
            "mode": "tool",
        },
    )

    events = db_session.query(models.AuditEvent).filter_by(
        event_type="chat.rag_retrieved", user_id=user.id,
    ).all()
    assert len(events) == 1
    assert events[0].payload["mode"] == "tool"
    assert events[0].payload["source_filenames"] == ["a.pdf", "b.png"]
    assert events[0].workspace_id == ws.id
    assert events[0].session_id == s.id


def test_audit_chat_event_writes_web_search(db_session, redirect_session_local):
    from core.ai_engine import _audit_chat_event
    user = _seed_user(db_session)
    ws = _seed_workspace(db_session, user.id)
    _audit_chat_event(
        user.id, ws.id, None,
        EventType.CHAT_WEB_SEARCH,
        {
            "query_preview": "k8s lb",
            "query_refined": "kubernetes load balancer setup guide",
            "k_requested": 5,
            "k_returned_by_searxng": 5,
            "k_fetched_ok": 3,
            "k_failed": 2,
            "failure_reasons": {"timeout": 2},
            "fetch_wall_clock_ms": 4200,
            "extracted_bytes_total": 18000,
            "synthesis_model_id": "qwen3.6:e2b",
        },
    )
    events = db_session.query(models.AuditEvent).filter_by(
        event_type="chat.web_search", user_id=user.id,
    ).all()
    assert len(events) == 1
    assert events[0].payload["query_preview"] == "k8s lb"
    assert events[0].payload["query_refined"] == "kubernetes load balancer setup guide"
    assert events[0].payload["k_requested"] == 5
    assert events[0].payload["k_fetched_ok"] == 3
    assert events[0].payload["k_failed"] == 2
    assert events[0].payload["failure_reasons"] == {"timeout": 2}
    assert events[0].payload["synthesis_model_id"] == "qwen3.6:e2b"


def test_audit_chat_event_writes_tool_invoked(db_session, redirect_session_local):
    from core.ai_engine import _audit_chat_event
    user = _seed_user(db_session)
    ws = _seed_workspace(db_session, user.id)
    _audit_chat_event(
        user.id, ws.id, None,
        EventType.CHAT_TOOL_INVOKED,
        {
            "tool_name": "ping_hostname",
            "arg_values": {"hostname": "example.com"},
            "succeeded": True,
        },
    )
    events = db_session.query(models.AuditEvent).filter_by(
        event_type="chat.tool_invoked", user_id=user.id,
    ).all()
    assert len(events) == 1
    assert events[0].payload["tool_name"] == "ping_hostname"


def test_audit_chat_event_tolerates_unknown_session_id(db_session, redirect_session_local):
    """If the session_id doesn't resolve (already deleted), the event still
    writes with session_id=NULL."""
    from core.ai_engine import _audit_chat_event
    user = _seed_user(db_session)
    ws = _seed_workspace(db_session, user.id)
    _audit_chat_event(
        user.id, ws.id, "deadbeef-not-a-real-id",
        EventType.CHAT_TOOL_INVOKED,
        {"tool_name": "x", "arg_values": {}, "succeeded": True},
    )
    events = db_session.query(models.AuditEvent).filter_by(
        event_type="chat.tool_invoked", user_id=user.id,
    ).all()
    assert len(events) == 1
    assert events[0].session_id is None
