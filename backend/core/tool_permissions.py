"""Per-user tool permission helpers (spec: 2026-05-19-per-user-allowed-tools.md).

Two shapes:
- enforce_allowed_tools: raise 400 on disallowed (strict sites).
- filter_allowed_tools: return (kept, dropped) for bulk sites that propagate
  multiple fields and can't afford to abort on one tool mismatch.

Both bypass when target_user.is_admin is True, and treat an empty
allowed_tools list as 'no restriction'.
"""
from fastapi import HTTPException

from db import models
from tools.registry import AVAILABLE_TOOLS


def enforce_allowed_tools(
    target_user: models.User,
    requested: list[str],
) -> None:
    if target_user.is_admin:
        return
    cap = list(target_user.allowed_tools or [])
    if not cap:
        return
    disallowed = [t for t in requested if t not in cap]
    if disallowed:
        raise HTTPException(
            status_code=400,
            detail=f"User is not allowed to use tools: {', '.join(disallowed)}",
        )


def filter_allowed_tools(
    target_user: models.User,
    requested: list[str],
) -> tuple[list[str], list[str]]:
    if target_user.is_admin:
        return list(requested), []
    cap = list(target_user.allowed_tools or [])
    if not cap:
        return list(requested), []
    kept = [t for t in requested if t in cap]
    dropped = [t for t in requested if t not in cap]
    return kept, dropped


def validate_tool_names(names: list[str]) -> None:
    """Raise 400 if any name isn't a known tool. Use at API boundary."""
    unknown = [n for n in names if n not in AVAILABLE_TOOLS]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown tool name(s): {', '.join(unknown)}",
        )
