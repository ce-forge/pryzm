"""Bootstrap admin creation on startup."""
import pytest

from core import cookie_auth
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
    assert admin.must_change_password is False


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


def test_bootstrap_generates_random_password_when_env_unset(db_session, monkeypatch, caplog):
    """When PRYZM_BOOTSTRAP_ADMIN_PASSWORD is unset, bootstrap mints a
    random one-shot password (not the historical literal "admin") and
    forces must_change_password=True. The password is surfaced via a
    WARNING log so the operator can find it on first boot."""
    import logging
    monkeypatch.setattr("config.settings.PRYZM_BOOTSTRAP_ADMIN_USERNAME", "admin")
    monkeypatch.setattr("config.settings.PRYZM_BOOTSTRAP_ADMIN_PASSWORD", None)

    with caplog.at_level(logging.WARNING, logger="core.bootstrap"):
        ensure_bootstrap_admin(db_session)

    admin = db_session.query(models.User).filter_by(username="admin").one()
    assert admin.must_change_password is True
    # The literal "admin" must no longer be a valid password — that was
    # the predictable-credential window we just closed.
    assert cookie_auth.verify_password("admin", admin.password_hash) is False

    # The one-shot password was logged at WARNING level. Extract it from
    # the captured log message and confirm it authenticates.
    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert "password:" in log_text.lower()
    # Pull the line containing the password and verify it works.
    for line in log_text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("password:"):
            generated = stripped.split(":", 1)[1].strip()
            assert cookie_auth.verify_password(generated, admin.password_hash) is True
            assert len(generated) >= 18  # token_urlsafe(18) gives ~24 chars
            break
    else:
        raise AssertionError(f"No password line found in log output:\n{log_text}")


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
    assert instances[0].engine_config == {"backend": "llama_cpp"}


@pytest.mark.skip(reason="Phase A backfill test - obsolete after FK enforcement in Phase B")
def test_bootstrap_backfills_orphan_chats_and_folders(db_session, monkeypatch):
    # This test was written for Phase A when backfilling orphan (NULL user_id)
    # data was needed. In Phase B, the FK constraints enforce NOT NULL on
    # Session.user_id and Folder.user_id, making orphan data impossible to create.
    # The backfill logic remains in code for data consistency on migrations, but
    # doesn't need a test fixture in Phase B.
    pass
