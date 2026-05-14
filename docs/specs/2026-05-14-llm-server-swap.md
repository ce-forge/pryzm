# LLM Server Swap — Design Spec

- **Date**: 2026-05-14
- **Status**: Draft, ready for review
- **Branch context**: spec authored on `main` after the codebase-remediation Phases 1–6 landed. Implementation cuts `refactor/llm-swap-*` branches off `main`.
- **Successor work**: this spec unblocks the planned **council workspace** (multi-agent cross-talk) and **image input** features. Both rely on the routing seam this spec ships.

## Context

Pryzm's inference backend is Ollama. Phase 3 of the codebase remediation co-located all Ollama-specific HTTP shape into `backend/core/ollama.py` as a single locus precisely so a future swap could happen surgically. Phase 4 added an `engine_config` JSONB column on `workspaces` to hold the per-workspace inference choice. That groundwork is now exercised: this spec swaps Ollama for raw `llama.cpp` (via `llama-swap`), removes per-workspace model selection in favor of automatic complexity-based routing, and adds the developer-facing model management UX that Ollama's `pull` command gave us "for free."

Three things motivate the swap:

1. **Performance headroom.** Ollama's defaults (n_gpu_layers, batch sizing, parallelism) tend to under-utilize the GPU for safety. Hand-tuned `llama-server` typically delivers 1.1–1.8x throughput on the same hardware. Anecdotal but consistent.
2. **Hot-swap between models.** `llama-swap` orchestrates multiple `llama-server` instances with on-demand load/unload and group-level "pin always-loaded" semantics. This is the seam the future *council workspace* (cross-talking agents, each potentially using a different model size) actually requires — Ollama's single-active-model scheduler is the wrong shape.
3. **Finer config knobs.** Per-model sampling parameters, jinja templates for tool-call formatting, KV cache quantization (`--cache-type-k/v`), flash attention. Ollama abstracts these; sometimes its defaults make tool-calling worse than what raw `llama.cpp` would do.

The user's preference is to hide model identity from the end user entirely. Workspaces stop pinning models. Instead, the system routes per-prompt: simple questions ("what's my IP?") to a small model, complex tasks (code, multi-step analysis, attached files) to a large one. The agentic loop escalates if the small model's first attempt fails. This pattern mirrors what production systems converged on (Anthropic's Haiku/Sonnet/Opus tiering, OpenAI's "auto" mode, the FrugalGPT cascade pattern).

### Explicitly out of scope

- **Image / vision input.** No upload UX changes; `/upload` stays text-only. The router's capability-tag system ships, but no vision model is added. Future image-input spec plugs in by tagging a model `[vision]` and updating the upload MIME filter.
- **Council workspace orchestration.** Multi-agent cross-talk is the next spec after this one. This spec ships the routing + multi-model loading that council needs but does not implement council itself.
- **Embedding-classifier router.** The `Router` interface accepts pluggable implementations. Only `HeuristicRouter` ships in v1. The classifier-based variant comes when we have logged routing decisions to learn from.
- **Audio / multimodal beyond images.** No foreseeable need.
- **Cloud / hosted-LLM support.** Pryzm stays 100% offline. The use of OpenAI-compatible wire format is purely about adopting the de facto local-inference standard (`llama-server`, vLLM, LM Studio all speak it); no API key path, no hosted backend.
- **3+ tier routing.** v1 ships exactly two tiers (small, large). Past 2 tiers, heuristic quality degrades and cascading latency compounds; jumping to 3+ tiers should coincide with the classifier-router upgrade, not happen incrementally.
- **Custom GGUF builds / quantization at install time.** Models are pulled as pre-built GGUFs from HuggingFace.

## Goals

1. Replace Ollama with `llama-swap`-orchestrated `llama-server` while preserving (or improving) every existing Pryzm behavior.
2. Capture an honest before/after performance comparison with logged metrics — not anecdote.
3. Hide model selection from the end user. Auto-route by complexity; escalate on failure. Workspaces own personality + tools + RAG corpus, not model identity.
4. Preserve the "Ollama-like ease of use" of adding a new model — via a Web UI that mutates the server config and reloads, plus first-request auto-download from HuggingFace.
5. Keep the routing layer pluggable so a future embedding-classifier or fine-tuned router slots in without architectural change.
6. Each phase is independently mergeable and revertable; main is never left in a half-coherent state.

