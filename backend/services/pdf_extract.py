"""PDF text-extraction seam.

Same shape as `services/image_describe.py`: one function the upload
endpoint can call with raw bytes, returns the text that gets chunked
and embedded into RAG. Implementation uses `pypdf` (pure-Python, MIT,
no system deps).

Scope is text-only PDFs. Scanned PDFs (image-as-page) yield empty
text here and bubble up as a 422 from /upload — OCR-via-render is a
future enhancement. Page count is capped to avoid pathological inputs
hanging the worker; the cap lives in config so it's tunable.
"""
from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError, PyPdfError

from config import settings


class InvalidPdf(Exception):
    """Raised when bytes can't be parsed as a PDF."""


def extract_text(pdf_bytes: bytes) -> str:
    """Extract plain text from `pdf_bytes`. Returns the empty string
    if the PDF has no extractable text (scanned/image PDFs are the
    common case here — caller maps empty → HTTP 422).

    Pages beyond `settings.PDF_EXTRACT_PAGE_LIMIT` are ignored to bound
    worst-case extraction time on hostile inputs.
    """
    try:
        reader = PdfReader(BytesIO(pdf_bytes))
    except (PdfReadError, PyPdfError, OSError) as exc:
        raise InvalidPdf(str(exc)) from exc

    limit = settings.PDF_EXTRACT_PAGE_LIMIT
    parts: list[str] = []
    for page in reader.pages[:limit]:
        try:
            text = page.extract_text() or ""
        except Exception:
            # A single malformed page shouldn't kill the whole extract.
            text = ""
        text = text.strip()
        if text:
            parts.append(text)
    return "\n\n".join(parts)
