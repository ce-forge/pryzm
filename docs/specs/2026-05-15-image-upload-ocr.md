# Image Upload + OCR — Design Spec

- **Date**: 2026-05-15
- **Status**: **Superseded by `docs/specs/2026-05-15-image-upload-vlm.md`.** The rapidocr-based ingestion path described here landed in PR #21; the follow-up VLM spec rips it out in favor of using Gemma-4's built-in vision capability (which was already loaded by llama-swap via the auto-mmproj behavior of `-hf`). Keep this file for historical reference.
- **Predecessor**: future-features Item 5 sub-item "image upload + analysis" from `docs/internal/2026-05-14-future-features.md`.
- **Branch context**: cut from `main` at 851db2e.

## Goal

Users can upload a JPG, PNG, or WebP image via the existing `/upload` flow. The image's text content (extracted via OCR) is chunked, embedded, and stored alongside any other knowledge document. From that point on, `search_knowledge_base` and the auto-RAG path retrieve image-derived text exactly like text-document chunks.

**Success criterion** (user-verifiable in the morning):

- Drag a JPG/PNG containing readable English text into the chat input.
- Upload succeeds (no 4xx in the network panel).
- Ask the chat "what does the image say?" or run a `search_knowledge_base` tool call for a phrase from the image. The relevant excerpt appears in retrieval results.

## Non-goals (MVP)

- **Multimodal embeddings (CLIP, jina-clip-v2).** Out of scope. v2 work; would require a `kind` discriminator on `document_chunks` and a parallel embed model in `llm-swap-config.yaml`.
- **Original-file persistence + thumbnails.** Out of scope. Persisting binary uploads requires a `storage_path` column on `documents` (Alembic migration) plus a static-file serving endpoint. Deferred to a separate, properly-scoped PR. See "Follow-ups."
- **PDF, DOCX, Markdown ingest.** Mentioned in the same future-features item but distinct work; handled in their own PRs.
- **Backend containerization.** Decided separately. The OCR engine choice here (rapidocr-onnxruntime, pure-Python) deliberately avoids forcing that decision tonight; see "OCR engine selection" below.

## OCR engine selection

The original task brief suggested Tesseract via `pytesseract`. After verification:

- Tesseract isn't installed on the dev host, and `apt install tesseract-ocr` requires sudo, which isn't available in the autonomous session.
- Tesseract on Windows is supported but requires a separate installer (UB Mannheim build) and `tesseract_cmd` configuration. That moves the "works on a fresh clone" bar to "user installs system-level OCR binary first," which the user has flagged as undesirable.
- The most-portable alternative is `rapidocr-onnxruntime` — a pip-installable, ONNX-Runtime-based OCR engine (port of PaddleOCR detection + recognition models to ONNX). Pure pip. Wheels for Linux/macOS/Windows. Models (~30 MB) auto-download into the package cache on first use.

**Decision: rapidocr-onnxruntime, isolated behind a single-function seam.**

`backend/services/ocr.py` exposes one function:

```python
def extract_text(image_bytes: bytes) -> str:
    """Return concatenated recognized text. Empty string if none found."""
```

Callers (today: `/upload`; tomorrow: any tool) only see the seam. Swapping to Tesseract — once the backend gets containerized and `apt install tesseract-ocr` becomes a Dockerfile line — is a one-file change inside `services/ocr.py`. No call-site touches. This explicitly preserves the cross-platform "clone + pip install + npm install + docker compose up" bootstrap shape.

**Trade-off acknowledged:** Tesseract is the de-facto best general-purpose OCR for printed Latin text and has a longer track record. rapidocr-onnxruntime is competitive on screenshots, signage, and short-text images (the dominant use case for an IT copilot — error dialog screenshots, device labels). For long-form scanned documents the gap matters more; that's a v2 problem (multimodal models will likely supersede pure-OCR anyway).

## Architecture

```
                 +------------------+
                 |   /upload (POST) |  routers/chat.py
                 +--------+---------+
                          |
                          | content_type sniff
                          v
       +-------------------------------------------+
       |    image/*  ?                             |
       +--------+----------------------+-----------+
                | yes                  | no
                v                      v
   +------------------------+   +---------------+
   |  services/ocr.py       |   |  decode UTF-8 |
   |  extract_text(bytes)   |   |  (existing)   |
   +----------+-------------+   +------+--------+
              |                        |
              +-----------+------------+
                          |
                          v
            services/knowledge.py
            ingest_document(client, db, filename, content=...)
                          |
                          v
                  Document + DocumentChunk rows
                  (unchanged path)
```

The image branch's single new piece is `services/ocr.py`. Everything downstream of `ingest_document(...)` is untouched.

## Components

### `backend/services/ocr.py` — new

- One public function: `extract_text(image_bytes: bytes) -> str`.
- Internally: load rapidocr's `RapidOCR` engine lazily (first call constructs; subsequent calls reuse). The constructor is heavy (loads ONNX models into memory ~30 MB), so a module-level singleton via `functools.lru_cache(maxsize=1)` is appropriate.
- Bytes → numpy array via Pillow (`Image.open(BytesIO(bytes))` → `.convert("RGB")` → `numpy.asarray`).
- `engine(np_image)` returns `(results, elapsed)`. `results` is a list of `[bbox, text, confidence]` or `None`. We concatenate `text` fragments with `\n`, preserving reading order top-to-bottom.
- Raises `ocr.InvalidImage` if Pillow fails to decode (caller maps to HTTP 400).
- Returns `""` if OCR ran but found no text.

### `backend/routers/chat.py::upload_document` — modified

- Branch on `file.content_type`:
  - `image/jpeg`, `image/png`, `image/webp` → call `ocr.extract_text(content)`, use the returned text as the document body.
  - Anything else → existing UTF-8 decode path.
