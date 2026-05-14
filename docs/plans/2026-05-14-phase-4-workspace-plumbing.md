# Phase 4 — Workspace Plumbing + Tool Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking. Implementation agents must apply Karpathy guidelines: minimum code, no speculative abstractions, surgical changes, verifiable success criteria.

**Goal:** Replace slug-as-string propagation with workspace-id (UUID string) throughout the backend. Tools receive `workspace_id`, never re-resolve slugs. Engine config is read once at the router boundary as a typed `EngineConfig` Pydantic model. Tool registry becomes per-request via `build_tool_set(workspace) → ResolvedToolSet`. Three parallel `DEFAULT_*` dicts in `services/workspaces.py` consolidate into one `BUILTIN_WORKSPACES` registry. Frontend exposes `activeWorkspace.id` and namespaces the message cache by `${workspaceId}:${sessionId}`. The deprecated `workspaces.preferred_model` column drops at the end.

**Architecture:** URL boundary still uses slugs (humans see slugs in URLs). FastAPI dependency resolves slug → `Workspace` ORM object at the route entry. From there, `workspace_id: str` (UUID), `engine_config: EngineConfig`, and `tool_set: ResolvedToolSet` flow downward. Tools never see the slug. The frontend cache keys partition per workspace so a workspace switch doesn't bleed cached data.

**Tech stack:** No new dependencies. Uses Pydantic 2.x (already in deps), SQLAlchemy 2.0 (sync), Alembic for the column drop.

**Spec reference:** [`docs/specs/2026-05-14-codebase-remediation.md`](../specs/2026-05-14-codebase-remediation.md) — Phase 4 section.

**Branch:** `refactor/phase-4-workspace-plumbing` (cut from main after Phase 3 + codemap chores merged).

---

## File Map

### Created
- `backend/core/engine_config.py` — `EngineConfig` Pydantic model + helper to read it from a `Workspace` row.
- `backend/services/builtins.py` — single `BUILTIN_WORKSPACES` registry replacing the three `DEFAULT_*` dicts.
- `backend/alembic/versions/<new>_drop_preferred_model.py` — drops the deprecated column.
- `backend/tests/test_engine_config.py` — unit tests for the model + reader.
- `backend/tests/test_tool_set.py` — unit tests for `build_tool_set`.
- `backend/tests/test_migration_drop_preferred_model.py` — alembic migration test.
- `backend/tests/e2e/test_phase4_smoke.py` — UI smoke for workspace switching + cache namespacing.

