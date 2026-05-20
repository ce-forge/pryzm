"""Single-URL fetch + extract for the web_search tool.

Wraps an httpx GET with content-type guarding, trafilatura extraction, and a
small enum of failure reasons. The orchestrator in tools/web.py composes many
of these in parallel under a wall-clock budget.
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx
import trafilatura


@dataclass(frozen=True)
class FetchResult:
    """Outcome of a single URL fetch.

    On success, `body` carries the extracted main text. On failure, `body` is
    empty and `failure_reason` is one of: `timeout`, a 3-char HTTP status code
    like `"403"`, `non-html`, `empty`, or `error` (catch-all for connect /
    transport / unexpected errors)."""
    url: str
    ok: bool
    body: str = ""
    failure_reason: str | None = None


async def fetch_and_extract(
    client: httpx.AsyncClient,
    url: str,
    per_request_timeout: float,
) -> FetchResult:
    """Fetch one URL, validate content type, run trafilatura. Never raises —
    every failure mode maps to a populated `failure_reason`."""
    try:
        resp = await client.get(url, timeout=per_request_timeout, follow_redirects=True)
    except httpx.TimeoutException:
        return FetchResult(url=url, ok=False, failure_reason="timeout")
    except httpx.RequestError:
        return FetchResult(url=url, ok=False, failure_reason="error")

    if resp.status_code >= 400:
        return FetchResult(url=url, ok=False, failure_reason=str(resp.status_code))

    content_type = (resp.headers.get("content-type") or "").lower()
    if not (content_type.startswith("text/html") or "xhtml" in content_type):
        return FetchResult(url=url, ok=False, failure_reason="non-html")

    extracted = trafilatura.extract(
        resp.text,
        include_comments=False,
        include_tables=True,
        favor_recall=False,
    )
    if not extracted or not extracted.strip():
        return FetchResult(url=url, ok=False, failure_reason="empty")

    return FetchResult(url=url, ok=True, body=extracted.strip())
