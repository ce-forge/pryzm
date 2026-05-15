"""Local OCR engine for verbatim text extraction from images.

The VLM captioner (services/image_describe.py) is good at understanding
what an image IS — UI structure, layout, what kind of screen, what
fields are visible — but its character-level reading falls into
language-prior pattern completion on camera-of-screen photos. A clear
"admin" gets read as "admin.n" because the model's IT-corpus prior is
strong on `firstname.lastname` username conventions.

RapidOCR (wrapping PaddleOCR via ONNX runtime) reads characters from
pixels without language priors. For identifier-class fields where
character-perfect accuracy matters (usernames, IDs, error codes, IP
addresses), this is the canonical source of truth.

The captioning pipeline runs OCR and VLM in parallel; the merged caption
keeps text under "EXTRACTED TEXT (OCR)" and structure under "CONTEXT".
There's exactly one place verbatim text lives, so the chat-time LLM
can't surface ambiguous "X or Y" readings to the user.
"""
from __future__ import annotations

import io
import logging
import threading
import time
from typing import Optional

from PIL import Image

_logger = logging.getLogger(__name__)


# RapidOCR's first-call initialization loads the detection + recognition
# models (~50MB onnx total). Lazy-load + thread-locked so the first
# upload pays the cost once; subsequent uploads reuse the instance.
_ocr_instance = None
_ocr_lock = threading.Lock()


def _get_engine():
    global _ocr_instance
    if _ocr_instance is None:
        with _ocr_lock:
            if _ocr_instance is None:
                from rapidocr_onnxruntime import RapidOCR
                _ocr_instance = RapidOCR()
    return _ocr_instance


def extract_text(image_bytes: bytes, mime: str) -> Optional[str]:
    """Run OCR on the image bytes. Returns extracted text as a single
    string with newlines preserving rough layout, or None if OCR
    fails / finds nothing.

    Never raises — the captioning pipeline must always have a path
    forward, even if OCR misbehaves. Failure modes return None and
    log at WARN; the caller falls back to the VLM-with-verbatim-prompt
    path.

    Runs synchronously (CPU-bound). Callers in async context should
    invoke via asyncio.to_thread.
    """
    if mime not in ("image/jpeg", "image/png", "image/webp"):
        return None
    started = time.perf_counter()
    try:
        # Normalize to RGB PNG bytes — RapidOCR is robust to formats
        # but normalization avoids surprising failures on rarely-seen
        # JPEG variants (CMYK, progressive with odd subsampling).
        img = Image.open(io.BytesIO(image_bytes))
        img.load()
        if img.mode != "RGB":
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        engine = _get_engine()
        result, _elapse = engine(buf.getvalue())
    except Exception as e:
        _logger.warning("ocr_extract: failed: %s", e)
        return None

    if not result:
        _logger.info("ocr_extract: no text detected (elapsed=%.2fs)", time.perf_counter() - started)
        return None

    # Result shape: [(bbox, text, confidence), ...]. Sort by y-coord
    # (top-of-bbox) for rough top-to-bottom reading order, then x for
    # within-line left-to-right. Threshold confidence at 0.5 to drop
    # garbage detections; legitimate UI text usually clears 0.85+.
    rows = []
    for bbox, text, confidence in result:
        if confidence < 0.5:
            continue
        if not text.strip():
            continue
        y_top = min(p[1] for p in bbox)
        x_left = min(p[0] for p in bbox)
        rows.append((y_top, x_left, text.strip()))

    if not rows:
        _logger.info("ocr_extract: all detections below confidence threshold")
        return None

    # Output each detected text segment on its own line, sorted by
    # (y, x) for top-to-bottom-then-left-to-right reading order. We do
    # NOT try to merge same-Y detections into "lines" — that broke
    # multi-column forms (e.g. sidebar items + main-panel form values
    # at the same vertical position got mashed together, hiding the
    # value-label relationship from the LLM downstream).
    #
    # Keeping each detection on its own line lets the LLM associate
    # labels with nearby values via proximity in the text stream.
    # Real layout reconstruction (column detection, table parsing) is
    # a deeper change handled by layout-aware OCR engines if needed.
    rows.sort()
    out_lines = [text for _, _, text in rows]

    elapsed = time.perf_counter() - started
    text_out = "\n".join(out_lines)
    _logger.info(
        "ocr_extract: detected %d lines (%d chars) in %.2fs",
        len(out_lines), len(text_out), elapsed,
    )
    # Full text content at INFO so the dev can grep backend logs and
    # see exactly what OCR captured. Indispensable for diagnosing
    # "the OCR gave crappy text" — without this we'd be guessing.
    _logger.info("ocr_extract: text content:\n%s", text_out)
    return text_out
