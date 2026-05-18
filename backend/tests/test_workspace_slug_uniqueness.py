"""Workspace slug uniqueness — verifies the partial unique indexes from
migration a65df9990a35 (templates globally unique; per-user instances
unique within (user_id, slug))."""
import pytest
from sqlalchemy.exc import IntegrityError

from db import models


def _clean(db):
    """Wipe workspaces + users so the next test's `downgrade base` (in its
    fixture setup) doesn't trip the restored UNIQUE(slug) constraint when
    template + instance share a slug."""
    db.query(models.Workspace).delete()
    db.query(models.User).delete()
    db.commit()


def _user(db, username: str) -> models.User:
    u = models.User(username=username, password_hash="dummy", is_active=True)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _ws(user_id: str | None, slug: str, *, is_template: bool = False) -> models.Workspace:
    return models.Workspace(
        slug=slug, display_name=slug, system_prompt="", enabled_tools=[],
        is_builtin=False, is_template=is_template, user_id=user_id,
        engine_config={"backend": "llama_cpp"},
    )


def test_same_user_cannot_have_two_non_template_workspaces_with_same_slug(db_session):
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


def test_two_users_can_each_have_non_template_workspace_with_same_slug(db_session):
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


def test_templates_have_globally_unique_slugs(db_session):
    _clean(db_session)
    try:
        db_session.add(_ws(None, "it_copilot", is_template=True))
        db_session.commit()

        db_session.add(_ws(None, "it_copilot", is_template=True))
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()
    finally:
        _clean(db_session)


def test_template_and_user_instance_can_share_slug(db_session):
    """A template and a user-owned instance may both use slug=it_copilot."""
    _clean(db_session)
    try:
        user = _user(db_session, "alice")

        db_session.add(_ws(None, "it_copilot", is_template=True))
        db_session.add(_ws(user.id, "it_copilot"))
        db_session.commit()  # must not raise

        rows = db_session.query(models.Workspace).filter_by(slug="it_copilot").all()
        assert len(rows) == 2
    finally:
        _clean(db_session)
