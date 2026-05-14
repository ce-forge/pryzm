"""Single-engine OCR seam.

Callers see one function: `extract_text(image_bytes) -> str`. The engine
is currently rapidocr-onnxruntime (pure-pip, ONNX-Runtime-based). Swapping
to Tesseract (or any other engine) is an internal change — call sites
don't move.
"""
from __future__ import annotations

from functools import lru_cache
from io import BytesIO

import numpy as np
from PIL import Image, UnidentifiedImageError


class InvalidImage(Exception):
    """Raised when bytes can't be decoded as an image."""


@lru_cache(maxsize=1)
def _engine():
    from rapidocr_onnxruntime import RapidOCR
    return RapidOCR()


def extract_text(image_bytes: bytes) -> str:
    """Recognize text in an image. Returns concatenated fragments in
    reading order, separated by newlines. Returns "" if no text is found.

    Raises InvalidImage when the bytes are not a decodable image.
    """
    try:
        img = Image.open(BytesIO(image_bytes)).convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise InvalidImage(str(exc)) from exc

    np_img = np.asarray(img)
    results, _elapsed = _engine()(np_img)
    if not results:
        return ""
    return "\n".join(text for _bbox, text, _conf in results)
