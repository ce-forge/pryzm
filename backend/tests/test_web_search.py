"""Unit tests for the web_search tool (SearxNG + page fetch + structured output).

SearxNG is still mocked via the requests library; page fetches are mocked via
respx so the new async fetch path doesn't touch the network. End-to-end
exercise against a running SearxNG + the live web is the manual smoke step on
the PR.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest
import requests
import respx


def _mock_searx_response(results: list[dict] | None = None, status: int = 200) -> MagicMock:
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status
    if status >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(f"{status} error")
    else:
        resp.raise_for_status.return_value = None
    resp.json.return_value = {"results": results if results is not None else []}
    return resp


def _fake_hits(n: int) -> list[dict]:
    return [
        {"title": f"Title {i}", "url": f"https://example.com/p{i}", "content": f"snippet {i}"}
        for i in range(1, n + 1)
    ]


def _ok_html(body_text: str) -> httpx.Response:
    return httpx.Response(
        200,
        text=f"<html><body><article><p>{body_text}</p></article></body></html>",
        headers={"content-type": "text/html"},
    )


@pytest.mark.asyncio
async def test_returns_structured_source_blocks_for_each_fetched_page():
    from tools.web import web_search

    with patch("tools.web.requests.get") as mock_get, respx.mock:
        mock_get.return_value = _mock_searx_response(_fake_hits(3))
        respx.get("https://example.com/p1").mock(return_value=_ok_html("Article one content."))
        respx.get("https://example.com/p2").mock(return_value=_ok_html("Article two content."))
        respx.get("https://example.com/p3").mock(return_value=_ok_html("Article three content."))

        out = await web_search("anything", num_results=3)

    assert "### Source [1]: Title 1" in out
    assert "https://example.com/p1" in out
    assert "Article one content." in out
    assert "### Source [2]: Title 2" in out
    assert "### Source [3]: Title 3" in out


@pytest.mark.asyncio
async def test_failed_sources_listed_in_footer_others_still_returned():
    from tools.web import web_search

    with patch("tools.web.requests.get") as mock_get, respx.mock:
        mock_get.return_value = _mock_searx_response(_fake_hits(3))
        respx.get("https://example.com/p1").mock(return_value=_ok_html("Body one."))
        respx.get("https://example.com/p2").mock(return_value=httpx.Response(403, text="nope"))
        respx.get("https://example.com/p3").mock(side_effect=httpx.TimeoutException("slow"))

        out = await web_search("anything", num_results=3)

    assert "### Source [1]: Title 1" in out
    # Failed sources don't get numbered blocks.
    assert "### Source [2]" not in out
    assert "### Source [3]" not in out
    assert "**Failed sources**" in out
    assert "https://example.com/p2 — 403" in out
    assert "https://example.com/p3 — timeout" in out


@pytest.mark.asyncio
async def test_all_fail_returns_single_line_error():
    from tools.web import web_search

    with patch("tools.web.requests.get") as mock_get, respx.mock:
        mock_get.return_value = _mock_searx_response(_fake_hits(2))
        respx.get("https://example.com/p1").mock(return_value=httpx.Response(403))
        respx.get("https://example.com/p2").mock(side_effect=httpx.TimeoutException("slow"))

        out = await web_search("anything", num_results=2)

    assert "### Source" not in out
    assert "none could be fetched" in out


@pytest.mark.asyncio
async def test_no_searxng_results_returns_no_results_message():
    from tools.web import web_search

    with patch("tools.web.requests.get") as mock_get:
        mock_get.return_value = _mock_searx_response([])
        out = await web_search("zzzz no hits")

    assert "No results for" in out


@pytest.mark.asyncio
async def test_searxng_unreachable_returns_failure_message():
    from tools.web import web_search

    with patch("tools.web.requests.get") as mock_get:
        mock_get.side_effect = requests.ConnectionError("refused")
        out = await web_search("anything")

    assert "Web search failed" in out


@pytest.mark.asyncio
async def test_num_results_clamped_at_eight():
    from tools.web import web_search

    with patch("tools.web.requests.get") as mock_get, respx.mock:
        mock_get.return_value = _mock_searx_response(_fake_hits(10))
        for i in range(1, 9):
            respx.get(f"https://example.com/p{i}").mock(return_value=_ok_html(f"body {i}"))

        out = await web_search("anything", num_results=20)

    # 9th and 10th hits never get fetched.
    assert "### Source [8]" in out
    assert "### Source [9]" not in out


@pytest.mark.asyncio
async def test_body_is_truncated_to_max_chars():
    from tools.web import web_search

    long_body = "Sentence. " * 1000  # ~10K chars
    with patch("tools.web.requests.get") as mock_get, respx.mock:
        mock_get.return_value = _mock_searx_response(_fake_hits(1))
        respx.get("https://example.com/p1").mock(return_value=_ok_html(long_body))

        out = await web_search("anything", num_results=1)

    # Extracted body inside the Source block should not exceed ~3000 chars.
    # The block has small surrounding boilerplate so we check the body line
    # contains "Sentence." many times but the whole output stays bounded.
    assert len(out) < 3500
    assert "Sentence." in out
