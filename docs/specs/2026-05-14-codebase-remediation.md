# Codebase Remediation — Design Spec

- **Date**: 2026-05-14
- **Status**: Draft, ready for review
- **Branch context**: spec authored on `refactor/phase-1-schema-foundations`. Phase 1 implementation builds on top.
- **Successor work**: this spec precedes (and unblocks) the planned admin-gating + per-workspace tool config work, and the future Ollama → llama.cpp swap.

## Context

A multi-agent design review (May 2026) surfaced ~30 issues across the backend agentic loop, data layer, HTTP layer, frontend state, and UI components. The issues cluster into five real themes, not thirty independent bugs:

1. **The async-shaped server uses sync-shaped I/O.** `requests.post` / `requests.get` are called from inside an SSE generator that FastAPI iterates asynchronously. Every call blocks an event-loop worker. The agentic tool loop has no client-disconnect propagation — closing the browser doesn't stop generation. Memory condensation, documented as "background," runs foreground inside the SSE generator's `finally`.
2. **Anyone reachable can do anything.** No auth on destructive endpoints. Several id-keyed routes don't verify that the resource belongs to the requesting workspace, allowing cross-workspace mutation (e.g., re-parenting another workspace's documents via the attachment claim path).
3. **Workspace identity flows as a renameable slug, not a stable id.** The slug propagates from URL through frontend hooks into backend tools, which re-resolve it on every call. Three frontend sources of truth for "current workspace" can disagree.
4. **Tools are baked at import time into a global registry.** Per-workspace tool configuration — the next roadmap phase — needs a runtime overlay; the current shape is a fixed roster filtered by name.
5. **The frontend has one shared context with split cache ownership.** Two hooks write to the message cache without coordination, producing the optimistic-id → real-id handoff races. ChatBubble re-renders every token.

A separate Ollama → llama.cpp inference-backend swap is planned but explicitly deferred. This spec shapes the codebase so the swap becomes a focused effort later, not a rewrite.

### Explicitly out of scope

- **Multi-user / admin / role permissions model.** A single shared bearer-token gate lands here; the full user system is a separate future spec.
- **Ollama → llama.cpp swap.** Hygiene-only co-location of Ollama-specific code lands here. The actual backend swap, including the `LLMClient` adapter abstraction, lands in its own future spec when there are two real backends to design against.
- **Frontend permission UI.** Auth is server-side only in this work.
- **State-management library introduction (Zustand, Jotai, Redux).** Native React contexts only.
- **Full test-suite buildout.** Per-phase verification uses the existing autotest harness plus a small pytest folder for migration + constraint checks.
- **Per-workspace tool *configuration*.** The data-shape seam (`per_tool_config` field) ships; the actual configuration UI and runtime use are deferred to the workspace-expansion follow-up.
- **Dynamic tool creator.** Deferred entirely.

## Goals

1. Close the security and cross-workspace mutation gaps so a future multi-user model can build on a sealed base.
2. Make workspace identity flow as a stable id, not a renameable slug. Eliminate per-tool slug re-resolution.
3. Move all Ollama-specific HTTP shape into one module so the future backend swap has a single locus to replace.
4. Make the SSE path actually asynchronous: request concurrency that doesn't serialize behind a single LLM call, disconnect propagation, and background condensation that runs out-of-band.
5. Give the frontend a single owner per cache bucket, a deterministic optimistic-id handoff, and an optimistic-mutation rollback pattern.
6. Each phase is independently mergeable and revertable; main is never left in a half-coherent state.

## Sequencing Decision

The remediation runs **bottom-up by data shape**: schema first, consumers conform.

**Why not security-first?** Security work depends on workspace boundaries being expressible as FK constraints; doing it before the schema work means temporary application-level checks that get reworked during the schema phase. Net more code touched.

**Why not vertical feature slices?** Slices that cross DB + backend + frontend produce large PRs that are harder to review surgically. Per-layer phases align with one-PR-per-phase review.

