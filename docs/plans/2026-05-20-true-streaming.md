# True Streaming for Chat Completions

## Context

`llm_server.chat()` currently calls llama-server with `stream: False` — it blocks until the full model response is generated, then `ai_engine.stream_chat()` fake-streams the result back to the client word-by-word at ~10 ms intervals. The visible cost is a 20–30 second blank window between the user sending and the first chunk appearing in the browser, because the model is still generating during that window and the backend has nothing to forward.

The fake-stream pattern was chosen for two reasons that are no longer load-bearing:

1. **Output cleanup with `_THINK_BLOCK_RE`** — easier to regex a complete blob than a token stream. Obsolete: llama.cpp's `--jinja` parser routes `<think>...</think>` content into a separate `reasoning_content` field, leaving `content` clean. The regex barely fires anymore.
2. **Tool-call detection** — the agentic loop needs the complete assistant message to know whether a tool was called. Solvable: accumulate `tool_calls` deltas server-side while forwarding `content` and `reasoning_content` deltas to the client. Standard pattern; every modern AI chat product does this.

The downstream UX problem this creates was surfaced by the reasoning-output-streaming work: the `ThinkingPanel` pill can't appear during the actual reasoning phase because reasoning_content doesn't reach the client until generation has already finished. Claude, ChatGPT, Gemini, and Open WebUI all stream during generation. We should too.

## Scope

In:
- New `llm_server.chat_stream()` as an async generator yielding deltas from llama-server's `/v1/chat/completions` SSE response.
- Refactor of `ai_engine.stream_chat()` to consume the new streaming source. Reasoning and content deltas forward to the caller immediately; tool-call deltas accumulate into a complete `tool_calls` list for the agentic-loop decision at end-of-stream.
- `is_reasoning` flag plumbed to the frontend so the ProcessingAnimation label can flip to `Thinking…` from message 1. The flag is the same `"reasoning" in router.catalog.get(model_id, set())` check as the SSE-emission gate from PR #116 — admin-toggleable via the System → Models tags chip. Non-tagged models keep the themed phrase pool (Refracting…, Splitting light…, etc.) so a vanilla chat model an admin installs doesn't falsely claim to be thinking.
- Frontend: ProcessingAnimation accepts an `isReasoning` prop; renders `Thinking…` when true, the existing themed phrase pool otherwise.
- Unit tests covering: streaming-mode reasoning emission timing, tool-call delta accumulation, error mid-stream, client disconnect mid-stream.

Out:
- Non-chat call sites that still use `llm_server.chat()` directly (image captioning, memory condenser, prompt-classification probes). Those produce single short responses where fake-streaming behavior is irrelevant; leave them on the existing entry point.
- Real-time tool-call render in the UI. Tool-call events still fire as they do today; the loop just sees them via accumulated deltas instead of a single non-streaming response.
- Token-level cancellation. Existing `is_disconnected` check fires at the SSE chunk boundary already; no per-token granularity needed.

## Architecture

```
                  client                         backend                       llama-server
                  ──────                         ───────                       ────────────
  /analyze  ──────────────────────►  stream_chat()
                                      │
                                      │  chat_stream(messages, tools, model)
                                      ├─────────────────────────────────────► POST /v1/chat/completions
                                      │                                       stream: true
                                      │                                       │
                                      │  ◄── delta {reasoning_content: "..."} ┤
                                      │  yield {type: reasoning_chunk}        │
                                      │  ◄── delta {reasoning_content: "..."} ┤
                                      │  yield {type: reasoning_chunk}        │
                                      │  ◄── delta {content: "..."} ──────────┤
                                      │  accumulate; yield chunk              │
                                      │  ◄── delta {tool_calls: [...]} ───────┤
                                      │  accumulate; do not yield             │
                                      │  ◄── [DONE] ──────────────────────────┤
                                      │
                                      │  if accumulated tool_calls:
                                      │      execute, loop
                                      │  else:
                                      │      done
                                      │
   ◄────────────── chunks forwarded ──┘
```

Three accumulators inside `chat_stream()`'s loop body, scoped per agentic-loop iteration:

- `acc_content: str` — every `delta.content` value concatenated. Forwarded as it arrives AND kept in the buffer.
- `acc_reasoning: str` — every `delta.reasoning_content` value concatenated. Forwarded immediately as `{type: reasoning_chunk}` events.
- `acc_tool_calls: list[dict]` — OpenAI's tool-call delta format streams the function name in one chunk and arguments token-by-token across many. Each delta carries an `index` field identifying which call it belongs to. Assemble into complete `[{id, function: {name, arguments}}]` objects keyed by index.

At end-of-stream, the loop body has the equivalent of the old non-streaming `message` dict (`{content, reasoning_content, tool_calls}`) and proceeds with the agentic logic unchanged.

## File-by-file changes

### `backend/core/llm_server.py`

