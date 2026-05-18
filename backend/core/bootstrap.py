"""First-boot bootstrap: create admin user if users table is empty,
instantiate templates for them, backfill existing chats/folders/workspaces.
"""
from sqlalchemy.orm import Session as DbSession

from config import settings
from core import cookie_auth
from db import models


def ensure_bootstrap_admin(db: DbSession) -> models.User | None:
    """If the users table is empty, create the bootstrap admin from env
    vars and instantiate the builtin templates. Returns the admin (or
    None if a non-empty users table means bootstrap is no-op)."""
    existing = db.query(models.User).first()
    if existing is not None:
        return None

    if not settings.PRYZM_BOOTSTRAP_ADMIN_PASSWORD:
        raise RuntimeError(
            "Users table is empty and PRYZM_BOOTSTRAP_ADMIN_PASSWORD is not set. "
            "Set the env var to bootstrap the first admin, then restart."
        )

    admin = models.User(
        username=settings.PRYZM_BOOTSTRAP_ADMIN_USERNAME,
        password_hash=cookie_auth.hash_password(settings.PRYZM_BOOTSTRAP_ADMIN_PASSWORD),
        is_admin=True,
        is_active=True,
        can_create_workspaces=True,
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)

    _instantiate_templates_for(db, admin)
    _backfill_orphan_data(db, admin)

    return admin


def _instantiate_templates_for(db: DbSession, user: models.User) -> None:
    # Per the partial unique indexes on workspaces, a user-owned instance
    # may share a template's slug — templates are unique only within
    # is_template=TRUE, and per-user instances are unique within
    # (user_id, slug). So the instance gets the template's literal slug.
    templates = db.query(models.Workspace).filter_by(is_template=True).all()
    for tmpl in templates:
        instance = models.Workspace(
            slug=tmpl.slug,
            display_name=tmpl.display_name,
            system_prompt=tmpl.system_prompt,
            enabled_tools=list(tmpl.enabled_tools or []),
            is_builtin=tmpl.is_builtin,
            is_template=False,
            template_id=tmpl.id,
            user_id=user.id,
            owner_can_edit=True,
            engine_config=dict(tmpl.engine_config or {}),
        )
        db.add(instance)
    db.commit()


def _backfill_orphan_data(db: DbSession, user: models.User) -> None:
    """Attach any pre-existing chats/folders/non-template workspaces
    without a user_id to the bootstrap admin."""
    db.query(models.Session).filter(models.Session.user_id.is_(None)).update(
        {"user_id": user.id}, synchronize_session=False,
    )
    db.query(models.Folder).filter(models.Folder.user_id.is_(None)).update(
        {"user_id": user.id}, synchronize_session=False,
    )
    db.query(models.Workspace).filter(
        models.Workspace.user_id.is_(None),
        models.Workspace.is_template.is_(False),
    ).update({"user_id": user.id}, synchronize_session=False)
    db.commit()
