"""Web search tool — queries a locally-hosted SearxNG instance.

SearxNG runs as a docker-compose service (see infra/searxng/settings.yml). The
tool calls its JSON API and returns a compact markdown list of the top-N hits
so the LLM can cite URLs in its reply. Failures degrade to a one-line error
string rather than raising — the LLM falls back to local knowledge.
"""
from __future__ import annotations

import requests

from config import settings
from .registry import tool


@tool(
    properties={
        "query": {
            "type": "string",
            "description": "The search query — natural language is fine.",
        },
        "num_results": {
            "type": "integer",
            "description": "How many top hits to return (default 3, max 5).",
        },
    },
    required=["query"],
    system_prompt_directive=(
        "Use `web_search` only for factual questions whose answer may have "
        "changed since training (current events, recent vendor releases, "
        "newly-published docs, news). Do NOT use it for questions answerable "
        "from local knowledge-base documents or general background knowledge."
    ),
)
def web_search(query: str, num_results: int = 3) -> str:
    """Search the web via SearxNG and return the top results as markdown."""
    capped = max(1, min(num_results, 5))
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

    lines = [f"Top {len(hits)} results for {query!r}:"]
    for i, hit in enumerate(hits, 1):
        title = hit.get("title", "(no title)")
        url = hit.get("url", "")
        snippet = (hit.get("content") or "").strip()
        lines.append(f"{i}. **{title}**\n   {url}\n   {snippet}")
    return "\n\n".join(lines)
