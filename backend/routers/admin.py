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
from services import llama_swap_config

router = APIRouter(prefix="/api/admin", tags=["admin"])
_logger = logging.getLogger("pryzm.admin")

_REPO_ROOT = llama_swap_config.REPO_ROOT
_LLAMA_CACHE = _REPO_ROOT / "infra" / "llama_models"
_yaml_lock = asyncio.Lock()

# In-memory map of model_id → download tracking metadata. Populated by
# add_model() when the request carries the HF picker's hints; consumed
# by the status SSE to emit real {bytes, total} progress events. Cleared
# on health pass or model delete. Lost on backend restart — by design,
# admin can just stop watching and re-open the panel.
_active_downloads: dict[str, dict] = {}


def _blobs_dir_for_repo(repo: str) -> pathlib.Path:
    """Map an HF repo like `bartowski/foo-GGUF` to the cache's blobs path."""
    if "/" not in repo:
        return _LLAMA_CACHE / "hub" / f"models--{repo}" / "blobs"
    org, name = repo.split("/", 1)
    return _LLAMA_CACHE / "hub" / f"models--{org}--{name}" / "blobs"


def _partial_blob_size(blobs_dir: pathlib.Path, blob_hash: str) -> int:
    """Return current on-disk size of the blob, picking up partial/incomplete
    variants llama.cpp might write during download. 0 if nothing is present yet."""
    if not blobs_dir.is_dir():
        return 0
    try:
        for path in blobs_dir.glob(f"{blob_hash}*"):
            try:
                return path.stat().st_size
            except OSError:
                pass
    except OSError:
        pass
    return 0

_ID_VALID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_REPO_QUANT_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+$")


class AddModelRequest(BaseModel):
    id: str = Field(..., min_length=1, max_length=128)
    repo: str = Field(..., description="HuggingFace repo:quant, e.g. bartowski/...:Q4_K_M")
    quant: Optional[str] = None  # Optional: if `repo` already contains `:quant`, this is ignored
    ngl: int = 99
    ctx_size: int = 8192
    group: str = "on-demand"
    tags: list[str] = Field(default_factory=list)
    # Optional progress-tracking hints from the HF picker — when present,
    # the status SSE emits real {bytes, total} events instead of just a
    # spinner. None of these are required: manual entries still work.
    expected_filename: Optional[str] = None
    expected_size: Optional[int] = None
    expected_blob_hash: Optional[str] = None


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
    data = llama_swap_config.read_yaml()
    models_cfg = data.get("models") or {}
    rows = [llama_swap_config.parse_model_row(mid, cfg) for mid, cfg in models_cfg.items()]
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

    if req.group not in {"on-demand", "always-on", "inactive"}:
        raise HTTPException(status_code=400, detail="group must be 'on-demand', 'always-on', or 'inactive'")

    async with _yaml_lock:
        data = llama_swap_config.read_yaml()
        models_cfg = data.setdefault("models", {})
        if req.id in models_cfg:
            raise HTTPException(status_code=409, detail=f"model id already exists: {req.id}")
        models_cfg[req.id] = {
            "cmd": ruamel.yaml.scalarstring.PreservedScalarString(
                llama_swap_config.build_cmd_block(
                    repo, quant, req.expected_filename,
                    req.ngl, req.ctx_size, req.group,
                ),
            ),
            "groups": [req.group],
            "tags": list(req.tags),
        }
        llama_swap_config.write_yaml(data)
        llama_swap_config.reload_llama_swap()
        llm_router.reload_router_from_yaml(llama_swap_config.YAML_PATH)

    # Stash progress-tracking metadata for the status SSE. Only populated
    # when the HF picker passes hints; manual adds skip and fall back to
    # the indeterminate spinner.
    if req.expected_blob_hash and req.expected_size:
        _active_downloads[req.id] = {
            "blob_hash": req.expected_blob_hash,
            "expected_size": int(req.expected_size),
            "blobs_dir": _blobs_dir_for_repo(repo),
            "filename": req.expected_filename,
        }

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
    return llama_swap_config.parse_model_row(req.id, data["models"][req.id])


@router.put("/models/{model_id}")
async def update_model(
    model_id: str,
    req: UpdateModelRequest,
    request: Request,
    db: DbSession = Depends(database.get_db),
    admin: models.User = Depends(cookie_auth.require_admin),
) -> dict:
    if req.group is not None and req.group not in {"on-demand", "always-on", "inactive"}:
        raise HTTPException(status_code=400, detail="group must be 'on-demand', 'always-on', or 'inactive'")

    async with _yaml_lock:
        data = llama_swap_config.read_yaml()
        models_cfg = data.get("models") or {}
        if model_id not in models_cfg:
            raise HTTPException(status_code=404, detail=f"model not found: {model_id}")

        existing = models_cfg[model_id]
        # Re-extract identity (repo + quant-or-filename) from the existing cmd;
        # identity is not editable through this endpoint.
        current = llama_swap_config.parse_model_row(model_id, existing)
        if not current["repo"] or not (current["quant"] or current["filename"]):
            raise HTTPException(
                status_code=500,
                detail=f"existing model {model_id} has no parseable repo + quant/filename in cmd; refusing to overwrite",
            )

        new_ngl = req.ngl if req.ngl is not None else (current["ngl"] or 99)
        new_ctx = req.ctx_size if req.ctx_size is not None else (current["ctx_size"] or 8192)
        new_group = req.group if req.group is not None else (current["group"] or "on-demand")
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
            llama_swap_config.build_cmd_block(
                current["repo"], current["quant"], current["filename"],
                new_ngl, new_ctx, new_group,
            ),
        )
        existing["groups"] = [new_group]
        existing["tags"] = list(new_tags)
        llama_swap_config.write_yaml(data)
        llama_swap_config.reload_llama_swap()
        llm_router.reload_router_from_yaml(llama_swap_config.YAML_PATH)

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
    return llama_swap_config.parse_model_row(model_id, data["models"][model_id])


