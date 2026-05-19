# Reasoning Output Streaming

## Context

The on-demand chat tier today is `gemma-4-E4B-it` (Q4_K_M, ~5.4 GB resident). A probe of `gemma-4-26B-A4B-it` (Q4_K_M, 17 GB) with MoE expert offload to system RAM landed at 4.7 GB resident, 47–49 tok/s generation, 125–205 tok/s prompt-eval. That's a 6.5× larger model at lower VRAM cost and matching throughput. Quality of reasoning output is visibly stronger.

Two facts about the new model shape the work:

1. **Thinking-mode is on by default.** Output goes to `reasoning_content` rather than `content`. At a 1200-token budget on a Pryzm-shaped prompt, the model stayed in reasoning the entire time and `content` was empty. We're not going to disable thinking — the reasoning is exactly the part that makes this model worth running. The UI needs to surface it.

2. **The router self-tunes.** `HeuristicRouter._partition_chat_models()` parses chat models from the catalog and assigns the smallest as small-tier and the largest as large-tier by regex-extracting a size hint from each model id. Adding `gemma-4-26B-A4B-it` puts a `26B` size hint into the catalog; the router will auto-promote it. The existing E4B entry stays in the file but gets moved to the `inactive` group via the admin dashboard, which removes it from the router's catalog. No router code changes.

## Scope

In:
- New llama-swap catalog entry for `gemma-4-26B-A4B-it` in the on-demand group, with `-ot "\.ffn_.*_exps\.weight=CPU"` and explicit `-hff` filename (the bartowski repo does not expose the `:quant` metadata shortcut).
- Backend: read `reasoning_content` from the chat-completion response and fake-stream it as a new `{type: "reasoning_chunk"}` SSE event, alongside the existing word-by-word `content` stream.
- Frontend SSE hook: accumulate `reasoning_chunk` into a parallel per-message cache.
- Frontend UI: replace the existing `ProcessingAnimation` text "PROCESSING" with two interactive pill labels — `reflecting...` while the small model runs (default) and `focusing...` while reasoning_content is streaming from the large model. Keep the prism SVG animation untouched.
- Frontend UI: `ThinkingPanel` component renders the reasoning_content. Collapsed by default in every state. Live updates during streaming; frozen text after `done`.
- Backend unit test covering the `reasoning_chunk` emission path.
- Autotest probe verifying end-to-end that a 26B-A4B request produces `reasoning_chunk` events.

Out:
- Editing or removing the E4B entry. The user moves it to the `inactive` group via the admin dashboard after this work merges.
- Agentic router rewrite (small model gets an `escalate_to_larger_model` tool). Tracked separately; the existing two escalation triggers (max-iterations, tool-error) keep working with the new target.
- Admin HF-picker `-hff` fallback. Ships as its own chore PR ahead of this one; this plan does not touch `routers/admin.py`.
- Vision coexistence test. The probe already showed the math fits comfortably; first real multimodal use after merge is its own verification.

## File-by-file changes

### `infra/llama-swap-config.yaml`

New `models:` entry, added to the `on-demand` group's `members:` list:

```yaml
groups:
  "on-demand":
    swap: false
    exclusive: false
    members:
    - "gemma-4-E4B-it"
    - "gemma-4-26B-A4B-it"
    - "qwen2-vl-2B-it"

models:
  "gemma-4-26B-A4B-it":
    cmd: |-
      /app/llama-server --port ${PORT}
      -hf bartowski/google_gemma-4-26B-A4B-it-GGUF
      -hff google_gemma-4-26B-A4B-it-Q4_K_M.gguf
      -ngl 99 --ctx-size 32768 --jinja --flash-attn on
      --cache-type-k q8_0 --cache-type-v q8_0
      -ot "\.ffn_.*_exps\.weight=CPU"
    tags:
    - code
    groups:
    - on-demand
```

The expert-offload regex must use double backslashes inside YAML so the shell sees `\.ffn_.*_exps\.weight=CPU` verbatim. The `code` tag matches the existing E4B entry so any tag-based routing keeps working when the catalog flips over.

Reload after the edit: `docker compose kill -s HUP llama-swap`. Group `members:` is technically a group-definition change — if HUP doesn't pick it up, fall back to `docker compose restart llama-swap`.

### `backend/core/ai_engine.py`

