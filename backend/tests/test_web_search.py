"""Unit tests for the web_search tool (SearxNG + page fetch + structured output).

SearxNG is mocked via the requests library. Page fetches are monkeypatched at
the fetch_and_extract level so tests don't spin up a real browser. End-to-end
exercise against a running SearxNG + the live web is the manual smoke step on
the PR.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from tools._web_fetch import FetchResult
from tools.web import _detect_time_range


@pytest.fixture(autouse=True)
def _stub_rerank(monkeypatch):
    """Skip embedding-based rerank in these orchestration tests. The rerank
    helper has its own dedicated tests in test_web_search_rerank.py — here
    we just want to verify the orchestrator handles success/failure shapes."""
    async def passthrough(client, chunks, query, char_budget, model=None):
        # Return chunks in original order up to char_budget — same behavior as
        # the embed-failure fallback path.
        out, used = [], 0
        for c in chunks:
            if used + len(c) > char_budget:
                break
            out.append(c)
            used += len(c)
        return out
    monkeypatch.setattr("tools.web.rerank_chunks_by_query", passthrough)


@pytest.fixture(autouse=True)
def _stub_refine_query(monkeypatch):
    """Skip query refinement in orchestration tests so SearxNG receives the
    raw query verbatim. Refinement has its own dedicated tests in
    test_web_search_query.py."""
    async def passthrough(client, raw_query, *, today=None, model=None):
        return raw_query
    monkeypatch.setattr("tools.web.refine_query", passthrough)


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


def _ok_result(url: str, body: str) -> FetchResult:
    return FetchResult(url=url, ok=True, body=body)


def _fail_result(url: str, reason: str) -> FetchResult:
    return FetchResult(url=url, ok=False, failure_reason=reason)


@pytest.mark.asyncio
async def test_returns_structured_source_blocks_for_each_fetched_page(monkeypatch):
    from tools.web import web_search

    async def fake_fetch(url, _timeout):
        label = url.rsplit("/", 1)[1]  # "p1", "p2", "p3"
        return _ok_result(url, f"Article {label} content.")

    monkeypatch.setattr("tools.web.fetch_and_extract", fake_fetch)

    with patch("tools.web.requests.get") as mock_get:
        mock_get.return_value = _mock_searx_response(_fake_hits(3))
        out, _audit = await web_search("anything", num_results=3)

    assert "### Source [1]: Title 1" in out
    assert "https://example.com/p1" in out
    assert "Article p1 content." in out
    assert "### Source [2]: Title 2" in out
    assert "### Source [3]: Title 3" in out


@pytest.mark.asyncio
async def test_failed_sources_listed_in_footer_others_still_returned(monkeypatch):
    from tools.web import web_search

    async def fake_fetch(url, _timeout):
        if "p1" in url:
            return _ok_result(url, "Body one.")
        if "p2" in url:
            return _fail_result(url, "403")
        return _fail_result(url, "timeout")

    monkeypatch.setattr("tools.web.fetch_and_extract", fake_fetch)

    with patch("tools.web.requests.get") as mock_get:
        mock_get.return_value = _mock_searx_response(_fake_hits(3))
        out, _audit = await web_search("anything", num_results=3)

    assert "### Source [1]: Title 1" in out
    # Failed sources don't get numbered blocks.
    assert "### Source [2]" not in out
    assert "### Source [3]" not in out
    assert "**Failed sources**" in out
    assert "https://example.com/p2 — 403" in out
    assert "https://example.com/p3 — timeout" in out


@pytest.mark.asyncio
async def test_all_fail_returns_single_line_error(monkeypatch):
    from tools.web import web_search

    async def fake_fetch(url, _timeout):
        if "p1" in url:
            return _fail_result(url, "403")
        return _fail_result(url, "timeout")

    monkeypatch.setattr("tools.web.fetch_and_extract", fake_fetch)

    with patch("tools.web.requests.get") as mock_get:
        mock_get.return_value = _mock_searx_response(_fake_hits(2))
        out, _audit = await web_search("anything", num_results=2)

    assert "### Source" not in out
    assert "none could be fetched" in out


@pytest.mark.asyncio
async def test_no_searxng_results_returns_no_results_message():
    from tools.web import web_search

    with patch("tools.web.requests.get") as mock_get:
        mock_get.return_value = _mock_searx_response([])
        out, _audit = await web_search("zzzz no hits")

    assert "No results for" in out


@pytest.mark.asyncio
async def test_searxng_unreachable_returns_failure_message():
    from tools.web import web_search

    with patch("tools.web.requests.get") as mock_get:
        mock_get.side_effect = requests.ConnectionError("refused")
        out, _audit = await web_search("anything")

    assert "Web search failed" in out


@pytest.mark.asyncio
async def test_num_results_clamped_at_eight(monkeypatch):
    from tools.web import web_search

    async def fake_fetch(url, _timeout):
        label = url.rsplit("/", 1)[1]
        return _ok_result(url, f"body {label}")

    monkeypatch.setattr("tools.web.fetch_and_extract", fake_fetch)

    with patch("tools.web.requests.get") as mock_get:
        mock_get.return_value = _mock_searx_response(_fake_hits(10))
        out, _audit = await web_search("anything", num_results=20)

    # 9th and 10th hits never get fetched.
    assert "### Source [8]" in out
    assert "### Source [9]" not in out


@pytest.mark.asyncio
async def test_body_is_truncated_to_max_chars(monkeypatch):
    from tools.web import web_search

    long_body = "Sentence. " * 1000  # ~10K chars

    async def fake_fetch(url, _timeout):
        return _ok_result(url, long_body)

    monkeypatch.setattr("tools.web.fetch_and_extract", fake_fetch)

    with patch("tools.web.requests.get") as mock_get:
        mock_get.return_value = _mock_searx_response(_fake_hits(1))
        out, _audit = await web_search("anything", num_results=1)

    # Extracted body inside the Source block should not exceed ~3000 chars.
    assert len(out) < 3500
    assert "Sentence." in out


def test_detect_time_range_recency_words_trigger_month():
    """Vague currency words → time_range=month so SearxNG returns recently-
    published content for currency-sensitive queries."""
    assert _detect_time_range("Python latest stable release") == "month"
    assert _detect_time_range("Microsoft 365 admin center recent changes") == "month"
    assert _detect_time_range("current ms365 admin center changes") == "month"
    assert _detect_time_range("upcoming Microsoft Build sessions") == "month"
    assert _detect_time_range("new pgvector features") == "month"


def test_detect_time_range_short_window_words_do_not_trigger():
    """Short-window words ("today", "this week", "yesterday") are NOT in the
    trigger list — they're strong keyword signals on their own, and stacking
    time_range on top excludes evergreen URLs (e.g. nrl.com/draw) that lack
    a recent publish date but ARE the canonical answer."""
    assert _detect_time_range("nrl schedule this week") is None
    assert _detect_time_range("what happened today") is None
    assert _detect_time_range("yesterday's outage") is None


def test_detect_time_range_no_recency_signal():
    """Evergreen, historical, and how-to queries get no time_range filter —
    they should rank purely on relevance, not freshness."""
    assert _detect_time_range("Cloudflare R2 pricing") is None
    assert _detect_time_range("CrowdStrike outage 2024 cause") is None
    assert _detect_time_range("how to enable BitLocker via Group Policy") is None
    assert _detect_time_range("Q1 2025 Azure AD changes") is None
    assert _detect_time_range("") is None
