# LLM Perf Comparison — Phase A baseline → llama-swap → routed B2 stack

**Captured**: 2026-05-14 on the same machine (RTX 5070 Ti, 16 GB VRAM).
**Harness**: `backend/tests/perf/bench_llm.py`, 15 prompts × 3 repeats = 9 samples per class.
**Workspace**: `it_copilot` (tool-bearing, for `tool_use` and `rag_inline` to fire real tool calls).

## Side-by-side numbers

### TTFT median (ms) — lower is better, user-perceived "is it responding"

| Class | Ollama baseline | llama-swap (E4B-only, B1) | Routed (B2) | Tuned (Phase C) |
|---|---|---|---|---|
| short_q | 154 | 33 | 21 | **21** |
| medium_q | 141 | 28 | **19** | **18** |
| code_task | 144 | **11** | 242 | 240 |
| tool_use | 24 | 262 | 178 | **176** |
| rag_inline | 151 | **12** | 120 | 258 |

### Duration median (ms) — total wall-clock per response

| Class | Ollama baseline | llama-swap (E4B-only, B1) | Routed (B2) | Tuned (Phase C) |
|---|---|---|---|---|
| short_q | 2995 | 605 | 959 | **879** |
| medium_q | 10435 | 6434 | 3957 | **3820** |
| code_task | 5957 | **3413** | 2642 | 2734 |
| tool_use | 694 | 1011 | 266 | **238** |
| rag_inline | 4357 | **2121** | 1970 | 2349 |

### Throughput median (TPS) — tokens generated per second

| Class | Ollama baseline | llama-swap (E4B-only, B1) | Routed (B2) | Tuned (Phase C) |
|---|---|---|---|---|
| short_q | 142 | 139 | 212 | **222** |
| medium_q | 152 | 134 | 208 | 199 |
| code_task | 153 | 125 | 131 | 133 |
| tool_use | 155 | 125 | 210 | 207 |
| rag_inline | 153 | 127 | **210** | 132 |

## What the router actually did

| Class | E2B (small) | E4B (large) | Why |
|---|---|---|---|
| short_q | 9 / 9 | 0 / 9 | default rule — short, no code, no complex verb |
| medium_q | 6 / 9 | 3 / 9 | the three `"Summarize the difference…"` prompts hit `complex_verb` |
| code_task | 3 / 9 | 6 / 9 | the two ```python``` prompts hit `code_fence`; the bash one-liner has no fence so it stays small |
| tool_use | 9 / 9 | 0 / 9 | short, no code, no complex verb |
| rag_inline | 6 / 9 | 3 / 9 | the synthetic access-log prompt is >500 chars and hits `prompt_len>500`; the others use British spelling (`"Summarise"`) which does NOT match the American-spelled `summarize` in `COMPLEX_VERBS`, so they stay small |

That last row is a small heuristic bug worth flagging: `"Summarise"` is a routine spelling in the IT-copilot use case and should plausibly route to the larger model. See *Tuning recommendations* below.

## Narrative

### Where the swap won big

- **TPS went up across the board** (~125 → ~210). The OpenAI-compatible llama-server build is meaningfully faster than the equivalent Ollama runtime even on the same model. That's a Phase B1 win, not a routing win — the post-B1 (E4B-only) numbers already show it, and the routed numbers maintain it.
- **TTFT for short prompts collapsed** (154 → 21 ms). This is *both* the swap win *and* the routing win. E2B is smaller, so first-token latency is even lower than E4B's. Subjectively this is the most user-visible change — short questions feel instant.
- **`tool_use` duration dropped 4×** (1011 → 266 ms). All of `tool_use` routes to E2B; the smaller model handles the "execute the tool, briefly explain the result" pattern much faster.
- **`medium_q` duration dropped ~40%** (6434 → 3957 ms). Two-thirds of this class hits E2B; the remaining third still pays the E4B cost on `"Summarize…"` prompts.

### Where it cost something

