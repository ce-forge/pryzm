"""Unit tests for the Ollama HTTP client wrapper (core.ollama).

T0 tests just verify the four expected functions exist as exports.
T1 will replace these with behavior tests using mocked httpx.
"""
from core import ollama


def test_module_exports_chat_stream():
    assert hasattr(ollama, "chat_stream")


def test_module_exports_embed():
    assert hasattr(ollama, "embed")


def test_module_exports_list_models():
    assert hasattr(ollama, "list_models")


def test_module_exports_generate():
    assert hasattr(ollama, "generate")
