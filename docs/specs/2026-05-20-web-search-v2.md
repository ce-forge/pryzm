# Web search v2 — page fetch + citations

## Status

Design ready for implementation. Builds on the SearxNG `web_search` tool shipped in PR #75 and the per-turn modes foundation in `core/modes.py`. Upgrades the tool in place — no new tool, no new mode, no new user-facing toggle.

## Why

The shipped `web_search` returns the top-N SearxNG hits as a snippet-only markdown list: title, URL, and the ~150-char content blurb that SearxNG ships per result. The chat model paraphrases from those blurbs without ever opening the linked pages, and the response carries no attribution — the user has no easy way to verify a claim or read further.

Three observed problems:

1. **No depth.** A SearxNG snippet is typically the first paragraph of the page or whatever the source set as `og:description`. The model is "researching" from headline-level text.
2. **No citations.** The model paraphrases all sources into one prose block. There is no marker tying any specific claim back to a specific URL.
3. **Noisy tool output.** The structured markdown list of titles + URLs + snippets renders verbatim in the chat as a tool-result block, ~30KB of text the user did not ask to see.

The fix is to pull page contents into the loop, give the model real text to synthesize over, and ask it to cite as it writes.

## Goals

- One `web_search` tool that fetches page contents for the top-K hits, extracts main content, and returns structured per-source blocks.
- Model writes the response with inline `[N]` citation markers only — no `**Sources**` footer, no URL list. The frontend renders the source list itself as a pill below the message.
- Globe toggle in the chat input remains the only user-facing signal — turning it on means "do real research."
- The synthesis turn runs on whatever model the existing heuristic router picks — no special override. Complex queries that trip `COMPLEX_VERBS` escalate to the larger model the same way they would without web_search.
- Tool-result block in the chat UI collapses to a compact "Searched: N sources" pill instead of dumping the per-source markdown.
- Per-source failures degrade gracefully — one timed-out page does not kill the whole turn.

## Non-goals

- Separate `web_search_research` tool or `deep_research` mode. Single tool, upgraded in place.
- URL-level caching. Same-query repeats refetch in v1. Revisit if real usage shows it pays off.
- Rich citation UI (superscript chips, hover-popovers, click-to-scroll). The model writes plain `[N]` markers inline; the existing markdown pipeline renders them and the frontend assembles the source list separately.
- JavaScript-rendered pages. Trafilatura on raw HTML only. Pages that are SPA shells with no server-rendered text return empty and are reported as failed sources.
- Robots-respecting fetching. We are a small self-hosted IT copilot, not a crawler.

## Architecture

End-to-end, when the user sends a turn with the globe toggle on:

