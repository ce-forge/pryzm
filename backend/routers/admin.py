"""Admin endpoints for model management.

CRUD over `infra/llama-swap-config.yaml`. Mutations go through `ruamel.yaml`
in round-trip mode so the file stays readable (comments and key order are
preserved — devs may still edit it by hand).

After a mutation: reload llama-swap via `docker compose kill -s HUP`, then
re-init the router catalog so the next chat request sees the new model. POST
additionally fires a warmup `/v1/chat/completions` in a background task —
that's what triggers llama-swap to download + load the model, so the UI sees
real progress from the moment the user clicks Add.

The status endpoint proxies llama-swap's own `/api/events` SSE feed, filtered
to the model id, and overlays a 1Hz `/upstream/<id>/health` probe so the
client gets a single `{"status": "loaded"}` terminator alongside the raw log
stream.
"""
from __future__ import annotations

import asyncio
import json
import logging
import pathlib
import re
import subprocess
import time
from typing import Any, Optional

import httpx
import ruamel.yaml
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DbSession

from config import settings
from core import cookie_auth, llm_router
from core.audit import EventType, log_event
from db import database, models

router = APIRouter(prefix="/api/admin", tags=["admin"])
_logger = logging.getLogger("pryzm.admin")

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
_YAML_PATH = _REPO_ROOT / "infra" / "llama-swap-config.yaml"
_yaml = ruamel.yaml.YAML()
_yaml.preserve_quotes = True
_yaml_lock = asyncio.Lock()

# Match `-hf <repo>:<quant>` and `--ctx-size <n>` inside the multi-line cmd string.
_HF_RE = re.compile(r"-hf\s+(\S+):(\S+)")
_NGL_RE = re.compile(r"-ngl\s+(\d+)")
_CTX_RE = re.compile(r"--ctx-size\s+(\d+)")
_ID_VALID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_REPO_QUANT_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+$")


def _read_yaml() -> dict:
    with open(_YAML_PATH) as f:
        return _yaml.load(f) or {}


def _write_yaml(data: dict) -> None:
    with open(_YAML_PATH, "w") as f:
        _yaml.dump(data, f)


def _reload_llama_swap() -> None:
    start = time.perf_counter()
    subprocess.run(
        ["docker", "compose", "kill", "-s", "HUP", "llama-swap"],
        cwd=_REPO_ROOT, check=True, timeout=5, capture_output=True,
    )
    duration_ms = int((time.perf_counter() - start) * 1000)
    _logger.info("admin.llama_swap_reloaded duration_ms=%d", duration_ms)


def _parse_model_row(model_id: str, cfg: dict) -> dict:
    cmd = " ".join((cfg.get("cmd") or "").split())  # collapse newlines/whitespace
    hf_match = _HF_RE.search(cmd)
    ngl_match = _NGL_RE.search(cmd)
    ctx_match = _CTX_RE.search(cmd)
    groups = cfg.get("groups") or []
    return {
        "id": model_id,
        "repo": hf_match.group(1) if hf_match else None,
        "quant": hf_match.group(2) if hf_match else None,
        "ngl": int(ngl_match.group(1)) if ngl_match else None,
        "ctx_size": int(ctx_match.group(1)) if ctx_match else None,
        "group": groups[0] if groups else None,
        "tags": list(cfg.get("tags") or []),
    }


def _build_cmd_block(repo: str, quant: str, ngl: int, ctx_size: int, group: str) -> str:
    """Render a multi-line `cmd:` value matching the style of existing entries.
    Chat models get k/v cache quantisation; embedding doesn't."""
    base = (
        f"/app/llama-server --port ${{PORT}}\n"
        f"-hf {repo}:{quant}\n"
        f"-ngl {ngl} --ctx-size {ctx_size} --jinja --flash-attn on"
    )
    if group == "chat":
        base += "\n--cache-type-k q8_0 --cache-type-v q8_0"
    return base


class AddModelRequest(BaseModel):
    id: str = Field(..., min_length=1, max_length=128)
    repo: str = Field(..., description="HuggingFace repo:quant, e.g. bartowski/...:Q4_K_M")
    quant: Optional[str] = None  # Optional: if `repo` already contains `:quant`, this is ignored
    ngl: int = 99
    ctx_size: int = 8192
    group: str = "chat"
    tags: list[str] = Field(default_factory=list)


