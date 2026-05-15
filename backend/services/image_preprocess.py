"""Light image preprocessing before sending bytes to the captioning VLM.

The pipeline output is unchanged on already-good images. Two transforms:

  1. Bicubic upscale to ~1024 on the long side if smaller. Small phone
     screenshots get more pixels per character, which helps the VLM
     read identifier-class fields (usernames, IDs) it would otherwise
     misread.
  2. Auto-contrast via PIL's histogram-stretch. No-op on already-good
     images; helps dim screenshots.

The bytes we PERSIST to disk are still the original — preprocessing
is in-memory only, so the on-disk file matches what the user uploaded.
"""
from __future__ import annotations

import io

from PIL import Image, ImageOps


_TARGET_LONG_SIDE = 1024
_UPSCALE_CAP = 2.0
_PIL_FORMAT_BY_MIME = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
}


def prepare_for_vlm(content: bytes, mime: str) -> bytes:
    """Return preprocessed image bytes in the same MIME as the input.

    Unknown MIMEs pass through unchanged — the upload route's MIME
    gate handles rejection upstream; we don't need to second-guess here.
    """
    pil_format = _PIL_FORMAT_BY_MIME.get(mime)
    if pil_format is None:
        return content

    try:
        img = Image.open(io.BytesIO(content))
        img.load()
    except Exception:
        # Corrupt / unreadable image — let the VLM call itself fail
        # rather than swallowing it here.
        return content

    # JPEG doesn't carry alpha; convert RGBA → RGB so the re-encode
    # doesn't error. Keep palette images as-is until the upscale step,
    # which converts them to RGB anyway.
    if pil_format == "JPEG" and img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGB")

    img = _upscale_if_small(img)
    img = ImageOps.autocontrast(img)

    out = io.BytesIO()
    save_kwargs: dict = {}
    if pil_format == "JPEG":
        save_kwargs = {"quality": 92, "optimize": True}
    elif pil_format == "PNG":
        save_kwargs = {"optimize": True}
    img.save(out, format=pil_format, **save_kwargs)
    return out.getvalue()


def _upscale_if_small(img: Image.Image) -> Image.Image:
    """Bicubic upscale to TARGET_LONG_SIDE if max(w,h) < TARGET.
    Capped at 2× the original — anything more produces artifacts that
    hurt VLM accuracy more than the resolution gain helps."""
    w, h = img.size
    long_side = max(w, h)
    if long_side >= _TARGET_LONG_SIDE:
        return img

    scale = min(_TARGET_LONG_SIDE / long_side, _UPSCALE_CAP)
    new_size = (max(1, round(w * scale)), max(1, round(h * scale)))
    # Convert palette/grayscale to a mode bicubic can handle cleanly.
    if img.mode == "P":
        img = img.convert("RGB")
    return img.resize(new_size, Image.Resampling.BICUBIC)
