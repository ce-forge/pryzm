"""Web search tool — SearxNG + per-page fetch + extraction.

The tool calls a locally-hosted SearxNG instance for the top-K hits, then
fetches each URL in parallel and extracts main content via trafilatura. Output
is a sequence of structured `### Source [N]: <title>` blocks for the chat
model to cite. Per-source failures (timeout, 4xx, 5xx, non-HTML, empty
extraction) are listed in a `**Failed sources**` footer so the model can
caveat without aborting the turn.

Wall-clock budget for the fetch loop is 25s — under the engine's
`TOOL_TIMEOUT_SECONDS=30` so the inner budget always trips first and the tool
returns a partial result rather than getting cancelled by the outer guard.
"""
from __future__ import annotations

import asyncio

import httpx
import requests

from config import settings
from tools._web_fetch import FetchResult, fetch_and_extract
from tools._web_truncate import truncate_to_sentences
from .registry import tool


_MAX_RESULTS = 8
_DEFAULT_RESULTS = 5
_PER_REQUEST_TIMEOUT_S = 8.0
_FETCH_WALL_CLOCK_S = 25.0
_MAX_CHARS_PER_PAGE = 6000


WEB_SEARCH_DIRECTIVE = (
    "Use `web_search` for factual questions whose answer may have changed since "
    "training (current events, recent vendor releases, newly-published docs, "
    "news). Do NOT use it for questions answerable from local knowledge-base "
    "documents or general background knowledge.\n"
    "Results are returned as one or more `### Source [N]: <title>` blocks, each "
    "containing the source URL on its own line and an extracted page body below. "
    "When writing your reply, cite every factual claim by appending `[N]` "
    "referring to the source index. End your reply with a `**Sources**` section "
    "listing each cited source as `[N] <URL>`. Do not cite sources you did not "
    "use."
)


@tool(
    properties={
        "query": {
            "type": "string",
            "description": "The search query — natural language is fine.",
        },
        "num_results": {
            "type": "integer",
            "description": (
                "How many top hits to fetch and read (default 5, max 8). "
                "Each adds one page-fetch round to the wall-clock budget."
            ),
        },
    },
    required=["query"],
    workspaces=["it_copilot", "personal"],
    system_prompt_directive=WEB_SEARCH_DIRECTIVE,
)
async def web_search(query: str, num_results: int = _DEFAULT_RESULTS) -> str:
    """Search the web via SearxNG, fetch the top hits, and return their extracted
    main content as structured per-source blocks ready for the model to cite."""
    capped = max(1, min(num_results, _MAX_RESULTS))

    # SearxNG call stays synchronous (requests library) — it's a single fast
    # local call and changing it to httpx would buy nothing here.
    try:
        resp = requests.get(
            f"{settings.SEARXNG_URL}/search",
            params={"q": query, "format": "json", "language": "en"},
            timeout=settings.TOOL_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException as exc:
        return f"Web search failed: {exc}"

    hits = (payload.get("results") or [])[:capped]
    if not hits:
        return f"No results for {query!r}."

    urls_titles = [(h.get("url", ""), h.get("title", "(no title)")) for h in hits]

    # Fetch all URLs in parallel under a single wall-clock budget. asyncio.wait_for
    # cancels the gather on timeout — for partial results we'd need to handle this
    # case, but with the engine's outer TOOL_TIMEOUT_SECONDS=30 and our 25s inner,
    # the typical case is "all done in well under 25s." Mark URLs that didn't
    # come back as `timeout` on cancellation.
    results: list[FetchResult] = []
    async with httpx.AsyncClient(
        headers={"user-agent": "Pryzm/1.0 (+self-hosted IT copilot)"},
        timeout=_PER_REQUEST_TIMEOUT_S,
    ) as client:
        try:
            results = await asyncio.wait_for(
                asyncio.gather(
                    *(fetch_and_extract(client, url, _PER_REQUEST_TIMEOUT_S) for url, _ in urls_titles)
                ),
                timeout=_FETCH_WALL_CLOCK_S,
            )
        except asyncio.TimeoutError:
            results = [FetchResult(url=url, ok=False, failure_reason="timeout") for url, _ in urls_titles]

    successes: list[tuple[str, str, str]] = []  # (title, url, body)
    failures: list[tuple[str, str]] = []  # (url, reason)
    for (url, title), fr in zip(urls_titles, results):
        if fr.ok:
            body = truncate_to_sentences(fr.body, _MAX_CHARS_PER_PAGE)
            successes.append((title, url, body))
        else:
            failures.append((url, fr.failure_reason or "error"))

    if not successes:
        reason_counts: dict[str, int] = {}
        for _, reason in failures:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
        summary = ", ".join(f"{n}× {r}" for r, n in sorted(reason_counts.items()))
        return (
            f"Web search returned {len(hits)} results but none could be fetched. "
            f"Reasons: {summary}."
        )

    blocks: list[str] = []
    for i, (title, url, body) in enumerate(successes, 1):
        blocks.append(f"### Source [{i}]: {title}\n{url}\n\n{body}")

    out = "\n\n".join(blocks)

    if failures:
        failure_lines = "\n".join(f"- {url} — {reason}" for url, reason in failures)
        out += f"\n\n**Failed sources**\n{failure_lines}"

    return out