After the existing content read at line 578, read `reasoning_content` and fake-stream it before the content stream. Mirror the existing word-split + small sleep so the cadence matches the rest of the output. Time the reasoning phase end-to-end so the finished panel can show a duration.

```python
content = message.get("content")
if content is None:
    content = ""

reasoning = (message.get("reasoning_content") or "").strip()
reasoning_duration_s: float | None = None
if reasoning:
    reasoning_start = time.perf_counter()
    words = reasoning.split(" ")
    for i, word in enumerate(words):
        if is_disconnected and await is_disconnected():
            return
        yield {"type": "reasoning_chunk", "chunk": word + (" " if i < len(words) - 1 else "")}
        await asyncio.sleep(0.01)
    reasoning_duration_s = round(time.perf_counter() - reasoning_start, 1)
    yield {"type": "reasoning_done", "duration_s": reasoning_duration_s}

content = _THINK_BLOCK_RE.sub('', content).strip()
# ... existing thought-stall + fallback logic unchanged ...
```

The duration is wall-clock fake-stream time, not the model's actual reasoning compute time (which is hidden inside the non-streaming `llm_server.chat` call). Wall-clock is what the user perceives, which is the right value to display. If the discrepancy ever matters, the real-compute time is available from `eval_duration` in the response and we can swap the source later.

Two notes on placement:

- Reasoning emits **before** content. That matches the model's order (thinking comes first) and gives the UI a clean phase progression: pill → optional panel expansion → final answer arrives.
- The `_THINK_BLOCK_RE.sub` on `content` is unrelated — that strips inline `<think>...</think>` tags that some other models emit inside their content string. It does not touch `reasoning_content` (which arrives in its own response field). Keep it as-is.

### `backend/tests/test_ai_engine_typed_events.py`

New test, modeled on the existing `test_tool_execution_yields_typed_events`. Mocks `llm_server.chat` to return a response with both `reasoning_content` and `content` set, and asserts the stream yields `{type: "reasoning_chunk"}` events covering the reasoning text before any `content` words appear.

```python
@pytest.mark.asyncio
async def test_reasoning_content_yields_reasoning_chunks(monkeypatch):
    """When the LLM returns reasoning_content, stream_chat yields it as
    {type: 'reasoning_chunk'} events before the content word stream."""

    async def fake_chat(*args, **kwargs):
        return {
            "message": {
                "role": "assistant",
                "content": "The answer is 42.",
                "reasoning_content": "Let me think about this carefully.",
            },
            "prompt_eval_count": 10,
            "eval_count": 8,
            "prompt_eval_duration": 100,
            "eval_duration": 200,
            "total_duration": 300,
        }

    monkeypatch.setattr("core.ai_engine.llm_server.chat", fake_chat)

    events = []
    async for item in stream_chat(
        client=None,
        messages=[{"role": "user", "content": "hi"}],
        workspace_id=None,
        engine_config=_minimal_engine_config(),
        tool_set=[],
        session_id="t1",
    ):
        events.append(item)

    reasoning_events = [e for e in events if isinstance(e, dict) and e.get("type") == "reasoning_chunk"]
    content_events = [e for e in events if isinstance(e, str)]

    assert reasoning_events, "expected reasoning_chunk events"
    assert "".join(e["chunk"] for e in reasoning_events).strip() == "Let me think about this carefully."
    assert "42" in "".join(content_events)
    # Order: all reasoning events fire before any content words.
    first_content_index = next(i for i, e in enumerate(events) if isinstance(e, str))
    last_reasoning_index = max(i for i, e in enumerate(events) if isinstance(e, dict) and e.get("type") == "reasoning_chunk")
    assert last_reasoning_index < first_content_index
```

If `_minimal_engine_config()` doesn't already exist as a helper in the test file, copy the shape used by `test_tool_execution_yields_typed_events` — same fixture, no new abstraction.

### `frontend/src/hooks/useInference.ts`

Add a `reasoning_chunk` branch alongside the existing `parsed.chunk` handler at line 252. Accumulate into a new state slot (`streamingReasoning`) keyed the same way as `streamingContent`, mirroring the optimistic-to-real id swap.

Concretely:

1. Add to the hook's state, parallel to `streamingContent`:

```typescript
const [streamingReasoning, setStreamingReasoning] = useState<Record<string, string>>({});
```

2. In the SSE consumer (after the existing `parsed.chunk` block):

