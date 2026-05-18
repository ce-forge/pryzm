"""log_event helper writes the expected row shape."""
from core.audit import log_event, EventType
from db import models


def test_log_event_with_user_and_payload(db_session):
    user = models.User(username="bob", password_hash="x", is_admin=False, is_active=True)
    db_session.add(user); db_session.commit(); db_session.refresh(user)

    event = log_event(
        db_session, EventType.AUTH_LOGIN_SUCCESS,
        user=user, payload={"reason": "valid"},
        source_ip="1.2.3.4", user_agent="curl/8.0",
    )
    db_session.commit()
    db_session.refresh(event)
    assert event.event_type == "auth.login_success"
    assert event.user_id == user.id
    assert event.user_display_name_at_event == "bob"
    assert event.payload == {"reason": "valid"}
    assert event.source_ip == "1.2.3.4"
    assert event.user_agent == "curl/8.0"


def test_log_event_without_user(db_session):
    event = log_event(
        db_session, EventType.AUTH_LOGIN_FAILURE,
        payload={"username_attempted": "ghost", "reason": "unknown_user"},
    )
    db_session.commit()
    db_session.refresh(event)
    assert event.user_id is None
    assert event.user_display_name_at_event is None
    assert event.payload["username_attempted"] == "ghost"