1. Frontend sends `modes: ["web_search"]` in the inference request.
2. Backend's `apply_modes()` activates the `web_search` mode, which force-includes the `web_search` tool. The router's heuristic pick stands — no tier override.
3. Model invokes `web_search(query, num_results=3)`.
4. Tool refines the raw query via the always-on small model (fixes typos, strips filler, preserves time references), then calls SearxNG with an optional `time_range=month` filter when the query carries a recency signal ("latest", "current", "recent", etc).
5. Tool fetches each result URL in parallel via Playwright + headless chromium (see `backend/tools/_web_fetch.py`) with a 25s wall-clock fetch budget (inside the engine's 30s outer tool timeout), extracts main content via trafilatura in precision mode on the rendered DOM, splits into paragraph chunks, reranks chunks by cosine similarity to the user's prompt via the always-on embedding model, and keeps the top chunks per page within a 3000-char budget.
6. Tool returns one `### Source [N]: <title>` block per successful fetch with the URL on its own line and the extracted body below. The output begins with a `**Searched as:** <refined query>` header and ends with an optional `**Failed sources**` block.
7. Synthesis turn (same loop iteration's next LLM call) sees the structured blocks and the tool's `system_prompt_directive` telling it to cite each claim inline with `[N]` and forbidding any `**Sources**` footer or URL list in the reply. The directive also nudges the model to issue SEPARATE web_search calls per entity for comparison questions.
8. Frontend renders the tool-result block as a sleek "N sources" pill below the assistant message (only after the stream completes). Expansion shows the refined query, the source list with clickable URLs, and any failed sources in a muted footer.

## Backend changes

### Modes (`core/modes.py`)

The `web_search` mode uses `force_tools` and `gates_tools` only — it does NOT set `tier_override`. The router's heuristic decides the model for the turn based on prompt complexity, history depth, attachments, etc. — same as any non-web turn.

```python
register_mode(Mode(
    name="web_search",
    force_tools=["web_search"],
    gates_tools=["web_search"],
))
```

An earlier iteration of this spec pinned web turns to a `web`-tagged model via `tier_override`. The override silently downgraded complex queries the heuristic had escalated to the large tier, so it was removed. The `tier_override` field on the `Mode` dataclass stays for future modes that genuinely need to pin a tier (e.g. `code-mode`), but no shipped mode uses it today.

### Tool rewrite (`tools/web.py`)

Async tool. Signature:

```python
@tool(
    properties={
        "query": {"type": "string", "description": "..."},
        "num_results": {"type": "integer", "description": "How many top hits to fetch and read (default 3, max 8)."},
    },
    required=["query"],
    workspaces=["it_copilot", "personal"],
    system_prompt_directive=WEB_SEARCH_DIRECTIVE,
)
async def web_search(query: str, num_results: int = 3) -> str:
    ...
```

Behavior:

1. Call SearxNG for top-K hits (K capped at 8, default 3).
2. Fetch all URLs in parallel via Playwright + headless chromium (`backend/tools/_web_fetch.py`) inside `asyncio.wait_for(..., timeout=25)`. Per-request timeout 8s. The 25s ceiling sits under the engine's `TOOL_TIMEOUT_SECONDS=30` so the inner budget always trips first and the tool can return a partial result rather than getting cancelled by the outer guard.
3. For each successful fetch (HTTP 2xx, content-type `text/html*` or `application/xhtml+xml`), extract main content with `trafilatura.extract(html, include_comments=False, include_tables=False, favor_precision=True)`. Precision over recall keeps cookie banners, related-articles, and sidebars out of the model's context; `include_tables=False` drops ASCII-table grids that corrupt the synthesis prompt.
4. Truncate each extracted body to 3000 chars at a sentence boundary. A small helper walks the body, accumulates whole sentences, and stops before exceeding the cap — `textwrap.shorten` is too aggressive on prose where one sentence can run past the limit on its own.
5. Assemble output:

   ```
   ### Source [1]: <title from SearxNG>
   <URL>

   <extracted body, ≤3000 chars>

   ### Source [2]: ...
   ```

6. If any source failed, append a footer:

   ```
   **Failed sources**
   - <URL> — timeout
   - <URL> — 403
   ```

   Reasons map: `timeout`, `<status code>`, `non-html`, `empty` (trafilatura returned nothing usable), `error` (catch-all).

7. If every source failed: return a single line — `Web search returned <K> results but none could be fetched. Reasons: <count summary>.` Lets the model fall back to internal knowledge or ask for refinement.

The `WEB_SEARCH_DIRECTIVE` (loaded from `core/prompts/tool_directives.default.json`) tells the model:

> Use `web_search` for factual questions whose answer may have changed since training (current events, recent vendor releases, newly-published docs, news). Do NOT use it for questions answerable from local knowledge-base documents or general background knowledge.
>
> Results are returned as one or more `### Source [N]: <title>` blocks, each containing the source URL on its own line and an extracted page body below. When writing your reply, cite every factual claim with an inline `[N]` marker referring to the source index. The frontend renders the source list separately as a pill below the message, so **do not** write a `**Sources**` footer or list any URLs in your reply — inline `[N]` markers only. Do not echo the `**Searched as:**` header or `**Failed sources**` block; both are internal metadata.

### Dependencies

Add to `backend/requirements.txt`:

- `trafilatura` (latest stable). Pulls in `lxml`, `justext` as deps; all wheel-installable, no compile required on the dev box.
- `playwright`. Headless chromium drives the actual fetch so JS-rendered pages produce real DOM. Browser binary install runs once via `playwright install chromium` in the backend setup path.

### Audit (`core/audit.py` / engine emission point)

The existing `chat.web_search` audit event is augmented with a richer payload:

```json
{
  "query_preview": "...",
  "query_refined": "...",
  "k_requested": 3,
  "k_returned_by_searxng": 3,
  "k_fetched_ok": 2,
  "k_failed": 1,
  "failure_reasons": {"timeout": 1},
  "fetch_wall_clock_ms": 11420,
  "extracted_bytes_total": 22418,
  "synthesis_model_id": "gemma-4-E2B-it"
}
```

Lets us answer "is this getting slow?" and "is one model carrying all the research load?" without new tables. Query string is already audit-logged today; the additional keys are additive.

## Frontend changes

### Tool-result rendering

Locate the component that renders tool-result blocks in the chat surface (`ToolCallsBlock.tsx` per recent UI work). Add a special case keyed on the tool name `web_search`:

- Default state: a single-line pill — `Searched: N sources` (where N is the count of `### Source [` headers in the result body). Globe icon to the left, count to the right.
- Click-to-expand reveals the raw markdown body, rendered through the existing markdown pipeline.
- Failed-sources footer, if present, renders inside the expanded view in a muted style.

Every other tool's result block renders unchanged.

### Inline citations and sources footer

No new components. The model writes `[1]`, `[2]` as plain text inline and ends with a markdown `**Sources**` section. The existing assistant-message markdown renderer handles both — URL auto-linking already works in the Sources footer.

### Globe toggle

No changes. Already gated on `enabled_tools.includes("web_search")` and dispatches `modes: ["web_search"]` on send.

## Error handling

| Condition | Tool behavior | User-visible effect |
|---|---|---|
| SearxNG returns no hits | Returns `No results for <query>.` | Model relays. |
| One page timeout or non-HTML | Skip with marker in Failed sources footer | Remaining sources synthesized normally. Failed list appears at the bottom of the expanded tool-result block. |
| All pages fail | Single-line error message | Model can answer from internal knowledge with caveat, or ask user to refine. |
| Trafilatura returns empty | Marked `empty` in Failed sources | Same as one-page failure. |
| SearxNG itself unreachable | Returns `Web search failed: <exc>` (current behavior) | Model falls back to internal knowledge — unchanged from today. |

## Observability

- Augmented `chat.web_search` audit event (see Audit section above).
- Backend log line per tool invocation at INFO level summarizing the same payload — easier to spot regressions during dev than tailing the audit table.
- No new tables, no new metrics endpoint. If usage shows we need them, that is a follow-up.

## Test plan

Backend:

- `tests/test_web_search.py` — extend existing tests to cover the new payload shape, structured output, per-source failure handling, all-fail path, K-capping at 8.
- Mock the fetcher at the `_render_page` seam (`tools/_web_fetch.py`) so the test suite never spins up a real chromium. Fixtures cover success, timeout, 403, non-HTML content-type, empty trafilatura output.
- `tests/test_modes.py` — assert `web_search` mode does NOT set `tier_override` (router decides).
- `tests/test_web_search_query.py` — refinement preserves time references and recency words; falls back to raw on LLM failure.
- `tests/test_web_search_fetch.py` — Playwright-backed fetcher (mocked at `_render_page` seam) classifies each failure mode (timeout, 403, non-html, empty, error).
- `tests/test_web_search_rerank.py` — paragraph splitter + cosine similarity + rerank order.

Frontend:

- Manual smoke under the `qatest` account: globe on, ask a factual current-events question, verify (a) tool-result block renders as a collapsed pill, (b) expanded view shows `### Source [N]` blocks, (c) assistant reply has inline `[N]` markers and the frontend-rendered source list pill below the message — and no `**Sources**` footer in the message body itself.
- Playwright smoke under `tests/smoke/` adds a `web_search.spec.ts` that drives the same flow and asserts the pill renders.

## Open questions

None blocking. Two items deferred to first real-usage observations:

- Comparison queries. The model can already issue multiple `web_search` calls per turn (the directive nudges this for "A vs B" questions), but the small model may not consistently decompose. If real usage shows it doesn't, the deterministic fallback is to have the refinement step emit multiple queries when the input is comparative.
- Caching. If users repeatedly research the same topics, add a small `URL → (body, fetched_at)` cache in front of the fetch loop. Unlikely to be needed.
