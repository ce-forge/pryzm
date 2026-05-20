"""Live SSE feed for the admin watch-while-loading panel.

`stream_status()` yields NDJSON lines while a model is loading. Three
concurrent producers feed a shared queue:

  - log_producer: forwards llama-swap's /api/events log lines
  - progress_producer: stat()s the partial blob on disk every 2s and emits
    {progress: {bytes, total}} — gives a real percentage for downloads
    tracked via the HF picker
  - health_producer: polls /upstream/<id>/health and signals completion

`_active_downloads` is the in-memory map of model_id → blob hints, populated
by the admin add_model endpoint and consumed here. Cleared on health pass
or model delete. Lost on backend restart — by design, admin can just stop
watching and re-open the panel.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import time
from typing import AsyncIterator

import httpx

from config import settings
from services.llama_swap_config import REPO_ROOT

_LLAMA_CACHE = REPO_ROOT / "infra" / "llama_models"

# In-memory map of model_id → download tracking metadata. Populated by the
# admin add_model endpoint when the request carries the HF picker's hints;
# consumed by stream_status() to emit real {bytes, total} progress events.
# Cleared on health pass or model delete. Lost on backend restart — by
# design, admin can just stop watching and re-open the panel.
_active_downloads: dict[str, dict] = {}


def blobs_dir_for_repo(repo: str) -> pathlib.Path:
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


async def stream_status(model_id: str) -> AsyncIterator[str]:
    base = settings.LLM_SERVER_URL.rstrip("/")
    events_url = f"{base}/api/events"
    health_url = f"{base}/upstream/{model_id}/health"
    deadline = time.monotonic() + 600  # 10-minute cap; multi-GB downloads need headroom

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
