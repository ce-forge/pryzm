"""Query refinement for the web_search tool.

The main chat model formulates a `query` arg when it decides to invoke
`web_search`, but that query often inherits the user's phrasing — typos,
filler words like "what is" / "how do I", verbose framing. A single-shot
rewrite via the always-on small model normalises the query before SearxNG
sees it.

Time references in the user's phrasing ("this week", "last month", "Q1 2025")
are preserved verbatim — they're the user's intent signal, and SearxNG ranks
on them. We do NOT inject today's date or rewrite time words; if the user
wanted historical scoping they'd say so themselves.

Falls back to the raw query on any failure — never blocks the tool turn.
"""
from __future__ import annotations

import httpx

from core import llm_server


_REFINE_PREPROMPT = (
    "Rewrite the user's question as a concise search query.\n\n"
    "Rules:\n"
    "1. Fix typos.\n"
    "2. Strip filler like \"what is\", \"how do I\", \"can you tell me\".\n"
    "3. Preserve specifics — names, places, version numbers, model numbers — "
    "and ALWAYS preserve recency / time words verbatim (\"current\", "
    "\"latest\", \"recent\", \"recently\", \"now\", \"today\", \"this week\", "
    "\"this month\", \"upcoming\", \"new\", \"last month\", \"Q1 2025\", "
    "etc). These words carry the user's freshness intent and must NOT be "
    "treated as filler or replaced with dates.\n"
    "4. Output ONLY the rewritten search query. No quotes, no prefix, "
    "no explanation."
)


async def refine_query(
    client: httpx.AsyncClient,
    raw_query: str,
    *,
    model: str = llm_server.DEFAULT_SMALL_CHAT_MODEL,
) -> str:
    """Return a refined search query string. On any error returns `raw_query`
    unchanged."""
    if not raw_query or not raw_query.strip():
        return raw_query
    prompt = _REFINE_PREPROMPT + f"\n\nQuestion: {raw_query.strip()}"
    try:
        out = await llm_server.generate(client, prompt=prompt, model=model)
    except Exception:
        return raw_query
    refined = out.strip().strip('"').strip("'")
    refined = refined.splitlines()[0] if refined else ""
    if not refined:
        return raw_query
    return refined