@router.delete("/models/{model_id}")
async def delete_model(
    model_id: str,
    request: Request,
    db: DbSession = Depends(database.get_db),
    admin: models.User = Depends(cookie_auth.require_admin),
) -> dict:
    async with _yaml_lock:
        data = llama_swap_config.read_yaml()
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
        llama_swap_config.write_yaml(data)
        _active_downloads.pop(model_id, None)
        llama_swap_config.reload_llama_swap()
        llm_router.reload_router_from_yaml(llama_swap_config.YAML_PATH)

    _logger.info("admin.model_removed id=%s", model_id)
    return {"deleted": model_id}


@router.get("/models/{model_id}/status")
async def model_status(model_id: str) -> StreamingResponse:
    """Live SSE feed for the watch-while-loading panel.

    Three concurrent sources pump events into a shared queue:
      - log_producer: forwards llama-swap's /api/events log lines
      - progress_producer: stat()s the partial blob on disk every 2s and
        emits {progress: {bytes, total}} — gives a real percentage for
        downloads tracked via the HF picker
      - health_producer: polls /upstream/<id>/health and signals completion
    """
    base = settings.LLM_SERVER_URL.rstrip("/")
    events_url = f"{base}/api/events"
    health_url = f"{base}/upstream/{model_id}/health"
    deadline = time.monotonic() + 600  # 10-minute cap; multi-GB downloads need headroom

    async def gen():
        yield json.dumps({"status": "subscribed", "id": model_id}) + "\n"
        timeout = httpx.Timeout(connect=5.0, read=None, write=5.0, pool=5.0)
        queue: asyncio.Queue[str] = asyncio.Queue()
        loaded = False

        async with httpx.AsyncClient(timeout=timeout) as client:

            async def log_producer() -> None:
                try:
                    async with client.stream("GET", events_url) as resp:
                        async for line in resp.aiter_lines():
                            if not line.startswith("data:"):
                                continue
                            try:
                                evt = json.loads(line[len("data:"):].strip())
                            except json.JSONDecodeError:
                                continue
                            if evt.get("type") != "logData":
                                continue
                            for log_line in (evt.get("data") or "").splitlines():
                                if log_line.strip():
                                    await queue.put(json.dumps({"log": log_line}) + "\n")
                except Exception:
                    # llama-swap dropped the SSE — let the main loop time out on health
                    pass

            async def progress_producer() -> None:
                while True:
                    entry = _active_downloads.get(model_id)
                    if entry:
                        current = _partial_blob_size(entry["blobs_dir"], entry["blob_hash"])
                        await queue.put(json.dumps({
                            "progress": {
                                "bytes": current,
                                "total": entry["expected_size"],
                            }
                        }) + "\n")
                    await asyncio.sleep(2.0)

            async def health_producer() -> bool:
                while time.monotonic() < deadline:
                    try:
                        r = await client.get(health_url, timeout=2.0)
                        if r.status_code == 200:
                            return True
                    except Exception:
                        pass
                    await asyncio.sleep(1.0)
                return False

            log_task = asyncio.create_task(log_producer())
            progress_task = asyncio.create_task(progress_producer())
            health_task = asyncio.create_task(health_producer())

            try:
                while True:
                    if health_task.done():
                        try:
                            loaded = health_task.result()
                        except Exception:
                            loaded = False
                        break
                    if time.monotonic() > deadline:
                        break
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=0.5)
                        yield event
                    except asyncio.TimeoutError:
                        continue
            finally:
                for t in (log_task, progress_task, health_task):
                    t.cancel()
                # Drain any final queued events so the client sees them.
                while not queue.empty():
                    try:
                        yield queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break

        _active_downloads.pop(model_id, None)
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
    files = []
    for entry in body:
        if entry.get("type") != "file":
            continue
        path = entry.get("path")
        if not isinstance(path, str) or not path.lower().endswith(".gguf"):
            continue
        # mmproj-*.gguf is the vision projection file, not a model weight.
        # Loading it standalone fails — exclude from the pickable file list.
        if path.lower().startswith("mmproj"):
            continue
        # The lfs.oid is the SHA256 used as the blob filename in HF's
        # cache. The backend later watches `blobs/<oid>` to compute real
        # download progress.
        lfs = entry.get("lfs") or {}
        files.append({
            "path": path,
            "size": int(lfs.get("size") or entry.get("size") or 0),
            "blob_hash": lfs.get("oid"),
        })
    files.sort(key=lambda f: f["path"])
    return files
