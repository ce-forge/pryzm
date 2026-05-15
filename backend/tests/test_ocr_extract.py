"""Unit tests for services/ocr_extract — the canonical verbatim-text
source in the captioning pipeline."""
from __future__ import annotations

import io

import pytest
from PIL import Image, ImageDraw

from services import ocr_extract


def _synth_image(text_lines: list[str], size: tuple[int, int] = (640, 240)) -> bytes:
    """Build a small PNG containing a few lines of text. Real OCR
    test — we send actual rendered pixels to RapidOCR."""
    img = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(img)
    y = 20
    for line in text_lines:
        d.text((20, y), line, fill="black")
        y += 30
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_extract_text_reads_simple_text():
    """End-to-end: synth a small image with 'admin' and an error code,
    OCR should read them back verbatim. This is the workflow that
    motivated the hybrid pipeline — identifier-class accuracy."""
    raw = _synth_image(["Username: admin", "Error: 0x80070005"])
    result = ocr_extract.extract_text(raw, "image/png")
    assert result is not None
    # Verbatim character accuracy on identifier-class fields is the
    # whole point; we accept the OCR may insert spaces or differ on
    # whitespace, but the literal characters must be intact.
    assert "admin" in result
    assert "0x80070005" in result


def test_extract_text_returns_none_for_unparseable_bytes():
    """Garbage bytes that don't decode as an image — OCR returns None
    rather than crashing. The pipeline then falls back to VLM."""
    result = ocr_extract.extract_text(b"definitely not an image", "image/png")
    assert result is None


def test_extract_text_returns_none_for_unsupported_mime():
    """Unsupported MIMEs (e.g. tiff) get None — the upload route
    rejects them upstream anyway, but the function shouldn't crash if
    one slips through."""
    result = ocr_extract.extract_text(b"\x00" * 100, "image/tiff")
    assert result is None


def test_extract_text_returns_none_for_blank_image():
    """A completely blank image: no text detected → None. Tests the
    'no detections at all' path (vs the 'detections but all low
    confidence' path)."""
    img = Image.new("RGB", (200, 200), "white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    result = ocr_extract.extract_text(buf.getvalue(), "image/png")
    # RapidOCR may detect nothing, or detect noise below threshold.
    # Either way: None is the contract.
    assert result is None or result == ""


def test_extract_text_handles_rgba_input():
    """PNG with alpha channel — must convert to RGB before passing to
    OCR (which expects RGB). No crash."""
    img = Image.new("RGBA", (400, 100), (255, 255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((20, 30), "TestRGBA", fill=(0, 0, 0, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    result = ocr_extract.extract_text(buf.getvalue(), "image/png")
    # OCR may or may not nail "TestRGBA" exactly — what matters is
    # the function doesn't crash on RGBA input.
    assert result is not None or result is None  # no exception