## Sequencing Decision

Five phases. **Phase A ships the metrics baseline first** so Phase C's comparison has real numbers to chew on, not vibes. **Phase B is split into B1/B2/B3** because shipping container swap + router + Web UI as one PR is too big to review surgically — each piece is independently meaningful and revertable.

**Why metrics first, not last:** if we land the swap then add metrics, we never get the Ollama baseline. Order matters here.

**Why the router doesn't ship with the container swap:** B1's success criterion is "the app works end-to-end on llama-swap with a hardcoded default model." That's a coherent ship. Adding the router on top is its own focused change. Combining them means a regression in either bisects to the same PR.

**Why the Web UI is its own PR:** it's the largest single piece of frontend work in this project (forms, validation, SSE for download progress, YAML mutation logic). Bundling it with router or container swap inflates the PR review surface.

---

## Phase A — LLM Perf Metrics

**Goal:** Capture per-request performance metrics on the existing Ollama path so Phase C can do a credible before/after comparison. No behavior change to Pryzm's current functionality.

### What gets logged

A single `logger.info("llm.metric", extra={...})` line emitted at the end of each LLM streaming call in `core/ollama.py:chat_stream`:

```
fields = {
    "model": str,
    "prompt_tokens": int,        # from Ollama's final chunk: prompt_eval_count
    "completion_tokens": int,    # from Ollama's final chunk: eval_count
    "ttft_ms": int,              # time from request start to first content chunk
    "duration_ms": int,          # total wall-clock from request start to last byte
    "tokens_per_sec": float,     # completion_tokens / (duration_ms - ttft_ms) * 1000
    "workspace_id": str,
    "session_id": str,
}
```

Embedding calls get a parallel but simpler line: `model, char_count, duration_ms`.

### Benchmark harness

`backend/tests/perf/bench_llm.py` — a CLI script that:

1. Reads `PRYZM_API_TOKEN` from `.env`.
2. Sends a fixed prompt set against a running backend (5 prompts: short Q, medium Q, code task, tool-use trigger, RAG-with-attachment).
3. Each prompt is sent N times (default N=3).
4. Tails the backend log for `llm.metric` entries it produced.
5. Aggregates: count, min/median/p95/max for `ttft_ms`, `duration_ms`, `tokens_per_sec` per prompt class.
6. Prints a markdown table to stdout. Optionally writes to `backend/tests/perf/results/<timestamp>-<backend>.md`.

### What is NOT in Phase A

- No persistence (no DB table)
- No `/api/metrics` endpoint
- No frontend UI surfacing metrics
- No histograms, no Prometheus exposition

These are explicit YAGNI. The single use case here is "capture two snapshots, compare." If continuous visibility becomes valuable later, the log lines are already structured — a Loki-style aggregator can be added without code changes.

### Success criterion

- `bench_llm.py` runs cleanly against the current Ollama-backed stack and produces a markdown table with non-zero TPS for all five prompt classes.
- The same script will be re-run unchanged on the llama-swap stack in Phase C.

### Risks

None substantive. Metrics layer is additive; no behavior change.

### Dependencies

None.

---

## Phase B1 — llama-swap Container + OpenAI-Compatible Backend

**Goal:** Replace Ollama with `llama-swap` end-to-end. Same Pryzm behavior, new inference path. Hardcoded default model used for everything (no router yet).

### Docker compose

Drop the `ollama` service from `docker-compose.yml`. Add:

```yaml
llama-swap:
  image: ghcr.io/mostlygeek/llama-swap:cuda
  container_name: pryzm_llama_swap
  ports:
    - "127.0.0.1:8080:8080"
  volumes:
    - ./infra/llama-swap-config.yaml:/app/config.yaml:ro
    - llama_models:/root/.cache/llama.cpp
  deploy:
    resources:
      reservations:
        devices:
          - capabilities: [gpu]
  restart: unless-stopped

volumes:
  llama_models:
```

