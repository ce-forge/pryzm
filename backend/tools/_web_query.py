"""Query refinement for the web_search tool.

The main chat model formulates a `query` arg when it decides to invoke
`web_search`, but that query inherits the user's phrasing — typos, vague
time references ("this week"), missing context. A single-shot rewrite via
the always-on small model normalizes the query before SearxNG sees it,
injects today's date so time-bound questions get year/month grounding, and
catches obvious typos.

Borrowed from huggingface/chat-ui's `src/lib/server/websearch/search/generateQuery.ts`.
Falls back to the raw query on any failure — never blocks the tool turn.
"""
from __future__ import annotations

from datetime import date

import httpx

from core import llm_server


_REFINE_PREPROMPT = (
    "Rewrite the user's question as a concise Google search query.\n"
    "Today is {today}.\n\n"
    "Rules:\n"
    "1. Replace vague time references (\"this week\", \"today\", \"latest\", "
    "\"current\", \"now\", \"recently\", \"upcoming\") with the explicit "
    "month and year derived from today's date.\n"
    "2. Fix typos.\n"
    "3. Preserve specifics from the question — names, places, version "
    "numbers, model numbers — do NOT generalise them away.\n"
    "4. Strip filler like \"what is\", \"how do I\", \"can you tell me\".\n"
    "5. Output ONLY the rewritten search query. No quotes, no prefix, "
    "no explanation."
)


async def refine_query(
    client: httpx.AsyncClient,
    raw_query: str,
    *,
    today: str | None = None,
    model: str = llm_server.DEFAULT_SMALL_CHAT_MODEL,
) -> str:
    """Return a refined search query string. On any error returns `raw_query`
    unchanged. `today` defaults to the current ISO date if not supplied —
    inject explicitly in tests for determinism."""
    if not raw_query or not raw_query.strip():
        return raw_query
    today_str = today or date.today().isoformat()
    prompt = (
        _REFINE_PREPROMPT.format(today=today_str)
        + f"\n\nQuestion: {raw_query.strip()}"
    )
    try:
        out = await llm_server.generate(
            client,
            prompt=prompt,
            model=model,
        )
    except Exception:
        return raw_query
    refined = out.strip().strip('"').strip("'")
    refined = refined.splitlines()[0] if refined else ""
    if not refined:
        return raw_query
    return refined
