"""slugify_unique must scope its existence check to the caller's user_id.

The DB enforces per-user slug uniqueness via the partial index
`uq_workspaces_user_slug`. A global check both produces suffixes nobody
asked for AND leaks the existence of another user's same-name workspace
through the `-2`/`-3` suffix pattern.
"""
from core import cookie_auth
from db import models
from services.workspaces import slugify_unique


def _seed_user(db_session, username: str) -> models.User:
    u = models.User(
        username=username,
        password_hash=cookie_auth.hash_password("test-pw-12chars"),
        is_active=True,
    )
    db_session.add(u); db_session.commit(); db_session.refresh(u)
    return u


def test_slugify_unique_ignores_other_users_slugs(db_session):
    """User A has 'personal'; user B asks for 'personal' too. Both get the
    bare 'personal' slug — DB-level partial unique index allows it."""
    user_a = _seed_user(db_session, "alice-slug")
    user_b = _seed_user(db_session, "bob-slug")

    db_session.add(models.Workspace(
        slug="personal",
        display_name="Personal",
        user_id=user_a.id,
        system_prompt="",
        enabled_tools=[],
        engine_config={"backend": "llama_cpp"},
    ))
    db_session.commit()

    out = slugify_unique(db_session, "Personal", user_id=user_b.id)
    assert out == "personal", f"got {out!r}; expected unsuffixed slug"


def test_slugify_unique_suffixes_when_same_user_collides(db_session):
    """Same user with two workspaces named the same gets the -2 suffix."""
    user = _seed_user(db_session, "carol-slug")
    db_session.add(models.Workspace(
        slug="notes",
        display_name="Notes",
        user_id=user.id,
        system_prompt="",
        enabled_tools=[],
        engine_config={"backend": "llama_cpp"},
    ))
    db_session.commit()

    out = slugify_unique(db_session, "Notes", user_id=user.id)
    assert out == "notes-2"


def test_slugify_unique_unscoped_still_works(db_session):
    """Admin paths that pass user_id=None retain the historical global
    behaviour — the option is preserved for that case."""
    user = _seed_user(db_session, "dave-slug")
    db_session.add(models.Workspace(
        slug="shared",
        display_name="Shared",
        user_id=user.id,
        system_prompt="",
        enabled_tools=[],
        engine_config={"backend": "llama_cpp"},
    ))
    db_session.commit()

    out = slugify_unique(db_session, "Shared")  # user_id=None
    assert out == "shared-2"
