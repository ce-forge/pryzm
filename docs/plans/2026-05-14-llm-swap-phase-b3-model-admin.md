# Phase B3 — Web UI for Model Management

## Context

Adding a new model to llama-swap today means editing `infra/llama-swap-config.yaml` by hand, then running `docker compose kill -s HUP llama-swap`. Pryzm is meant to be a tool a dev can fork and configure, so "edit a YAML in another window" is friction we should remove.

B3 wires a Settings → Models panel that lists installed models, adds new ones from a HuggingFace `repo:quant` string, and deletes them. The YAML stays canonical (refreshing the page shows what's on disk), so manual edits keep working alongside the UI.

**Deviation from spec — download triggers at Add time, not first prompt.** The spec implies downloads happen lazily on first request, with progress shown inside the chat panel. That's the wrong default: it ties a long blocking operation to a chat turn, and the user has no signal during it. v1 fires a warmup request in the background immediately after the YAML write, and the Settings modal shows progress *there*. The chat panel never encounters an undownloaded model unless the warmup failed (which is a separate error path, not a UX surface).

**Progress signal — proxy llama-swap's `/api/events`, don't tail docker logs.** llama-swap exposes an SSE event stream at `http://localhost:8080/api/events` that emits real-time `logData` events from the underlying `llama-server` child process. We pass those through (filtered to the new model id) and let the frontend display them. No docker-log tailing, no parsing assumptions baked into the backend.

## Scope

In:
- New `backend/routers/admin.py` — `GET/POST/DELETE /api/admin/models` and `GET /api/admin/models/{id}/status` (SSE pass-through of `/api/events`).
- YAML mutation through `ruamel.yaml` (preserves comments + ordering — important because the file is also hand-edited).
- `subprocess.run(['docker', 'compose', 'kill', '-s', 'HUP', 'llama-swap'])` to reload llama-swap after mutations. `orbital` is already in the `docker` group, so no sudo.
- `asyncio.Lock` around read-modify-write-reload so concurrent admin calls can't corrupt the YAML.
- **Background warmup request after Add** — backend fires `POST /v1/chat/completions` with `model=<new id>`, `max_tokens=1`, dummy prompt. This is what triggers llama-swap to download + load the model. The warmup runs in a `BackgroundTasks` so the POST returns quickly.
- Frontend: new "Models" section in `Settings.tsx`. List view, add modal that stays open showing live progress until `loaded`, delete-with-confirm.
- Pin llama-swap image tag in `docker-compose.yml` so SIGHUP and `/api/events` behavior stay deterministic.

Out:
- **Editing models.** Per spec, edits are manual YAML.
- **Deleting cached GGUFs from the volume.** Manual.
- **Separate admin role.** Existing single bearer token gates all admin endpoints (matches Phase 2 model).
- **First-request download UI in the chat panel.** No longer needed — downloads happen at Add time, so the chat side won't encounter an undownloaded model except after a manual YAML edit that bypassed the UI. If you want a safety net there later, it's a small follow-up.

## File-by-file changes

### `backend/requirements.txt`

Add `ruamel.yaml==0.18.6` (or current). PyYAML stays for the router's read-only catalog parse — `ruamel` is only used for round-trip writes.

### `backend/routers/admin.py` (new, ~180 lines)

```python
import asyncio
import pathlib
import subprocess
from typing import Optional

import httpx
import ruamel.yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from config import settings
from core.auth import require_token
from core import llm_router  # to re-init the router after YAML changes

router = APIRouter(prefix="/api/admin", tags=["admin"])

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
_YAML_PATH = _REPO_ROOT / "infra" / "llama-swap-config.yaml"
_yaml = ruamel.yaml.YAML()      # round-trip mode preserves comments + order
_yaml.preserve_quotes = True
_yaml_lock = asyncio.Lock()


def _read_yaml() -> dict:
    with open(_YAML_PATH) as f:
        return _yaml.load(f) or {}

def _write_yaml(data: dict) -> None:
    with open(_YAML_PATH, "w") as f:
        _yaml.dump(data, f)

def _reload_llama_swap() -> None:
    # SIGHUP makes llama-swap re-read its config without restarting the container.
    subprocess.run(
        ["docker", "compose", "kill", "-s", "HUP", "llama-swap"],
        cwd=_REPO_ROOT, check=True, timeout=5,
    )
```

Endpoints (all gated by `Depends(require_token)` at the router-include level):

- `GET /api/admin/models` — returns `[{id, repo, quant, ngl, ctx_size, group, tags, loaded}]`. Parses each model's `cmd` field to extract `repo:quant` (regex on `-hf <repo>:<quant>`) and `--ctx-size N`. `loaded` comes from a concurrent batch of `httpx.AsyncClient.get(f"{LLM_SERVER_URL}/upstream/{id}/health")` calls — 200 → loaded, anything else → not loaded.

- `POST /api/admin/models` — body `{id, repo, quant, ngl=99, ctx_size=8192, group="chat", tags=[]}`. Validates: `id` is unique, `repo:quant` looks like `<org>/<repo>:<quant>`. Builds the `cmd` string matching the existing config style. Acquires `_yaml_lock`, reads, mutates, writes, reloads. Re-initialises the router catalog (`llm_router.init_router(...)`). **Then schedules a warmup task via `BackgroundTasks`** that hits `POST {LLM_SERVER_URL}/v1/chat/completions` with the new model id, a single-token cap, and a trivial prompt. Returns the new model row immediately — the caller subscribes to the status SSE for progress.

- `DELETE /api/admin/models/{id}` — 404 if not in YAML. Refuses to delete `nomic-embed-text-v1.5` or any model with `embedding` in its tags (would silently break RAG). Acquires lock, removes, writes, reloads. Re-inits the router. Returns `{"deleted": id}`. **Note:** the cached GGUF stays on disk in the named volume — manual cleanup if needed.

- `GET /api/admin/models/{id}/status` — `StreamingResponse(media_type="application/x-ndjson")`. Opens an `httpx.AsyncClient.stream("GET", f"{LLM_SERVER_URL}/api/events")` and iterates its SSE lines. For each event with `type=logData`, forwards the inner `data` lines that mention the model id as `{"log": "<line>"}`. In parallel, polls `/upstream/{id}/health` every 1s; emits `{"status": "loaded"}` and closes when the probe returns 200. 5-minute wall-clock cap; on timeout emits `{"status": "error", "detail": "load timed out"}` and closes.

### `backend/main.py`

```python
from routers import health, chat, workspaces, admin
...
app.include_router(admin.router, dependencies=[Depends(require_token)])
```

One line in the imports, one line in the includes.

### `backend/core/llm_router.py`

No structural change, but expose a `reload_router_from_yaml()` helper next to `init_router` so the admin router can re-init without duplicating the path-resolution logic:

```python
def reload_router_from_yaml(yaml_path: pathlib.Path) -> HeuristicRouter:
    return init_router(build_catalog_from_yaml(yaml_path))
```

### `frontend/src/components/Settings.tsx`

Existing modal has two sections (Connection, Micro-Prompts). Add a third — "Models" — that opens by default if the user clicks "Models" from a new sidebar entry, otherwise reachable inside Settings.

Components (in the same file or extracted as needed — judge during impl):

- **`<ModelList />`** — fetches `GET /api/admin/models` on mount, renders one row per model:
  - Left: id (mono font), repo path subtle.
  - Middle: group badge (`chat` / `always-on`), tags as small chips.
  - Right: status dot (⬤ loaded / ◌ not loaded) + delete button.
  - Delete button hidden for any model with `embedding` tag (server also refuses; this is UI clarity).
  - Delete confirms via existing `ConfirmModal.tsx`. Body warns "This is a default model" when id is `gemma-4-E2B-it` or `gemma-4-E4B-it`.

- **`<AddModelButton />`** — opens a modal form:
  - Name (free text — validates "letters/digits/dash, unique" client-side).
  - HuggingFace repo:quant (single text input — backend regex catches malformed).
  - GPU layers (number, default 99).
  - Context size (number, default 8192).
  - Group (select: `chat` / `always-on`).
  - Tags (multi-select chips from `embedding | vision | code`).
  - Submit → `POST /api/admin/models`, then immediately opens an SSE consumer on `/api/admin/models/{id}/status`. Modal transitions to a "Downloading <model>…" view with:
    - A scrolling log pane that appends `log` events as they arrive (mono font, latest at bottom, auto-scroll).
    - A spinner with a "Loaded ✓" terminal state when `status: loaded` arrives.
    - A "Cancel" button that closes the SSE; the model stays in YAML (user can delete it from the list if they don't want to keep it).
  - On `status: error`, modal shows the error detail and stays open so the user can copy/paste it.

Styling matches the existing `bg-[#1e1f20] / border-[#333537]` palette.

### `docker-compose.yml`

Pin the llama-swap image tag. Today it likely uses `:latest` or a non-pinned tag — switch to a specific `:cuda-vX.Y.Z` so SIGHUP semantics stay deterministic. Note the exact tag at implementation time after a `docker images | grep llama-swap` check.

## Test plan

Unit (in `backend/tests/test_admin_models.py`):
- `_read_yaml` / `_write_yaml` round-trip preserves comments and field order (load file from fixtures, write back, compare bytes).
- `POST /api/admin/models` happy path adds the entry (use a temp YAML path via monkeypatch, no real SIGHUP — mock `subprocess.run`).
- `POST` rejects duplicate id.
- `POST` rejects malformed `repo:quant`.
- `DELETE` rejects embedding-tagged model.
- `DELETE` rejects unknown id with 404.
- Concurrent POSTs (test via `asyncio.gather`) don't corrupt the YAML — relies on `_yaml_lock`.
- All endpoints 401 without bearer token.

E2E (in `backend/tests/e2e/test_phase_b3_smoke.py`):
- `GET /api/admin/models` against the live backend returns the three real models (`gemma-4-E2B-it`, `gemma-4-E4B-it`, `nomic-embed-text-v1.5`) and reports `loaded` for the currently-loaded model.
- Skipped if `docker` isn't available on `PATH` (the SIGHUP path needs it).

UI smoke (Playwright, `backend/tests/e2e/test_phase_b3_ui_smoke.py`):
- Open Settings → Models. Assert the three default models render.
- Click "Add Model", fill a known-small repo (don't actually wait for download in CI — assert the POST went out and the SSE consumer opened, then bail).
- Delete a non-default model that was added by the test. Verify it disappears from the list and from the YAML on disk.

## Logging / observability

Three new log lines on `pryzm.admin` (new logger, same StreamHandler config inherited via parent):
- `admin.model_added id=<id> repo=<repo:quant>`
- `admin.model_removed id=<id>`
- `admin.llama_swap_reloaded duration_ms=<n>`

Failures from the `subprocess.run` SIGHUP step log a `WARNING` with stderr captured.

## Risks & rollback

- **Concurrent YAML edits.** Mitigated by `_yaml_lock` plus the read-modify-write being entirely under it.
- **SIGHUP doesn't take effect.** llama-swap docs are clear, but a pinned image tag protects against silent behavior change on `docker compose pull`.
- **`ruamel.yaml` reorders things.** Round-trip mode preserves order — verified in unit test.
- **`docker` binary missing from PATH.** Local subprocess raises `FileNotFoundError`; the endpoint returns 500 with a clear message. Pryzm dev setup always has Docker (it runs the compose stack), but the test for `docker` presence is one extra startup check worth adding.
- **Rollback.** Revert the PR. The YAML on disk reverts naturally (it's checked into git). Models added through the UI that aren't in git stay on disk but the router catalog is rebuilt at next startup so they remain functional until the dev removes them manually.

## Critical files to modify

- `backend/requirements.txt` — add `ruamel.yaml`.
- `backend/routers/admin.py` — new (~180 lines).
- `backend/main.py` — one import, one `include_router` line.
- `backend/core/llm_router.py` — small helper `reload_router_from_yaml`.
- `frontend/src/components/Settings.tsx` — third section + `ModelList` + `AddModelButton`.
- `docker-compose.yml` — pin llama-swap image tag.
- `backend/tests/test_admin_models.py` — new.
- `backend/tests/e2e/test_phase_b3_smoke.py` — new.
- `backend/tests/e2e/test_phase_b3_ui_smoke.py` — new.

## Out of scope (deferred to follow-up)

- **Parsed progress percentage.** v1 shows the raw log stream from llama-server. If the lines turn out to be ugly or sparse in practice, a follow-up parses out a `bytes_downloaded` / `total_bytes` shape and surfaces a real progress bar. Cheaper to ship the raw stream first and see what we actually have.
- **First-request download progress UI in the chat panel.** No longer needed in the normal flow — Add triggers the download. Could become useful as a safety net for users who edit YAML by hand and skip the UI.
- **Editing existing models.**
- **Deleting cached GGUFs from the volume.**
- **Separate admin role** (single bearer token stays the gate).
- **Capability-tag enforcement at the chat boundary.** Today only `embedding` is consulted by the router; `vision` / `code` are placeholders for future router behavior.