```typescript
if (parsed.type === "reasoning_chunk" && parsed.chunk) {
  fullReasoning += parsed.chunk;
  setStreamingReasoning((prev) => {
    const next = { ...prev, [optimisticId]: fullReasoning };
    if (realDbId !== null) next[realDbId] = fullReasoning;
    return next;
  });
}
```

3. Declare `let fullReasoning = "";` next to the existing `fullAssistantMessage` declaration at the top of the stream loop.

4. Export `streamingReasoning` from the hook's return value alongside `streamingContent`.

5. In the id-migration block (around line 200), copy `streamingReasoning[optimisticId]` over to the new real id the same way `streamingContent` is migrated.

The reasoning text does **not** need to be persisted to the message cache after the stream ends — once `done` fires, the panel reads from the message row's saved `reasoning_content` field (see "Persistence" below). The in-hook state is a streaming-window concern only.

### Persistence: `backend/db/models.py` + Alembic migration

Messages need a place to keep the final reasoning text + its duration so reopening a chat shows the panel populated. Two nullable columns on `messages`:

```python
class Message(Base):
    # ... existing columns ...
    reasoning_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    reasoning_duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
```

Migration: new Alembic revision adding both columns with no default and no backfill. Existing messages keep `NULL`; the UI treats null/empty the same way and renders nothing.

In `routers/chat.py` (search for the existing `Message(role="assistant", ...)` insert at end-of-stream), capture the accumulated reasoning string and the `reasoning_done` duration_s, pass them to the row.

The persisted columns are also returned from `GET /sessions/{id}/messages` — the existing serializer dumps all column fields, so adding the SQLAlchemy columns gives the API fields for free.

### `frontend/src/components/ProcessingAnimation.tsx`

Make the label dynamic. The component currently hardcodes "Processing" with uppercase shimmer styling. Replace with a `label` prop, lowercase styling, and remove the uppercase tracking class.

```tsx
export default function ProcessingAnimation({ label = "reflecting…" }: { label?: string }) {
  return (
    <div className="flex items-center mt-4 mb-2 pl-4">
      <span
        className="text-[12px] tracking-wide mr-4"
        style={{
          background: 'linear-gradient(90deg, #4b5563 0%, #4b5563 40%, #ffffff 50%, #4b5563 60%, #4b5563 100%)',
          backgroundSize: '200% 100%',
          WebkitBackgroundClip: 'text',
          color: 'transparent',
          animation: 'textShimmer 5s infinite linear'
        }}
      >
        {label}
      </span>
      {/* style + svg unchanged */}
      ...
    </div>
  );
}
```

