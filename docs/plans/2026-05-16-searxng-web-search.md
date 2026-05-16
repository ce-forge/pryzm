# SearxNG web_search — PR-A implementation plan

**Spec:** `docs/specs/2026-05-16-searxng-web-search.md`
**Branch:** `feat/searxng-web-search`
**Scope:** SearxNG service + `web_search` tool. Workspace-level opt-in only. No modes foundation, no UI toggle (those land in PR-B).

## Steps

1. **Backend tests (RED).** `backend/tests/test_web_search.py` — 8 tests, all expected to fail until step 2.
2. **Backend tool (GREEN).** `backend/tools/web.py`. Register via `@tool(workspaces=["it_copilot"], system_prompt_directive=...)`. Import from `backend/tools/__init__.py` so the registry picks it up at module load.
3. **Config.** Add `SEARXNG_URL: str = "http://127.0.0.1:8888"` to `backend/config.py`.
4. **SearxNG service.** Add `searxng` to `docker-compose.yml` (127.0.0.1:8888, restart: always, settings mounted ro). Create `infra/searxng/settings.yml` with `use_default_settings: true` and overrides (secret_key, limiter off, JSON format, en).
5. **Verify.** Full backend suite green. `docker compose up -d searxng` then `curl 127.0.0.1:8888/search?q=test&format=json`. Live tool call via the Python REPL returns proper markdown.
6. **Docs.** Spec + this plan. Commit. Push branch.
7. **Open PR.** Lean PR body (per `feedback_lean_pr_descriptions.md`).

## Verification

**Automated:** `./venv/bin/pytest tests/test_web_search.py` (8 pass). Full suite: 250+ pass, no regressions.

**Manual (post-merge or pre-merge after backend restart):**
1. `docker compose up -d searxng`
2. Backend restart (`--reload` doesn't watch new tool modules deterministically; clean restart is the safe move).
3. WorkspaceSettings → IT Copilot → toggle `web_search` on.
4. Ask a current-info question (e.g. "what's the latest macOS version?"). Confirm tool fires, result renders in `ToolCallsBlock`, LLM cites the URLs in its reply.

## Out of scope (PR-B)

- `modes: list[str]` field on `InferenceRequest`
- `backend/core/modes.py` registry + `apply_modes()`
- Globe-icon toggle in `ChatInput.tsx`
- Per-session `webSearchEnabled` state on `ChatContext`
- `modes` forwarding in `useInference.ts`

## Risk notes

- `searxng/searxng:latest` is a floating tag. Pin by digest in a chore PR if it drifts (matches the `llama-swap` pinning convention).
- SearxNG's first request after container start does engine handshakes; expect a slow first call (~2–3s). Subsequent calls are fast.
- Some upstream engines occasionally rate-limit. SearxNG returns the engines that did respond + `unresponsive_engines` in the JSON. Today we surface results as-is; partial degradation is acceptable.