### Modified
- `backend/services/workspaces.py` — `BUILTIN_WORKSPACES` import replaces the three local dicts; resolver functions take `workspace_id` not slug where useful.
- `backend/tools/registry.py` — `@tool` decorator raises on duplicate name (was silent overwrite); new `build_tool_set(workspace) -> ResolvedToolSet` exported.
- `backend/tools/retrieval.py` — tools receive `workspace_id`, no slug re-resolution.
- `backend/core/ai_engine.py` — `stream_chat`, `condense_chat_memory`, `generate_title` take `workspace_id` + `engine_config` parameters (not slug).
- `backend/routers/chat.py` — resolves slug → Workspace once via dependency, passes id + engine_config + tool_set downward. Removes any per-tool slug lookups.
- `backend/routers/workspaces.py` — uses the `BUILTIN_WORKSPACES` registry for the reset endpoint.
- `backend/schemas.py` — fix the `mode: str = "itCopilot"` typo (camelCase doesn't match any slug). The default should be removed entirely; the route requires `workspace` explicitly.
- `backend/db/models.py` — when `preferred_model` is dropped, remove from `Workspace`.
- `frontend/src/hooks/useWorkspaces.ts` — `activeWorkspace` shape stays (already has `id`), but consumers stop reading `slug` for non-URL purposes.
- `frontend/src/hooks/useSession.ts` — message cache key becomes `${workspaceId}:${sessionId}`.
- `frontend/src/hooks/useInference.ts` — same cache key shape; optimistic IDs include workspace prefix.
- `frontend/src/context/ChatContext.tsx` — exposes `activeWorkspaceId` alongside `workspace` (slug) for components that need it.

### Untouched
- Database tables (only the column drop, no schema reshape).
- Frontend UI components (visual changes only happen if a component was reading workspace.slug for display purposes — those stay).

---

## Pre-flight

Confirm Phase 3 baseline:

```bash
cd /home/orbital/projects/pryzm
git log main..HEAD --oneline                # empty initially
./backend/venv/bin/pytest backend/tests/ --quiet | tail -3
# Expected: 59/59 pass
./backend/venv/bin/python backend/tests/codemap/codemap.py | tail -2
# Confirm codemap regenerates cleanly
```

---

## Task 0 — `EngineConfig` Pydantic model + reader

**Files:**
- Create: `backend/core/engine_config.py`
- Create: `backend/tests/test_engine_config.py`

### Step 1: Write the failing test

`backend/tests/test_engine_config.py`:

```python
"""Unit tests for EngineConfig — the typed view over workspaces.engine_config JSONB."""
import pytest

from core.engine_config import EngineConfig, engine_config_for


def test_parse_valid_config():
    cfg = EngineConfig.model_validate({"backend": "ollama", "model": "gemma4:e4b"})
    assert cfg.backend == "ollama"
    assert cfg.model == "gemma4:e4b"


def test_missing_backend_raises():
    with pytest.raises(Exception):  # pydantic ValidationError subclass
        EngineConfig.model_validate({"model": "x"})


def test_missing_model_raises():
    with pytest.raises(Exception):
        EngineConfig.model_validate({"backend": "ollama"})


def test_unsupported_backend_raises():
    # Phase 4 ships with Ollama only; llama.cpp lands in a later spec.
    with pytest.raises(Exception):
        EngineConfig.model_validate({"backend": "openai", "model": "gpt-4"})


def test_engine_config_for_workspace_row(db_session):
    """engine_config_for(workspace) reads the JSONB column and returns the model."""
    from db import models
    ws = models.Workspace(
        id="ws-cfg", slug="ws-cfg", display_name="x",
        system_prompt="", enabled_tools=[], is_builtin=False,
        engine_config={"backend": "ollama", "model": "qwen3.6:27b"},
    )
    db_session.add(ws)
    db_session.commit()

    cfg = engine_config_for(ws)
    assert cfg.backend == "ollama"
    assert cfg.model == "qwen3.6:27b"
```

### Step 2: Run to verify failure

```bash
cd /home/orbital/projects/pryzm/backend
./venv/bin/pytest tests/test_engine_config.py -v
```

Expected: `ModuleNotFoundError: No module named 'core.engine_config'`.

### Step 3: Implement

Create `backend/core/engine_config.py`:

```python
"""Typed view over workspaces.engine_config JSONB.

The schema lives in db.models.Workspace.engine_config as JSONB. This module
gives the rest of the codebase a typed handle on those values without each
caller re-parsing the dict.

Today only the ollama backend is supported. The future llama.cpp swap (see
[[project-llama-cpp-swap]] in private memory) extends the `backend` Literal.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from db import models


class EngineConfig(BaseModel):
    """Inference backend choice + parameters for a workspace.

    Future llama.cpp swap will add sampling/context params (n_ctx, n_gpu_layers,
    temperature, etc.). For now: backend + model is the minimum.
    """
    backend: Literal["ollama"]
    model: str


def engine_config_for(workspace: models.Workspace) -> EngineConfig:
    """Read the JSONB column and return the typed model."""
    return EngineConfig.model_validate(workspace.engine_config)
```

### Step 4: Verify

```bash
cd /home/orbital/projects/pryzm/backend
./venv/bin/pytest tests/test_engine_config.py tests/ --quiet --ignore=tests/e2e | tail -3
```

Expected: 64/64 pass (59 prior + 5 new).

### Step 5: Commit

```bash
cd /home/orbital/projects/pryzm
git add backend/core/engine_config.py backend/tests/test_engine_config.py
git commit -m "feat(workspaces): EngineConfig pydantic model for the engine_config JSONB."
```

---

## Task 1 — `BUILTIN_WORKSPACES` registry consolidation

**Files:**
- Create: `backend/services/builtins.py`
- Modify: `backend/services/workspaces.py` (replace three `DEFAULT_*` dicts with imports from `builtins.py`)
- Modify: `backend/routers/workspaces.py` (reset endpoint uses the registry)

### Step 1: Audit current shape

```bash
grep -n "DEFAULT_ENABLED_TOOLS\|DEFAULT_DISPLAY_NAMES\|DEFAULT_COLORS\|is_builtin\|builtin" /home/orbital/projects/pryzm/backend/services/workspaces.py | head -20
```

Note the three `DEFAULT_*` dicts (keyed by slug) and any seed/reset code that consumes them.

### Step 2: Write the failing test

Append to `backend/tests/test_workspace_boundary.py` (the natural home):

```python
def test_builtin_workspaces_registry_has_expected_slugs():
    from services.builtins import BUILTIN_WORKSPACES
    slugs = {b.slug for b in BUILTIN_WORKSPACES}
    # The two original builtins must be present.
    assert "it_copilot" in slugs
    assert "personal" in slugs


def test_builtin_record_has_required_fields():
    from services.builtins import BUILTIN_WORKSPACES, BuiltinWorkspace
    for b in BUILTIN_WORKSPACES:
        assert isinstance(b, BuiltinWorkspace)
        assert b.slug
        assert b.display_name
        assert b.system_prompt_file
        assert isinstance(b.enabled_tools, list)
        assert b.engine_config["backend"] == "ollama"
        assert b.engine_config["model"]
```

### Step 3: Run to verify failure

```bash
./venv/bin/pytest tests/test_workspace_boundary.py::test_builtin_workspaces_registry_has_expected_slugs -v
```

Expected: `ModuleNotFoundError: No module named 'services.builtins'`.

### Step 4: Implement the registry

Create `backend/services/builtins.py`:

```python
"""Single source of truth for builtin workspace seeds.

Replaces the three parallel DEFAULT_* dicts in services/workspaces.py
(enabled_tools, display_names, colors). The seed migration and the reset
endpoint both read from here.

Adding a new builtin: append to the BUILTIN_WORKSPACES list.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BuiltinWorkspace:
    slug: str
    display_name: str
    color: str
    system_prompt_file: str
    enabled_tools: list[str]
    engine_config: dict


BUILTIN_WORKSPACES: list[BuiltinWorkspace] = [
    BuiltinWorkspace(
        slug="it_copilot",
        display_name="IT Copilot",
        color="indigo",
        system_prompt_file="it_copilot.txt",
        enabled_tools=[
            # IMPLEMENTER: lift the actual list from
            # services/workspaces.py:DEFAULT_ENABLED_TOOLS["it_copilot"]
        ],
        engine_config={"backend": "ollama", "model": "gemma4:e4b"},
    ),
    BuiltinWorkspace(
        slug="personal",
        display_name="Personal",
        color="emerald",  # OR whatever the actual current color is — read existing
        system_prompt_file="personal.txt",
        enabled_tools=[
            # IMPLEMENTER: lift from DEFAULT_ENABLED_TOOLS["personal"]
        ],
        engine_config={"backend": "ollama", "model": "gemma4:e4b"},
    ),
]


def get_builtin(slug: str) -> BuiltinWorkspace | None:
    """Look up a builtin by slug; None if not found."""
    for b in BUILTIN_WORKSPACES:
        if b.slug == slug:
            return b
    return None
```

(Implementer: read `services/workspaces.py` and `routers/workspaces.py` to extract the actual `enabled_tools` lists + colors for each builtin. Don't guess — copy from the real source.)

### Step 5: Replace the three DEFAULT_* dicts

In `backend/services/workspaces.py`:
- Remove `DEFAULT_ENABLED_TOOLS`, `DEFAULT_DISPLAY_NAMES`, `DEFAULT_COLORS`.
- Replace consumers with `services.builtins.get_builtin(slug)` lookups.

In `backend/routers/workspaces.py` reset endpoint: when resetting a builtin, fetch from the registry, write `display_name`, `system_prompt` (load from file), `enabled_tools`, `color`, `engine_config` back to the row.

### Step 6: Verify

```bash
./venv/bin/pytest tests/ --quiet --ignore=tests/e2e | tail -3
```

Expected: 66/66 pass (64 prior + 2 new registry tests).

Also run a manual smoke: reset a builtin workspace and confirm it works.

```bash
TOKEN=$(grep '^PRYZM_API_TOKEN=' /home/orbital/projects/pryzm/.env | cut -d= -f2)
curl -s -X POST -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:8000/workspaces/personal/reset" | head -c 200
```

Expected: 200 with the reset workspace JSON.

### Step 7: Commit

```bash
git add backend/services/builtins.py backend/services/workspaces.py backend/routers/workspaces.py backend/tests/test_workspace_boundary.py
git commit -m "refactor(workspaces): consolidate DEFAULT_* dicts into BUILTIN_WORKSPACES registry."
```

---

## Task 2 — Tool registry per-request resolution

**Files:**
- Modify: `backend/tools/registry.py` — add `build_tool_set(workspace) -> ResolvedToolSet`; raise on duplicate `@tool` name.
- Modify: `backend/tools/retrieval.py` — tools take `workspace_id` (already do today after Phase 3's adjustments, but verify); no slug parameter.
- Modify: `backend/tools/network.py` — same audit.
- Modify: `backend/tools/system.py` — same audit.
- Create: `backend/tests/test_tool_set.py` — unit tests for the resolver + duplicate-name guard.

### Step 1: Write the failing test

`backend/tests/test_tool_set.py`:

```python
"""Unit tests for build_tool_set + duplicate-name guard."""
import pytest

from tools.registry import build_tool_set, ResolvedToolSet


def test_resolved_tool_set_has_three_fields():
    """ResolvedToolSet should expose callables, definitions, per_tool_config."""
    from db import models
    ws = models.Workspace(
        id="ws", slug="ws", display_name="x",
        system_prompt="", enabled_tools=[], is_builtin=False,
        engine_config={"backend": "ollama", "model": "gemma4:e4b"},
    )
    result = build_tool_set(ws)
    assert isinstance(result, ResolvedToolSet)
    assert isinstance(result.callables, dict)
    assert isinstance(result.definitions, list)
    assert isinstance(result.per_tool_config, dict)


def test_tool_set_filters_by_enabled_tools(db_session):
    """Only tools listed in workspace.enabled_tools appear in the resolved set."""
    from db import models
    ws = models.Workspace(
        id="ws-filter", slug="ws-filter", display_name="x",
        system_prompt="", enabled_tools=["search_knowledge_base"], is_builtin=False,
        engine_config={"backend": "ollama", "model": "gemma4:e4b"},
    )
    result = build_tool_set(ws)
    # Whatever tools are registered, the resolved set should only include
    # search_knowledge_base.
    assert set(result.callables.keys()) <= {"search_knowledge_base"}


def test_duplicate_tool_name_raises():
    """Two @tool decorators with the same name should raise at registration time."""
    from tools.registry import tool, AVAILABLE_TOOLS

    # Use a unique name unlikely to collide with existing tools.
    @tool(name="phase4_test_unique_xyz", description="test", parameters={"type": "object", "properties": {}})
    def f1():
        pass

    with pytest.raises(Exception):  # specific exception type lands in implementation
        @tool(name="phase4_test_unique_xyz", description="test", parameters={"type": "object", "properties": {}})
        def f2():
            pass

    # Cleanup so future test runs don't fail on stale registration.
    AVAILABLE_TOOLS.pop("phase4_test_unique_xyz", None)
```

### Step 2: Implement

In `backend/tools/registry.py`:

1. Add `ResolvedToolSet` dataclass:

```python
from dataclasses import dataclass, field

@dataclass(frozen=True)
class ResolvedToolSet:
    callables: dict[str, callable]
    definitions: list[dict]
    per_tool_config: dict[str, dict]


def build_tool_set(workspace) -> ResolvedToolSet:
    """Per-request resolution of which tools this workspace gets.

    Today: filters AVAILABLE_TOOLS by workspace.enabled_tools (a list of names).
    Future per-workspace tool config will land in workspace.tool_config (JSONB),
    which this resolver will surface as per_tool_config. The shape exists today
    but is always empty.
    """
    enabled = set(workspace.enabled_tools or [])
    callables = {n: AVAILABLE_TOOLS[n] for n in enabled if n in AVAILABLE_TOOLS}
    definitions = [d for d in TOOL_DEFINITIONS if d["function"]["name"] in enabled]
    per_tool_config = getattr(workspace, "tool_config", None) or {}
    return ResolvedToolSet(callables=callables, definitions=definitions, per_tool_config=per_tool_config)
```

2. Update the `@tool` decorator to raise on duplicate name:

```python
class ToolRegistrationError(Exception):
    pass


def tool(name, description, parameters):
    def decorator(fn):
        if name in AVAILABLE_TOOLS:
            raise ToolRegistrationError(
                f"Tool name {name!r} already registered (was: {AVAILABLE_TOOLS[name].__qualname__}). "
                "Each tool name must be unique across the registry."
            )
        AVAILABLE_TOOLS[name] = fn
        # ... existing TOOL_DEFINITIONS append logic ...
        return fn
    return decorator
```

3. Wire `build_tool_set` into the routes that currently call `resolve_tools_for_workspace` (or whatever the existing per-workspace resolver is named in `services/workspaces.py`). Replace the inline filter with `build_tool_set(workspace)`.

### Step 3: Verify

```bash
./venv/bin/pytest tests/ --quiet --ignore=tests/e2e | tail -3
```

Expected: 69/69 pass (66 prior + 3 new).

Also send a chat message manually to confirm the agentic loop still works with the new resolved tool set:

```bash
TOKEN=$(grep '^PRYZM_API_TOKEN=' /home/orbital/projects/pryzm/.env | cut -d= -f2)
curl -s -N -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"prompt":"hi","mode":"personal","model":"gemma4:e4b","attachments":[],"skip_db_save":true}' \
  http://127.0.0.1:8000/analyze | head -3
```

### Step 4: Commit

```bash
git add backend/tools/registry.py backend/tests/test_tool_set.py
git commit -m "feat(tools): build_tool_set per-request resolver + raise on duplicate name."
```

---

## Task 3 — Backend workspace identity propagation (slug → id)

**Files:**
- Modify: `backend/core/ai_engine.py` — `stream_chat`, `condense_chat_memory`, `generate_title` take `workspace_id: str` + `engine_config: EngineConfig` instead of slug.
- Modify: `backend/routers/chat.py` — resolves slug → `Workspace` ORM via dependency, threads id + engine_config + tool_set downward.
- Modify: `backend/routers/workspaces.py` — slug-only at URL boundary; internal logic uses ORM objects.
- Modify: `backend/schemas.py` — `mode: str = "itCopilot"` → either remove the default (require) or fix to `"it_copilot"`. The route should require workspace explicitly; remove the default.

### Step 1: Audit the slug-passing call chain

Find every site in `backend/core/`, `backend/routers/`, `backend/services/`, `backend/tools/` that passes a workspace SLUG (not the ORM object or id):

```bash
grep -rn "workspace_slug\|workspace:\s*str\|workspace=request\.\|mode=" backend/core backend/routers backend/services backend/tools --include="*.py" | grep -v __pycache__ | grep -v test_
```

This task replaces those with `workspace_id` or the full ORM object.

### Step 2: Update ai_engine.py signatures

```python
# Before:
async def stream_chat(client, messages, workspace_id, session_id=None, model_name="...", is_disconnected=None):

# After:
async def stream_chat(
    client,
    messages,
    *,
    workspace_id: str,
    engine_config: EngineConfig,
    tool_set: ResolvedToolSet,
    session_id: str | None = None,
    is_disconnected=None,
):
    # Use engine_config.model instead of model_name parameter.
    # Use tool_set.definitions instead of looking up via slug.
    # Use tool_set.callables for execution.
```

Same shape adjustment for `condense_chat_memory` and `generate_title`.

### Step 3: Update routers/chat.py

Add a workspace resolver dependency:

```python
def workspace_dep(
    workspace: str = "personal",  # Slug from query param or body. Default is required-ish.
    db: Session = Depends(database.get_db),
) -> models.Workspace:
    """Resolve a workspace slug to its ORM row. 404 if not found."""
    ws = db.query(models.Workspace).filter_by(slug=workspace).first()
    if not ws:
        raise HTTPException(status_code=404, detail=f"Workspace not found: {workspace}")
    return ws


@router.post("/analyze")
async def analyze_data(
    request: AnalyzeRequest,
    http_request: Request,
    background_tasks: BackgroundTasks,
    workspace: models.Workspace = Depends(workspace_dep),  # ← ORM object, not slug
    db: Session = Depends(database.get_db),
    http_client: httpx.AsyncClient = Depends(get_http_client),
):
    engine_config = engine_config_for(workspace)
    tool_set = build_tool_set(workspace)
    # ... existing setup, but pass workspace.id and engine_config to ai_engine.stream_chat:
    async for chunk in ai_engine.stream_chat(
        http_client, messages,
        workspace_id=workspace.id,
        engine_config=engine_config,
        tool_set=tool_set,
        session_id=chat_session.id,
        is_disconnected=http_request.is_disconnected,
    ):
        ...
```

Resolve `AnalyzeRequest.mode` situation:
- Today: `mode: str = "itCopilot"` (broken default). The route reads `request.mode` and passes to `get_or_default(db, request.mode)`.
- Fix: remove the `mode` field entirely from `AnalyzeRequest`. The workspace is determined by the URL boundary (query param) via the `workspace_dep` dependency. The frontend already passes the workspace; the body field is redundant.
- This is a breaking change to the request shape. The frontend's `useInference.ts` already constructs the body — update it to drop `mode` and pass `workspace` via the URL.

### Step 4: Frontend — drop the mode field from /analyze body

In `frontend/src/hooks/useInference.ts`, find the POST body for `/analyze`:

```typescript
// Before (sketch):
apiFetch("/analyze", {
  method: "POST",
  body: JSON.stringify({ prompt, mode: workspace, model, attachments, ... }),
  headers: { "Content-Type": "application/json" },
})

// After: drop mode; pass workspace as a query param.
apiFetch(`/analyze?workspace=${encodeURIComponent(workspace)}`, {
  method: "POST",
  body: JSON.stringify({ prompt, model, attachments, ... }),
  headers: { "Content-Type": "application/json" },
})
```

### Step 5: Verify

```bash
./venv/bin/pytest tests/ --quiet --ignore=tests/e2e | tail -3
```

Manual chat probe:

```bash
TOKEN=$(grep '^PRYZM_API_TOKEN=' /home/orbital/projects/pryzm/.env | cut -d= -f2)
curl -s -N -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"prompt":"hi","model":"gemma4:e4b","attachments":[],"skip_db_save":true}' \
  "http://127.0.0.1:8000/analyze?workspace=personal" | head -3
```

Expected: streaming chunks. Manual browser test: open the frontend, switch workspaces, send messages in each, confirm everything still works.

### Step 6: Commit

```bash
git add backend/core/ai_engine.py backend/routers/chat.py backend/routers/workspaces.py backend/schemas.py frontend/src/hooks/useInference.ts
git commit -m "refactor(workspaces): propagate workspace_id + engine_config; slug stays at URL boundary."
```

---

## Task 4 — Frontend workspace identity + cache namespacing

**Files:**
- Modify: `frontend/src/hooks/useWorkspaces.ts` — ensure `activeWorkspace` exposes `id` cleanly.
- Modify: `frontend/src/hooks/useSession.ts` — message cache keys become `${workspaceId}:${sessionId}`.
- Modify: `frontend/src/hooks/useInference.ts` — optimistic IDs include workspace prefix.
- Modify: `frontend/src/context/ChatContext.tsx` — expose `activeWorkspaceId` for components that need it.

The cache namespacing is the load-bearing change — switching workspaces shouldn't surface another workspace's cached messages.

### Step 1: Update cache key shape

In `useSession.ts`, find the message cache map:

```typescript
// Before:
const messageCache = useRef<Map<string, Message[]>>(new Map());
// Key: sessionId

// After:
// Key: `${workspaceId}:${sessionId}`
const cacheKey = (workspaceId: string, sessionId: string) => `${workspaceId}:${sessionId}`;
```

Every cache read/write needs the new key shape. The implementer must trace every `.get(sessionId)` and `.set(sessionId, ...)` and update.

### Step 2: Drop stale buckets on workspace switch

When `activeWorkspace.id` changes, optionally clear cache buckets for the prior workspace (or just leave them and let them garbage-collect). The simpler choice: leave them; React's component remount handles the visible state.

### Step 3: Verify

```bash
./venv/bin/pytest tests/ --quiet --ignore=tests/e2e | tail -3
```

Manual test: open the app, send a message in `personal`, switch to `it_copilot`, confirm the chat history is `it_copilot`'s (not `personal`'s). Switch back — `personal`'s history should still be there (cached under its key).

### Step 4: Commit

```bash
git add frontend/src/hooks/useSession.ts frontend/src/hooks/useInference.ts frontend/src/context/ChatContext.tsx
git commit -m "refactor(frontend): namespace message cache by workspace id."
```

---

## Task 5 — Drop deprecated `preferred_model` column

**Files:**
- Create: `backend/alembic/versions/<new>_drop_preferred_model.py`
- Modify: `backend/db/models.py` — remove the `preferred_model` field from `Workspace`.
- Create: `backend/tests/test_migration_drop_preferred_model.py`

### Step 1: Confirm no code reads preferred_model anymore

```bash
grep -rn "preferred_model" backend frontend --include="*.py" --include="*.ts" --include="*.tsx" | grep -v __pycache__ | grep -v test_
```

Expected: zero hits in production code (only `# DEPRECATED` comments + possibly Phase 1 backfill migration references).

If there are any references in non-test code, fix them BEFORE the drop.

### Step 2: Write the migration test

```python
"""Verify the preferred_model column drop."""
from sqlalchemy import text


def test_column_dropped(reset_test_db, alembic_cfg):
    from alembic import command
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    command.upgrade(alembic_cfg, "head")
    engine = create_engine(reset_test_db, poolclass=NullPool)
    with engine.connect() as conn:
        col = conn.execute(text("""
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'workspaces' AND column_name = 'preferred_model'
        """)).scalar()
    engine.dispose()
    assert col is None


def test_downgrade_restores_column(reset_test_db, alembic_cfg):
    from alembic import command
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    command.downgrade(alembic_cfg, "base")
    command.upgrade(alembic_cfg, "head")
    command.downgrade(alembic_cfg, "-1")  # back to just before this migration

    engine = create_engine(reset_test_db, poolclass=NullPool)
    with engine.connect() as conn:
        col = conn.execute(text("""
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'workspaces' AND column_name = 'preferred_model'
        """)).scalar()
    engine.dispose()
    assert col == 1
```

### Step 3: Generate migration and write it

```bash
cd /home/orbital/projects/pryzm/backend
./venv/bin/alembic revision -m "drop_preferred_model"
```

Body:

```python
"""drop deprecated workspaces.preferred_model

Phase 1 added engine_config and marked preferred_model deprecated. Phase 4
removed the last consumer. This drops the column.

Revision ID: <generated>
Revises: a8c69f612a8a
"""
from alembic import op
import sqlalchemy as sa

revision = "<generated>"
down_revision = "a8c69f612a8a"  # the Phase 1 final head
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column("workspaces", "preferred_model")


def downgrade():
    op.add_column("workspaces", sa.Column("preferred_model", sa.String(), nullable=True))
    # Backfill from engine_config so the column isn't all-NULL.
    op.execute("""
        UPDATE workspaces
        SET preferred_model = engine_config->>'model'
        WHERE engine_config IS NOT NULL
    """)
```

### Step 4: Remove from `db/models.py`

In `backend/db/models.py`, remove the `preferred_model = Column(...)` line from `Workspace`.

### Step 5: Run migration against dev DB

```bash
cd /home/orbital/projects/pryzm/backend
./venv/bin/alembic upgrade head
```

Verify:

```bash
docker exec pryzm_db psql -U pryzm_admin -d pryzm_core -c "\d workspaces" | grep preferred_model
# Expected: no output (column gone)
```

### Step 6: Verify tests

```bash
./venv/bin/pytest tests/ --quiet --ignore=tests/e2e | tail -3
```

Expected: 71/71 pass.

### Step 7: Commit

```bash
git add backend/alembic/versions/*_drop_preferred_model.py backend/db/models.py backend/tests/test_migration_drop_preferred_model.py
git commit -m "feat(schema): drop deprecated workspaces.preferred_model column."
```

---

## Task 6 — Phase 4 e2e UI smoke

**Files:**
- Create: `backend/tests/e2e/test_phase4_smoke.py`

### Tests to write

1. **`test_workspace_switch_preserves_history`** — send a message in `personal`, switch to `it_copilot`, switch back to `personal`, verify the message is still there (cache key working).

2. **`test_workspace_switch_isolates_history`** — send a message in `personal`, switch to `it_copilot`, confirm the `personal` message does NOT appear.

3. **`test_chat_works_in_each_builtin`** — send a quick "hi" in both `personal` and `it_copilot`, verify both stream successfully.

(Adapt selectors to the actual UI as in Phase 2 / Phase 3 e2e tests.)

### Verify

```bash
cd /home/orbital/projects/pryzm/backend
./venv/bin/pytest tests/e2e/ -v
```

Expected: 12/12 pass (9 prior + 3 new).

### Commit

```bash
git add backend/tests/e2e/test_phase4_smoke.py
git commit -m "test(e2e): phase 4 UI smoke — workspace identity + cache namespacing."
```

---

## Task 7 — Final review + codemap regeneration + auto-merge

Controller work.

### Step 1: Branch sweep + full suite

```bash
git log main..HEAD --oneline    # ~7 commits
./venv/bin/pytest tests/ --quiet | tail -3    # unit + integration
./venv/bin/pytest tests/e2e/ --quiet | tail -3 # e2e
```

### Step 2: Regenerate the codemap

```bash
./venv/bin/python tests/codemap/codemap.py
```

Open the HTML, confirm visually:
- Backend zone shows the new files (`engine_config.py`, `builtins.py`).
- Tool registry node has the expected importers (ai_engine, routers).
- No phantom (red dashed) edges introduced.

### Step 3: Push + open PR + auto-merge

```bash
git push -u origin refactor/phase-4-workspace-plumbing
gh pr create --title "Phase 4 — workspace plumbing + tool registry" --body "$(...lean body...)"
gh pr merge --squash --delete-branch
git checkout main && git pull origin main
```

Report in chat: "Phase 4 merged at <SHA>. Cutting Phase 5 next."

---

## Risks and rollback

- **Mid-flight chat break**: Tasks 3-4 change the request/response shape. Frontend + backend must land together to avoid the chat path being broken between commits. Sequence them carefully OR bundle into a single commit if isolating proves fragile.
- **`mode` field removal**: any external script that POSTs to `/analyze` with a `mode` field will silently break (Pydantic ignores unknown fields by default). The frontend is the only consumer; surface this for the user.
- **Cache key change**: if any localStorage key uses the old single-`sessionId` shape, it'll start fresh after Phase 4. Acceptable since the cache is in-memory not localStorage (the `pryzm_folders_open_*` localStorage key is per-workspace already).
- **Tool registry duplicate-raise**: if any existing tool gets imported twice somehow (e.g., a circular import) the registration would now raise. Lightly likely; if it happens, the import order needs fixing, not the registry.
- **Rollback**: `git revert <merge-commit>` undoes the whole phase. Migration is reversible (Step 5 has a downgrade).

---

## Related memory

- [[project-workspace-roadmap]] — the broader workspace expansion direction this phase enables.
- [[project-llama-cpp-swap]] — `EngineConfig`'s `backend: Literal["ollama"]` extends to llama.cpp here.
- [[feedback-karpathy-for-subagents]] — implementer agents get the guidelines.
- [[feedback-lean-pr-descriptions]] — Phase 4 PR body stays short.
- [[feedback-auto-merge-authorized]] — Task 7 uses `gh pr merge --squash --delete-branch`.
- [[project-ui-smoke-harness]] — Task 6 is the per-phase e2e harness extension.
