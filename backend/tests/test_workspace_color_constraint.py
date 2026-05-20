"""workspace.color allowlist CHECK constraint (D2).

Migration c7f2e9a1b8d3 pins both `workspaces.color` and
`workspace_templates.color` to a fixed allowlist that mirrors the
frontend's WORKSPACE_COLORS map. Any future row carrying an unknown
color should die at insert time, not silently work and then fail in the
UI when getWorkspaceColorClasses falls back to the default.
"""
import pytest
from sqlalchemy.exc import IntegrityError

from core import cookie_auth
from db import models
from utils.constants import WORKSPACE_COLORS


def _seed_user(db_session) -> models.User:
    u = models.User(
        username="color-tester",
        password_hash=cookie_auth.hash_password("test-pw-12chars"),
    )
    db_session.add(u); db_session.commit(); db_session.refresh(u)
    return u


def test_workspaces_color_rejects_unknown_value(db_session):
    user = _seed_user(db_session)
    db_session.add(models.Workspace(
        slug="bad-color",
        display_name="Bad",
        user_id=user.id,
        system_prompt="",
        enabled_tools=[],
        engine_config={"backend": "llama_cpp"},
        color="not-a-real-color",
    ))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_workspaces_color_accepts_known_values(db_session):
    user = _seed_user(db_session)
    for c in WORKSPACE_COLORS:
        db_session.add(models.Workspace(
            slug=f"ok-{c}",
            display_name=f"OK {c}",
            user_id=user.id,
            system_prompt="",
            enabled_tools=[],
            engine_config={"backend": "llama_cpp"},
            color=c,
        ))
        db_session.commit()


def test_workspaces_color_accepts_null(db_session):
    user = _seed_user(db_session)
    db_session.add(models.Workspace(
        slug="ok-null",
        display_name="OK NULL",
        user_id=user.id,
        system_prompt="",
        enabled_tools=[],
        engine_config={"backend": "llama_cpp"},
        color=None,
    ))
    db_session.commit()


def test_workspace_templates_color_rejects_unknown_value(db_session):
    db_session.add(models.WorkspaceTemplate(
        slug="bad-template-color",
        display_name="Bad Template",
        system_prompt="",
        enabled_tools=[],
        engine_config={"backend": "llama_cpp"},
        color="some-random-string",
    ))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