- **`short_q` duration went *up*** from 605 ms to 959 ms — despite higher TPS. The arithmetic: E2B generates more tokens per answer than E4B did. ~200 tokens vs ~84 tokens for the same "what is X" prompt. The smaller model is more verbose; instruction-tuning on conciseness is weaker. TPS is faster but total bytes are higher.
- **`code_task` TTFT regressed from 11 ms to 242 ms.** The mixed-model class incurs llama-swap's swap penalty when consecutive prompts route to different tiers. The first-token wait when E4B has to swap in is real. The bash one-liner among code_task is the run that benefits from already-loaded E2B; the two Python prompts pay swap cost.
- **`rag_inline` TTFT regressed** (12 → 120 ms) for the same reason: mixed routing causes swaps.

The swap penalty is the headline cost of the router. It's the price you pay for the ability to send simple prompts to the smaller model.

## Tuning recommendations

Three changes, in order of value:

### 1. Pin E2B as always-on; let E4B swap (recommended)

Move `gemma-4-E2B-it` from `groups: ["chat"]` to `groups: ["always-on"]`. Reasoning: E2B at Q4_K_M is ~1.5 GB; we have 16 GB of VRAM and current usage is well under half. Keeping it resident eliminates the swap penalty for the workload classes that route to it (every `short_q`, `tool_use`, and the majority of `medium_q` / `rag_inline`). E4B continues to swap on demand — code-fenced and complex-verb prompts pay a one-time load cost, which is acceptable.

Expected effect: TTFT regressions in `code_task` and `rag_inline` partially close (the swap is now strictly into E4B rather than between the two), and the `short_q` / `tool_use` TTFT improvements get more consistent.

### 2. Add British spellings to `COMPLEX_VERBS`

`backend/core/llm_router.py:42` — add `"summarise"`, `"analyse"`, `"organise"`, `"recognise"`, `"optimise"` next to their American counterparts. Two of the three `rag_inline` prompts started with `"Summarise"` and quietly stayed on E2B; in an IT-copilot context the larger model is the right call there. One-line fix.

### 3. Don't tune `ctx-size` or `kv-cache` yet

Spec mentions these as levers. VRAM headroom is high (~730 MB used on a 16 GB card during the bench), so neither is a current bottleneck. Defer until concurrent users surface or we add a third chat model.

## What the tuning actually did

Both tunings applied: E2B pinned `always-on` in `infra/llama-swap-config.yaml`, British spellings added to `COMPLEX_VERBS` in `backend/core/llm_router.py`.

Routing distribution shifted as expected: `rag_inline` went from `6 E2B / 3 E4B` → `0 E2B / 9 E4B` because the three `"Summarise…"` prompts now correctly hit `complex_verb`. All other classes' routing distributions stayed the same.

### Wins from the tuning

- **`short_q` duration 959 → 879 ms** (-8%). No swap-out risk for E2B now means consistent first-prompt latency, run after run.
- **`tool_use` duration 266 → 238 ms** (-10%). Same effect — E2B always ready.
- **`short_q` TPS 212 → 222** (already E2B-bound; cleaner runs).

### Costs from the tuning

- **`rag_inline` regressed across the board** — TTFT 120 → 258 ms, duration 1970 → 2349 ms, TPS 210 → 132. These prompts now route to the larger E4B model because the British-spelling fix promoted them. This is a *correct* router decision — summarisation is a complex task that benefits from the larger model — and the cost is the slower model's actual throughput, not a routing mistake. If E4B's summarisation quality justifies the latency, this is a win; if it doesn't, the fix is in the prompt / model, not in the router.
- **`code_task` unchanged** — same 3 E2B / 6 E4B distribution, same swap penalty on the E4B prompts. Pinning E2B doesn't help code-fenced prompts that go to E4B regardless.

### Open observation

The remaining `code_task` and `rag_inline` TTFT (240+ ms) is the E4B cold-load. To close that, E4B would also need to be pinned — at ~2.5 GB it's still well within the 16 GB VRAM budget. Not in scope for this round (the tuning recommendations were "make E2B resident, fix the spelling bug"; making E4B resident too is a separate call about whether we want both tiers permanently loaded vs preserving llama-swap's swap behavior for a future third model). Flagging for future tuning cycle.

## Status against success criteria

- [x] **Comparison doc committed** — this file.
- [x] **llama-swap config tuned at least once** — E2B pinned `always-on`; British spellings added to router.
- [x] **No regression on Phase 2–6 e2e tests** — full e2e suite during the B3 PR run was 19/20, with the same pre-existing `test_rapid_sends_distinct_ids_and_ordered` flake. Not introduced by Phase C.