Changes: prop-driven label, dropped `font-semibold uppercase`, dropped `tracking-[0.2em]` (replaced with normal `tracking-wide` — the lowercase pill doesn't need wide letterspacing). The shimmer animation stays.

Three glyphs to remember when typing labels: lowercase ASCII, ellipsis is the U+2026 horizontal ellipsis character (`…`), not three dots.

### `frontend/src/components/ThinkingPanel.tsx` (new)

Renders the reasoning_content. Always collapsed on initial render; click the header to expand. While streaming, the live text updates inside whether expanded or not.

```tsx
import React, { useState } from "react";

interface ThinkingPanelProps {
  reasoning: string;
  durationSeconds?: number; // when known (post-stream), shown next to "Thinking"
  variant?: "live" | "finished"; // live = sits next to ProcessingAnimation pill; finished = sits above the message
}

export default function ThinkingPanel({ reasoning, durationSeconds, variant = "finished" }: ThinkingPanelProps) {
  const [open, setOpen] = useState(false);

  if (!reasoning) return null;

  return (
    <div className={variant === "live" ? "mt-2 pl-4" : "mt-1 mb-2 pl-1"}>
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-1.5 text-[11px] text-gray-500 hover:text-gray-300 transition-colors"
      >
        <span className={`inline-block transition-transform ${open ? 'rotate-90' : ''}`}>▸</span>
        <span>Thinking{durationSeconds != null ? ` (${durationSeconds}s)` : ""}</span>
      </button>
      {open && (
        <div className="mt-2 px-3 py-2 rounded-lg border border-[#333537] bg-[#1a1b1c] text-[12px] text-gray-400 leading-relaxed whitespace-pre-wrap">
          {reasoning}
        </div>
      )}
    </div>
  );
}
```

Two visual variants, same component:
- `variant="live"` — sits beside the running ProcessingAnimation pill while the model is still reasoning. The duration is unknown so the label reads just `Thinking`.
- `variant="finished"` — sits above the final assistant message, showing `Thinking (Ns)` once known.

### `frontend/src/components/ActiveSession.tsx`

Two integration points:

1. Pre-stream / mid-stream pill label. The render at line 214 (`<ProcessingAnimation />`) currently shows the default "reflecting…" label. When `streamingReasoning[currentId]` is non-empty (the large-tier model is mid-think), switch the label to `focusing…` and mount `ThinkingPanel` next to it.

```tsx
{currentIsProcessing && messages.length > 0 && !myStreamingText && (
  <>
    <ProcessingAnimation
      label={streamingReasoning[currentId] ? "focusing…" : "reflecting…"}
    />
    {streamingReasoning[currentId] && (
      <ThinkingPanel reasoning={streamingReasoning[currentId]} variant="live" />
    )}
  </>
)}
```

`currentId` is whichever id the streaming cache uses (real DB id once migrated, optimistic before). Reuse whatever the file already pulls — don't introduce a new lookup.

2. Pull `streamingReasoning` out of the `useInference` hook and pass it through to wherever messages are rendered (same plumbing as `streamingContent`).

### `frontend/src/components/ChatBubble.tsx`

Render the finished `ThinkingPanel` above the assistant message body, only on assistant turns where `reasoning` is non-empty. Insert at line 105 (before the `<div className="${...} break-words min-w-0">` that wraps the message content):

```tsx
{message.role === "assistant" && message.reasoning_content && (
  <ThinkingPanel
    reasoning={message.reasoning_content}
    durationSeconds={message.reasoning_duration_s}
    variant="finished"
  />
)}
```

Two new optional fields on the `message` prop shape: `reasoning_content?: string` and `reasoning_duration_s?: number`. Both come from the message row.

During the streaming window the panel renders from `streamingReasoning[currentId]` via the parent (ActiveSession), not from `message.reasoning_content` (which is empty until the row is finalized).

### `frontend/src/data/test_suite.json` (optional addition)

If the test_suite runner has an entry for the large-model escalation path, add a `reasoning_content` assertion. If not, skip — the autotest probe (below) is the load-bearing verification.

## Verification

Backend:

- `./venv/bin/pytest tests/test_ai_engine_typed_events.py -v` — green, including the new `test_reasoning_content_yields_reasoning_chunks`.
- `./venv/bin/pytest -q` — full sweep stays green.

Autotest probe (extend `/tmp/pryzm_autotest.py` or run inline):

- POST a chat completion to a workspace, prompt the model with a multi-step reasoning question, force `tier=large` if the runner supports it.
- Parse the NDJSON stream for `{"type": "reasoning_chunk"}` events. Expect at least one before the first `chunk` event.
- Assert the final persisted message row exposes `reasoning_content` non-null.

Manual UI:

- Send a long-form reasoning question. Confirm the prism animation shows with `reflecting…` initially, then switches to `focusing…` once reasoning_content begins streaming, with a clickable `▸ Thinking` pill alongside.
- Click the pill mid-stream. Panel expands; text continues to update live.
- After the message finishes, confirm the streaming pill is gone and a smaller `▸ Thinking (Ns)` pill sits above the answer. Click to expand; reasoning text is shown frozen.
- Reload the session. The finished pill is still there with the same content. Click to expand.
- Send a short query that routes to the small model. Confirm `reflecting…` shows, no thinking pill appears, no panel renders. The fallback path stays intact for models that don't emit reasoning_content.

## Rollout notes

- The catalog entry adds `gemma-4-26B-A4B-it` alongside E4B. Until the user marks E4B inactive via the admin dashboard, both are catalog members. The router picks `gemma-4-26B-A4B-it` as large-tier immediately because of the size-hint regex.
- First request to the new model triggers llama.cpp's mmap of 17 GB experts into system RAM — cold-load adds a few seconds. Subsequent requests are warm.
- 17 GB of the GGUF lives at `infra/llama_models/probe/google_gemma-4-26B-A4B-it-Q4_K_M.gguf` from the probe. After the catalog entry merges and llama-swap re-downloads through the standard cache path (`hub/models--bartowski--google_gemma-4-26B-A4B-it-GGUF/...`), the probe file is redundant and can be removed by hand.
- Branch: `feat/reasoning-output-streaming`. One PR. The branch name is deliberately model-agnostic — 26B-A4B is the first user of this infrastructure, not the only conceivable one.
