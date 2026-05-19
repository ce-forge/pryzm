# Pryzm UI smoke harness

End-to-end browser tests against the live dev stack. Catches the kind
of regression that's hard to spot in a manual sweep — the autoscroll
race in PR #117 went through three "fixes" before the playwright probe
that became this test caught the real cause.

## Run

1. Make sure the dev stack is alive: `docker compose up -d`, backend on
   `:8000`, frontend on `:3000`, llama-swap on `:8080`.
2. Export credentials for a **non-admin** test user that has at least
   one workspace:
   ```
   export PRYZM_SMOKE_USER=<username>
   export PRYZM_SMOKE_PASS=<password>
   ```
   (Non-admin so the admin-gating test is meaningful. The harness will
   skip cleanly with a hint if the env vars are missing.)
3. From repo root:
   ```
   ./backend/venv/bin/pytest tests/smoke -v
   ```

## What's covered

| Test | Catches |
|---|---|
| `test_login_renders_chat` | Auth or chat-shell mount broken. |
| `test_message_send_produces_a_response` | Streaming pipeline silent end-to-end. |
| `test_admin_test_suite_button_hidden_for_non_admin` | Admin gate regressed (PR #118). |
| `test_markdown_math_renders_via_katex` | KaTeX wiring broken (PR #118). |
| `test_markdown_code_block_renders` | CodeBlock not rendering fenced code. |
| `test_autoscroll_follows_streaming_content` | Autoscroll doesn't keep up with the stream (PR #117). |
| `test_autoscroll_disables_on_wheel_up_and_reengages` | The rAF-timestamp-as-force-flag bug (PR #117). |

## Adding tests

Drop a `test_<thing>(authed_page)` function into `test_smoke.py`.
Helpers in `conftest.py`:

- `send_prompt(page, text, settle_s=0.3)` — types + submits a prompt.
- `chat_scroll_state(page)` — reads `{scrollTop, scrollHeight, clientHeight, distance}` for the chat feed (not the sidebar).
- `wait_for_overflow(page, min_overflow_px=400, timeout_s=45)` — blocks until the feed exceeds the viewport by `min_overflow_px`. Required before any scroll-based assertion.

## When to run

Before merging any UI-touching PR. The autoscroll tests in particular
catch a failure mode that's hard to spot by eye during a manual sweep.

## What it doesn't cover

- Mobile / touch interaction paths.
- Visual regressions (no pixel-diff). Layout and styling slip-ups need
  manual review or a separate visual-snapshot tool.
- Backend correctness — that's covered by `backend/tests/`.