class UpdateModelRequest(BaseModel):
    """Fields editable on an existing model. `id` and `repo:quant` are
    identity — to change either, delete the entry and re-add it. Everything
    here is optional; only the keys the client sends get applied."""
    ngl: Optional[int] = None
    ctx_size: Optional[int] = None
    group: Optional[str] = None
    tags: Optional[list[str]] = None


async def _warmup_model(model_id: str) -> None:
    """Trigger llama-swap to download + load the model by sending a 1-token
    chat completion. Runs in a BackgroundTasks scope, so failures only log."""
    url = f"{settings.LLM_SERVER_URL.rstrip('/')}/v1/chat/completions"
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": "ok"}],
        "max_tokens": 1,
        "stream": False,
    }
    # Generous timeout: a cold HuggingFace download can take many minutes.
    timeout = httpx.Timeout(connect=10.0, read=900.0, write=10.0, pool=5.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
    except Exception as e:
        _logger.warning("admin.warmup_failed id=%s error=%s", model_id, e)


async def _fetch_running_model_ids() -> set[str]:
    """Ask llama-swap which model processes are currently running. Single GET
    against `/running`, returns a list of llama-server children with state.
    /upstream/<id>/health is the wrong probe — it actively tries to LOAD the
    model, blocking (or accidentally starting one) on unloaded ids."""
    base = settings.LLM_SERVER_URL.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{base}/running")
            if r.status_code == 200:
                return {
                    p["model"]
                    for p in (r.json() or {}).get("running") or []
                    if p.get("state") == "ready" and p.get("model")
                }
    except Exception:
        pass
    return set()


@router.get("/models")
async def list_models() -> list[dict]:
    data = _read_yaml()
    models_cfg = data.get("models") or {}
    rows = [_parse_model_row(mid, cfg) for mid, cfg in models_cfg.items()]
    loaded_ids = await _fetch_running_model_ids()
    for row in rows:
        row["loaded"] = row["id"] in loaded_ids
    return rows


@router.post("/models", status_code=201)
async def add_model(
    req: AddModelRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    db: DbSession = Depends(database.get_db),
    admin: models.User = Depends(cookie_auth.require_admin),
) -> dict:
    if not _ID_VALID_RE.match(req.id):
        raise HTTPException(status_code=400, detail="id must match [A-Za-z0-9][A-Za-z0-9._-]*")

    # Allow either "repo:quant" in the `repo` field OR split across repo+quant.
    if ":" in req.repo:
        repo_full = req.repo
    elif req.quant:
        repo_full = f"{req.repo}:{req.quant}"
    else:
        raise HTTPException(status_code=400, detail="repo must contain :quant, or quant must be supplied separately")
    if not _REPO_QUANT_RE.match(repo_full):
        raise HTTPException(status_code=400, detail=f"repo:quant looks malformed: {repo_full!r}")
    repo, quant = repo_full.split(":", 1)

    if req.group not in {"chat", "always-on"}:
        raise HTTPException(status_code=400, detail="group must be 'chat' or 'always-on'")

    async with _yaml_lock:
        data = _read_yaml()
        models_cfg = data.setdefault("models", {})
        if req.id in models_cfg:
            raise HTTPException(status_code=409, detail=f"model id already exists: {req.id}")
        models_cfg[req.id] = {
            "cmd": ruamel.yaml.scalarstring.PreservedScalarString(
                _build_cmd_block(repo, quant, req.ngl, req.ctx_size, req.group),
            ),
            "groups": [req.group],
            "tags": list(req.tags),
        }
        _write_yaml(data)
        try:
            _reload_llama_swap()
        except subprocess.CalledProcessError as e:
            _logger.warning(
                "admin.llama_swap_reload_failed stderr=%s", e.stderr.decode(errors="replace") if e.stderr else "")
            # Don't fail the request — the YAML is written; SIGHUP can be retried manually.
        llm_router.reload_router_from_yaml(_YAML_PATH)

    _logger.info("admin.model_added id=%s repo=%s", req.id, repo_full)
    log_event(
        db, EventType.ADMIN_SYSTEM_MODEL_ADDED,
        user=admin, request=request,
        payload={
            "model_id": req.id,
            "repo": repo_full,
            "ctx_size": req.ctx_size,
            "ngl": req.ngl,
            "tags": list(req.tags or []),
            "group": req.group,
            "vision": "vision" in (req.tags or []),
        },
    )
    db.commit()
    background_tasks.add_task(_warmup_model, req.id)
    return _parse_model_row(req.id, data["models"][req.id])


@router.put("/models/{model_id}")
async def update_model(
    model_id: str,
    req: UpdateModelRequest,
    request: Request,
    db: DbSession = Depends(database.get_db),
    admin: models.User = Depends(cookie_auth.require_admin),
) -> dict:
    if req.group is not None and req.group not in {"chat", "always-on"}:
        raise HTTPException(status_code=400, detail="group must be 'chat' or 'always-on'")

    async with _yaml_lock:
        data = _read_yaml()
        models_cfg = data.get("models") or {}
        if model_id not in models_cfg:
            raise HTTPException(status_code=404, detail=f"model not found: {model_id}")

        existing = models_cfg[model_id]
        # Re-extract identity (repo:quant) from the existing cmd; identity is
        # not editable through this endpoint.
        current = _parse_model_row(model_id, existing)
        if not current["repo"] or not current["quant"]:
            raise HTTPException(
                status_code=500,
                detail=f"existing model {model_id} has no parseable repo:quant in cmd; refusing to overwrite",
            )

        new_ngl = req.ngl if req.ngl is not None else (current["ngl"] or 99)
        new_ctx = req.ctx_size if req.ctx_size is not None else (current["ctx_size"] or 8192)
        new_group = req.group if req.group is not None else (current["group"] or "chat")
        new_tags = req.tags if req.tags is not None else list(current["tags"])

        changed_fields = []
        if req.ngl is not None and current["ngl"] != new_ngl:
            changed_fields.append("ngl")
        if req.ctx_size is not None and current["ctx_size"] != new_ctx:
            changed_fields.append("ctx_size")
        if req.group is not None and current["group"] != new_group:
            changed_fields.append("group")
        if req.tags is not None and list(current["tags"]) != list(new_tags):
            changed_fields.append("tags")

        existing["cmd"] = ruamel.yaml.scalarstring.PreservedScalarString(
            _build_cmd_block(current["repo"], current["quant"], new_ngl, new_ctx, new_group),
        )
        existing["groups"] = [new_group]
        existing["tags"] = list(new_tags)
        _write_yaml(data)
        try:
            _reload_llama_swap()
        except subprocess.CalledProcessError as e:
            _logger.warning(
                "admin.llama_swap_reload_failed stderr=%s", e.stderr.decode(errors="replace") if e.stderr else "")
        llm_router.reload_router_from_yaml(_YAML_PATH)

    _logger.info(
        "admin.model_updated id=%s ngl=%d ctx_size=%d group=%s tags=%s",
        model_id, new_ngl, new_ctx, new_group, new_tags,
    )
    log_event(
        db, EventType.ADMIN_SYSTEM_MODEL_EDITED,
        user=admin, request=request,
        payload={"model_id": model_id, "changed_fields": changed_fields},
    )
    db.commit()
    return _parse_model_row(model_id, data["models"][model_id])


@router.delete("/models/{model_id}")
async def delete_model(
    model_id: str,
    request: Request,
    db: DbSession = Depends(database.get_db),
    admin: models.User = Depends(cookie_auth.require_admin),
) -> dict:
    async with _yaml_lock:
        data = _read_yaml()
        models_cfg = data.get("models") or {}
        if model_id not in models_cfg:
            raise HTTPException(status_code=404, detail=f"model not found: {model_id}")
        tags = list(models_cfg[model_id].get("tags") or [])
        if "embedding" in tags:
            raise HTTPException(
                status_code=400,
                detail="refusing to delete the embedding model — RAG depends on it",
            )
        log_event(
            db, EventType.ADMIN_SYSTEM_MODEL_REMOVED,
            user=admin, request=request,
            payload={"model_id": model_id},
        )
        db.commit()
        del models_cfg[model_id]
        _write_yaml(data)
        try:
            _reload_llama_swap()
        except subprocess.CalledProcessError as e:
            _logger.warning(
                "admin.llama_swap_reload_failed stderr=%s", e.stderr.decode(errors="replace") if e.stderr else "")
        llm_router.reload_router_from_yaml(_YAML_PATH)

    _logger.info("admin.model_removed id=%s", model_id)
    return {"deleted": model_id}


@router.get("/models/{model_id}/status")
async def model_status(model_id: str) -> StreamingResponse:
    base = settings.LLM_SERVER_URL.rstrip("/")
    events_url = f"{base}/api/events"
    health_url = f"{base}/upstream/{model_id}/health"
    deadline = time.monotonic() + 300  # 5-minute cap on total wait

    async def gen():
        # Yield an immediate ping so the client knows the stream is alive.
        yield json.dumps({"status": "subscribed", "id": model_id}) + "\n"
        timeout = httpx.Timeout(connect=5.0, read=None, write=5.0, pool=5.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async def health_poller() -> bool:
                """Return True once /upstream/<id>/health passes (or deadline)."""
                while time.monotonic() < deadline:
                    try:
                        r = await client.get(health_url, timeout=2.0)
                        if r.status_code == 200:
                            return True
                    except Exception:
                        pass
                    await asyncio.sleep(1.0)
                return False

            health_task = asyncio.create_task(health_poller())
            try:
                async with client.stream("GET", events_url) as resp:
                    async for line in resp.aiter_lines():
                        if health_task.done() and health_task.result():
                            break
                        if not line.startswith("data:"):
                            continue
                        try:
                            evt = json.loads(line[len("data:"):].strip())
                        except json.JSONDecodeError:
                            continue
                        if evt.get("type") != "logData":
                            continue
                        log_chunk = evt.get("data", "")
                        # Forward every log line during the watch window.
                        # The previous substring filter on model_id missed the
                        # HF downloader's progress lines (they contain the
                        # filename, not the model id), leaving the pane empty
                        # during downloads. The window is scoped to one admin
                        # action so cross-model noise is rare.
                        for log_line in log_chunk.splitlines():
                            if log_line.strip():
                                yield json.dumps({"log": log_line}) + "\n"
                        if time.monotonic() > deadline:
                            break
            finally:
                health_task.cancel()
                try:
                    loaded = await health_task
                except (asyncio.CancelledError, Exception):
                    loaded = False
        if loaded:
            yield json.dumps({"status": "loaded", "id": model_id}) + "\n"
        else:
            yield json.dumps({"status": "error", "id": model_id, "detail": "load timed out"}) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


# ---------------------------------------------------------------------------
# HuggingFace search proxy
#
# Admins shouldn't need to leave the dashboard to find a GGUF to add. These
# two endpoints proxy the public HF API: search returns matching repos with
# the `gguf` library filter; files returns the GGUF blobs in a specific repo
# so the admin can pick a quant. The backend's IP is what gets rate-limited
# (not every admin's browser), and routing through here means HF auth could
# be added centrally later if private repos ever matter.
# ---------------------------------------------------------------------------

_HF_API_BASE = "https://huggingface.co/api"
_HF_TIMEOUT = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)


@router.get("/hf-search")
async def hf_search(q: str, limit: int = 20) -> list[dict]:
    """Search HuggingFace for GGUF repos matching `q`."""
    q = (q or "").strip()
    if not q:
        return []
    limit = max(1, min(limit, 50))
    params = {
        "search": q,
        "filter": "gguf",
        "limit": str(limit),
        "sort": "downloads",
        "direction": "-1",
    }
    try:
        async with httpx.AsyncClient(timeout=_HF_TIMEOUT) as client:
            r = await client.get(f"{_HF_API_BASE}/models", params=params)
            r.raise_for_status()
            body = r.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"HuggingFace search failed: {e}")
    return [
        {
            "id": m.get("id") or m.get("modelId"),
            "downloads": m.get("downloads", 0),
            "likes": m.get("likes", 0),
            "tags": list(m.get("tags") or []),
            "last_modified": m.get("lastModified"),
        }
        for m in body
        if (m.get("id") or m.get("modelId"))
    ]


@router.get("/hf-files")
async def hf_files(repo: str) -> list[dict]:
    """List GGUF files in a HuggingFace repo so the admin can pick a quant."""
    repo = (repo or "").strip()
    if not repo or "/" not in repo:
        raise HTTPException(status_code=400, detail="repo must look like 'org/name'")
    try:
        async with httpx.AsyncClient(timeout=_HF_TIMEOUT) as client:
            r = await client.get(f"{_HF_API_BASE}/models/{repo}/tree/main")
            if r.status_code == 404:
                raise HTTPException(status_code=404, detail=f"repo not found: {repo}")
            r.raise_for_status()
            body = r.json()
    except HTTPException:
        raise
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"HuggingFace tree fetch failed: {e}")
    files = [
        {
            "path": entry.get("path"),
            "size": entry.get("size", 0),
        }
        for entry in body
        if entry.get("type") == "file"
        and isinstance(entry.get("path"), str)
        and entry["path"].lower().endswith(".gguf")
        # mmproj-*.gguf is the vision projection file, not a model weight.
        # Loading it standalone fails — exclude from the pickable file list.
        and not entry["path"].lower().startswith("mmproj")
    ]
    files.sort(key=lambda f: f["path"])
    return files
