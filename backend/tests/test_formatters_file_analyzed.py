"""Unit tests for format_file_analyzed.

Earlier versions of this seam embedded base64 image data inline for a
thumbnail in the assistant turn. That added megabytes of base64 to
every saved assistant message and froze the chat-load UI; the embed
was reverted (see git log for the formatter file). These tests pin
the simple-source-line shape so we don't drift back into embedding.
"""
from __future__ import annotations

from utils.formatters import format_file_analyzed


def test_single_source_shape():
    out = format_file_analyzed(["notes.md"])
    assert "**File Analyzed:** `notes.md`" in out
    assert "data:image/" not in out


def test_multiple_sources_joined_with_comma():
    out = format_file_analyzed(["a.jpg", "b.png"])
    assert "`a.jpg, b.png`" in out
    assert "data:image/" not in out


def test_function_signature_does_not_accept_image_paths():
    """The image_paths kwarg was removed deliberately. If a future
    refactor re-adds it, this test will fail loudly so the change is
    revisited intentionally."""
    import inspect
    params = list(inspect.signature(format_file_analyzed).parameters)
    assert params == ["sources"]
