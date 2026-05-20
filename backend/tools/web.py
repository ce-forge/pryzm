"""Web search tool — SearxNG + per-page fetch + extraction.

The tool calls a locally-hosted SearxNG instance for the top-K hits, then
fetches each URL in parallel and extracts main content via trafilatura. Output
is a sequence of structured `### Source [N]: <title>` blocks for the chat
model to cite. Per-source failures (timeout, 4xx, 5xx, non-HTML, empty
extraction) are listed in a `**Failed sources**` footer so the model can
caveat without aborting the turn.

Wall-clock budget for the *fetch loop* is 25s — under the engine's
`TOOL_TIMEOUT_SECONDS=30` so the inner budget trips first and the tool returns
a structured error rather than getting cancelled by the outer guard. The
SearxNG call runs before the fetch loop and uses its own timeout; a slow
SearxNG can eat into the engine's outer budget.
"""
from __future__ import annotations

import asyncio
import time

import httpx
import requests

from config import settings
from tools._web_fetch import FetchResult, fetch_and_extract
from tools._web_query import refine_query
from tools._web_rerank import rerank_chunks_by_query, split_into_chunks
from tools._web_truncate import truncate_to_sentences
from .registry import tool


# Per-call stats stash for the engine's audit emission. Module-level and
# single-flight by design — the engine reads `get_last_stats()` synchronously
# right after `web_search` returns (no `await`/`yield` in between) and
# snapshots into a local. Without that synchronous snapshot, a concurrent
# /analyze request's `web_search` could overwrite the stash between
# completion and read. Don't paper over this with a lock — fix the call
# site to snapshot.
_LAST_STATS: dict = {}


def get_last_stats() -> dict:
    """Return the stats dict from the most recent web_search call."""
    return dict(_LAST_STATS)


def _set_stats(**kwargs) -> None:
    _LAST_STATS.clear()
    _LAST_STATS.update(kwargs)


_MAX_RESULTS = 8
_DEFAULT_RESULTS = 3
_PER_REQUEST_TIMEOUT_S = 8.0
_FETCH_WALL_CLOCK_S = 25.0
_MAX_CHARS_PER_PAGE = 3000


