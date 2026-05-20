"""Unified template push: preview + apply across users.

Replaces the older per-call /push and /instantiate split with a single
flow that classifies every user as one of three states relative to a
given template, then executes a per-row action set chosen by admin.

States:
  - linked: user has a workspace whose template_id == this template
  - slug_match_unlinked: user has a workspace with the template's slug
        but template_id is NULL or pointing elsewhere
  - none: user has no workspace with this slug

Actions (one per target row in an apply call):
  - update: overwrite the linked workspace from the template
  - adopt:  set template_id on the slug-matched workspace and overwrite
  - create: instantiate a fresh workspace from the template

Server re-checks state before executing each action and rejects any
mismatch (the preview the admin saw may be stale).
"""
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.orm import Session

from core.tool_permissions import enforce_allowed_tools, filter_allowed_tools
from db import models


RowState = Literal["linked", "slug_match_unlinked", "none"]
Action = Literal["update", "adopt", "create"]

_SETTINGS_FIELDS = ("system_prompt", "enabled_tools", "color", "engine_config")


@dataclass
class PreviewRow:
    user_id: str
    username: str
    state: RowState
    workspace_id: str | None
    owner_can_edit: bool | None
    diff_fields: list[str]


def _diff_fields(ws: models.Workspace, t: models.WorkspaceTemplate) -> list[str]:
    """Return the names of fields that would change if we pushed `t` onto `ws`.
    Ignores ordering inside enabled_tools (set comparison)."""
    out: list[str] = []
    if (ws.system_prompt or "") != (t.system_prompt or ""):
        out.append("system_prompt")
    if set(ws.enabled_tools or []) != set(t.enabled_tools or []):
        out.append("enabled_tools")
    if (ws.color or None) != (t.color or None):
        out.append("color")
    if dict(ws.engine_config or {}) != dict(t.engine_config or {}):
        out.append("engine_config")
    return out


def build_preview(db: Session, t: models.WorkspaceTemplate) -> list[PreviewRow]:
    """For every user, return a PreviewRow describing what an apply would do.

    One row per user, sorted by username for stable UI ordering.
    """
    users = db.query(models.User).order_by(models.User.username.asc()).all()
    rows: list[PreviewRow] = []
    for u in users:
        linked = (
            db.query(models.Workspace)
            .filter(models.Workspace.user_id == u.id, models.Workspace.template_id == t.id)
            .first()
        )
        if linked is not None:
            rows.append(PreviewRow(
                user_id=u.id, username=u.username, state="linked",
                workspace_id=linked.id, owner_can_edit=linked.owner_can_edit,
                diff_fields=_diff_fields(linked, t),
            ))
            continue
        slug_match = (
            db.query(models.Workspace)
            .filter(models.Workspace.user_id == u.id, models.Workspace.slug == t.slug)
            .first()
        )
        if slug_match is not None:
            rows.append(PreviewRow(
                user_id=u.id, username=u.username, state="slug_match_unlinked",
                workspace_id=slug_match.id, owner_can_edit=slug_match.owner_can_edit,
                diff_fields=_diff_fields(slug_match, t),
            ))
            continue
        rows.append(PreviewRow(
            user_id=u.id, username=u.username, state="none",
            workspace_id=None, owner_can_edit=None, diff_fields=[],
        ))
    return rows


def _overwrite_from_template(ws: models.Workspace, t: models.WorkspaceTemplate, kept_tools: list[str]):
    """Copy the four template-settings fields onto the workspace.
    `kept_tools` is the post-permission-filter tool set for this user."""
    for field in _SETTINGS_FIELDS:
        value = getattr(t, field, None)
        if field == "enabled_tools":
            value = kept_tools
        elif field == "engine_config" and value is not None:
            value = dict(value)
        setattr(ws, field, value)


@dataclass
class ApplyOutcome:
    user_id: str
    action: Action
    workspace_id: str
    dropped_tools: list[str]


def apply_targets(
    db: Session,
    t: models.WorkspaceTemplate,
    targets: list[tuple[str, Action, bool]],
) -> tuple[list[ApplyOutcome], list[dict]]:
    """Execute the actions. Each target is (user_id, action, owner_can_edit).

    Returns (outcomes, rejections). On any per-row error the row is added
    to `rejections` and the others continue — the call is best-effort but
    the DB is committed only once at the end so a hard error rolls back
    the whole batch.

    The router is responsible for emitting audit events from the outcomes.
    """
    outcomes: list[ApplyOutcome] = []
    rejections: list[dict] = []
    template_tools = list(t.enabled_tools or [])

    for user_id, action, owner_can_edit in targets:
        user = db.query(models.User).filter_by(id=user_id).first()
        if user is None:
            rejections.append({"user_id": user_id, "reason": "user_not_found"})
            continue

        # Instantiate (create) is the strict site per the per-user-allowed-tools
        # spec: a fresh workspace must not carry tools the target user is barred
        # from. update/adopt are filter sites — they preserve continuity for
        # users who already had the template applied before their cap tightened.
        if action == "create":
            try:
                enforce_allowed_tools(user, template_tools)
            except Exception as exc:
                rejections.append({
                    "user_id": user_id,
                    "reason": "disallowed_tools",
                    "detail": getattr(exc, "detail", str(exc)),
                })
                continue
            kept, dropped = list(template_tools), []
        else:
            kept, dropped = filter_allowed_tools(user, template_tools)

        if action == "update":
            ws = (
                db.query(models.Workspace)
                .filter(models.Workspace.user_id == user.id, models.Workspace.template_id == t.id)
                .first()
            )
            if ws is None:
                rejections.append({"user_id": user_id, "reason": "not_linked"})
                continue
            _overwrite_from_template(ws, t, kept)
            outcomes.append(ApplyOutcome(user_id=user.id, action="update",
                                         workspace_id=ws.id, dropped_tools=dropped))

        elif action == "adopt":
            ws = (
                db.query(models.Workspace)
                .filter(models.Workspace.user_id == user.id,
                        models.Workspace.slug == t.slug,
                        models.Workspace.template_id.is_(None))
                .first()
            )
            if ws is None:
                rejections.append({"user_id": user_id, "reason": "no_slug_match_or_already_linked"})
                continue
            ws.template_id = t.id
            _overwrite_from_template(ws, t, kept)
            outcomes.append(ApplyOutcome(user_id=user.id, action="adopt",
                                         workspace_id=ws.id, dropped_tools=dropped))

        elif action == "create":
            existing = (
                db.query(models.Workspace)
                .filter(models.Workspace.user_id == user.id, models.Workspace.slug == t.slug)
                .first()
            )
            if existing is not None:
                rejections.append({"user_id": user_id, "reason": "workspace_with_slug_exists"})
                continue
            ws = models.Workspace(
                slug=t.slug,
                display_name=t.display_name,
                system_prompt=t.system_prompt,
                enabled_tools=kept,
                color=t.color,
                template_id=t.id,
                user_id=user.id,
                owner_can_edit=owner_can_edit,
                engine_config=dict(t.engine_config or {}),
            )
            db.add(ws)
            db.flush()
            outcomes.append(ApplyOutcome(user_id=user.id, action="create",
                                         workspace_id=ws.id, dropped_tools=dropped))

        else:
            rejections.append({"user_id": user_id, "reason": f"unknown_action:{action}"})

    return outcomes, rejections