**Why not swap to llama.cpp first?** Building an `LLMClient` adapter with one real backend is a speculative abstraction. The adapter shape will guess wrong about llama.cpp's actual quirks (tool-calling format per model, streaming envelope, embedding endpoint). The adapter is justified only once there are two real backends. This spec instead co-locates Ollama-specific code in a single module as hygiene, so the future swap effort has one place to look.

Each phase has a tight verification: a migration runs cleanly, an endpoint behaves correctly, a smoke probe passes. Sequencing means each phase's success is checkable before the next begins.

---

## Phase 1 — Schema Foundations

**Goal:** Establish the data-layer shape that subsequent phases conform to. No application-code changes; migrations only.

### Migrations

Five revisions, one logical change each. Each ships with a down-migration and a smoke probe.

#### Revision A — `workspaces.engine_config` (JSONB)

```sql
ALTER TABLE workspaces ADD COLUMN engine_config JSONB;

UPDATE workspaces
SET engine_config = jsonb_build_object('backend', 'ollama', 'model', preferred_model)
WHERE engine_config IS NULL;

ALTER TABLE workspaces ALTER COLUMN engine_config SET NOT NULL;
ALTER TABLE workspaces ALTER COLUMN engine_config
  SET DEFAULT '{"backend": "ollama", "model": "gemma4:e4b"}'::jsonb;
```

`workspaces.preferred_model` is **not** dropped here. It stays as a deprecated column read by no one once Phase 4 lands, then drops in a later revision. Karpathy #3: don't break consumers in the same migration as the data-shape change.

**Pydantic shape (used in Phase 4):**
```python
class EngineConfig(BaseModel):
    backend: Literal["ollama"]  # llama.cpp added later in a separate spec
    model: str
    # Future fields (n_ctx, n_gpu_layers, sampling params) added as needed.
```

#### Revision B — `document_chunks.workspace_id`

```sql
ALTER TABLE document_chunks ADD COLUMN workspace_id INTEGER REFERENCES workspaces(id);

UPDATE document_chunks dc
SET workspace_id = d.workspace_id
FROM documents d
WHERE dc.document_id = d.id;

ALTER TABLE document_chunks ALTER COLUMN workspace_id SET NOT NULL;
CREATE INDEX ix_chunks_workspace_document ON document_chunks(workspace_id, document_id);
```

Removes the join-through-`documents` requirement when filtering chunks by workspace. Enables cleaner FK-level boundary enforcement in Phase 2.

#### Revision C — `messages.role` constraint

```sql
ALTER TABLE messages
  ADD CONSTRAINT messages_role_check
  CHECK (role IN ('user', 'assistant', 'tool', 'memory'));
```

CHECK constraint, not a native Postgres ENUM. CHECK constraints are dropped/replaced cheaply; native ENUMs require `ALTER TYPE` dances. SQLAlchemy declares `Enum(..., native_enum=False)` to mirror.

#### Revision D — pgvector index

```sql
CREATE INDEX CONCURRENTLY ix_chunks_embedding
  ON document_chunks
  USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);
```

`lists=100` is reasonable for tens of thousands of chunks. Re-tune in a follow-up if recall degrades.

#### Revision E — minor constraints

```sql
ALTER TABLE messages ALTER COLUMN session_id SET NOT NULL;
ALTER TABLE documents ALTER COLUMN is_global SET DEFAULT false;
```

Plus: backfill any rows that violate (`session_id IS NULL`, `is_global IS NULL`) — there should be none in normal operation, but the migration asserts the precondition or fails loudly.

### Success criterion

- `alembic upgrade head && alembic downgrade base && alembic upgrade head` runs clean against a fresh DB.
- `alembic downgrade -1` works for each of the five revisions independently.
- Integrity checks pass on a dev-DB snapshot: no NULL `workspace_id` on `document_chunks`, no `messages.role` outside the enum, no NULL `messages.session_id`.

### Risks