WEB_SEARCH_DIRECTIVE = (
    "Use `web_search` for factual questions whose answer may have changed since "
    "training (current events, recent vendor releases, newly-published docs, "
    "news). Do NOT use it for questions answerable from local knowledge-base "
    "documents or general background knowledge.\n"
    "Results are returned as one or more `### Source [N]: <title>` blocks, each "
    "containing the source URL on its own line and an extracted page body below. "
    "When writing your reply, cite every factual claim by appending `[N]` "
    "referring to the source index. Do not cite sources you did not use. The "
    "user's UI shows the source list separately, so do NOT write a `**Sources**` "
    "footer or list URLs in your reply — only the inline `[N]` markers. If a "
    "`**Failed sources**` footer appears in the tool output, that is internal "
    "metadata — do not echo it in your reply either."
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

    # Reset stats to a zero baseline at function entry. The engine reads
    # get_last_stats() right after this coroutine returns; without the
    # baseline reset, a tool cancellation (e.g. the engine's outer
    # TOOL_TIMEOUT_SECONDS firing before we reach any later _set_stats
    # call) would leave the previous call's stats in the stash and the
    # audit row would silently misattribute them.
    _set_stats(
        k_requested=capped, k_returned_by_searxng=0, k_fetched_ok=0, k_failed=0,
        failure_reasons={}, fetch_wall_clock_ms=0, extracted_bytes_total=0,
        query_raw=query, query_refined=query,
    )

    # Refine the search query via the always-on small model: normalises
    # phrasing, fixes typos, and injects today's date so time-bound questions
    # like "this week" produce a year/month-anchored query. Falls back to the
    # raw query on any failure — never blocks the tool turn.
    async with httpx.AsyncClient() as refine_client:
        refined_query = await refine_query(refine_client, query)

    # SearxNG call stays synchronous (requests library). It blocks the event
    # loop until the local SearxNG responds, but Pryzm is single-user and
    # SearxNG is on the same host — the blocking window is sub-second in
    # practice. Switching to httpx would make this awaitable but buys no
    # real concurrency for this single-user workload.
    try:
        resp = requests.get(
            f"{settings.SEARXNG_URL}/search",
            params={"q": refined_query, "format": "json", "language": "en"},
            timeout=settings.TOOL_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException as exc:
        _set_stats(
            k_requested=capped, k_returned_by_searxng=0, k_fetched_ok=0, k_failed=0,
            failure_reasons={}, fetch_wall_clock_ms=0, extracted_bytes_total=0,
            query_raw=query, query_refined=refined_query,
        )
        return f"Web search failed: {exc}"

    hits = (payload.get("results") or [])[:capped]
    if not hits:
        _set_stats(
            k_requested=capped, k_returned_by_searxng=len(hits), k_fetched_ok=0, k_failed=0,
            failure_reasons={}, fetch_wall_clock_ms=0, extracted_bytes_total=0,
            query_raw=query, query_refined=refined_query,
        )
        return f"No results for {refined_query!r}."

    urls_titles = [(h.get("url", ""), h.get("title", "(no title)")) for h in hits]

    # Fetch all URLs in parallel under a single wall-clock budget. asyncio.wait_for
    # cancels the gather on timeout, discarding even already-completed fetches —
    # so a single 25s straggler in a batch of 8 wipes out the other 7. A
    # shield-based variant could collect partials; v1 accepts the simpler
    # all-or-timeout shape and marks every URL as `timeout` on cancellation.
    results: list[FetchResult] = []
    fetch_t0 = time.monotonic()
    try:
        results = await asyncio.wait_for(
            asyncio.gather(
                *(fetch_and_extract(url, _PER_REQUEST_TIMEOUT_S) for url, _ in urls_titles)
            ),
            timeout=_FETCH_WALL_CLOCK_S,
        )
    except asyncio.TimeoutError:
        results = [FetchResult(url=url, ok=False, failure_reason="timeout") for url, _ in urls_titles]
    fetch_wall_clock_ms = int((time.monotonic() - fetch_t0) * 1000)

    successes_raw: list[tuple[str, str, str]] = []  # (title, url, raw_body)
    failures: list[tuple[str, str]] = []  # (url, reason)
    for (url, title), fr in zip(urls_titles, results):
        if fr.ok:
            successes_raw.append((title, url, fr.body))
        else:
            failures.append((url, fr.failure_reason or "error"))

    # Embedding-based rerank: per-source, keep only chunks semantically similar
    # to the query. Drops sidebars / related-articles / off-topic content that
    # trafilatura preserved. Falls back to raw-body truncation on any embed
    # failure (network, model unloaded) — never blocks synthesis.
    successes: list[tuple[str, str, str]] = []
    if successes_raw:
        async with httpx.AsyncClient() as embed_client:
            for title, url, raw_body in successes_raw:
                chunks = split_into_chunks(raw_body)
                picked = await rerank_chunks_by_query(
                    embed_client, chunks, query, char_budget=_MAX_CHARS_PER_PAGE,
                )
                body = "\n\n".join(picked)
                # Sentence-truncate as a final guard — rerank's char_budget is the
                # primary cap but pathological chunk sizes could overshoot slightly.
                body = truncate_to_sentences(body, _MAX_CHARS_PER_PAGE)
                successes.append((title, url, body))

    failure_reasons: dict[str, int] = {}
    for _, reason in failures:
        failure_reasons[reason] = failure_reasons.get(reason, 0) + 1

    if not successes:
        _set_stats(
            k_requested=capped,
            k_returned_by_searxng=len(hits),
            k_fetched_ok=0,
            k_failed=len(failures),
            failure_reasons=failure_reasons,
            fetch_wall_clock_ms=fetch_wall_clock_ms,
            extracted_bytes_total=0,
            query_raw=query,
            query_refined=refined_query,
        )
        summary = ", ".join(f"{n}× {r}" for r, n in sorted(failure_reasons.items()))
        return (
            f"Web search returned {len(hits)} results but none could be fetched. "
            f"Reasons: {summary}."
        )

    extracted_bytes_total = sum(len(body.encode()) for _, _, body in successes)
    _set_stats(
        k_requested=capped,
        k_returned_by_searxng=len(hits),
        k_fetched_ok=len(successes),
        k_failed=len(failures),
        failure_reasons=failure_reasons,
        fetch_wall_clock_ms=fetch_wall_clock_ms,
        extracted_bytes_total=extracted_bytes_total,
        query_raw=query,
        query_refined=refined_query,
    )

    blocks: list[str] = []
    for i, (title, url, body) in enumerate(successes, 1):
        blocks.append(f"### Source [{i}]: {title}\n{url}\n\n{body}")

    out = "\n\n".join(blocks)

    if failures:
        failure_lines = "\n".join(f"- {url} — {reason}" for url, reason in failures)
        out += f"\n\n**Failed sources**\n{failure_lines}"

    return out
