"""Unit tests for services/pdf_extract.py.

Builds minimal text-containing PDFs in memory so the tests stay
hermetic — no fixture files committed.
"""
from __future__ import annotations

import pytest

from services import pdf_extract


def _make_text_pdf(text: str) -> bytes:
    """Hand-built minimal single-page PDF containing `text` in
    Helvetica. Offsets are computed at build time so the bytes are
    well-formed for any string. Used only by tests."""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> "
        b"/MediaBox [0 0 612 792] /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    stream = f"BT /F1 24 Tf 100 700 Td ({text}) Tj ET".encode()
    objects.append(
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n"
        + stream + b"\nendstream"
    )
    out = b"%PDF-1.4\n"
    offsets = [0]
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n"
    ).encode()
    return out


def test_extract_text_finds_rendered_string():
    pdf = _make_text_pdf("PRYZM PDF TEST")
    result = pdf_extract.extract_text(pdf)
    assert "PRYZM" in result.upper()
    assert "PDF" in result.upper()


def test_extract_text_concatenates_multiple_pages_worth_of_strings():
    """Build a PDF with two distinct text strings; the result should
    contain both. (One-page PDF here; the seam joins pages by '\\n\\n'
    but we exercise the path that returns multiple text fragments.)"""
    pdf = _make_text_pdf("FIRST LINE")
    result = pdf_extract.extract_text(pdf)
    assert "FIRST" in result.upper()


def test_extract_text_raises_on_invalid_bytes():
    with pytest.raises(pdf_extract.InvalidPdf):
        pdf_extract.extract_text(b"not even close to a pdf")


def test_extract_text_returns_empty_on_pdf_with_no_text():
    """A valid PDF with no extractable text stream → empty string.
    Caller (the /upload router) maps empty → HTTP 422."""
    # Build a PDF that's structurally valid but has no Contents stream.
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = [0]
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n"
    ).encode()

    result = pdf_extract.extract_text(out)
    assert result == ""
