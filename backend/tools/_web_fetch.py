"""Single-URL fetch + extract for the web_search tool.

Uses headless chromium via Playwright to render JS-rendered pages, then
runs trafilatura on the rendered DOM. Wraps the whole call in a single
try/except so the never-raises contract holds — every failure mode
(timeout, 4xx, 5xx, non-html, empty extract, browser/page error) maps
to a populated `failure_reason`.
"""
from __future__ import annotations

from dataclasses import dataclass

import trafilatura
from playwright.async_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeout

from tools._browser import new_context


@dataclass(frozen=True)
class FetchResult:
    """Outcome of a single URL fetch.

    On success, `body` carries the extracted main text. On failure, `body` is
    empty and `failure_reason` is one of: `timeout`, a 3-char HTTP status code
    like `"403"`, `non-html`, `empty`, or `error` (catch-all for browser /
    transport / unexpected errors)."""
    url: str
    ok: bool
    body: str = ""
    failure_reason: str | None = None


async def _render_page(url: str, per_request_timeout: float) -> tuple[int | None, str, str]:
    """Render `url` in headless chromium and return (status, content_type, html).

    Returns (None, "", "") on timeout. Raises PlaywrightError on unrecoverable
    browser errors. Tests monkeypatch this to avoid spinning up a real browser."""
    ctx = await new_context()
    try:
        page = await ctx.new_page()
        try:
            resp = await page.goto(
                url,
                wait_until="load",
                timeout=int(per_request_timeout * 1000),  # playwright wants ms
            )
        except PlaywrightTimeout:
            return (None, "", "")

        if resp is None:
            raise PlaywrightError("goto returned None")

        content_type = (resp.headers.get("content-type") or "").lower()
        html = await page.content()
        return (resp.status, content_type, html)
    finally:
        try:
            await ctx.close()
        except Exception:
            pass


async def fetch_and_extract(url: str, per_request_timeout: float) -> FetchResult:
    """Render `url` in headless chromium, extract main content with
    trafilatura, return a FetchResult. Never raises."""
    try:
        status, content_type, html = await _render_page(url, per_request_timeout)
    except PlaywrightError:
        return FetchResult(url=url, ok=False, failure_reason="error")
    except Exception:
        return FetchResult(url=url, ok=False, failure_reason="error")

    if status is None:
        return FetchResult(url=url, ok=False, failure_reason="timeout")
    if status >= 400:
        return FetchResult(url=url, ok=False, failure_reason=str(status))
    if not (content_type.startswith("text/html") or "xhtml" in content_type):
        return FetchResult(url=url, ok=False, failure_reason="non-html")

    try:
        extracted = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=False,
            favor_precision=True,
        )
    except Exception:
        return FetchResult(url=url, ok=False, failure_reason="error")

    if not extracted or not extracted.strip():
        return FetchResult(url=url, ok=False, failure_reason="empty")

    return FetchResult(url=url, ok=True, body=extracted.strip())
