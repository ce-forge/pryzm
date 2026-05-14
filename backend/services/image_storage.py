"""Tiny on-disk store for uploaded images.

VLM Milestone 2: image bytes are saved alongside the Document row so
ai_engine can re-attach the original to the LLM call when an
image-derived chunk is selected by RAG (Milestone 3).

Path scheme: backend/data/uploads/<uuid>.<ext>.
- The UUID is generated here, independent of the Document id, so the
  caller can save the file before the Document row exists. The linkage
  is via Document.storage_path.
- The directory is created lazily on first save.
- Deletes run via a SQLAlchemy after_delete event listener on Document
  (see db/models.py); this module exposes only save_image. Keep the
  delete-side close to the row lifecycle, not here.
"""
from __future__ import annotations

import base64
import os
import uuid

# Module-level constant: where the uploads live. Computed once at import,
# absolute path, so the same value is used regardless of which directory
# the FastAPI worker process was launched from.
_UPLOADS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "uploads")
)

# Map supported MIME -> extension. The /upload router enforces the same
# set; if a new image type lands later it gets added in both places.
_MIME_TO_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


def save_image(image_bytes: bytes, mime: str) -> str:
    """Write `image_bytes` to disk under data/uploads/, return the absolute
    path. Caller (the upload endpoint) is expected to validate `mime` first.

    Raises ValueError if `mime` isn't one we know how to give an extension
    to — keeps unknown extensions out of the upload dir.
    """
    if mime not in _MIME_TO_EXT:
        raise ValueError(f"Unsupported image MIME for storage: {mime}")

    os.makedirs(_UPLOADS_DIR, exist_ok=True)
    name = f"{uuid.uuid4().hex}{_MIME_TO_EXT[mime]}"
    path = os.path.join(_UPLOADS_DIR, name)
    with open(path, "wb") as f:
        f.write(image_bytes)
    return path


# Inverse of _MIME_TO_EXT used by the re-attach path (Milestone 3): the
# Document only carries a path; the MIME has to be re-derived from the
# extension on disk. Keep the two tables next to each other so they
# can't drift.
_EXT_TO_MIME = {ext: mime for mime, ext in _MIME_TO_EXT.items()}


def read_as_data_url(path: str) -> str | None:
    """Read an image file from disk and return a base64 data URL of the
    form `data:image/png;base64,…`. Returns None if the file is missing
    or has an unsupported extension — caller decides what to do.

    Used by ai_engine to re-attach the original bytes to the LLM call
    when RAG selects an image-derived chunk.
    """
    if not path or not os.path.exists(path):
        return None
    ext = os.path.splitext(path)[1].lower()
    mime = _EXT_TO_MIME.get(ext)
    if not mime:
        return None
    with open(path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("ascii")
    return f"data:{mime};base64,{encoded}"
