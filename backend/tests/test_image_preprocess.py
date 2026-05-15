"""Unit tests for image preprocessing applied before VLM captioning."""
from __future__ import annotations

import io

from PIL import Image, ImageDraw

from services import image_preprocess


def _make_jpeg(width: int, height: int, brightness_range: tuple[int, int] = (0, 255)) -> bytes:
    """Synthesize a JPEG of the given size with a brightness gradient
    that ranges over `brightness_range`. The narrower the range, the
    more headroom autocontrast has to stretch."""
    lo, hi = brightness_range
    img = Image.new("RGB", (width, height), color=(lo, lo, lo))
    d = ImageDraw.Draw(img)
    # Diagonal gradient: row 0 is lo, last row is hi.
    for y in range(height):
        v = lo + int((hi - lo) * (y / max(1, height - 1)))
        d.line([(0, y), (width - 1, y)], fill=(v, v, v))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=92)
    return out.getvalue()


def _open(b: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(b))
    img.load()
    return img


def test_small_image_is_upscaled_to_target_long_side():
    """200x100 → 1024x512 (2x cap allows 200→400; target wants 1024;
    cap wins for very small images)."""
    raw = _make_jpeg(200, 100)
    out = image_preprocess.prepare_for_vlm(raw, "image/jpeg")
    w, h = _open(out).size
    # 200 * 2x cap = 400 long side. The 1024 target is gated by the
    # 2x cap, so the upscaled image is exactly 2x.
    assert max(w, h) == 400, (w, h)
    assert min(w, h) == 200, (w, h)


def test_medium_image_upscales_to_target():
    """800x600 → 1024x768. Scale 1.28x, under the 2x cap."""
    raw = _make_jpeg(800, 600)
    out = image_preprocess.prepare_for_vlm(raw, "image/jpeg")
    w, h = _open(out).size
    assert max(w, h) == 1024, (w, h)
    # Aspect ratio preserved within rounding.
    assert abs((w / h) - (800 / 600)) < 0.01


def test_large_image_is_left_untouched():
    """2000x1500 ≥ target → no upscale. Autocontrast may still run
    but dimensions stay put."""
    raw = _make_jpeg(2000, 1500)
    out = image_preprocess.prepare_for_vlm(raw, "image/jpeg")
    w, h = _open(out).size
    assert (w, h) == (2000, 1500)


def test_autocontrast_stretches_low_range():
    """An image with all pixels in [50, 100] should come out with
    pixels covering near-full [0, 255] after autocontrast."""
    raw = _make_jpeg(1024, 1024, brightness_range=(50, 100))
    out = image_preprocess.prepare_for_vlm(raw, "image/jpeg")
    img = _open(out)
    # Sample the histogram. After autocontrast the spread is ~250+.
    pixels = list(img.convert("L").get_flattened_data())
    spread = max(pixels) - min(pixels)
    assert spread > 200, f"expected stretched range, got spread={spread}"


def test_mime_preserved_jpeg():
    raw = _make_jpeg(800, 600)
    out = image_preprocess.prepare_for_vlm(raw, "image/jpeg")
    assert _open(out).format == "JPEG"


def test_mime_preserved_png():
    img = Image.new("RGB", (800, 600), color=(120, 120, 120))
    src = io.BytesIO()
    img.save(src, format="PNG")
    out = image_preprocess.prepare_for_vlm(src.getvalue(), "image/png")
    assert _open(out).format == "PNG"


def test_rgba_png_round_trips_jpeg_when_mime_is_jpeg():
    """A PNG-with-alpha sent in as image/jpeg (unusual but possible
    via mismatched headers) must not crash on the JPEG re-encode.
    Alpha gets dropped — acceptable for VLM captioning."""
    img = Image.new("RGBA", (800, 600), color=(0, 0, 0, 0))
    src = io.BytesIO()
    img.save(src, format="PNG")
    out = image_preprocess.prepare_for_vlm(src.getvalue(), "image/jpeg")
    # Should still be readable, no crash.
    assert _open(out).format == "JPEG"


def test_unknown_mime_passes_through_unchanged():
    """Unknown MIMEs (e.g. image/tiff) pass through untouched —
    the upload route gates supported MIMEs upstream."""
    raw = b"\x00\x01\x02\x03"
    out = image_preprocess.prepare_for_vlm(raw, "image/tiff")
    assert out is raw or out == raw


def test_corrupt_bytes_pass_through_unchanged():
    """Garbage that advertises image/jpeg shouldn't blow up here —
    the VLM call itself will surface the bad image."""
    raw = b"definitely not a jpeg"
    out = image_preprocess.prepare_for_vlm(raw, "image/jpeg")
    assert out == raw
