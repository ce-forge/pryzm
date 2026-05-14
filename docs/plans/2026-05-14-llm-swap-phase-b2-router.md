# Phase B2 — Router + Escalation + Capability Tags

## Context

Phase B1 (#13) put llama-swap in front of two Gemma 4 variants but hardcoded every chat to `gemma-4-E4B-it` (the larger model). That works correctness-wise but wastes the smaller model entirely — short prompts pay 4B-parameter latency for no reason, and we can't even tell how often the small model would have sufficed.

Phase B2 inserts a heuristic router in front of `llm_server.chat`. Two tiers. Short/simple prompts route to the small model; long, code-bearing, multi-turn, or complex-verb prompts route to the large model. If a small-tier run hits an obvious failure mode (max tool loops or a tool error), the request is re-issued once against the large model.

This is the foundation for Phase C's comparison work: only with per-request tier logged can we evaluate whether the router is paying off or just adding latency.

**Deviation from spec, per [[project-router-escalation-triggers]]:** The spec lists three escalation triggers (max-iterations, tool-error, short-response-no-tool). Drop the third — it false-positives whenever the user asks for a short answer. Ship with two.

## Scope

In:
- `core/llm_router.py` (new) — `HeuristicRouter` + tier picker + capability-tag catalog
- `core/llm_server.py` — add `DEFAULT_SMALL_CHAT_MODEL` constant; `chat()` signature unchanged (the `model` param stays; the router calls it)
- `core/ai_engine.py:stream_chat` — route at entry, plug the post-loop escalation block in
- `core/ai_engine.py:generate_title` — switch from `DEFAULT_CHAT_MODEL` (E4B) to `DEFAULT_SMALL_CHAT_MODEL` (E2B). Hardcoded, not routed: title output is always a 5-word string, so the router's complexity heuristics would over-promote long/code-fenced first messages to E4B for no benefit.
- `main.py` lifespan — build the catalog from `infra/llama-swap-config.yaml` once at startup, attach to app state
- `core/llm_metrics.py` — add `llm.route` and `llm.escalate` log lines matching existing `llm.metric` style
- Tests: unit tests on `_pick_tier`, one e2e probe asserting routing decisions hit the log

Out:
- `condense_chat_memory` (`ai_engine.py`) — stays pinned to `DEFAULT_CHAT_MODEL` (E4B). It summarizes >15 turns into a memory row; long input + comprehension load means the large model is correct here.
- Model picker UI (B3 owns that).
- Adding new capability tags beyond the existing `"embedding"`. The infrastructure parses tags generically; we just don't define new ones today.
- Re-escalation, fallback chains, or routing tunables exposed as config. Keep the heuristic thresholds hardcoded — surface them later if/when Phase C says they need to move.

## File-by-file changes

### `backend/core/llm_router.py` (new, ~80 lines)

```python
from enum import Enum
import logging
import yaml

_logger = logging.getLogger("pryzm.llm")

class Tier(Enum):
    SMALL = "small"
    LARGE = "large"

class HeuristicRouter:
    COMPLEX_VERBS = {
        "compare", "analyze", "plan", "design", "evaluate",
        "synthesize", "summarize", "write a", "implement", "debug",
    }

    def __init__(self, catalog: dict[str, set[str]]):
        # catalog: {model_id -> set of capability tags}
        self.catalog = catalog
        self._small, self._large = self._partition_chat_models()

    def _partition_chat_models(self) -> tuple[str, str]:
        chat_models = [m for m, tags in self.catalog.items() if "embedding" not in tags]
        # Convention: id contains size hint (E2B = small, E4B = large).
        # Pick smallest for SMALL tier, largest for LARGE tier.
        # If catalog ever has 3+ chat models, sort by inferred size and pick endpoints.
        small = next(m for m in chat_models if "E2B" in m or "1b" in m.lower())
        large = next(m for m in chat_models if "E4B" in m or "4b" in m.lower())
        return small, large

    def pick(self, prompt: str, history: list[dict], attachments: list[str]) -> tuple[str, Tier, str]:
        """Returns (model_id, tier, reason_keyword)."""
        tier, reason = self._pick_tier(prompt, history, attachments)
        model = self._large if tier is Tier.LARGE else self._small
        return model, tier, reason

    def _pick_tier(self, prompt, history, attachments) -> tuple[Tier, str]:
        if attachments:                       return Tier.LARGE, "attachments"
        if len(prompt) > 500:                 return Tier.LARGE, "prompt_len>500"
        if "```" in prompt:                   return Tier.LARGE, "code_fence"
        lower = prompt.lower()
        if any(v in lower for v in self.COMPLEX_VERBS):
            return Tier.LARGE, "complex_verb"
        if len(history) > 8:                  return Tier.LARGE, "history>8"
        return Tier.SMALL, "default"


def build_catalog_from_yaml(path: str) -> dict[str, set[str]]:
    with open(path) as f:
        cfg = yaml.safe_load(f)
    return {
        model_id: set(model_cfg.get("tags", []) or [])
        for model_id, model_cfg in cfg.get("models", {}).items()
    }
```

### `backend/main.py` — lifespan startup

Parse YAML once, attach `HeuristicRouter` to `app.state.router`. Use existing FastAPI startup pattern (lifespan or `@app.on_event("startup")` — whichever this codebase already uses; check before writing). Path: `infra/llama-swap-config.yaml`, resolved relative to repo root.

### `backend/core/ai_engine.py:stream_chat`

Two surgical insertions:

**1. At entry (~line 165, before the loop init):** route the prompt.
```python
router = request_app.state.router  # or wherever it's reachable
prompt_text = messages[-1].get("content", "") if messages else ""
attachments = []  # text-only today; future image messages will populate this
model, tier, route_reason = router.pick(prompt_text, messages[:-1], attachments)
_logger.info(
    "llm.route model=%s tier=%s reason=%s prompt_len=%d",
    model, tier.value, route_reason, len(prompt_text),
)
```
If the call site already received an explicit `tier` kwarg (set by an escalating re-entry — see below), skip routing and use the passed model.

**2. Replace the hardcoded `DEFAULT_CHAT_MODEL` at line 174–179** with the routed `model`.

**3. After the tool loop (~line 272, before the outer except):** escalation gate.
```python
escalation_triggered = (
    tier is Tier.SMALL
    and not escalated
    and (
        (loop_count >= max_loops and not finished_cleanly)  # max-iterations
        or had_tool_error                                    # tool-error
    )
)
if escalation_triggered:
    _logger.info(
        "llm.escalate from=%s to=%s reason=%s",
        model, router._large,
        "max_iterations" if loop_count >= max_loops else "tool_error",
    )
    async for chunk in stream_chat(messages, tier=Tier.LARGE, escalated=True):
        yield chunk
    return
```

**4. Track `had_tool_error`:** add `had_tool_error = False` next to `finished_cleanly` at line 166. Flip it to `True` in the existing tool-call except blocks at lines 218 (timeout) and 224 (exception). One line each.

### `backend/core/llm_server.py`

Two edits:
- Add `DEFAULT_SMALL_CHAT_MODEL = "gemma-4-E2B-it"` next to the existing `DEFAULT_CHAT_MODEL` (line 32). `generate_title` will import and use it.
- Remove the comments at lines 15–16 that flag "Phase B2's router will replace those references" — those are obsolete after this PR.

`chat()` signature is unchanged. `DEFAULT_CHAT_MODEL` stays as the fallback for `condense_chat_memory`.

### `backend/core/ai_engine.py:generate_title` (line 290)

One-line swap: `model=llm_server.DEFAULT_CHAT_MODEL` → `model=llm_server.DEFAULT_SMALL_CHAT_MODEL`. No routing call — title gen always wants the small model regardless of the user's first message.

### `backend/core/llm_metrics.py`

No structural change. The two new log lines (`llm.route`, `llm.escalate`) live in `ai_engine.py` and use the same `logging.getLogger("pryzm.llm")` pattern, so they flow through the existing observability path automatically.

## Test plan

Unit tests (new file `backend/tests/unit/test_llm_router.py`):
- One test per `_pick_tier` branch (attachments, len>500, code fence, complex verb, history>8, default) — each asserts the right `(Tier, reason)` tuple.
- `build_catalog_from_yaml`: load the real `infra/llama-swap-config.yaml`, assert `{"nomic-embed-text-v1.5"}` has `{"embedding"}` and that the two Gemma entries have empty tag sets.
- `HeuristicRouter._partition_chat_models`: round-trip with the real catalog → `small == "gemma-4-E2B-it"`, `large == "gemma-4-E4B-it"`.

Escalation unit test (in the same file): patch `stream_chat` internals so `loop_count` reaches `max_loops` with `finished_cleanly = False`, assert the recursive `stream_chat` call fires with `tier=Tier.LARGE, escalated=True`. No real LLM call.

E2E smoke (new test `backend/tests/e2e/test_phase_b2_smoke.py`):
- Send a short prompt ("what is 2+2?"), capture the log stream from the backend process, assert it contains `tier=small`.
- Send a prompt >500 chars (paste a paragraph in the test), assert `tier=large`.
- Both flows complete with a visible assistant bubble (reuse `_ASSISTANT_HAS_CONTENT` from the existing smoke suite).

Run with: `cd backend && ./venv/bin/pytest tests/unit/test_llm_router.py tests/e2e/test_phase_b2_smoke.py -v`.

## Logging

Two new lines, both via `logging.getLogger("pryzm.llm")`, % formatting to match `llm.metric`:

```
llm.route model=gemma-4-E2B-it tier=small reason=default prompt_len=42
llm.escalate from=gemma-4-E2B-it to=gemma-4-E4B-it reason=max_iterations
```

Phase C will grep these to evaluate routing accuracy alongside `llm.metric`.

## Risks & rollback

- **Mis-routed obvious-complex prompt** — escalation catches it. Cost: one wasted small-model invocation, not a wrong answer.
- **Escalation thrashes** — single-step only; `escalated=True` short-circuits the gate on re-entry.
- **YAML drift** — if `infra/llama-swap-config.yaml` changes and `_partition_chat_models` can't find a small/large match by name convention, it raises at startup. That's the right failure mode (loud, immediate) rather than silent mis-routing at request time.
- **Rollback** — revert this PR. `DEFAULT_CHAT_MODEL` is still in `llm_server.py`, so `chat()` calls without an explicit `model` keep working.

## Critical files to modify

- `backend/core/llm_router.py` — new
- `backend/main.py` — lifespan startup hook
- `backend/core/ai_engine.py` — lines 165–179 (route + use routed model), 272 (escalation gate), 218/224 (had_tool_error flag flips), 290 (generate_title swap to small model)
- `backend/core/llm_server.py` — add `DEFAULT_SMALL_CHAT_MODEL`, strip lines 15–16 comments
- `backend/tests/unit/test_llm_router.py` — new
- `backend/tests/e2e/test_phase_b2_smoke.py` — new

## Out of scope (explicit non-goals)

- Touching `condense_chat_memory` (stays on E4B; long-input summarization needs the larger model).
- Re-escalation, fallback chains, multi-step escalation.
- Configurable router thresholds, A/B switching, or a "force tier" flag.
- B3's Web UI for model management.
- Embedding-router or fine-tuned router (the `Router` Protocol exists per spec but only `HeuristicRouter` ships).
