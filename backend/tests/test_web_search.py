"""Unit tests for the web_search tool (SearxNG-backed).

Mocks the HTTP call to SearxNG rather than hitting a real instance, so these
tests run in CI without docker. End-to-end exercise against a running
container is the manual verification step on the PR.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests


def _mock_searx_response(results: list[dict] | None = None, status: int = 200) -> MagicMock:
    """Build a stand-in for requests.Response carrying a SearxNG-shape JSON body.

    SearxNG's /search?format=json returns an object with a `results` array; each
    entry has at least `title`, `url`, and `content` (snippet).
    """
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status
    if status >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(f"{status} error")
    else:
        resp.raise_for_status.return_value = None
    resp.json.return_value = {"results": results if results is not None else []}
    return resp


def test_happy_path_returns_markdown_with_top_n():
    """Three valid SearxNG hits → numbered markdown with **title**, URL, snippet."""
    from tools.web import web_search

    fake_results = [
        {"title": "Pryzm Docs", "url": "https://example.com/a", "content": "First snippet."},
        {"title": "Pryzm Blog", "url": "https://example.com/b", "content": "Second snippet."},
        {"title": "Pryzm Source", "url": "https://example.com/c", "content": "Third snippet."},
        {"title": "Should Not Appear", "url": "https://example.com/d", "content": "Fourth."},
    ]
    with patch("tools.web.requests.get", return_value=_mock_searx_response(fake_results)):
        out = web_search("pryzm", num_results=3)

    assert "**Pryzm Docs**" in out
    assert "https://example.com/a" in out
    assert "First snippet." in out
    assert "**Pryzm Blog**" in out
    assert "**Pryzm Source**" in out
    assert "Should Not Appear" not in out  # cap at num_results


def test_default_num_results_is_three():
    """Calling without num_results caps at 3."""
    from tools.web import web_search

    fake_results = [
        {"title": f"R{i}", "url": f"https://example.com/{i}", "content": f"snippet{i}"}
        for i in range(5)
    ]
    with patch("tools.web.requests.get", return_value=_mock_searx_response(fake_results)):
        out = web_search("anything")

    assert "**R0**" in out
    assert "**R1**" in out
    assert "**R2**" in out
    assert "**R3**" not in out
    assert "**R4**" not in out


def test_empty_results_returns_clear_message():
    """SearxNG returns no results → tool returns a recognizable 'no results' line, not empty string."""
    from tools.web import web_search

    with patch("tools.web.requests.get", return_value=_mock_searx_response([])):
        out = web_search("totally-made-up-string-xyzzy")

    assert out  # not empty
    assert "no results" in out.lower()


def test_http_error_returns_message_not_raises():
    """SearxNG 5xx → tool returns an error message; never raises (LLM needs the string)."""
    from tools.web import web_search

    with patch("tools.web.requests.get", return_value=_mock_searx_response([], status=503)):
        out = web_search("anything")

    assert out
    assert "search failed" in out.lower() or "error" in out.lower()


def test_network_error_returns_message_not_raises():
    """Connection refused / DNS failure → tool returns an error message; never raises."""
    from tools.web import web_search

    with patch(
        "tools.web.requests.get",
        side_effect=requests.ConnectionError("connection refused"),
    ):
        out = web_search("anything")

    assert out
    assert "search failed" in out.lower() or "error" in out.lower()


def test_query_is_sent_to_searxng():
    """The query string actually reaches SearxNG's `q` param."""
    from tools.web import web_search

    with patch("tools.web.requests.get", return_value=_mock_searx_response([])) as mock_get:
        web_search("my unique query")

    # Inspect kwargs / args of the call. Tool should pass `q=<query>` as a param.
    call = mock_get.call_args
    params = call.kwargs.get("params") or (call.args[1] if len(call.args) > 1 else {})
    assert params.get("q") == "my unique query"
    assert params.get("format") == "json"


def test_tool_is_registered_with_directive():
    """The @tool decorator registers web_search in AVAILABLE_TOOLS with a non-empty directive."""
    # Import the module to trigger registration
    import tools.web  # noqa: F401
    from tools.registry import AVAILABLE_TOOLS

    assert "web_search" in AVAILABLE_TOOLS
    fn = AVAILABLE_TOOLS["web_search"]
    assert getattr(fn, "system_prompt_directive", "")  # non-empty


def test_tool_definition_includes_query_parameter():
    """The JSON schema exposed to the LLM has `query` as a required string parameter."""
    import tools.web  # noqa: F401
    from tools.registry import TOOL_DEFINITIONS

    web_def = next((d for d in TOOL_DEFINITIONS if d["function"]["name"] == "web_search"), None)
    assert web_def is not None
    params = web_def["function"]["parameters"]
    assert "query" in params["properties"]
    assert params["properties"]["query"]["type"] == "string"
    assert "query" in params["required"]
