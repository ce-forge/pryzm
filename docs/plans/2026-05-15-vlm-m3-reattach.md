# VLM Milestone 3 — Re-attach Original Image on RAG Hit (Plan)

- **Date**: 2026-05-15
- **Spec**: `docs/specs/2026-05-15-image-upload-vlm.md` (Milestone 3 section)
- **Branch**: `feat/vlm-reattach` from `main` at `bf0e32e`

## Scope

When the auto-RAG path in `ai_engine.stream_chat` selects an image-derived chunk (its parent Document has a non-null `storage_path` that exists on disk), the original image bytes are re-attached to the next LLM call as an `image_url` content block. The model now sees both the caption-text context AND the actual pixels.

**Not in this PR:**

- Re-attach on the tool-RAG path (when the LLM calls `search_knowledge_base` itself). Lower urgency; harder hook point.
- Router escalation to E4B when a session has image context. Optional follow-up — measured impact unknown.
- Frontend UI for image thumbnails. Filed as a separate follow-up.

## Steps

| # | Step | Verify |
|---|---|---|
| 1 | `services/image_storage.read_as_data_url(path) -> str \| None` reads a file from disk and returns a base64 `data:image/*;base64,…` URL. Returns None for missing/unsupported. | Unit test asserts shape; missing path → None; .tiff → None. |
| 2 | `HeuristicRouter.vision_capable(model_id) -> bool` consults the catalog tag set. Vision-capable models in the live YAML are the two Gemma-4 chat models. | Unit test: tag present/absent/unknown model. |
| 3 | `services/knowledge._collect_reattach_paths(documents) -> list[str]` extracts `storage_path` from each Document, dedupes, filters missing files. Order-preserving so retrieval rank is preserved. | Unit test covers dedupe + missing-file filter + None paths. |
| 4 | `services/knowledge.retrieve_relevant_chunks` adds `reattach_images` field to its return shape — populated from the Documents the retrieved chunks belong to. Both the overview-mode and semantic-search code paths emit it. | Integration test: image-derived chunk → field has the file path; text-derived chunk → empty list. |
| 5 | `core/ai_engine.stream_chat` consumes `reattach_images`: when non-empty AND the routed model is `vision_capable`, the last user message's `content` (which was a string carrying RAG context + clean query) is converted into a content-block list with `image_url` blocks appended for each path. Falls back to the existing string-content path when either condition is false. | Live E2E (see Step 7). |
| 6 | Full suite green. | 145/145 unit tests pass (was 135 in M2; +10 from `test_reattach.py`). |
| 7 | Live E2E: upload a known image (cat photo fixture), trigger the auto-RAG path with `[Attached_File:…]`, assert the streamed response mentions visual details only inferrable from pixels. Inspect token counts. | Got `prompt_tokens=1105` (text-only would be ~300-500), assistant said "black and white portrait of a domestic cat" — pixels reached the model. |
| 8 | Commit, PR, auto-merge. | Merged. |

## Risks / unknowns

- **Tool-RAG path is not covered.** If the user asks a follow-up question without an `[Attached_File:]` marker, the LLM may call `search_knowledge_base` directly; the retrieval returns text only via the tool message. Re-attach there requires a different hook (mutate the tool result? inject on the next turn?). Worth its own design pass; not in M3.
- **Multi-image prompts.** If retrieval surfaces multiple image-bearing docs, all are re-attached. Token cost scales linearly. Bounded by `top_k=3` retrieval ceiling.
- **Vision tag drift.** If the YAML is hand-edited to remove the `vision` tag from a still-vision-capable model, re-attach silently disables for that model. Mitigated because the tag also reflects whether mmproj will load; if vision is off, the model wouldn't accept the image anyway.
- **String vs. list content downstream.** Some legacy paths might assume `recent_messages[-1]["content"]` is a string. Audited and re-attach only happens at the end of the auto-RAG branch, after the existing string-mutation steps. Downstream code is the chat completion call, which already handles both shapes.

## Done when

- All 8 steps green.
- Live E2E shows vision-only words in the response.
- PR description is a 6-line release note.
