# Image Upload + OCR — Implementation Plan

- **Date**: 2026-05-15
- **Spec**: `docs/specs/2026-05-15-image-upload-ocr.md`
- **Branch**: `feat/image-upload-ocr` cut from `main` at 851db2e
- **Target**: single PR, mergeable end-to-end

## Karpathy guardrails for this plan

- **Think:** decisions are recorded in the spec; this plan executes them. If a step surfaces a contradiction with the spec, stop and revise the spec, do not silently improvise.
- **Simplicity first:** OCR seam is one function; one new file; no engine-abstract-base-class; no plugin registry. Add abstraction only when the second engine arrives.
- **Surgical:** every changed line traces to "ingest an image as text via OCR." No drive-by formatting, no unrelated refactor of `upload_document`.
- **Goal-driven:** each step has a verifiable check. Don't mark done until the check passes.

## Step 1 — Add OCR dependencies, verify they install

**Files:** `backend/requirements.txt`

**Change:** append two pinned lines:

```
Pillow==12.2.0
rapidocr-onnxruntime==1.4.4
```

**Verify:**

```bash
cd backend && venv/bin/pip install -r requirements.txt
venv/bin/python -c "from rapidocr_onnxruntime import RapidOCR; print(RapidOCR.__module__)"
```

Both lines should succeed; the import should print a module path. Expected wheel size: rapidocr ~30 MB ONNX models cached on first construction (not at import).

## Step 2 — Write the OCR seam

**Files:** `backend/services/ocr.py` (new)

**Shape:**

- `InvalidImage(Exception)` — raised on Pillow decode failure.
- `_engine()` — `@lru_cache(maxsize=1)` factory returning a `RapidOCR` instance.
- `extract_text(image_bytes: bytes) -> str` — bytes → Pillow → numpy RGB → `_engine()(np)` → `\n`.join recognized text fragments. Returns `""` if none found.

**Verify:**

Standalone:

```python
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
from services.ocr import extract_text
img = Image.new("RGB", (400, 100), "white")
ImageDraw.Draw(img).text((10, 30), "PRYZM OCR TEST", fill="black")
buf = BytesIO(); img.save(buf, format="PNG")
text = extract_text(buf.getvalue())
assert "PRYZM" in text.upper(), f"got: {text!r}"
print("ok:", text)
```

Run from `backend/` with venv active. Pass = string contains "PRYZM".

## Step 3 — Unit test: `backend/tests/test_ocr.py`

**Files:** `backend/tests/test_ocr.py` (new)

**Tests:**

- `test_extract_text_finds_rendered_string` — generate a known-text PNG, assert substring.
- `test_extract_text_empty_on_blank_image` — pure white PNG returns `""`.
- `test_extract_text_raises_on_invalid_bytes` — `b"not an image"` → `InvalidImage`.

**Verify:**

```bash
cd backend && venv/bin/pytest tests/test_ocr.py -v
```

All three pass. First run will download rapidocr ONNX models (~30 MB) one time.

## Step 4 — Wire `/upload` to branch on content type

**Files:** `backend/routers/chat.py`

**Change in `upload_document`:**

After the streamed-read block produces `content: bytes`, branch:

```python
if (file.content_type or "").startswith("image/"):
    if file.content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(400, detail=f"Unsupported image type: {file.content_type}")
    try:
        text_content = await asyncio.to_thread(ocr.extract_text, content)
    except ocr.InvalidImage:
        raise HTTPException(400, detail="Image bytes could not be decoded as a valid image.")
    if not text_content.strip():
        raise HTTPException(422, detail="No text could be extracted from this image.")
else:
    try:
        text_content = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Only UTF-8 text files are currently supported.")
```

Wrap rapidocr's sync work in `asyncio.to_thread` so the event loop isn't blocked. Add `import asyncio` and `from services import ocr` at the top of the file (alongside the existing `from services import knowledge`).

**Verify:** unit-level — none. The integration test in Step 6 covers this path end-to-end.

## Step 5 — Bump UPLOAD_MAX_BYTES

**Files:** `backend/config.py`

**Change:** one line.

```python
UPLOAD_MAX_BYTES: int = 10 * 1024 * 1024  # 10 MiB — accommodates image uploads (was 100 KiB, text-only)
```