New async generator alongside `chat()`. Same parameter signature.

```python
async def chat_stream(
    client: httpx.AsyncClient,
    messages: list,
    tools: list | None,
    model: str,
    options: dict | None = None,
) -> AsyncIterator[dict]:
    """POST /v1/chat/completions with stream=True. Yields delta dicts of
    shape {role?, content?, reasoning_content?, tool_calls?, finish_reason?}
    one per upstream SSE event. Final yield is {finish_reason: "stop"|...}
    so callers can detect end-of-stream cleanly. Metrics emit once on close."""
```

Implementation:
- `client.stream("POST", url, json={..., "stream": True}, timeout=settings.LLM_TIMEOUT_SECONDS)` — note `stream(...)` not `post(...)`.
- Iterate `aiter_lines()`, strip `data: ` prefix, skip empty lines, skip `data: [DONE]`.
- For each event, `json.loads`, extract `choices[0].delta`, yield.
- Capture `usage` and `timings` from the FINAL event (some llama.cpp builds put them there). Emit `llm.metric` once on close, same shape as the existing `emit_chat_metric` call. Reuse `_adapt_chat_response`'s timing-conversion code by extracting it to a small helper.

Existing `chat()` stays untouched. It's still used by captioning and the memory condenser.

### `backend/core/ai_engine.py`

In `stream_chat()`'s loop body, replace the `llm_server.chat(...)` call with the streaming version. The post-call processing (reasoning emit, content cleanup, tool-call branch) restructures into a single pass over the delta stream:

```python
acc_content = ""
acc_reasoning = ""
acc_tool_calls: dict[int, dict] = {}  # index -> partial tool_call
reasoning_started_at: float | None = None
reasoning_done_emitted = False

async for delta in llm_server.chat_stream(client, messages, tools, model, options):
    if is_disconnected and await is_disconnected():
        return

    # Reasoning channel — forward immediately, never accumulate to the
    # tool-detection buffer (reasoning_content cannot be a tool call).
    rc = delta.get("reasoning_content")
    if rc and surface_reasoning:
        if reasoning_started_at is None:
            reasoning_started_at = time.perf_counter()
        acc_reasoning += rc
        yield {"type": "reasoning_chunk", "chunk": rc}

    # Content channel — forward AND accumulate. Accumulation is for
    # the post-loop "did the model write a final answer or just tool calls?"
    # check; forwarding is for the user to see tokens land in real time.
    ct = delta.get("content")
    if ct:
        # First content token closes the reasoning phase if it was open.
        if reasoning_started_at is not None and not reasoning_done_emitted:
            yield {
                "type": "reasoning_done",
                "duration_s": round(time.perf_counter() - reasoning_started_at, 1),
            }
            reasoning_done_emitted = True
        acc_content += ct
        yield ct  # plain string, matches the existing content-chunk shape

    # Tool-call deltas — accumulate by index. llama-server streams the
    # function name in one chunk, then arguments token-by-token across
    # subsequent chunks; assemble into complete objects.
    for tc_delta in (delta.get("tool_calls") or []):
        idx = tc_delta.get("index", 0)
        slot = acc_tool_calls.setdefault(idx, {
            "id": tc_delta.get("id"),
            "type": "function",
            "function": {"name": "", "arguments": ""},
        })
        if tc_delta.get("id"):
            slot["id"] = tc_delta["id"]
        fn = tc_delta.get("function") or {}
        if fn.get("name"):
            slot["function"]["name"] = fn["name"]
        if fn.get("arguments"):
            slot["function"]["arguments"] += fn["arguments"]

# If reasoning was emitted but the model never produced content (max-
# tokens hit during thinking), close the reasoning phase now so the
# UI shows a duration.
if reasoning_started_at is not None and not reasoning_done_emitted:
    yield {
        "type": "reasoning_done",
        "duration_s": round(time.perf_counter() - reasoning_started_at, 1),
    }

# Reconstruct the message dict the rest of the loop body expects.
message = {
    "role": "assistant",
    "content": acc_content,
    "reasoning_content": acc_reasoning,
}
tool_calls_list = [acc_tool_calls[i] for i in sorted(acc_tool_calls)]
if tool_calls_list:
    message["tool_calls"] = tool_calls_list

# Existing tool-call branch and stall-detection branch take over from here,
# unchanged. _THINK_BLOCK_RE moves to a per-chunk filter inside the content
# branch above (cheap, runs on tiny strings). It's a safety net for any
# non-reasoning-aware model an admin installs that still emits raw <think>
# tags as plain content — the catalog-tag gate covers the well-behaved
# case where llama.cpp's parser already routed them.
```

Net effect: reasoning + content stream to the client during generation; tool-call detection still happens at end-of-stream.

### Frontend: `routers/chat.py` and `useInference.ts`

