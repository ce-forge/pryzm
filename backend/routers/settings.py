"""End-user settings metadata.

Routes the Settings + WorkspaceSettings UIs fetch to populate their
forms (available tools, available chat models, micro-prompt overrides).

Distinct from `admin.py` (model CRUD / system administration) — these
are read by every signed-in user, not gated to admins.
"""
from typing import Dict

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session as DbSession

from core import cookie_auth, llm_server
from core.audit import EventType, log_event
from core.deps import get_http_client
from core.prompt_manager import MICRO_PROMPTS
from db import database, models
from tools.registry import TOOL_DEFINITIONS


router = APIRouter(tags=["Settings"])


@router.get("/api/tools")
def get_tools_metadata():
    """Lists registered tools with their schemas for the workspace settings UI."""
    return [
        {
            "name": d["function"]["name"],
            "description": d["function"]["description"],
        }
        for d in TOOL_DEFINITIONS
    ]


@router.get("/api/models")
async def get_chat_models(http_client: httpx.AsyncClient = Depends(get_http_client)):
    """List the chat-capable models llama-swap has configured. The list is
    derived from infra/llama-swap-config.yaml at server start; embedding-tagged
    models are filtered out."""
    try:
        all_models = await llm_server.list_models(http_client)
        return [m for m in all_models if "embed" not in m.lower()]
    except Exception:
        return [llm_server.DEFAULT_CHAT_MODEL]


@router.get("/api/prompts")
def get_prompts():
    return MICRO_PROMPTS.get_all()


@router.patch("/api/prompts")
def update_prompts(
    payload: Dict[str, str],
    request: Request,
    db: DbSession = Depends(database.get_db),
    admin: models.User = Depends(cookie_auth.require_admin),
):
    """Upsert one or more prompt overrides. Values are constrained to strings
    by the schema so callers can't smuggle non-string JSON into the file.
    To remove an override (and fall back to the default), DELETE the key."""
    MICRO_PROMPTS.save_prompts(payload)
    log_event(
        db, EventType.ADMIN_SYSTEM_MICRO_PROMPT_EDITED,
        user=admin, request=request,
        payload={"keys_changed": list(payload.keys()), "action": "edited"},
    )
    db.commit()
    return {"status": "success"}


@router.delete("/api/prompts/{key}")
def delete_prompt_override(
    key: str,
    request: Request,
    db: DbSession = Depends(database.get_db),
    admin: models.User = Depends(cookie_auth.require_admin),
):
    """Drop a single prompt override so the default takes effect again."""
    removed = MICRO_PROMPTS.delete_prompt(key)
    if not removed:
        raise HTTPException(status_code=404, detail="No override exists for that key.")
    log_event(
        db, EventType.ADMIN_SYSTEM_MICRO_PROMPT_EDITED,
        user=admin, request=request,
        payload={"keys_changed": [key], "action": "deleted"},
    )
    db.commit()
    return {"status": "deleted", "key": key}
