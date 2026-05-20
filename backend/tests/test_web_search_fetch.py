"""Unit tests for the per-URL fetch+extract helper used by web_search.

Mocks httpx via respx so no real HTTP traffic happens. Each test isolates one
failure mode or the happy path; the orchestrator in tools/web.py composes them.
"""
from __future__ import annotations

import httpx
import pytest
import respx

from tools._web_fetch import FetchResult, fetch_and_extract


@pytest.mark.asyncio
async def test_happy_path_returns_extracted_body():
    html = (
        "<html><body><article>"
        "<p>This is the article body. It is long enough to extract.</p>"
        "</article></body></html>"
    )
    async with httpx.AsyncClient() as client:
        with respx.mock:
            respx.get("https://example.com/a").mock(
                return_value=httpx.Response(200, text=html, headers={"content-type": "text/html"})
            )
            result = await fetch_and_extract(client, "https://example.com/a", per_request_timeout=2)
    assert result.ok
    assert "article body" in result.body
    assert result.failure_reason is None


@pytest.mark.asyncio
async def test_non_html_content_type_returns_non_html_failure():
    async with httpx.AsyncClient() as client:
        with respx.mock:
            respx.get("https://example.com/pdf").mock(
                return_value=httpx.Response(200, text="%PDF...", headers={"content-type": "application/pdf"})
            )
            result = await fetch_and_extract(client, "https://example.com/pdf", per_request_timeout=2)
    assert not result.ok
    assert result.failure_reason == "non-html"


@pytest.mark.asyncio
async def test_403_returns_status_failure():
    async with httpx.AsyncClient() as client:
        with respx.mock:
            respx.get("https://example.com/locked").mock(
                return_value=httpx.Response(403, text="Forbidden")
            )
            result = await fetch_and_extract(client, "https://example.com/locked", per_request_timeout=2)
    assert not result.ok
    assert result.failure_reason == "403"


@pytest.mark.asyncio
async def test_empty_extraction_returns_empty_failure():
    """trafilatura returns empty for pages with no usable main content."""
    async with httpx.AsyncClient() as client:
        with respx.mock:
            respx.get("https://example.com/shell").mock(
                return_value=httpx.Response(200, text="<html><body></body></html>", headers={"content-type": "text/html"})
            )
            result = await fetch_and_extract(client, "https://example.com/shell", per_request_timeout=2)
    assert not result.ok
    assert result.failure_reason == "empty"


@pytest.mark.asyncio
async def test_timeout_returns_timeout_failure():
    async with httpx.AsyncClient() as client:
        with respx.mock:
            respx.get("https://example.com/slow").mock(side_effect=httpx.TimeoutException("timed out"))
            result = await fetch_and_extract(client, "https://example.com/slow", per_request_timeout=2)
    assert not result.ok
    assert result.failure_reason == "timeout"


@pytest.mark.asyncio
async def test_other_request_errors_return_error_failure():
    async with httpx.AsyncClient() as client:
        with respx.mock:
            respx.get("https://example.com/boom").mock(side_effect=httpx.ConnectError("nope"))
            result = await fetch_and_extract(client, "https://example.com/boom", per_request_timeout=2)
    assert not result.ok
    assert result.failure_reason == "error"