`routers/chat.py` adds `is_reasoning: bool` to the `started` event payload — computed from the routed model's catalog tags (same `"reasoning" in router.catalog.get(model_id, set())` check as the SSE-emission gate). Needs the router to expose the routed model ID for the started-event composition; either inline the catalog check or pass the routed model down from `ai_engine.stream_chat()` via a callback / earlier-yielded event.

Simpler path: emit a typed event from `stream_chat()` as the first yield, right after the router picks:

```python
yield {"type": "route", "is_reasoning": surface_reasoning, "tier": tier.value}
```

`chat.py`'s `generate()` loop already forwards typed dict chunks as JSON lines; the `started` event composition stays untouched, and `useInference.ts` learns a new event type.

`useInference.ts` adds a `streamingIsReasoning: Record<sessionId, boolean>` state and a handler for the `route` event that sets it. ActiveSession passes the per-session value to `ProcessingAnimation` as `isReasoning`. ProcessingAnimation renders `Thinking…` when true, the themed phrase otherwise.

### Tests

`backend/tests/test_ai_engine_streaming.py` (new):

- `test_streaming_reasoning_emits_chunks_as_they_arrive` — mock chat_stream to yield reasoning_content deltas, assert reasoning_chunk events fire 1:1.
- `test_streaming_content_forwards_immediately` — mock content deltas, assert plain-string chunks yield in order with no buffering.
- `test_streaming_tool_call_accumulation` — mock tool-call deltas split across chunks (name in first, arguments in three subsequent), assert the loop sees a single complete tool_call.
- `test_streaming_tool_call_with_partial_content` — model emits a short content prefix then a tool_call; assert content was forwarded AND the tool fires.
- `test_streaming_client_disconnect_mid_stream` — is_disconnected returns True mid-stream, assert the generator exits without hanging.

Existing `test_ai_engine_typed_events.py` tests need the mock router to provide a streaming chat function. Mock-shape change is small; behavior assertions stay the same.

Frontend: no formal test framework. Verify manually:
- Smaller-model turn: prism + themed phrase, no pill, content streams immediately.
- Reasoning-model turn: prism + `Thinking…` label, pill appears within ~100 ms, reasoning text populates the pill live, content starts streaming when `</think>` lands.

## Risks

- **llama-server streaming format drift**: the pinned image in `docker-compose.yml` is `:cuda` digest `1ac0ae06…`. The `delta` shape and `tool_calls` index semantics are stable in mainline llama.cpp but worth re-verifying with one curl probe against the running container before code changes land.
- **Tool calls during reasoning_content**: untested whether any chat template emits tool_call deltas inside the `<think>` block. Gemma 4's template puts tool calls after `</think>`, but the accumulator should treat tool-call deltas as final regardless of where they arrive — the worst case is a reasoning chunk preceding a tool call, which the existing tool-execution flow handles fine.
- **httpx streaming timeout semantics**: `client.stream(...)` uses the same `timeout` setting as `client.post(...)`. The current `settings.LLM_TIMEOUT_SECONDS` covers the full request lifecycle, not per-chunk. A model that produces tokens slowly but steadily for 5 minutes might trip a timeout that `chat()` survived because the response landed in one network read. Worth setting an explicit read-timeout that resets on each chunk.
- **Stray `<think>` tags from non-tagged models**: admins can install arbitrary GGUFs via the HF picker, and a model that didn't get a proper jinja template (or one whose template doesn't separate reasoning) could leak `<think>...</think>` markers into the `content` stream. Mitigated by keeping `_THINK_BLOCK_RE` as a per-chunk filter on the content branch — see the ai_engine snippet above. The regex only fires on matched pairs of a known tag allowlist, so legitimate angle-bracket content (`Vec<T>`, HTML examples) passes through.

## Test plan

1. Curl probe pre-implementation: confirm llama-server's streaming SSE shape for reasoning_content + content + tool_calls deltas against `gemma-4-26B-A4B-it` and `gemma-4-E2B-it`. Save sample to `docs/internal/` for reference.
2. Implement `chat_stream()` against the verified shape; cover with unit tests.
3. Refactor `stream_chat()` in `ai_engine.py`; full backend test sweep passes.
4. Add `route` event + frontend wiring; manual smoke pass on three scenarios (small model regular chat, reasoning model long prompt, reasoning model that triggers a tool).
5. Phase-PR manual verification: time-to-first-pill < 500 ms; no UI regressions in tool-call flows; reasoning_content persisted to DB matches what streamed.

## Rollback

`chat()` and the existing fake-stream path stay in the codebase during this PR. If issues surface post-merge, swap a single import line in `ai_engine.stream_chat()` back to `chat()` and the fake-stream loop body reactivates. No data migration involved; the DB schema is unchanged from PR #116.

Cleanup pass (remove `chat()` if `chat_stream()` proves stable) is its own follow-up PR after enough real-world use to be confident — not in the initial merge.
