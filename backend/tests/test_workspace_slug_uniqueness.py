"""Workspace slug uniqueness — per-user instances unique within (user_id, slug)."""
import pytest
from sqlalchemy.exc import IntegrityError

from db import models


def _clean(db):
    db.query(models.Workspace).delete()
    db.query(models.User).delete()
    db.commit()


def _user(db, username: str) -> models.User:
    u = models.User(username=username, password_hash="dummy", is_active=True)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _ws(user_id: str, slug: str) -> models.Workspace:
    return models.Workspace(
        slug=slug, display_name=slug, system_prompt="", enabled_tools=[],
        user_id=user_id,
        engine_config={"backend": "llama_cpp"},
    )


def test_same_user_cannot_have_two_workspaces_with_same_slug(db_session):
    _clean(db_session)
    try:
        user = _user(db_session, "alice")
        db_session.add(_ws(user.id, "it_copilot"))
        db_session.commit()

        db_session.add(_ws(user.id, "it_copilot"))
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()
    finally:
        _clean(db_session)


def test_two_users_can_each_have_workspace_with_same_slug(db_session):
    _clean(db_session)
    try:
        alice = _user(db_session, "alice")
        bob = _user(db_session, "bob")

        db_session.add(_ws(alice.id, "it_copilot"))
        db_session.add(_ws(bob.id, "it_copilot"))
        db_session.commit()  # must not raise

        rows = db_session.query(models.Workspace).filter_by(slug="it_copilot").all()
        assert {r.user_id for r in rows} == {alice.id, bob.id}
    finally:
        _clean(db_session)