- **Backfill drift on chunks.** A row with NULL `Document.workspace_id` (shouldn't exist, but) would block the NOT NULL set. Migration asserts the precondition before ALTER and fails clearly if violated.
- **`ivfflat` index creation on a populated table.** `CONCURRENTLY` avoids locking writes. If the table is small, the index doesn't materially help; if large, it materially helps. Either way: not harmful.

### Dependencies

None. Phase 1 can land in isolation.

---

## Phase 2 — Auth + Workspace Boundary Enforcement

**Goal:** Close the no-auth and cross-workspace mutation gaps. Establish the workspace-boundary enforcement pattern that the remaining backend phases rely on.

### Auth approach — explicit non-goal

This phase establishes a **gate**, not a user system. A single shared bearer token, configured via env (`PRYZM_API_TOKEN`). FastAPI dependency `require_token()` reads `Authorization: Bearer <token>`, constant-time compares, returns 401 on mismatch.

**Explicitly deferred to a future spec:**

- User accounts.
- Per-user-per-workspace ACLs.
- Token rotation.
- Audit log.
- JWT or session-based auth.

Karpathy #2: building the full multi-user model now is speculative — we don't yet have the user-facing requirements for it. The gate is what we need; build the gate.

### Frontend wiring

- Settings panel exposes a token field, persisted to `localStorage`.
- A single global `fetch` wrapper injects the `Authorization` header on every API call. One chokepoint, not threaded through every call site.
- Absent token → UI shows a "configure token" gate; no API calls fire.

### Exempt routes

`/health` only. Everything else requires the token.

### Workspace boundary enforcement

A reusable dependency `verify_workspace_owns(resource_id, resource_type) -> Resource`:

1. Look up the resource by id.
2. Return **404** (not 403) if the resource doesn't exist OR belongs to another workspace.

**Why 404, not 403:** Returning 403 leaks the existence of the resource in some other workspace. 404 keeps the boundary opaque. Karpathy #1: explicit decision, surfaced.

Applied to:
- `PATCH /messages/{id}` and `DELETE /messages/{id}`
- `POST /sessions/{id}/truncate`
- The attachment claim path inside `/analyze` (today: `Document.id.in_(request.attachments)`, unscoped — now scoped to the workspace).
- Document edit/delete routes.

### Reset endpoint

`POST /workspaces/{slug}/reset` requires the auth token AND rejects with **400** for non-builtin workspaces (`is_builtin = false`). UI already gates the reset button on `is_builtin`; this is server-side enforcement to match.

### Success criterion

A smoke probe in the autotest harness verifies:
- A destructive route called without a token → 401.
- Editing a message that belongs to another workspace → 404.
- Re-parenting a document from another workspace via attachment claim → 404 (the document is not found in the requesting workspace's scope).
- Resetting a non-builtin workspace → 400.

### Risks

- **Local dev workflow:** the user must set `PRYZM_API_TOKEN` to use the app. Mitigation: dev `.env.example` ships with a placeholder; clear error message on missing token; settings UI surfaces the gap.
- **CORS still permissive:** the `allow_origins` list stays as-is; auth is the actual gate. The hardcoded LAN IP is removed as part of Phase 6.

### Dependencies

Phase 1 (FK boundaries on `document_chunks.workspace_id` enable the cross-workspace 404 path cleanly).

---

## Phase 3 — Async I/O, Ollama Co-Location, Background Condensation

**Goal:** Make the SSE path actually asynchronous. Co-locate Ollama-specific code as hygiene for the future backend swap. Move memory condensation out of the response path.

### `httpx.AsyncClient`

Single instance created in FastAPI's lifespan handler, shared across requests via app state. Defaults:

- 120s timeout for chat
- 30s for embeddings
- 5s for tag list

Connection pooling eliminates per-request TCP+TLS overhead.

### `backend/core/ollama.py`

New module. **All** Ollama-specific HTTP shape lives here:

```python
async def chat_stream(messages, tools, model, **opts) -> AsyncIterator[OllamaChunk]: ...
async def embed(text: str, model: str) -> list[float]: ...
async def list_models() -> list[str]: ...
```

`ai_engine.py`, `services/knowledge.py`, `routers/chat.py`, and `routers/workspaces.py` stop calling Ollama directly and import from this module.

**This is not an abstract interface.** No `LLMClient` base class. No `Protocol`. No registry. Just one module holding Ollama-specific code. The future llama.cpp swap will introduce the abstract interface at that point, when there are two real backends to design against. Karpathy #2.

### Cancellation propagation

- `/analyze` becomes `async def`. The agentic loop awaits all `httpx` calls and accepts `asyncio.CancelledError`.
- Each loop iteration checks `await request.is_disconnected()` and raises `CancelledError` on True.
- Async tools simply await. Sync tools (subprocess ping, network probes) run via `asyncio.to_thread(...)` so cancellation is honored at thread boundaries.
- Each tool call wrapped in `asyncio.wait_for(..., timeout=TOOL_TIMEOUT)` to bound the worst case.

Total request budget bounded by: `MAXIMUM_TOOL_LOOPS * (LLM_TIMEOUT + tools_per_loop * TOOL_TIMEOUT)`.

### Background memory condensation

The condensation work moves out of the SSE generator entirely. Uses FastAPI's `BackgroundTasks` — runs after the response is sent.

**Race protection:** a Postgres advisory lock keyed on a session-scoped hash. Conceptually:

```python
# Acquire an advisory lock on a hash of "condense:{session_id}".
# If another worker already holds the lock, skip silently.
if not await acquire_advisory_lock(f"condense:{session_id}"):
    return
try:
    await condense_chat_memory(...)
finally:
    await release_advisory_lock(f"condense:{session_id}")
```

(Implementation detail in the plan: `pg_try_advisory_lock` takes a `bigint`, so the helper hashes the key via `hashtextextended` or similar to produce a stable 64-bit handle.)

If condensation fails, the failure is logged and the task ends. The next request that crosses the threshold will retry. No retry storm.

**Why not Celery / a real queue:** `BackgroundTasks` is what FastAPI ships with. Adding queue infrastructure for one workload that runs every ~15 messages is over-engineering. Karpathy #2: simplest thing that works. Upgrade if metrics later say so.

### SSE error envelope

Today: stream emits `{"chunk": "..."}` for content, ends with `{"done": true}`. An error is indistinguishable from text.

New: errors emit `{"error": "<human msg>", "code": "<machine_code>"}` and terminate the stream. Frontend distinguishes normal-end from error-end and surfaces UI accordingly.

### Success criterion

Smoke probes:
- Three parallel `/analyze` calls overlap in time (response timing matches concurrency, not serial).
- A simulated client disconnect mid-stream cancels the loop within ≤2s.
- Memory condensation runs out-of-band (response closes before condensation log entry appears).
- An induced Ollama error produces an `{"error", "code"}` envelope, not a normal-looking final chunk.

### Risks

- **Behavior changes under load.** Concurrency that previously serialized is now real; tools and downstream resources may see surprising parallelism. Mitigated by per-tool timeouts and an explicit `MAXIMUM_CONCURRENT_REQUESTS` config if needed.
- **Cancellation semantics on subprocess tools.** Killing a `subprocess.run` mid-execution requires careful signal handling. Mitigation: run subprocesses with `asyncio.create_subprocess_exec`, propagate cancellation as `SIGTERM` then `SIGKILL` on a budget.

### Dependencies

Phase 2 (auth makes smoke probes realistic; the disconnect-during-auth path is testable).

---

## Phase 4 — Workspace Plumbing + Tool Registry

**Goal:** Stop passing slugs into tools. Refactor the tool registry to support per-workspace resolution (and seam in the future per-tool config). Eliminate the three parallel "builtin defaults" dicts.

### Workspace identity propagation

The slug stays at the URL boundary (humans see slugs). The id flows below.

1. Router resolves slug → `Workspace` ORM object in a FastAPI dependency.
2. The engine receives `workspace_id: str` (the UUID string used as the primary key in `db/models.py`) and a typed `engine_config: EngineConfig` (Pydantic model).
3. Tools receive `workspace_id` only. No slug. No re-resolution. The current `tools/retrieval.py:26` re-lookup goes away.

`engine_config` is read once per request at the router boundary, then propagated as a typed parameter through the call chain. No second DB roundtrip from tools.

### Tool registry refactor

The global registry (`AVAILABLE_TOOLS`, `TOOL_DEFINITIONS`) stays — it's the manifest of available tools in the codebase. What changes is how a request *resolves* its tool set:

```python
@dataclass(frozen=True)
class ResolvedToolSet:
    callables: dict[str, Callable]
    definitions: list[dict]
    per_tool_config: dict[str, dict]

def build_tool_set(workspace: Workspace) -> ResolvedToolSet:
    enabled = set(workspace.enabled_tools)
    return ResolvedToolSet(
        callables={n: AVAILABLE_TOOLS[n] for n in enabled if n in AVAILABLE_TOOLS},
        definitions=[d for d in TOOL_DEFINITIONS if d["function"]["name"] in enabled],
        per_tool_config=workspace.tool_config or {},
    )
```

Three outcomes:
- Tools filtered per workspace, resolved cleanly per request.
- `per_tool_config` shape exists for future per-workspace tool *configuration* — the column ships, the use is deferred. Karpathy #2: ship the column shape (cheap), not the configuration UI (premature).
- Duplicate-tool registration raises at import time (fixes `tools/registry.py:11` silent overwrite).

### Builtin workspaces — single source of truth

The three parallel `DEFAULT_*` dicts in `services/workspaces.py` consolidate:

```python
@dataclass(frozen=True)
class BuiltinWorkspace:
    slug: str
    display_name: str
    color: str
    enabled_tools: list[str]
    system_prompt_file: str
    engine_config: dict

BUILTIN_WORKSPACES: list[BuiltinWorkspace] = [
    BuiltinWorkspace(
        slug="it_copilot",
        display_name="IT Copilot",
        color="indigo",
        enabled_tools=["search_knowledge_base", "check_port", ...],
        system_prompt_file="it_copilot.txt",
        engine_config={"backend": "ollama", "model": "gemma4:e4b"},
    ),
    BuiltinWorkspace(...),  # personal
]
```

Seed migration imports from this. Reset endpoint reads from this. No drift.

### Frontend workspace identity

- `useWorkspaces` returns `activeWorkspace` as an object including `id`.
- Slug remains in the URL only. URL → workspace lookup happens once in `useWorkspaces`; downstream consumers reference the object, never re-parse the URL.
- Message cache keys become `${workspaceId}:${sessionId}` so cache cleanly partitions per workspace (switching workspaces doesn't bleed cache buckets).

### Drop deprecated `preferred_model`

Phase 1 left the column. Now that no caller references `preferred_model` directly (all reads go through `engine_config`), a small migration drops it:

```sql
ALTER TABLE workspaces DROP COLUMN preferred_model;
```

Lands at the end of Phase 4.

### Success criterion

Smoke probes:
- Rename a workspace's slug while a request is in flight (test harness coordinates); the in-flight request still resolves correctly via id.
- Adding a tool to one workspace's `enabled_tools` and listing `/api/tools` for another workspace doesn't include it.
- A duplicate `@tool` registration raises `ToolRegistrationError` at import time (verified by an intentional duplicate in a test fixture).

### Risks

- **Frontend cache key change.** Existing in-memory caches with `${sessionId}` keys are invalidated when the format changes. Acceptable since cache is in-memory and rehydrates from server on next request.
- **`preferred_model` drop** is the only schema change in this phase. Down-migration restores the column with `engine_config->>'model'` as the backfill source.

### Dependencies

Phase 1 (`engine_config` column exists). Phase 2 (workspace scoping enforced — id-based identity meaningful).

---

## Phase 5 — Frontend State Ownership

**Goal:** Single owner per cache bucket. Eliminate the optimistic-id handoff races. Add a rollback pattern for failing UI mutations. Stop ChatBubble re-rendering on every token.

### Context split

The single 11-key `ChatContext` becomes five focused contexts:

| Context | Owns | Update cadence |
|---|---|---|
| `WorkspaceContext` | `activeWorkspace`, `workspaces[]`, `switchWorkspace` | Rare |
| `SessionContext` | `sessions[]`, `currentSession`, `folders[]`, message cache | Moderate |
| `InferenceContext` | `isStreaming`, `sendMessage`, `stopInference` | Per-token during streams |
| `UploaderContext` | upload queue, progress | Independent |
| `TestSuiteContext` | test runner state | Dev-only, env-gated |

A token streaming in only re-renders `InferenceContext` consumers. The sidebar (Session) and switcher (Workspace) stay stable.

**Explicitly not** introducing `use-context-selector`, Zustand, or any state library. Native contexts only. Karpathy #2.

### Cache ownership — single writer

**Rule: `SessionContext` owns the message cache.** Public API:

```ts
type SessionContextAPI = {
  getMessages: (sessionId: string) => Message[];
  appendChunk: (sessionId: string, messageId: string, chunk: string) => void;
  finalizeMessage: (sessionId: string, messageId: string, content: string, status: 'success' | 'failed') => void;
  replaceMessages: (sessionId: string, messages: Message[]) => void;
  migrateBucket: (fromKey: string, toKey: string) => boolean;  // atomic
  notifySessionCreated: (realId: string, optimisticId: string) => void;
};
```

`useInference` calls these methods. It does **not** hold its own setter. This removes the two-writer race.

### Optimistic-ID handoff

- IDs come from `crypto.randomUUID()`. No `Date.now()` collisions on rapid sends, double-clicks, or React 19 strict-mode double invocation.
- `migrateBucket(optimisticKey, realKey)` atomically copies the entry, deletes the optimistic key, and returns success.
- A `migratedIds: Map<optimisticId, realId>` lets `stopInference(optimisticId)` find the right AbortController after migration. Optimistic-key entries are deleted from the controller map after rekey.

### Optimistic-mutation rollback

A small helper, used at every mutation site:

```ts
async function withRollback<T>(
  applyLocal: () => void,
  rollback: () => void,
  apiCall: () => Promise<T>,
): Promise<T> {
  applyLocal();
  try {
    return await apiCall();
  } catch (e) {
    rollback();
    throw e;
  }
}
```

~15 lines total. Applied to:
- Folder create / rename / delete / drag-drop.
- Workspace edit (in `WorkspaceSettings.tsx` — replaces fire-and-forget PATCH on blur).
- Message edit.

### Re-render storm fixes

- `ChatBubble` is `React.memo`'d.
- `ActiveSession.tsx:77` stops spreading `{...m, content: displayContent}` per render — passes `m` and `displayContent` as separate props so `m`'s object identity stays stable.
- Callbacks (`onDeleteRequest`, etc.) stabilized via `useCallback` with refined deps; a `useRef`-held latest-value pattern where deps would otherwise force recreation.
- `streamingSessionIdsRef` reads stop happening in render bodies; converted to state where the read affects render.

### `window.dispatchEvent("chatCreated")` removal

Replaced by direct method calls on `SessionContext.notifySessionCreated`. No window-level pub/sub.

### Success criterion

Smoke probes (autotest + manual):
- Send 3 messages within 200ms; all 3 land with distinct IDs and ordered correctly.
- Navigate away from a streaming session and back; no orphan empty bubbles.
- Toggle a workspace setting with the backend forced to 500; UI rolls back to the prior value.
- React profiler shows ChatBubble re-renders bounded to the bubble being streamed, not the full list.

### Dependencies

Phase 2 (auth errors land as HTTP codes the rollback can detect). Phase 3 (SSE error envelope distinguishable). Phase 4 (workspace id is the cache key namespace).

---

## Phase 6 — Cleanups

Execution-only, no design. One PR.

- **ConfirmModal:** Escape handler, focus trap, `role="dialog"`, ARIA label.
- **Hardcoded LAN IPs:** remove `192.168.0.108` from `config.py:28-33` and `frontend/src/utils/constants.ts:6-13`. Replace with env-driven values.
- **Builtin Delete button:** hide in `WorkspaceSettings.tsx:307-320` for `is_builtin = true`.
- **Empty Suspense:** drop the no-children Suspense block in `app/layout.tsx:38-39`.
- **`pryzm_model` localStorage:** delete the duplicate model-selection path now that workspace `engine_config` owns it.
- **`"document overview"` literal:** replace the string match in `services/knowledge.py:137-157` with an explicit parameter or constant.

### Success criterion

One manual walkthrough per item. No regressions in autotest smoke probes from previous phases.

### Dependencies

Conceptually none, but ships last to avoid mixing with substantive work. Can land in parallel with Phase 5 if calendar pressure exists.

---

## Cross-Cutting Concerns

### Testing strategy

No full test-suite buildout. Per-phase verification combines:

- **`pytest` for mechanical checks** — a small new `tests/` folder. Migration up/down, role-enum constraint, FK enforcement, duplicate-tool error. ~10–15 tests total across all phases.
- **`/tmp/pryzm_autotest.py` extensions** — phase-specific smoke probes per the success criteria above. The autotest harness already exists ([[reference-debug-tools]]) and is the natural home for HTTP-level verification.
- **Manual + `/tmp/pryzm_screenshot.py`** — frontend visual spot-checks per Phase 5.

Karpathy #2: minimum viable verification per phase. The full test culture is its own future project.

### Observability

Each phase adds one or two `logger.info()` lines for previously-invisible behaviors:

- Phase 2: cross-workspace 404s.
- Phase 3: condensation start/end/skip; per-tool timeout fires; cancellation propagation.
- Phase 4: duplicate-tool errors; tool-set resolution per request.
- Phase 5: optimistic→real migration; rollback fires.

Stdlib `logging` only. No metrics infrastructure (Prometheus, StatsD) in this work.

### Rollback playbook

- **Phase 1:** `alembic downgrade -1` per revision. Each is independently revertable.
- **Phases 2–6:** `git revert <merge-commit>` and redeploy. No data-shape changes after Phase 1 (Phase 4's `preferred_model` drop is the sole exception; restore via the down-migration).
- **Mid-phase rollback:** abandon the branch. Main is unaffected.

### PR cadence

- **Phase 1:** one PR per migration revision (five PRs) for independent revertability. Each PR's success criterion is its migration up/down + smoke probe.
- **Phases 2–5:** one PR per phase.
- **Phase 6:** one PR for the batch.

Total expected PR count: ~10.

### Branch naming

```
refactor/phase-1-schema-foundations   (this branch — spec lives here, then migrations)
refactor/phase-2-auth-boundaries
refactor/phase-3-async-ollama
refactor/phase-4-workspace-plumbing
refactor/phase-5-frontend-state
refactor/phase-6-cleanups
```

Each branch cut from main after the prior phase merges.

---

## Glossary

- **engine_config** — JSONB column on `workspaces` holding the inference backend choice and parameters. Today: `{"backend": "ollama", "model": "<name>"}`. Future: gains llama.cpp variants and sampling params when that swap lands.
- **workspace_id vs slug** — `id` is the stable UUID-string primary key (`Column(String, primary_key=True, default=generate_uuid)`), used for FKs and inter-service references. `slug` is the human-readable URL token, used only at the URL boundary and for display. Slugs may change; ids do not.
- **per_tool_config** — JSONB field on the resolved tool set, shape ships in Phase 4 but use is deferred. Future per-workspace tool *configuration* (e.g., "allow `check_port` to scan RFC1918 only in this workspace") will read from here.
- **Co-location** — moving Ollama-specific HTTP shape into `core/ollama.py` as a single module. Not an abstraction; just one place to find the code that talks to Ollama.
- **Optimistic ID** — a frontend placeholder UUID assigned to a new session before the backend creates and returns the real session id. Migrated atomically once the real id arrives in the first SSE chunk.

---

## Related memory

- [[project-workspace-roadmap]] — the workspace expansion plan this remediation precedes.
- [[project-llama-cpp-swap]] — the future backend swap this remediation prepares the seam for.
- [[feedback-foundations-over-shortcuts]] — the user preference informing this spec's "do it properly" shape.
- [[feedback-karpathy-for-subagents]] — implementation agents executing this plan get Karpathy guidelines in their brief.
- [[reference-debug-tools]] — the autotest + screenshot harnesses used as per-phase smoke probes.