**Verify:** included in Step 6 integration test (image fixture > 100 KiB sanity).

## Step 6 — Integration test: `backend/tests/test_image_upload.py`

**Files:** `backend/tests/test_image_upload.py` (new)

**Tests:**

- `test_image_upload_creates_searchable_document` — generate PNG with "ROUTER ENERGY 12345", POST to `/upload`, assert 200, then query `DocumentChunk` and assert "ROUTER" substring present.
- `test_blank_image_rejected_422` — pure white PNG → 422.
- `test_unsupported_image_type_rejected_400` — `content_type="image/tiff"` → 400.

The test uses the existing `db_session` and `client` fixtures (or constructs a `TestClient(app)` directly per the existing pattern for upload tests; check what `test_async_analyze.py` does).

**Verify:**

```bash
cd backend && venv/bin/pytest tests/test_image_upload.py -v
```

All three pass. Requires the embed model in llama-swap to be up (existing test prerequisite).

## Step 7 — Frontend MIME accept

**Files:** `frontend/src/components/ChatInput.tsx`

**Change in `processFiles`:**

```diff
- const validExts = [".txt", ".md", ".py", ".csv", ".json", ".log", ".yaml", ".yml", ".conf", ".ini"];
+ const validExts = [".txt", ".md", ".py", ".csv", ".json", ".log", ".yaml", ".yml", ".conf", ".ini", ".jpg", ".jpeg", ".png", ".webp"];
```

That's the entire change. The `<input type="file" multiple>` already accepts any file; we filter by extension after selection. No `accept=` attribute change needed (we already accept all and validate post-hoc).

**Verify:** open the running frontend, click the paperclip, pick a PNG, observe that the upload card shows "uploading" not "Unsupported format."

## Step 8 — End-to-end smoke

Use `/tmp/pryzm_autotest.py` (or a small ad-hoc script) to:

1. POST a generated PNG with known text to `/upload`.
2. Assert 200 + a `document_id`.
3. POST a chat message to `/analyze` that includes a question whose answer requires the OCR'd text. Verify the response either calls `search_knowledge_base` or includes the known string.

If 1+2 pass, that's the load-bearing check. Step 3 is nice-to-have; if flaky (LLM nondeterminism), drop it and rely on the unit + integration tests.

## Step 9 — PR

- Confirm `git diff --stat` matches the per-step file list — no drift.
- Confirm `venv/bin/pytest tests/` (full unit suite) is no worse than baseline (note: `test_llm_metrics` is pre-existing flaky in combined runs; that's a separate task).
- Commit, push branch, open PR with a 6-line release-notes-style description per project convention.
- Auto-merge gate per the autonomous-mode authorization:
  - Unit tests pass ✓
  - Integration tests pass ✓
  - No migrations involved ✓
  - No auth/CORS/credential surface touched ✓
  - → auto-merge

## File summary

| File | Change |
|---|---|
| `backend/requirements.txt` | +2 lines |
| `backend/services/ocr.py` | new (~30 lines) |
| `backend/config.py` | 1-line bump |
| `backend/routers/chat.py` | ~12-line branch in `upload_document` + 2 imports |
| `frontend/src/components/ChatInput.tsx` | 1-line extension of `validExts` |
| `backend/tests/test_ocr.py` | new (~40 lines) |
| `backend/tests/test_image_upload.py` | new (~60 lines) |
| `docs/specs/2026-05-15-image-upload-ocr.md` | new (committed in same PR) |
| `docs/plans/2026-05-15-image-upload-ocr.md` | new (committed in same PR) |

Approximate diff: ~200 lines added, ~5 lines modified across 5 existing files.

## Risks and mitigations

- **First-call latency.** OCR engine cold-load adds 2-4s to the first upload after backend boot. Mitigation: documented; not blocking the spec.
- **Model download on CI.** First test run downloads ONNX models. Mitigation: rapidocr caches under the package install; subsequent runs are free. CI runners get one slow run; acceptable.
- **Sync OCR blocking the event loop.** Mitigated by `asyncio.to_thread`.
- **rapidocr breaking change.** Pinned to 1.4.4. Bumping is opt-in.
- **Embed model down during test.** Same risk the existing upload tests already have; not new.
