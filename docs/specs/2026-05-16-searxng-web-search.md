# SearxNG web_search tool — design spec

**Status:** PR-A in flight (this PR). PR-B (modes foundation + UI toggle) planned next.
**Filed:** 2026-05-16
**Tracks:** task #50 (second half — the first half was the tool-directive refactor, PR #72).
**Related memory:** `project_searxng_next_session.md`, `feedback_tool_guidance_lives_on_tools.md`.

## Problem

The "Google search integration" line item in `docs/internal/2026-05-14-future-features.md` was promoted to **SearxNG self-hosted** to avoid API-key cost and per-provider lock-in (Google CSE / Brave / SerpAPI). Pryzm's IT-copilot use case routinely hits questions whose answers post-date training data (current versions, vendor advisories, KB articles), and the LLM has no path to the open web today.

## Goal

A `web_search` tool that queries a locally-hosted SearxNG instance and returns the top hits as markdown. The LLM cites URLs in its reply naturally; no new UI rendering required for v1.

## Phasing

Two PRs.

**PR-A (this PR):** SearxNG container, `web_search` tool, env wiring. Workspace-level opt-in via the existing `enabled_tools` mechanism — no per-turn override path. Lets us validate SearxNG quality and the tool's output shape end-to-end with minimum surface area.

**PR-B (next):** Per-turn "modes" foundation (`modes: list[str]` on `InferenceRequest`, registry parallel to tools, `force_tools` + `directive` + `tier_override` levers). Globe-icon toggle next to the send button. `web_search` becomes mode #1. Sets up the seam for future neighbors: deep-research, strict-RAG, code-mode, brainstorm.

This spec covers PR-A. PR-B will land its own spec when it begins.

## Architecture (PR-A)

### `web_search` tool — `backend/tools/web.py`

- `web_search(query: str, num_results: int = 3) -> str`. `num_results` clamps to [1, 5].
- Calls `${SEARXNG_URL}/search?q=...&format=json&language=en` via `requests`, timeout `TOOL_TIMEOUT_SECONDS` (30s).
- Returns markdown: `"Top N results for 'query':"` + numbered list of `**title**`, URL, snippet.
- Failure modes return a one-line string (HTTPError, ConnectionError, timeout). Never raises — the LLM needs a string back to plan its next step.
- Empty results → `"No results for 'query'."`.

### `@tool` registration

- `system_prompt_directive` describes when to use it: factual questions whose answer may have changed (current events, recent vendor releases, newly-published docs, news). Explicitly *not* for questions answerable from local KB or general knowledge.
- Default `workspaces=["it_copilot"]` — personal workspace is intentionally excluded.
- Not added to any builtin's default `enabled_tools` list. Workspaces opt in via WorkspaceSettings.

### SearxNG service

- `searxng/searxng:latest` (will pin by digest in a follow-up chore if it proves stable).
- Container name `pryzm_searxng`. Bound `127.0.0.1:8888:8080`.
- `infra/searxng/settings.yml` — minimal override on top of upstream defaults:
  - `use_default_settings: true`
  - `server.secret_key` set (required by upstream; rotate if SearxNG ever leaves loopback)
  - `server.limiter: false` (we hit it from the backend, not browsers)
  - `search.formats: [html, json]`
  - `search.default_lang: en`

### Config

- New `SEARXNG_URL: str = "http://127.0.0.1:8888"` on `Settings` (`backend/config.py`).

## Verification

**Automated (this PR):**
- `backend/tests/test_web_search.py` — 8 tests covering: happy-path top-N markdown shape, default `num_results=3`, empty-results message, HTTP 5xx returns message (no raise), connection error returns message (no raise), query reaches SearxNG with correct params, decorator registration with directive, JSON schema exposure.
- Mocks `requests.get`; no real network.

**Manual (on this PR):**
- `docker compose up -d searxng` — container starts.
- `curl 127.0.0.1:8888/search?q=test&format=json` — returns valid JSON with `results`.
- Enable `web_search` on a workspace via Settings, ask a current-info question, confirm the LLM invokes the tool and the result renders in `ToolCallsBlock`.

## Out of scope (deferred)

- Per-turn "modes" mechanism + UI toggle — PR-B.
- Structured citation rendering (`CitationCard` component) — PR-C, only if v1 plain markdown proves noisy.
- Per-workspace SearxNG settings (region, safe-search) — deferred to `tool_config` JSONB once that lands.
- A `web_fetch_page` companion tool — out of scope; if it lands, `tools/web.py` gets a `MODULE_DIRECTIVE` then.

## Open questions (non-blocking)

1. **Default `num_results`.** Three (proposed) vs five. Token cost vs citation density. Three holds for v1.
2. **Upstream rate limits.** SearxNG occasionally surfaces 429 from individual engines via `unresponsive_engines`. Today we treat any HTTP error as a string fallback; degraded-but-partial results are still returned because SearxNG itself returns 200.
