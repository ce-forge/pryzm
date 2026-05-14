# VLM M3-Followup — Tool-RAG Re-attach (Plan)

- **Date**: 2026-05-15
- **Spec**: `docs/specs/2026-05-15-image-upload-vlm.md` (Milestone 3 follow-ups)
- **Branch**: `feat/tool-rag-reattach` from `main` at `b8beca2`

## Scope

When the LLM calls `search_knowledge_base` (the agentic tool) and the search surfaces an image-derived chunk, the original image bytes get re-attached to the *next* iteration of the agentic loop. This closes the gap from M3, which only covered the auto-RAG branch (the `[Attached_File:]` marker path).

**Not in this PR:** any other tool's hooks for re-attach (currently only `search_knowledge_base` retrieves chunks).

## Why a side-channel and not a return-value change

`_execute_tool` and the loop expect tools to return text — the result lands as a `tool` role message whose `content` the LLM reads verbatim. Returning JSON would confuse the LLM (it would see raw structure as the search result). Returning a separate object would require widening the entire tool protocol for a single capability. A `ContextVar` published by the tool and consumed by the engine keeps the data flow clean: text in the tool message, paths via the side-channel.

## Steps

| # | Step | Verify |
|---|---|---|
| 1 | `services/knowledge` exposes `_PENDING_IMAGE_PATHS` (ContextVar), `consume_pending_image_paths()`, and `_publish_pending_image_paths(documents)`. Order-preserving dedupe; second drain returns empty. | Unit tests: empty start, publish-then-drain, dedupe-within-batch. |
| 2 | `tools/retrieval.search_knowledge_base` calls `_publish_pending_image_paths` after collecting chunks for each query. Only docs with non-null `storage_path` are published. | Unit test seeds an image doc + a text doc, runs the tool, asserts only the image path lands in the queue. |
| 3 | `core/ai_engine.stream_chat` drains the queue right after the tool-call batch loop. If `router.vision_capable(routed_model)` AND paths were published, appends a synthetic `user` message with `text` + `image_url` content blocks to `full_messages`. The next loop iteration's LLM call sees both the tool text AND the original pixels. | Live E2E (Step 5). |
| 4 | Full suite green. | 151/151 unit tests pass (+4 from `test_reattach`). |
| 5 | Live E2E — force E4B routing (vision-tagged) and ask a question that requires search. Assert `prompt_tokens` is materially higher than the comparable text-only turn AND the response describes vision-only details (lighting, composition, framing) the caption text doesn't carry. | Got `prompt_tokens=2413` (vs 1932 on the E2B turn), response: "directional lighting, deep shadows, bi-color pattern, intense gaze" — descriptors only inferable from pixels. |
| 6 | Commit, PR, auto-merge. | Merged. |

## Risks / unknowns

- **ContextVar across tool boundary.** The tool runs synchronously via `_execute_tool` which wraps in `asyncio.to_thread`. Python's contextvars propagate across `to_thread` correctly (the thread inherits the parent context). Confirmed by the test that exercises the tool and then reads the queue from the test process.
- **Queue lifetime.** The queue is drained once per tool-call batch. If `consume_pending_image_paths` is called outside the loop or in a fresh context, paths might appear stale or get lost. Mitigated by the atomic read-and-clear pattern.
- **E2B no longer vision-tagged.** The user removed the `vision` tag from E2B via the admin UI; re-attach is therefore silently skipped when E2B is the routed model. That is correct behavior — the model would not accept image content blocks if vision is not loaded — but it does mean image-aware answers require routing to E4B. Worth a router heuristic enhancement (escalate to E4B when pending images exist) as a follow-up.

## Done when

- All 6 steps green.
- Live E2E shows vision-only descriptors in the response.
- PR description is a 6-line release note.
