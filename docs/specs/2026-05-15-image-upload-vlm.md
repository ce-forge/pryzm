# Image Upload + VLM Captioning — Design Spec

- **Date**: 2026-05-15
- **Status**: Draft, accepted in conversation. Three-milestone implementation.
- **Supersedes**: `docs/specs/2026-05-15-image-upload-ocr.md` (rapidocr/OCR approach landed in PR #21; this spec rips it out and replaces with the existing Gemma-4 multimodal capability).
- **Branch context**: cut from `main` at `4b40c6d`.

## What changed

Two facts discovered after the OCR spec landed:

1. **Gemma-4-E2B and Gemma-4-E4B are already multimodal.** The HuggingFace model cards advertise text + image + audio. The Bartowski GGUF quants both ship mmproj projector files (~990 MB at f16).
2. **`llama-server -hf` auto-downloads and loads mmproj.** The existing `cmd` lines in `infra/llama-swap-config.yaml` already get vision capability — the only reason image input wasn't working before is that nothing in the backend called `/v1/chat/completions` with an `image_url` content block.

A live smoke against the running llama-swap stack confirmed it:

```text
STATUS: 200  elapsed: 2.5s
FINAL CONTENT:
This image displays a technical error log from the Pryzm ITConsole … The
specific error reported is "Pryzm ITConsole Error 0x80070005." … Suggested
fix: restart Volume Shadow Copy service.
```

The model captured every line of rendered text verbatim plus contextual semantic framing useful for retrieval. Strictly better than the rapidocr path it replaces.

## Goal

Users upload JPG/PNG/WebP images. The vision-capable chat model writes a detailed description on ingest; the description is embedded into the existing RAG store. At chat time, when RAG retrieval surfaces an image-derived chunk, the **original image bytes are re-attached** to the LLM call so the model can verify what it's claiming about the picture by looking again.

## Architecture

```
                          /upload
                              |
            +-----------------+-----------------+
            |  content_type starts with image/  |
            +-----------------+-----------------+
                              |
                              v
              services/image_describe.py
              describe(image_bytes) -> str
                              |
              calls llm_server.chat(
                  messages=[image_url + describe prompt],
                  model="gemma-4-E4B-it"
              )
                              |
                              v
              services/knowledge.py::ingest_document(
                  content=description,
                  storage_path=<saved-bytes>  # NEW: Document.storage_path
              )
                              |
                              v
              chunks + Document row pointing at saved file


At chat time
                  /analyze user turn
                          |
                          v
              retrieve_relevant_chunks(query)
                          |
                          v
              for each chunk whose Document has storage_path:
                  re-attach the original image as image_url
                          |
                          v
              llm_server.chat([
                  system,
                  ... history,
                  user message (text + re-attached images),
              ])
```

The new pieces are: the image-describe seam, a `storage_path` column on `documents`, and the re-attach step inside `ai_engine.stream_chat`. Everything else (chunking, embedding, retrieval, the OpenAI-compatible HTTP shape) is reused as-is.

## Milestones (one PR each)

### Milestone 1 — Caption swap

Replace today's rapidocr path with VLM captioning. Functional parity (uploaded images become searchable text), better-quality captions, smaller dependency footprint.

**Out of this PR:**

- File persistence (Milestone 2). Captions still ingest as text; original bytes still discarded after captioning. Image search by text continues to work; image re-attach at chat time does not yet.

**Diff (estimated):**

| File | Change |
|---|---|
| `backend/services/ocr.py` → `backend/services/image_describe.py` | Rename + replace body. New body posts to `llm_server.chat` with the image as a `data:image/*;base64,…` content block. |
| `backend/routers/chat.py` | Swap `from services import knowledge, ocr` for `from services import knowledge, image_describe`. Update the call in `upload_document`. |
| `backend/requirements.txt` | Drop `Pillow`, `rapidocr-onnxruntime`. |
| `backend/tests/test_ocr.py` → `backend/tests/test_image_describe.py` | Rewrite. Mock the HTTP call (don't depend on a live llama-server in unit tests). |
| `backend/tests/test_image_upload.py` | Update import + monkeypatch target. End-to-end integration test still seeds a workspace, posts an image, and asserts a chunk with the captioned text. |
| `infra/llama-swap-config.yaml` | Drop the now-incorrect `# vision is reserved` comment. Otherwise unchanged — vision is already on via auto-mmproj. |
| `docs/specs/2026-05-15-image-upload-ocr.md` | Add a Status: Superseded line at the top, pointing here. |

### Milestone 2 — Original-file persistence

Add a `storage_path` column on `documents` so the original image survives the ingest call. Required by Milestone 3's re-attach step; also unblocks the long-deferred thumbnail rendering work.

**Diff (estimated):**

| File | Change |
|---|---|
| `backend/alembic/versions/<rev>_documents_storage_path.py` | New migration. `ADD COLUMN storage_path VARCHAR(512) NULL` on `documents`. Reversible. |
| `backend/db/models.py` | Add `storage_path: Mapped[str \| None]` on `Document`. |
| `backend/services/knowledge.py::ingest_document` | New `storage_path` keyword. When set, the value is written onto the Document row. Caller (Document upload) computes the path and writes the bytes. |
| `backend/routers/chat.py::upload_document` | For image branch only: write the bytes to `backend/data/uploads/<doc_id>.<ext>`, pass the path to `ingest_document`. Cleanup-on-delete handled by a SQLAlchemy `after_delete` event listener on `Document`. |
| `backend/tests/test_migration_storage_path.py` | Migration up/down round-trip. |
| `backend/tests/test_image_upload.py` | Add: after upload, `storage_path` is populated and the file exists at that path. After Document delete, the file is gone. |
| `.gitignore` | Add `backend/data/uploads/` (the bytes themselves are not committed). |

**Where the file goes.** `backend/data/uploads/<doc_id>.<ext>`. One directory, flat layout, doc_id as the unique key. The Document row owns the path; deletion cascades through the SQLAlchemy event listener so we don't leak files.

**Extension derivation.** From `Document.filename`, fallback to MIME-type → extension lookup. Simple `os.path.splitext`.

### Milestone 3 — Re-attach at chat time

When the RAG path returns chunks whose parent Document has a `storage_path`, the original image is loaded from disk and re-attached to the next LLM call as a content block alongside the existing text context.

**Diff (estimated):**

| File | Change |
|---|---|
| `backend/services/knowledge.py::retrieve_relevant_chunks` | Return shape gains a `reattach_images: list[str]` field carrying file paths (deduplicated). |
| `backend/core/ai_engine.py::stream_chat` | When the message list is built, if `reattach_images` is non-empty AND the active model is vision-capable, inject the images as additional `image_url` content blocks on the user turn. |
| `backend/core/llm_router.py` (small) | Helper `model_is_vision_capable(name) -> bool` consulting a hardcoded set: `{"gemma-4-E2B-it", "gemma-4-E4B-it"}`. The router does NOT escalate to E4B just because images are present in this PR — that's a follow-up. v3 keeps the existing router heuristic untouched. |
| `backend/tests/test_reattach.py` | Stub the LLM call, verify the outgoing payload contains the re-attached `image_url`. |

**Why a flag instead of inspecting the messages**: keeping the re-attach paths data-driven (the retrieval result already knows what was retrieved) avoids the engine doing redundant DB lookups to figure out which chunks came from images.

## Caption prompt

System prompt (locked in for Milestone 1, easy to revise later):

> You are an image-description tool for a knowledge base. Write a detailed paragraph (3-6 sentences) describing the image: what it shows, any visible text verbatim, technical specifics, and anything a later search query might match. No preamble, no thinking out loud.

User content: `"Describe this image for our knowledge base."` plus the `image_url` block.

`temperature=0.2`, `max_tokens=600`.

**Why a system prompt:** Gemma's reasoning_content can swallow the actual answer if the model decides the task warrants thinking. An explicit "no preamble, no thinking out loud" plus a high enough max_tokens keeps the response in `content`. The seam falls back to `reasoning_content` if `content` is empty as a defensive measure.

## Configuration

| Setting | Default | Lives in |
|---|---|---|
| `IMAGE_CAPTION_MODEL` | `gemma-4-E4B-it` | `config.py` |
| `IMAGE_CAPTION_MAX_TOKENS` | 600 | `config.py` |
| `IMAGE_CAPTION_TEMPERATURE` | 0.2 | `config.py` |
| `UPLOAD_MAX_BYTES` | 10 MiB (already raised in #21) | `config.py` |

## Error paths

| Condition | Response |
|---|---|
| File > 10 MiB | HTTP 413 |
| Image fails to decode in the model (no Pillow check anymore — the model itself errors) | HTTP 400 with the upstream message |
| Captioning call times out (LLM_TIMEOUT_SECONDS) | HTTP 504 |
| Caption is empty after strip | HTTP 422 |
| `storage_path` write fails (disk full, permission) | HTTP 500, no Document row created |

## Performance notes

- Captioning latency: **~2.5s on a warm E4B** (measured on the live stack). When E4B isn't currently in VRAM, llama-swap pays a swap-in cost of ~10-30s on first call. Acceptable for upload UX; UI shows the "uploading" state throughout. (If this becomes painful, we revisit with the speculative-decoding follow-up — see Follow-ups.)
- Image re-attach prefill cost: a 600x200 PNG prefills in ~150 ms on E4B per the smoke probe. Multi-image re-attach scales linearly; in practice the RAG path returns ≤3 chunks so ≤3 images re-attached.

## Testing

- **Unit:** mock the HTTP call to `/v1/chat/completions`; verify the request shape carries the image as base64, the system prompt is correct, and the response's `content` is returned. Fallback-to-`reasoning_content` path tested.
- **Integration (M1):** seed a workspace, post an in-memory PNG to `/upload`, assert a Document and chunks are created with caption text. Embedding mocked.
- **Integration (M2):** upload, assert `storage_path` exists and the bytes are on disk. Delete the document, assert the file is gone.
- **Integration (M3):** seed an image-derived Document, run the chat path, assert the outgoing LLM call contains the re-attached `image_url`.
- **Migration (M2):** upgrade + downgrade smoke against the test DB.

## Follow-ups (separate PRs)

1. **Speculative decoding** with `AtomicChat/gemma-4-E4B-it-assistant-GGUF` (~80 MB draft model). Up to 3x decode speedup on E4B with no quality change. Helps chat-time generation; modest help on captioning (prefill-dominated).
   - **Blocked on llama.cpp support (as of 2026-05-15).** Investigated the integration — `-hfd AtomicChat/gemma-4-E4B-it-assistant-GGUF` downloads the file correctly, but the model's GGUF declares `general.architecture = "gemma4_assistant"` (a new MTP-specific architecture). The currently bundled `llama-server` (build `b9128-856c3adac`) fails with `unknown model architecture: 'gemma4_assistant'` and exits during startup. The feature waits on an upstream llama.cpp release that adds the architecture. When that lands, the config change is a single `-hfd` flag and a llama-swap restart; the benchmark harness from the investigation (median predicted/s across 4 runs, drop run 1 as the cold start) can be reused unchanged.
   - Baseline measured on the current build: median 139.8 predicted/s on E4B at `--ctx-size 8192`, Q4_K_M, 300 output tokens.
2. **Thumbnail UI surface.** Render a thumbnail of the original image next to chat bubbles that reference an image-derived Document. Needs a `/uploads/<doc_id>` static endpoint and a small frontend change. Trivial once Milestone 2 lands.
3. **Audio ingest.** Gemma-4-E2B/E4B accept audio natively; same shape as image upload (base64 in chat completions). 30 s clip limit per the model card. A natural Milestone 4 if you want a real "drop a Zoom recording, ask about it" feature.
4. **Multimodal embeddings.** The original future-features doc Item 5 mentioned this as the cleanest theoretical path. Now optional, since re-attach gives us pixel-level access where it matters.
5. **Per-image caption regeneration.** Admin/Settings UI to re-caption an existing image (e.g., after upgrading the captioning model). Touches `routers/admin.py`.
6. **Vision router signal.** If a session has any image-derived Document in context, the router could pin E4B for the next turn (since E2B's vision is also capable but smaller). Optional — depends on whether E2B's image answers are visibly worse than E4B's.

## Why Path B (caption + RAG + re-attach) over Path A (opaque attach) or Path C (multimodal embeddings)

- **Path A (opaque attach):** every chat turn referencing an image re-uploads it to the model. Doesn't scale beyond a few images per session. No text-side search.
- **Path C (multimodal embeddings):** cleanest cross-modal search story but a schema discriminator on `document_chunks`, a new embedding model in llama-swap, and new retrieval logic. Bigger lift; deferred per existing future-features doc.
- **Path B (this spec):** the description is text, so the existing RAG pipeline retrieves images by query just like any document. The original bytes get re-attached at generation time so the LLM still sees pixels when it matters. Reuses every existing component.