The named volume persists downloaded GGUFs across container restarts.

### `infra/llama-swap-config.yaml`

Ships with three model definitions (subject to user confirmation of the Gemma equivalents at implementation time):

```yaml
healthCheckTimeout: 3600   # allow first-request HuggingFace downloads to finish

groups:
  "chat":
    swap: true             # one chat model loaded at a time (VRAM budget)
    exclusive: false       # don't unload always-on group
  "always-on":
    swap: false
    exclusive: false
    persistent: true

models:
  "gemma-3-1b-it":         # tier-1 default (small)
    cmd: >
      /app/llama-server --port ${PORT}
      -hf bartowski/gemma-3-1b-it-GGUF:Q4_K_M
      -ngl 99 --ctx-size 8192 --jinja --flash-attn
      --cache-type-k q8_0 --cache-type-v q8_0
    groups: ["chat"]
    tags: []               # capability tags (vision, code, etc.); empty = text-only general

  "gemma-3-4b-it":         # tier-2 default (larger; placeholder for "gemma4:e4b" equivalent)
    cmd: >
      /app/llama-server --port ${PORT}
      -hf bartowski/gemma-3-4b-it-GGUF:Q4_K_M
      -ngl 99 --ctx-size 8192 --jinja --flash-attn
      --cache-type-k q8_0 --cache-type-v q8_0
    groups: ["chat"]
    tags: []

  "nomic-embed-text-v1.5": # embedding model; pinned always-on so RAG never pays swap cost
    cmd: >
      /app/llama-server --port ${PORT}
      -hf nomic-ai/nomic-embed-text-v1.5-GGUF:Q8_0
      -ngl 99 --embeddings --batch-size 8192
      --rope-scaling yarn --rope-freq-scale 0.75
    groups: ["always-on"]
    tags: ["embedding"]
```

The exact Gemma model identifiers (and the resolution of `gemma4:e4b` to its HuggingFace equivalent) is a small piece of pre-work in B1's implementation plan. The user confirmed Gemma family as the default; specific HF repos pinned at plan-write time.

### Backend refactor

Rename `backend/core/ollama.py` → `backend/core/llm_server.py`. Same three exported functions, OpenAI-compatible wire format. The Phase A metric extraction logic moves with the file and updates its field names: `prompt_eval_count` → `usage.prompt_tokens`, `eval_count` → `usage.completion_tokens`. The `bench_llm.py` script is unchanged; only the metric-emitter source field names differ.

| Old (Ollama) | New (OpenAI-compatible via llama-swap) |
|---|---|
| `POST /api/chat` (NDJSON stream) | `POST /v1/chat/completions {stream: true}` (SSE: `data: {...}\n\n`) |
| `POST /api/embeddings` | `POST /v1/embeddings` |
| `GET /api/tags` | `GET /v1/models` |

Tool-call shape is functionally identical — minor field path renames (`message.tool_calls` is the same; the response wrapper differs).

### `EngineConfig` migration

A single Alembic revision drops the `model` field from `workspaces.engine_config` JSONB:

```sql
UPDATE workspaces SET engine_config = engine_config - 'model';
```

