# VLM Milestone 2 — Original-File Persistence (Plan)

- **Date**: 2026-05-15
- **Spec**: `docs/specs/2026-05-15-image-upload-vlm.md` (Milestone 2 section)
- **Branch**: `feat/vlm-image-storage` from `main` at `9a300bf`

## Scope

Image uploads now persist the original bytes on disk. The Document row carries a `storage_path` pointing at the file. Milestone 3 will read this back to re-attach the image at chat time.

**Not in this PR:** the re-attach itself (M3), any UI surface for thumbnails (filed as a follow-up in the spec).

## Steps

| # | Step | Verify |
|---|---|---|
| 1 | Alembic migration `b4fac9a8c30f` adds `documents.storage_path VARCHAR(512) NULL`. | `alembic upgrade head` + `\d documents` shows the column. |
| 2 | `db/models.Document.storage_path` mirrors the column. After-delete listener at the bottom of `db/models.py` removes the on-disk file when the row goes away. | Unit test deletes a Document and asserts the file is gone. |
| 3 | New module `services/image_storage.py` with `save_image(bytes, mime) -> str`. Lives under `backend/data/uploads/`; filename is a UUID, extension derived from MIME. | Unit test asserts file written + path returned. |
| 4 | `services/knowledge.py::ingest_document` gains `storage_path: str \| None = None`. Passed through to the Document constructor. | Unit test asserts the value lands on the row. |
| 5 | `routers/chat.py::upload_document` calls `image_storage.save_image` for image content, then passes the result to `ingest_document`. Done AFTER captioning so a failed caption doesn't leak files. | Live smoke: upload a JPG, check `documents.storage_path` is set and the file exists. |
| 6 | Migration tests: upgrade adds column, downgrade drops it, pre-existing rows get NULL on upgrade. | 3 tests green. |
| 7 | Integration tests: ingest_document writes the path; save_image's MIME gate works; after_delete cleans up. | 4 new tests green. |
| 8 | Full suite green. | 135/135 unit tests pass (was 128 in M1). |
| 9 | Live smoke + delete cleanup. | File at the expected path after upload; file gone after Document delete. |
| 10 | Commit, PR, auto-merge. | Merged. |

## Risks / unknowns

- **File path encoding.** `storage_path` is `VARCHAR(512)`; absolute paths exceeding 512 chars would truncate. Realistic max is ~120 chars on the current scheme (`<repo>/backend/data/uploads/<32-hex>.<3-letter>`). Acceptable.
- **Orphaned files on partial failures.** If the DB commit fails after `save_image` succeeded, the file is orphaned. Acceptable for this iteration; an admin sweep is a possible follow-up. (Inverse risk — leftover files — is bigger than the inverse — leftover rows pointing at missing files — which we handle gracefully in M3 with a fallback.)
- **Transaction rollback after delete.** SQLAlchemy's `after_delete` fires before the transaction commits. If the surrounding transaction rolls back, the row stays but the file is gone. Documented in the listener comment; acceptable since the inverse (orphan files) is the more common failure mode.

## Done when

- All 10 steps green.
- Live smoke confirms persistence + cleanup.
- PR description is a 6-line release note.
