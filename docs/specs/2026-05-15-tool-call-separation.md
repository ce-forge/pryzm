# Tool-call separation — design spec

**Status:** Brainstorm complete, awaiting implementation plan.
**Filed:** 2026-05-15
**Tracks:** root-cause fix for the LLM-mimicry issue surfaced after the tool-directive refactor (PR #72)
**Related:** the temporary `_strip_tool_mimicry` band-aid (commit `60a4a42`) is removed by this work.

## Problem

Assistant turns are persisted as a single `messages.content` text column that concatenates three distinct things produced during `/analyze`:

1. The engine-emitted `> **Tool:**` markdown header for each tool call
2. The engine-emitted ```text``` block carrying each tool's literal result
3. The model's actual synthesis prose

When the next user message arrives, the history loader reads each prior assistant row as `{role: "assistant", content: <combined blob>}` and the LLM sees its own past output formatted as narrative text containing what looks like tool-call markdown. Small local models learn the pattern and start producing the same markdown inside their `content` field on subsequent turns — without invoking a real tool. The chat surface then displays the LLM-generated mimicry as if it were real tool output, with hallucinated values.

The `_strip_tool_mimicry` regex at `core/ai_engine.py` (added in `60a4a42`) papers over the display symptom but the LLM still sees badly-shaped history and the mimicry impulse persists.

## Goal

Tool calls and their results are first-class structured data on the assistant turn, stored in their own column, rendered by their own frontend component, and re-emitted to the LLM as proper OpenAI-style `tool_calls` + `{role: "tool"}` messages on subsequent turns. The LLM never sees its prior tool calls flattened into narrative text.

## Scope

**In scope:**
- New `messages.tool_calls JSONB NULL` column.
- Restructured streaming: `ai_engine.stream_chat` yields typed `tool_call` and `tool_result` events alongside the existing text chunks. The two text-yields it currently does (`format_tool_execution`, `format_code_block`) are removed.
- `/analyze` route-handler event-collection: pair `tool_call`/`tool_result` events into a list, save on the assistant Message row.
- History-rebuild logic that handles both shapes (legacy single-content rows AND new structured rows).
- Frontend SSE consumer captures the new event types into a `toolCalls` slice.
- New `ToolCallsBlock.tsx` component renders the structured data with the same visual style users see today.
- `MessageHistory` schema gains `tool_calls: Optional[List[ToolCall]]`.
- Migration that adds the column, no backfill.
- Removal of the `_strip_tool_mimicry` band-aid (regex + tests).
- Unit tests for history-rebuild, event-pairing, and the new column persistence.
- E2E probe: send a tool-using prompt, verify DB-saved `tool_calls` is populated and `content` is synthesis-only.

**Out of scope:**
- Per-tool-call analytics (no GIN index, no query patterns; add later if needed).
- Streaming live stdout from tools — current behavior of "tool runs to completion, full result emitted as one string" is preserved.
- Frontend branch / edit / delete UX changes — tool_calls being a column on the assistant row means existing row-level operations work unchanged.
- Backfill of legacy assistant rows — they keep their single-content blob; history-rebuild handles them as today.

## Architecture

### Schema

```sql
ALTER TABLE messages ADD COLUMN tool_calls JSONB NULL;
```

Mirrors `referenced_docs` exactly — same shape, same lifecycle, same nullability.

JSONB shape per assistant turn:

```json
[
  { "name": "dns_lookup",   "args": {"domain": "youtube.com"},      "result": "DNS Lookup successful: …" },
  { "name": "execute_ping", "args": {"hostname": "142.250.x.x"},     "result": "Ping successful …" }
]
```

`args` stores only the user-visible args (the existing `display_args` filter in `ai_engine.py` that hides `workspace_id` / `session_id`). `result` is the raw tool return string. Order matches execution order within the turn.

### Streaming events from `ai_engine.stream_chat`

The two current text-yields inside the tool-call loop:

```python
yield format_tool_execution(func_name, display_args)
# … tool executes …
yield format_code_block(result)
```

are replaced with structured events:

```python
yield {"type": "tool_call",   "name": func_name, "args": display_args}
# … tool executes …
yield {"type": "tool_result", "name": func_name, "result": result}
```

The existing text-chunk path (`yield word + " "`) and the `files_referenced` event stay untouched.

### `/analyze` route handler

Adds a `tool_calls_acc: list[dict]` accumulator next to the existing `referenced_docs` accumulator. Event dispatch in the stream loop:

| Event type           | Action                                                                                                |
| -------------------- | ----------------------------------------------------------------------------------------------------- |
| `tool_call`          | `tool_calls_acc.append({"name": ev.name, "args": ev.args, "result": None})`                           |
| `tool_result`        | Find the most-recent entry with `result is None`, set its `result` to `ev.result`.                    |
| `files_referenced`   | Existing logic — accumulate into `referenced_docs`.                                                   |
| Text chunk           | Existing logic — accumulate into `full_response`, emit to client.                                      |
| Other dict events    | Passed through to the SSE client as today.                                                            |

After the stream completes, the save path becomes:

```python
ai_msg = models.Message(
    session_id=session_id,
    role="assistant",
    content=full_response,
    status="complete",
    referenced_docs=referenced_docs,
    tool_calls=tool_calls_acc or None,
)
```

### History-rebuild

The current line in `/analyze`:

```python
safe_messages = [{"role": msg.role, "content": msg.content} for msg in history]
```

becomes a small helper:

```python
def build_safe_messages(history):
    out = []
    for msg in history:
        if msg.role == "assistant" and msg.tool_calls:
            out.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {"function": {"name": tc["name"], "arguments": tc["args"]}}
                    for tc in msg.tool_calls
                ],
            })
            for tc in msg.tool_calls:
                out.append({
                    "role": "tool",
                    "name": tc["name"],
                    "content": tc.get("result") or "",
                })
        else:
            out.append({"role": msg.role, "content": msg.content})
    return out
```

Legacy rows with `tool_calls IS NULL` produce the flat shape, exactly as today. New rows produce the structured shape the LLM was trained to consume. Mixed-mode is safe — any modern OpenAI-compatible LLM accepts both within the same conversation.

### Frontend rendering

New TypeScript type in `types/chat.ts`:

```typescript
export interface ToolCall {
  name: string;
  args: Record<string, unknown>;
  result: string;
}
```

New component `frontend/src/components/ToolCallsBlock.tsx` reads a `toolCalls: ToolCall[]` prop and renders each entry with the existing visual style users already see — the `> **Tool:** name → args` blockquote header plus a ```text``` code block with the result. The difference is the data source: structured props, not markdown-in-content.

`ChatBubble.tsx` renders the new block between the assistant prose (`AssistantMessage`) and the existing `ReferencedFilesPreview`. Same conditional pattern: `message.toolCalls && message.toolCalls.length > 0`.

### Live streaming

`useInference.ts` gains a `streamingToolCalls: Record<string, ToolCall[]>` slice that mirrors the existing `streamingContent: Record<string, string>` lifecycle. As `tool_call` / `tool_result` events arrive, the array updates and re-renders the in-flight assistant turn so the user sees tool calls land as they happen — same UX as today, just driven by a different data path.

At finalize, `pendingToolCalls` is passed through `finalizeAssistantMessage(ws, sid, content, referencedFiles, toolCalls)`, which merges it onto the message in `messageCache`.

### History load

`MessageHistory` schema in `backend/schemas.py` gets `tool_calls: Optional[List[ToolCall]] = None`. The `useSession.ts` history mapper adds `toolCalls: m.tool_calls ?? undefined` next to the existing `referencedFiles` mapping.

## Pairing logic for `tool_call` ↔ `tool_result`

The engine emits them in strict sequence per execution: `tool_call`, then the tool runs to completion (or timeout/error — both produce a `tool_result`), then `tool_result`, all within one async iteration of the inner loop. The route handler pairs them by **order**, not by name:

- A `tool_call` always opens a new pending entry with `result: None`.
- A `tool_result` always completes the most-recent open entry.

Name-matching would break for tools called twice in one turn with different args (e.g. `search_knowledge_base` with two queries serialized one after the other). Order-based pairing is correct and simpler.

## Error handling

- **Tool timeout / exception** — the engine catches the exception, sets `result` to the error string, sets `had_tool_error = True`, then yields `tool_result` with that error string. The accumulator pairs it normally; the saved JSONB entry has the error in `result`. The chat surface displays it the same way as a normal result. The `had_tool_error` flag continues to drive escalation as today.
- **Client disconnect mid-stream** — the existing `disconnected` check at the top of the stream loop kicks in. Whatever pairs completed are saved with whatever shape the accumulator ended up in. Pending `tool_call` entries with `result: None` get dropped before save (a small filter in the save path: `[tc for tc in tool_calls_acc if tc["result"] is not None]`).
- **Malformed structured event** — the route handler validates `type`, `name`, and `args`/`result` shape on each event. Bad events are logged and skipped; the stream continues. Defensive but cheap.
- **Old row with corrupted `tool_calls` JSON** — history-rebuild treats malformed JSONB as if `tool_calls IS NULL` (falls back to flat shape). Logged at WARN.

## Removed code

- `_TOOL_HEADER_MIMICRY` and `_TEXT_BLOCK_MIMICRY` regex constants in `core/ai_engine.py`.
- `_strip_tool_mimicry()` function in `core/ai_engine.py`.
- The two call sites in the model-content branch that invoke `_strip_tool_mimicry`.
- `test_strip_tool_mimicry_removes_lookalike_blocks` and `test_strip_tool_mimicry_preserves_other_code_blocks` in `tests/test_tool_directive_render.py`.
- `format_tool_execution()` and `format_code_block()` in `utils/formatters.py` — no longer called anywhere. Delete to keep the formatter module focused.

## Testing

### Unit tests

- **`tests/test_history_rebuild.py`** (new). Pure-function test of the new helper. Three cases:
  1. Single legacy assistant row (`tool_calls IS NULL`, content has narrative + old markdown) → emits one flat `{role: "assistant", content}`.
  2. Single new assistant row (`tool_calls = [...]`, content is pure synthesis) → emits one structured assistant message plus one `{role: "tool"}` per call, in order.
  3. Mixed history with both → emits the right shape per row.

- **`tests/test_event_pairing.py`** (new). Tests the route-handler accumulator logic in isolation:
  1. Single call + result → one paired entry.
  2. Two calls, two results, all from the same tool → each result pairs with its own call by order.
  3. Disconnect after `tool_call` with no `tool_result` arriving → the unpaired entry is filtered out at save.

### Migration test

`tests/test_migration_add_tool_calls.py`. Standard pattern (matches `test_migration_force_reset_prompts.py`):
- Upgrade adds the column; existing rows have NULL.
- Downgrade removes it cleanly.

### E2E probes

Reusing `/tmp/pryzm_autotest.py`:

1. `it_copilot` "Check if reddit.com is up" → assert (a) at least one network tool appears in the saved `tool_calls` JSONB and (b) the saved `content` contains **no** `> **Tool:**` or ```text``` substrings.
2. Reload the same session via `GET /sessions/{id}` → assert the response includes the `tool_calls` field with the same shape.
3. UI smoke (Playwright): load a session with `tool_calls` populated, assert the tool-call block renders and its text matches the JSONB result.

## Rollout

Single PR, single migration, no backfill. Old rows and new rows coexist in the same table.

**Migration:** adds the column, drops it on revert. Both directions clean.

**Reverting the PR** would lose the JSONB data for any assistant rows written between merge and revert — those rows' synthesis `content` would still render (just without their tool-call block until the turn is re-run). No corruption.

## Risks

1. **Visual drift between legacy and new turns** — legacy rows render the engine markdown via the markdown engine; new rows render via the React component. Aiming for identical-looking output, but small differences (font weight, code-block padding) are possible. The component's CSS should explicitly match the markdown-rendered version.

2. **Mimicry resurgence on long sessions with legacy rows** — strip-mimicry is removed in this PR. A session that mixes pre-PR and post-PR turns might briefly see the LLM pattern-mimicking from the legacy rows it sees in mid-stream history. As legacy rows age out (sessions naturally turn over), the issue self-resolves. Re-add the band-aid if it becomes painful.

3. **Pairing logic bugs** — if a `tool_result` ever arrives without a preceding `tool_call`, the accumulator silently has nothing to attach to. The route handler logs WARN and drops the event. Tests cover the normal cases; this is a defensive guard for engine-side bugs.

## Open questions

None blocking. Implementation plan to follow.
