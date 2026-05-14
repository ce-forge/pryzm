# VLM Milestone 1 — Caption Swap (Plan)

- **Date**: 2026-05-15
- **Spec**: `docs/specs/2026-05-15-image-upload-vlm.md` (Milestone 1 section)
- **Branch**: `feat/vlm-caption-swap` from `main` at `4b40c6d`

## Scope

Replace the rapidocr-based image ingestion path landed in PR #21 with VLM captioning via the existing Gemma-4 multimodal capability. Functional parity (uploaded images become searchable text); higher caption quality; smaller dependency footprint.

**Not in this PR:** original-file persistence (M2), ai_engine re-attach at chat time (M3), speculative-decoding draft model (separate follow-up).

## Steps

| # | Step | Verify |
|---|---|---|
| 1 | Mark the OCR spec superseded at the top of `docs/specs/2026-05-15-image-upload-ocr.md`. | Diff shows one-line Status update. |
| 2 | Write the VLM spec (already done). | File exists at `docs/specs/2026-05-15-image-upload-vlm.md`. |
| 3 | Add a config knobs block (`IMAGE_CAPTION_MODEL`, `IMAGE_CAPTION_MAX_TOKENS`, `IMAGE_CAPTION_TEMPERATURE`) to `backend/config.py`. | Settings load without error. |
| 4 | Write `backend/services/image_describe.py` — `describe(client, image_bytes, mime) -> str`. Posts to `llm_server.chat` with the image as a base64 `data:` URL. Falls back to `reasoning_content` if `content` is empty. Raises `InvalidImage` on unsupported MIME. | Module imports cleanly. |
| 5 | Update `backend/routers/chat.py` to use `image_describe` in place of `ocr`. Drop the local MIME allowlist (lives in the seam now). | `grep ocr backend/routers/` returns nothing. |
| 6 | Drop `Pillow` and `rapidocr-onnxruntime` from `backend/requirements.txt`. Uninstall from venv. | `pip list` no longer lists either. |
| 7 | Delete `backend/services/ocr.py` and `backend/tests/test_ocr.py`. | Files gone. |
| 8 | Write `backend/tests/test_image_describe.py` — 4 cases: payload shape, reasoning_content fallback, empty caption, unsupported MIME. | `pytest tests/test_image_describe.py` green. |
| 9 | Rewrite `backend/tests/test_image_upload.py` — three cases, all mocking `llm_server.chat` / `llm_server.embed` so the tests stay hermetic. | `pytest tests/test_image_upload.py` green. |
| 10 | Drop the "vision is reserved" comment in `infra/llama-swap-config.yaml`. Add `tags: ["vision"]` to both E2B and E4B model rows. | YAML parses; `test_build_catalog_from_real_yaml` updated to assert the new tag. |
| 11 | Live smoke: POST a JPG to `/upload`, verify 200 + chunk created with a captioned description. | Round-trip green; chunk text describes the image. |
| 12 | Live smoke: POST an `image/tiff`, verify 400 with "Unsupported image MIME". | Got 400 with correct message. |
| 13 | Run full unit suite. | 128/128 pass (was 127 before; net +1 from new tests minus deleted test_ocr.py). |
| 14 | Commit, push, open PR, auto-merge per the user's authorization at major milestones. | PR merged into main. |

## Risks / unknowns

- **Cold E4B swap-in.** When E4B isn't currently in VRAM, the first captioning call pays a swap-in cost (~10-30s on the user's hardware). Surfaced in the spec; acceptable for upload UX. Not in scope to fix in M1.
- **`reasoning_content` routing.** Gemma 4's thinking mode sometimes puts the answer in `reasoning_content`. Mitigated by (a) an explicit "no preamble, no thinking out loud" system prompt, and (b) a defensive fallback in `describe`. Tested.
- **Token cost.** Captions average ~300 tokens. For very busy uploaders this could exhaust context windows in long sessions; not an M1 concern.

## Done when

- All 14 steps green.
- Live smoke shows a real image → real caption → real chunk in DB.
- PR description is a 6-line release note per project convention.
