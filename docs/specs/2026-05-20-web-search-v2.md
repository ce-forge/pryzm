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
- Model writes the response with inline `[N]` citation markers and a `**Sources**` footer mapping each marker to a URL.
- Globe toggle in the chat input remains the only user-facing signal — turning it on means "do real research."
- A model carrying the `web` tag handles the synthesis turn, so admins can move web work to a stronger model without touching code.
- Tool-result block in the chat UI collapses to a compact "Searched: N sources" pill instead of dumping the per-source markdown.
- Per-source failures degrade gracefully — one timed-out page does not kill the whole turn.

## Non-goals

- Separate `web_search_research` tool or `deep_research` mode. Single tool, upgraded in place.
- URL-level caching. Same-query repeats refetch in v1. Revisit if real usage shows it pays off.
- Rich citation UI (superscript chips, hover-popovers, click-to-scroll). The model writes plain `[N]` markers and a Sources footer; the existing markdown pipeline renders them.
- JavaScript-rendered pages. Trafilatura on raw HTML only. Pages that are SPA shells with no server-rendered text return empty and are reported as failed sources.
- Robots-respecting fetching. We are a small self-hosted IT copilot, not a crawler.

## Architecture

End-to-end, when the user sends a turn with the globe toggle on:

1. Frontend sends `modes: ["web_search"]` in the inference request.
2. Backend's `apply_modes()` activates the `web_search` mode, which force-includes the `web_search` tool and emits a `tier_override="web"` hint.
3. The chat router picks a model. `stream_chat` consumes the tier hint: if a model carries the `web` tag, that model is used for this turn instead of the heuristic pick. If no model is tagged, the heuristic pick stands.
4. Model invokes `web_search(query, num_results=3)`.
5. Tool calls SearxNG, then fetches each result URL in parallel with a 25s wall-clock fetch budget (inside the engine's 30s outer tool timeout), extracts main content via trafilatura in precision mode, caps each to 3000 chars.
6. Tool returns one `### Source [N]: <title>` block per successful fetch with the URL on its own line and the extracted body below. Failed sources go in a `**Failed sources**` footer.
7. Synthesis turn (same loop iteration's next LLM call) sees the structured blocks and the tool's `system_prompt_directive` telling it to cite each claim with `[N]` and end with a `**Sources**` footer.
8. Frontend renders the tool-result block as a collapsed "Searched: 5 sources" pill; the assistant prose with inline `[N]` markers and the sources footer render through the normal markdown path.

## Backend changes

### Model catalog (`infra/llama-swap-config.yaml`)

Add `web` to `gemma-4-E2B-it`'s tags. E2B is the always-on small model; tagging it `web` means the synthesis turn for a research call lands on E2B by default. If E2B can't write clean cited research, the tag moves to `gemma-4-E4B-it` or `gemma-4-26B-A4B-it` with no code change.

```yaml
"gemma-4-E2B-it":
  cmd: |-
    /app/llama-server --port ${PORT}
    -hf bartowski/google_gemma-4-E2B-it-GGUF:Q4_K_M
    -ngl 99 --ctx-size 8192 --jinja --flash-attn on
  tags:
    - web
  groups:
    - always-on
```

### Router (`core/llm_router.py`)

New method on `HeuristicRouter`:

```python
def web_capable_model(self) -> str | None:
    """First chat model carrying the `web` tag, or None. Mirrors
    vision_capable_model() — tag-driven so the catalog YAML is the
    only place that decides which model runs research synthesis."""
    for model_id, tags in self.catalog.items():
        if "web" in tags and "embedding" not in tags:
            return model_id
    return None
```

Identical shape to `vision_capable_model()`. Returns `None` if no model is tagged — the caller falls back to the heuristic pick.

### Modes (`core/modes.py`)

Set `tier_override="web"` on the existing `web_search` mode. The dataclass already has the field; this is its first real consumer.

```python
register_mode(Mode(
    name="web_search",
    force_tools=["web_search"],
    gates_tools=["web_search"],
    tier_override="web",
))
```

Mode's `directive` stays empty. Citation guidance lives on the tool, not the mode.

### Engine wiring (`core/ai_engine.py`)

After `apply_modes` returns its tier hint, override the router's pick when the hint matches a tagged model:

```python
tool_set, system_prompt, tier_hint = apply_modes(tool_set, system_prompt, modes)
model_id, tier, reason = router.pick(prompt, history, attachments)
if tier_hint == "web":
    web_model = router.web_capable_model()
    if web_model is not None:
        model_id = web_model
        reason = "mode_tier_override:web"
```

Generic enough that future modes (`code-mode` with `tier_override="code"`, etc.) reuse the same path by adding their own `*_capable_model()` lookup.

### Tool rewrite (`tools/web.py`)

Async tool. Signature:

```python
@tool(
    properties={
        "query": {"type": "string", "description": "..."},
        "num_results": {"type": "integer", "description": "How many top hits to fetch and read (default 5, max 8)."},
    },
    required=["query"],
    workspaces=["it_copilot", "personal"],
    system_prompt_directive=WEB_SEARCH_DIRECTIVE,
)
async def web_search(query: str, num_results: int = 5) -> str:
    ...
```

Behavior:

1. Call SearxNG for top-K hits (K capped at 8, default 5).
2. Fetch all URLs in parallel via `httpx.AsyncClient` inside `asyncio.wait_for(..., timeout=25)`. Per-request timeout 8s. The 25s ceiling sits under the engine's `TOOL_TIMEOUT_SECONDS=30` so the inner budget always trips first and the tool can return a partial result rather than getting cancelled by the outer guard.
3. For each successful fetch (HTTP 2xx, content-type `text/html*` or `application/xhtml+xml`), extract main content with `trafilatura.extract(html, include_comments=False, include_tables=True)`.
4. Truncate each extracted body to 6000 chars at a sentence boundary. A small helper walks the body, accumulates whole sentences, and stops before exceeding the cap — `textwrap.shorten` is too aggressive on prose where one sentence can run past the limit on its own.
5. Assemble output:

   ```
   ### Source [1]: <title from SearxNG>
   <URL>

   <extracted body, ≤6000 chars>

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

The `WEB_SEARCH_DIRECTIVE` constant in the same module:

> Use `web_search` for factual questions whose answer may have changed since training (current events, recent vendor releases, newly-published docs, news). Do NOT use it for questions answerable from local knowledge-base documents or general background knowledge.
>
> Results are returned as one or more `### Source [N]: <title>` blocks, each containing the source URL on its own line and an extracted page body below. When writing your reply, cite every factual claim by appending `[N]` referring to the source index. End your reply with a `**Sources**` section listing each cited source as `[N] <URL>`. Do not cite sources you did not use.

### Dependencies

Add to `backend/requirements.txt`:

- `trafilatura` (latest stable). Pulls in `lxml`, `justext` as deps; all wheel-installable, no compile required on the dev box.

`httpx` is already transitively available via FastAPI's `TestClient`, but it is not listed as a top-level dep. Add it explicitly.

### Audit (`core/audit.py` / engine emission point)

The existing `chat.web_search` audit event is augmented with a richer payload:

```json
{
  "query": "...",
  "k_requested": 5,
  "k_returned_by_searxng": 5,
  "k_fetched_ok": 4,
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
- Mock httpx with `respx` or similar so we don't hit the live internet from the test suite. Fixtures for: success, timeout, 403, non-HTML content-type, empty trafilatura output.
- `tests/test_modes.py` — assert `web_search` mode's `tier_override` round-trips through `apply_modes` as `"web"`.
- New `tests/test_llm_router.py` (or extend existing) — `web_capable_model()` returns the tagged model, returns `None` when no model is tagged.
- `tests/test_ai_engine.py` — when modes return `tier_hint == "web"` and a model is tagged, `stream_chat` uses that model.

Frontend:

- Manual smoke under the `qatest` account: globe on, ask a factual current-events question, verify (a) tool-result block renders as a collapsed pill, (b) expanded view shows `### Source [N]` blocks, (c) assistant reply has inline `[N]` markers and a Sources footer with clickable URLs.
- Playwright smoke under `tests/smoke/` adds a `web_search.spec.ts` that drives the same flow and asserts the pill renders.

## Open questions

None blocking. Two items deferred to first real-usage observations:

- E2B-vs-larger for synthesis. If E2B writes weak cited research, the `web` tag moves to E4B or 26B with no code change. Single-line YAML edit, `kill -s HUP llama-swap`.
- Caching. If users repeatedly research the same topics, add a small `URL → (body, fetched_at)` cache in front of the fetch loop. Unlikely to be needed.
