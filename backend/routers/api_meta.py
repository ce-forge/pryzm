"""Metadata endpoints for the settings UI: tools, models, and prompt
overrides. Surfaces what the agentic loop has access to without
exposing the registry internals."""
from typing import Dict

import httpx
from fastapi import APIRouter, Depends, HTTPException

from core import llm_server
from core.deps import get_http_client
from core.prompt_manager import MICRO_PROMPTS


router = APIRouter(tags=["Metadata"])


@router.get("/api/tools")
def get_tools_metadata():
    """List registered tools with their schemas for the workspace settings UI."""
    from tools.registry import TOOL_DEFINITIONS
    return [
        {
            "name": d["function"]["name"],
            "description": d["function"]["description"],
        }
        for d in TOOL_DEFINITIONS
    ]


@router.get("/api/models")
async def get_chat_models(http_client: httpx.AsyncClient = Depends(get_http_client)):
    """Chat-capable models from llama-swap; embedding models filtered out."""
    try:
        all_models = await llm_server.list_models(http_client)
        return [m for m in all_models if "embed" not in m.lower()]
    except Exception:
        return [llm_server.DEFAULT_CHAT_MODEL]


@router.get("/api/prompts")
def get_prompts():
    return MICRO_PROMPTS.get_all()


@router.patch("/api/prompts")
def update_prompts(payload: Dict[str, str]):
    """Upsert prompt overrides. DELETE removes one and the default takes over."""
    MICRO_PROMPTS.save_prompts(payload)
    return {"status": "success"}


@router.delete("/api/prompts/{key}")
def delete_prompt_override(key: str):
    removed = MICRO_PROMPTS.delete_prompt(key)
    if not removed:
        raise HTTPException(status_code=404, detail="No override exists for that key.")
    return {"status": "deleted", "key": key}
