"""Unit tests for the OCR seam in services/ocr.py.

These tests construct images in memory (Pillow) and assert that
extract_text recovers the rendered string. They run without the DB,
Redis, or LLM server.
"""
from io import BytesIO

import pytest
from PIL import Image, ImageDraw

from services import ocr


def _render_png(text: str, size=(500, 120)) -> bytes:
    img = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(img)
    draw.text((20, 30), text, fill="black")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_extract_text_finds_rendered_string():
    png = _render_png("PRYZM OCR TEST")
    result = ocr.extract_text(png)
    assert "PRYZM" in result.upper()


def test_extract_text_empty_on_blank_image():
    img = Image.new("RGB", (200, 100), "white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    result = ocr.extract_text(buf.getvalue())
    assert result == ""


def test_extract_text_raises_on_invalid_bytes():
    with pytest.raises(ocr.InvalidImage):
        ocr.extract_text(b"not an image, just garbage bytes")