- If the OCR result is empty (after `.strip()`), return HTTP 422 with `detail="No text could be extracted from this image."`. The caller does NOT create a Document row in this case; nothing to retrieve later means nothing to ingest.
- The rest of the function (size cap, session lookup, `ingest_document` call, response shape) is unchanged.

### `backend/config.py::Settings` — modified

- Bump `UPLOAD_MAX_BYTES` from `100 * 1024` (100 KiB) to `10 * 1024 * 1024` (10 MiB). Single knob. Side-effect: text uploads can also be 10 MiB now; this is fine — chunking handles it, and a stream-bail at 10 MiB is still cheap memory-wise.
- Rationale for single knob over a separate `UPLOAD_IMAGE_MAX_BYTES`: minimal tech debt. Two knobs would invite divergence and complicate the streaming-bail logic. 10 MiB is a generous ceiling for both modes.

### `backend/requirements.txt` — modified

- Add `Pillow==12.2.0`.
- Add `rapidocr-onnxruntime==1.4.4`.

(Pin to current latest; existing requirements pattern uses exact-version pins.)

### `frontend/src/components/ChatInput.tsx` — modified

- Extend `validExts` to include `.jpg`, `.jpeg`, `.png`, `.webp`. That's the entire UI change — the existing `useUploader` POST path uses FormData and doesn't care about MIME.

## Error paths

| Condition | Response |
|---|---|
| File > 10 MiB | HTTP 413 (existing path) |
| Image bytes don't decode | HTTP 400 "Image bytes could not be decoded as a valid image." |
| OCR ran but found no text | HTTP 422 "No text could be extracted from this image." |
| OCR engine model download fails (first-run, offline) | HTTP 500, surface upstream error message |
| Non-image, non-UTF-8 file | HTTP 400 (existing path) |

The 422-on-empty-OCR is the only behavior shift worth flagging: a successful upload returning a 4xx is a small UX inversion, but it's correct — we are refusing to create a knowledge document that has no content to retrieve. Frontend already renders `errorMessage` on a failed upload card, so this surfaces gracefully.

## Testing

Two layers:

### Unit test: `backend/tests/test_ocr.py` (new)

- Use Pillow's `ImageDraw` to render a PNG in memory containing a known string ("PRYZM OCR TEST").
- Encode as PNG bytes.
- Call `ocr.extract_text(bytes)`.
- Assert `"PRYZM" in result.upper()` (case-insensitive substring is robust against minor recognition variance).

This test is fully self-contained — no fixture file in git, no external network. It will trigger the first-time model download (~30 MB) on CI / fresh clone; that's a one-time cost cached in the rapidocr package directory.

### Integration test: `backend/tests/test_image_upload.py` (new)

- Spin up `TestClient(app)` with the existing DB fixture.
- Generate a known-text PNG in-memory.
- POST it to `/upload` with `file=("test.png", bytes, "image/png")` and `workspace="it_copilot"`.
- Assert HTTP 200 and a `document_id` in the response.
- Query `DocumentChunk` rows for that document — assert at least one chunk and that one chunk's `content` contains the known string.

The `test_ocr.py` unit test runs without DB/LLM dependencies. `test_image_upload.py` requires the existing test DB fixture and the LLM server for embedding (matches the existing test pattern for the upload endpoint).

### Manual smoke

Beyond unit/integration: drop a real-world JPG screenshot into the chat input on the running dev stack, verify it ingests and is retrievable via a chat question. Captured via a `pryzm_autotest.py` probe extension in the morning if time permits.

## Performance notes

- First OCR call after backend boot: ~2-4s (model load).
- Subsequent calls: ~0.3-1.5s for a typical screenshot. Dominated by image dimensions; rapidocr resizes internally.
- Memory: rapidocr engine holds ~150 MB resident once loaded. Acceptable for the single-user dev setup; not great for a multi-tenant production deployment (would want a separate inference process pool, but that's a future concern alongside backend containerization).
- The `/upload` endpoint blocks the event loop for the duration of `extract_text` because `RapidOCR.__call__` is sync CPU work. Real impact is small (1-2s per upload). If this becomes a concern, wrap in `asyncio.to_thread(...)`. **Doing this in v1**: yes — cheap insurance, single line.

## Follow-ups (do not include in this PR)

1. **Original-file persistence + thumbnail rendering.** Requires `storage_path` column on `documents` (migration), a static-file endpoint, and a small UI change to show a thumbnail next to image-derived knowledge entries. Maybe ~1 day. Filed as a successor to this spec.
2. **Multimodal embeddings.** CLIP / jina-clip-v2 path. Different shape of work — fits inside the broader Item 5 plan.
3. **Tesseract swap once backend is containerized.** Modify `services/ocr.py` only. The Dockerfile adds `RUN apt-get install -y tesseract-ocr` and `services/ocr.py` switches to pytesseract. Call sites untouched.
4. **OCR language packs.** rapidocr ships English models by default. Multi-language requires explicit model selection in the engine constructor. File as a config-only follow-up.
5. **Async ingestion for large images.** Spin off to a background task and return immediately. Only worth doing once an upload-progress UI surface exists.

## Open questions for the user (review on wake)

None blocking. Decisions made during this session that are worth a quick second look:

- **OCR engine: rapidocr-onnxruntime instead of Tesseract.** Captured in detail under "OCR engine selection."
- **No original-file persistence in v1.** Deferred to its own PR with a proper schema migration.
- **UPLOAD_MAX_BYTES bumped to 10 MiB globally.** Single knob, applies to text uploads too.
- **422 (not 200) on empty-OCR-result uploads.** Refuses to create empty knowledge docs.

Each is a sensible default; redirect any of them and the change is small.