Down-migration restores `engine_config.model = 'gemma4:e4b'` for builtin workspaces, NULL for user-created. The Pydantic model `EngineConfig` (Phase 4's `backend/core/engine_config.py`) drops the `model: str` field; `backend` becomes the only required field. The column itself stays — it's still the right home for future per-workspace overrides if a council member needs to force a specific model.

### Frontend changes

- `WorkspaceSettings.tsx` drops the "Preferred model" select entirely. Workspaces no longer expose a model picker.
- The model list state (`installedModels`) and the `/api/models` fetch removed from `WorkspaceSettings.tsx` (it was only feeding the select).
- Header `ChatHeader.tsx` displays a workspace badge only — no model name (since model is dynamic per-prompt now).

### `.env`

- `OLLAMA_URL` removed. Add `LLM_SERVER_URL`, default `http://llama-swap:8080`.
- `.env.example` updated. The old name is removed immediately; no compat shim (per Karpathy #2 — single-source-of-truth, no straddle period).

### Tests

- Unit tests in `backend/tests/` that mocked Ollama HTTP need their fixtures updated to OpenAI-compatible response shapes. Mechanical refactor.
- Phase 2/3/4/5/6 e2e tests should pass unchanged — they exercise the full stack and don't care which backend serves inference.
- A new unit test `backend/tests/test_llm_server.py` covers the OpenAI-compat wire format parsing (SSE framing, tool_calls extraction, usage block).

### Success criterion

- `docker compose up -d` with no `ollama` reference succeeds.
- A single chat message in either builtin workspace round-trips end-to-end against `llama-swap`.
- `bench_llm.py` runs against the new stack and produces non-zero TPS.
- All Phase 2–6 e2e tests pass.

### Risks

- **Cold first-request latency.** First time a model is hit, `llama-server` downloads its GGUF from HuggingFace (5s for 1B, ~30s for 4B, minutes for 27B+). The `healthCheckTimeout: 3600` setting accommodates this. The user-facing experience on first run will be a slow first prompt; subsequent prompts use the cached GGUF and are instant.
- **VRAM budget.** With both tier-1 and tier-2 models in `swap: true`, swapping between them costs the model load time on each alternation. For users with VRAM headroom, manually moving them to `swap: false` is one YAML edit. Documented.
- **Tool-calling format edge cases.** Some models implement OpenAI tool-calling worse than Ollama's wrapped version. Discovered in Phase C; mitigated by pinning known-good models in the defaults.

### Dependencies

Phase A (so Phase C has the baseline to compare against; B1 itself does not require A to ship, but the order matters for the comparison).

---

## Phase B2 — Router + Escalation + Capability Tags

**Goal:** Replace the hardcoded default model from B1 with automatic per-prompt routing. Two tiers, heuristic-based intake, single-step escalation on failure. Capability-tag system in place but unused (until image-input or other future capabilities ship).

### `core/llm_router.py`

```python
from enum import Enum
from typing import Protocol

class Tier(Enum):
    SMALL = "small"
    LARGE = "large"

class Router(Protocol):
    def pick_model(
        self,
        prompt: str,
        history: list[dict],
        attachments: list[str],
    ) -> str: ...
    """Returns a llama-swap model id (e.g. 'gemma-3-1b-it')."""

class HeuristicRouter:
    """v1. Coarse but predictable. Pluggable interface lets us drop in
    EmbeddingRouter or a fine-tuned router later without touching call sites."""

    COMPLEX_VERBS = {
        "compare", "analyze", "plan", "design", "evaluate",
        "synthesize", "summarize", "write a", "implement", "debug",
    }

    def __init__(self, model_catalog: dict[str, set[str]]):
        # model_catalog: {model_id -> set of capability tags}
        self.catalog = model_catalog

    def pick_model(self, prompt, history, attachments):
        needed_caps: set[str] = set()
        # (image attachments would set needed_caps.add("vision") here in the
        # future. Today, attachments are text-only and add no capability req.)

        candidates = [
            m for m, tags in self.catalog.items()
            if needed_caps.issubset(tags) and "embedding" not in tags
        ]

        tier = self._pick_tier(prompt, history, attachments)
        return self._select_for_tier(candidates, tier)

    def _pick_tier(self, prompt, history, attachments):
        if attachments: return Tier.LARGE
        if len(prompt) > 500: return Tier.LARGE
        if "```" in prompt: return Tier.LARGE
        lower = prompt.lower()
        if any(kw in lower for kw in self.COMPLEX_VERBS):
            return Tier.LARGE
        if len(history) > 8: return Tier.LARGE
        return Tier.SMALL

    def _select_for_tier(self, candidates, tier):
        # Convention: model id contains size hint ("1b", "4b", etc.).
        # Picks the smallest for SMALL, largest for LARGE among candidates.
        # Concrete impl details land in the implementation plan.
        ...
```

### Escalation in the agentic loop

In `backend/core/ai_engine.py:stream_chat`, after the existing tool loop completes, evaluate whether the result warrants escalation:

```python
ESCALATION_TRIGGERS = (
    "loop hit max iterations",
    "tool returned an error envelope",
    "response < 30 chars and no tool was called",
)

if (
    selected_tier == Tier.SMALL
    and not already_escalated
    and any_trigger_fired
):
    logger.info("llm.escalate", extra={"from": "small", "to": "large", "reason": ...})
    yield from stream_chat(messages, tier=Tier.LARGE, escalated=True)
```

Single-step only. No cascading (escalation does not re-escalate). The bound is one extra full-prompt invocation per request.

### Capability tags

The `tags: []` field in `infra/llama-swap-config.yaml` is parsed by the backend on startup and exposed to the router via the catalog. Today only `["embedding"]` is meaningful (used to exclude embedding models from chat candidates). Future tags (`vision`, `code`, etc.) plug in without router code changes.

### Logging

Each chat request logs:

```
llm.route model=gemma-3-1b-it tier=small reason=heuristic prompt_len=42
```

If escalation fires:

```
llm.escalate from=gemma-3-1b-it to=gemma-3-4b-it reason=max_iterations_hit
```

These feed the same observability path as Phase A's `llm.metric` — we'll grep them in Phase C to evaluate routing accuracy.

### Success criterion

- A short-prompt smoke ("what is 2+2?") routes to `gemma-3-1b-it`, logs `tier=small`.
- A long-prompt smoke (>500 chars) or one containing a code fence routes to `gemma-3-4b-it`, logs `tier=large`.
- A small-tier request that hits `MAXIMUM_TOOL_LOOPS` logs an `llm.escalate` and the user sees the final answer (from the large model). Verified in a unit test that mocks the loop hitting max iterations.

### Risks

- **Heuristic mis-routes obvious-complex prompts.** Mitigation: escalation catches it. The cost is one wasted small-model invocation, not a wrong answer.
- **Escalation thrashes on certain prompts.** Mitigation: single-step only; escalated requests cannot re-escalate.

### Dependencies

Phase B1 (the model catalog and llama-swap interface).

---

## Phase B3 — Web UI for Model Management

**Goal:** Replace "edit YAML by hand" with a Settings panel. Adds a model in 3 clicks. First-request HuggingFace download surfaces progress in the UI.

### Backend admin endpoints

All gated by the existing bearer token:

- `GET /api/admin/models` — returns the parsed list of models from `infra/llama-swap-config.yaml`: `[{id, repo, quant, ngl, ctx_size, group, tags, loaded, downloaded}]`. The `loaded` and `downloaded` flags come from probing llama-swap's `/upstream/<model>/health` endpoint and checking the cache volume for the GGUF file.
- `POST /api/admin/models` — body `{id, repo, quant, ngl, ctx_size, group, tags}`. Appends to the YAML using `ruamel.yaml` (preserves comments + ordering), then sends `SIGHUP` to the llama-swap container via `os.kill` (if same-host) or `docker compose kill -s HUP llama-swap`. Returns the new model entry.
- `DELETE /api/admin/models/{id}` — removes the entry from YAML, sends SIGHUP. Does NOT delete the cached GGUF (manual cleanup of the Docker volume).
- `GET /api/admin/models/{id}/status` — SSE stream emitting download progress. Backend tails the llama-swap log for download events from `llama-server` and forwards. Closes when model is loaded or fails.

### Frontend

A new "Models" section in the existing Settings panel (`Settings.tsx`):

- **Installed models list.** Each row: id, repo, quant, group badge, tags. Status indicator: ⬤ loaded / ⊙ downloaded but not loaded / ◌ not downloaded yet. Delete button per row, with standard confirmation. The delete button is *hidden* for the embedding model only (deleting it would break RAG silently); the two default chat models can be removed via the UI but the confirmation surfaces "This is a default model — the app falls back to the other tier if removed." (Devs may legitimately want to swap defaults to a different model.)
- **"Add model" button** opens a form modal:
  - **Name** (free-form, validated as a unique YAML key)
  - **HuggingFace repo:quant** (e.g., `bartowski/Qwen2.5-Coder-7B-Instruct-GGUF:Q4_K_M`)
  - **GPU layers** (default 99, "all on GPU")
  - **Context size** (default 8192)
  - **Group** (dropdown: `chat`, `always-on`)
  - **Tags** (multi-select chips from a known set: `embedding`, `vision`, `code`)
  - **Submit** → POST `/api/admin/models` → poll/SSE the status endpoint → show download progress → confirm.
- **First-request download progress.** When the user sends a prompt that targets a model that isn't downloaded yet, the chat UI shows "Downloading <model> from HuggingFace…" inline with a progress bar (sourced from `/api/admin/models/{id}/status` SSE).

### Out of scope for B3

- Editing existing models in the UI. Edits remain manual YAML changes (rare operation; not worth the form complexity).
- Deleting cached GGUFs from the volume. Manual operation.
- Authentication beyond the existing bearer token. The admin endpoints don't get a separate role; one token does everything (matches Phase 2's "single shared bearer" model).

### Success criterion

- From the Settings UI, a dev adds `bartowski/Qwen2.5-Coder-7B-Instruct-GGUF:Q4_K_M` as `qwen-coder-7b`, sees it appear in the list within 1s, sees download progress when first prompt routes to it.
- Removing a model removes the entry from YAML and the model is no longer in `/v1/models`.
- Refreshing the page preserves the list (state is the YAML, not in-memory).

### Risks

- **Concurrent YAML mutations.** Two devs hitting the endpoint simultaneously could race. Mitigation: an `asyncio.Lock` around the YAML read-modify-write + reload sequence. Acceptable for single-tenant scope.
- **SIGHUP handling assumptions.** llama-swap's reload behavior is well-documented but version-dependent. We pin a specific image tag (e.g., `ghcr.io/mostlygeek/llama-swap:cuda-v0.x.y`) at implementation time and bump deliberately.

### Dependencies

Phase B1 (the YAML to mutate). B2 is not strictly required, but in practice these ship in order.

---

## Phase C — Comparison & Tune

**Goal:** Run the same benchmark from Phase A against the new stack. Document the delta. Tune llama-swap per-model flags based on findings.

### Process

1. Run `bench_llm.py` against the running llama-swap stack with the same prompt set.
2. Compare against the Phase A baseline file. Compute deltas: TPS, TTFT, duration.
3. Write `docs/specs/2026-MM-DD-llm-perf-comparison.md`:
   - Markdown table side-by-side
   - Brief narrative: where llama-swap won, where it didn't, why
   - Tuning recommendations
4. Apply the tuning recommendations to `infra/llama-swap-config.yaml`:
   - Adjust `-ngl` if VRAM permits more layers on GPU
   - Tune `--ctx-size` per model (smaller = faster + less VRAM)
   - Add `--cache-type-k q4_0 --cache-type-v q4_0` for memory pressure (trade quality for VRAM)
   - Consider `--parallel N` if concurrent users surface
5. Re-run the benchmark, append updated numbers to the comparison doc.

### What this phase does NOT do

- It does NOT introduce new models (B3's UI handles that).
- It does NOT change the router (B2 owns that).
- It does NOT add a metrics dashboard (Phase A's logs are sufficient for the comparison).

### Success criterion

- Comparison doc committed.
- llama-swap config tuned at least once based on numbers.
- No regression on any Phase 2–6 e2e test.

### Risks

- **The comparison shows llama-swap is slower on some workloads.** Then we know: it's the model defaults that matter most, not the wrapper. Tune. If still slower in some case, document and accept (you've gained the hot-swap + UX wins regardless).

### Dependencies

Phase A (baseline), Phase B1 (the new stack), Phase B2 (router; routing decisions affect the per-prompt model picked, which affects the numbers).

---

## Cross-Cutting Concerns

### Testing strategy

Same per-phase pattern as the codebase remediation:

- Phase A: a single pytest unit for the metric extraction logic, plus the bench script's own self-test (`--dry-run` mode).
- Phase B1: unit tests for the OpenAI wire format parser; existing e2e suite runs unchanged against the new stack.
- Phase B2: unit tests for `HeuristicRouter._pick_tier` covering each branch; one e2e probe that asserts a long prompt is routed to the larger model (assertable via a logger spy or by reading the `llm.route` log line).
- Phase B3: an e2e probe that adds a model via the UI, verifies it appears in `/v1/models`, deletes it, verifies it's gone.
- Phase C: comparison run is the test. No new code under test.

The Playwright e2e harness at `backend/tests/e2e/` continues to be the home for UI smoke probes.

### Observability

Each phase adds one or two logger lines:

- Phase A: `llm.metric` (per request)
- Phase B2: `llm.route` (which tier picked + why), `llm.escalate` (when the loop fires escalation)
- Phase B3: `model.add` and `model.remove` (admin endpoint actions)

Stdlib `logging` only. No metrics infrastructure.

### Rollback playbook

- **Phase A:** revert PR. No data shape changes.
- **Phase B1:** revert PR + restore Ollama service in `docker-compose.yml`. The Alembic migration's down-revision restores `engine_config.model = 'gemma4:e4b'` for builtins. Pulled GGUFs in the named volume can stay (cheap, ignored if Ollama is back).
- **Phase B2:** revert PR. Backend reverts to hardcoded default model from B1.
- **Phase B3:** revert PR. Manual YAML editing is the fallback (it's how we'd been operating anyway).
- **Phase C:** docs-only; revert PR.

### PR cadence

- Phase A: 1 PR
- Phase B1: 1 PR
- Phase B2: 1 PR
- Phase B3: 1 PR
- Phase C: 1 PR

Total: 5 PRs.

### Branch naming

```
refactor/llm-swap-phase-a-metrics
refactor/llm-swap-phase-b1-container
refactor/llm-swap-phase-b2-router
refactor/llm-swap-phase-b3-admin-ui
refactor/llm-swap-phase-c-tune
```

Each branch cut from `main` after the prior phase merges.

---

## Glossary

- **llama-swap** — a thin Go proxy in front of `llama-server` (the OpenAI-compatible HTTP server shipped by `llama.cpp`). Manages multiple `llama-server` instances, routing requests to the right one and handling on-demand load/unload. Adds zero inference overhead.
- **OpenAI-compatible** — refers to the JSON wire format (endpoint paths, request/response schemas, SSE framing) standardized by OpenAI's API and adopted by virtually all local-inference servers. Has nothing to do with hosted OpenAI services. Pryzm remains 100% offline.
- **Tier** — a routing classification (SMALL / LARGE in v1) used to pick which model to serve a request. Independent of model identity (the model catalog can have many models; the router picks among them per tier).
- **Capability tag** — a string like `vision`, `embedding`, `code` attached to a model in YAML. Used by the router to filter candidate models by what they can do, separately from tier.
- **Escalation** — single-step retry of a request with the next-larger tier when the small-tier attempt failed (max iterations hit, low-quality output, etc.). Bounded to one escalation per request.
- **HuggingFace pull** — `llama-server` accepts `-hf <repo>:<quant>` and downloads the GGUF from the Hugging Face Hub on first use. Cached in the `llama_models` Docker volume forever after.

---

## Related memory

- [[project-llama-cpp-swap]] — the original placeholder note for this swap; this spec executes on it.
- [[project-workspace-roadmap]] — the workspace expansion that depends on the routing seam this spec ships.
- [[feedback-foundations-over-shortcuts]] — informs the choice to ship the pluggable router interface even though v1 only has one impl.
- [[feedback-karpathy-for-subagents]] — implementation agents executing this plan get Karpathy guidelines in their brief.
- [[reference-stack-commands]] — `--reload-delay 2.0` flag for the dev backend (hardware-comfort setting).
- [[reference-debug-tools]] — autotest + screenshot harnesses used as per-phase smoke probes.
