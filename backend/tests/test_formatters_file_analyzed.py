"""Unit tests for format_file_analyzed's thumbnail-embedding behavior.

The function is called by ai_engine when the auto-RAG path produces
retrieved context. With image-bearing chunks (Documents whose
storage_path resolves on disk), the formatter embeds base64 data URLs
inline so the frontend renders thumbnails inside the same blockquote.
"""
from __future__ import annotations

import os

from utils.formatters import format_file_analyzed


def test_no_image_paths_keeps_existing_shape():
    """Backwards-compat: callers passing only `sources` get the original
    blockquote line."""
    out = format_file_analyzed(["notes.md"])
    assert "**File Analyzed:** `notes.md`" in out
    assert "data:image/" not in out


def test_image_paths_embedded_as_data_urls(tmp_path):
    """Real on-disk PNG → emitted as a base64 data URL inside the
    blockquote so the markdown renderer renders the thumbnail."""
    img = tmp_path / "shot.png"
    img.write_bytes(b"png-bytes")
    out = format_file_analyzed(["shot.png"], image_paths=[str(img)])
    assert "**File Analyzed:** `shot.png`" in out
    assert "![attached image](data:image/png;base64," in out


def test_missing_image_path_skipped_silently(tmp_path):
    """Stale or deleted storage path → the source line still renders, no
    broken thumbnail markup."""
    out = format_file_analyzed(
        ["shot.png"], image_paths=[str(tmp_path / "gone.png")]
    )
    assert "**File Analyzed:** `shot.png`" in out
    assert "data:image/" not in out


def test_multiple_paths_one_thumbnail_per_image(tmp_path):
    a = tmp_path / "a.jpg"; a.write_bytes(b"a")
    b = tmp_path / "b.png"; b.write_bytes(b"b")
    out = format_file_analyzed(
        ["a.jpg", "b.png"], image_paths=[str(a), str(b)]
    )
    assert out.count("![attached image](data:image/") == 2
    assert "data:image/jpeg;base64," in out
    assert "data:image/png;base64," in out
