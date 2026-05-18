"""Bootstrap admin creation on startup."""
import pytest

from core.bootstrap import ensure_bootstrap_admin
from db import models


def test_bootstrap_creates_admin_when_users_empty(db_session, monkeypatch):
    monkeypatch.setattr("config.settings.PRYZM_BOOTSTRAP_ADMIN_USERNAME", "admin")
    monkeypatch.setattr("config.settings.PRYZM_BOOTSTRAP_ADMIN_PASSWORD", "bootstrap-pw-123456")

    ensure_bootstrap_admin(db_session)

    admin = db_session.query(models.User).filter_by(username="admin").one()
    assert admin.is_admin is True
    assert admin.is_active is True
    assert admin.can_create_workspaces is True


def test_bootstrap_noop_when_users_already_exist(db_session, monkeypatch):
    monkeypatch.setattr("config.settings.PRYZM_BOOTSTRAP_ADMIN_USERNAME", "admin")
    monkeypatch.setattr("config.settings.PRYZM_BOOTSTRAP_ADMIN_PASSWORD", "bootstrap-pw-123456")
    db_session.add(models.User(
        username="existing", password_hash="dummy", is_admin=False, is_active=True,
    ))
    db_session.commit()

    ensure_bootstrap_admin(db_session)

    # Bootstrap admin should NOT have been created
    assert db_session.query(models.User).filter_by(username="admin").first() is None


def test_bootstrap_raises_when_users_empty_and_no_password(db_session, monkeypatch):
    monkeypatch.setattr("config.settings.PRYZM_BOOTSTRAP_ADMIN_PASSWORD", None)

    with pytest.raises(RuntimeError, match="PRYZM_BOOTSTRAP_ADMIN_PASSWORD"):
        ensure_bootstrap_admin(db_session)


def test_bootstrap_instantiates_builtin_templates_for_admin(db_session, monkeypatch):
    monkeypatch.setattr("config.settings.PRYZM_BOOTSTRAP_ADMIN_USERNAME", "admin")
    monkeypatch.setattr("config.settings.PRYZM_BOOTSTRAP_ADMIN_PASSWORD", "bootstrap-pw-123456")

    # The migrated test DB already has the seeded builtin templates
    # (it_copilot, personal) at head. Clear them so this test exercises a
    # known, isolated template set.
    db_session.query(models.WorkspaceTemplate).delete()
    db_session.commit()

    template = models.WorkspaceTemplate(
        id="tmpl-it", slug="it_copilot", display_name="IT Copilot",
        system_prompt="IT helper", enabled_tools=[],
        engine_config={"backend": "llama_cpp"},
    )
    db_session.add(template)
    db_session.commit()

    ensure_bootstrap_admin(db_session)

    admin = db_session.query(models.User).filter_by(username="admin").one()
    instances = db_session.query(models.Workspace).filter_by(
        user_id=admin.id, template_id="tmpl-it",
    ).all()
    assert len(instances) == 1
    assert instances[0].slug == "it_copilot"


@pytest.mark.skip(reason="Phase A backfill test - obsolete after FK enforcement in Phase B")
def test_bootstrap_backfills_orphan_chats_and_folders(db_session, monkeypatch):
    # This test was written for Phase A when backfilling orphan (NULL user_id)
    # data was needed. In Phase B, the FK constraints enforce NOT NULL on
    # Session.user_id and Folder.user_id, making orphan data impossible to create.
    # The backfill logic remains in code for data consistency on migrations, but
    # doesn't need a test fixture in Phase B.
    pass
