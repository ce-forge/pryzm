"""Unit tests for the per-URL fetch+extract helper used by web_search.

Monkeypatches _render_page so no real browser or network traffic happens.
Each test isolates one failure mode or the happy path; the orchestrator in
tools/web.py composes them.
"""
from __future__ import annotations

import pytest

from tools._web_fetch import FetchResult, fetch_and_extract


@pytest.mark.asyncio
async def test_happy_path_returns_extracted_body(monkeypatch):
    html = (
        "<html><body><article>"
        "<p>This is the article body. It is long enough to extract.</p>"
        "</article></body></html>"
    )

    async def fake_render(url, timeout):
        return (200, "text/html", html)

    monkeypatch.setattr("tools._web_fetch._render_page", fake_render)

    result = await fetch_and_extract("https://example.com/a", per_request_timeout=2)
    assert result.ok
    assert "article body" in result.body
    assert result.failure_reason is None


@pytest.mark.asyncio
async def test_non_html_content_type_returns_non_html_failure(monkeypatch):
    async def fake_render(url, timeout):
        return (200, "application/pdf", "%PDF...")

    monkeypatch.setattr("tools._web_fetch._render_page", fake_render)

    result = await fetch_and_extract("https://example.com/pdf", per_request_timeout=2)
    assert not result.ok
    assert result.failure_reason == "non-html"


@pytest.mark.asyncio
async def test_403_returns_status_failure(monkeypatch):
    async def fake_render(url, timeout):
        return (403, "text/html", "Forbidden")

    monkeypatch.setattr("tools._web_fetch._render_page", fake_render)

    result = await fetch_and_extract("https://example.com/locked", per_request_timeout=2)
    assert not result.ok
    assert result.failure_reason == "403"


@pytest.mark.asyncio
async def test_empty_extraction_returns_empty_failure(monkeypatch):
    """trafilatura returns empty for pages with no usable main content."""
    async def fake_render(url, timeout):
        return (200, "text/html", "<html><body></body></html>")

    monkeypatch.setattr("tools._web_fetch._render_page", fake_render)

    result = await fetch_and_extract("https://example.com/shell", per_request_timeout=2)
    assert not result.ok
    assert result.failure_reason == "empty"


@pytest.mark.asyncio
async def test_timeout_returns_timeout_failure(monkeypatch):
    async def fake_render(url, timeout):
        return (None, "", "")

    monkeypatch.setattr("tools._web_fetch._render_page", fake_render)

    result = await fetch_and_extract("https://example.com/slow", per_request_timeout=2)
    assert not result.ok
    assert result.failure_reason == "timeout"


@pytest.mark.asyncio
async def test_other_request_errors_return_error_failure(monkeypatch):
    from playwright.async_api import Error as PlaywrightError

    async def fake_render(url, timeout):
        raise PlaywrightError("connection refused")

    monkeypatch.setattr("tools._web_fetch._render_page", fake_render)

    result = await fetch_and_extract("https://example.com/boom", per_request_timeout=2)
    assert not result.ok
    assert result.failure_reason == "error"
