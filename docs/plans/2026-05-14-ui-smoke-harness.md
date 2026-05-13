# UI Smoke Harness Implementation Plan (chore)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Implementation agents must apply Karpathy guidelines: minimum code, no speculative abstractions, surgical changes, verifiable success criteria.

**Goal:** Add a Playwright-based UI smoke harness so each phase's end-to-end browser verification is scripted instead of manual. Initial scope: harness infrastructure + Phase 2 smoke tests.

**Architecture:** `backend/tests/e2e/` parallels `backend/tests/smoke/`. Pytest-based, sync Playwright API (`playwright.sync_api`), headless Chromium by default. Fixtures handle browser lifecycle, dev-server readiness, and token injection. Each phase will get a `test_phaseN_smoke.py` going forward.

**Tech stack:** Playwright Python (already in venv); pytest harness from Phase 1 reused. No CI integration in this PR — local-run only. No visual regression yet — pass/fail + screenshot capture per test for human review.

**Branch:** `chore/ui-smoke-harness` (cut from main after Phase 2 merged at `a64d07a`).

---

## File Map

### Created
- `backend/tests/e2e/__init__.py` — empty package marker.
- `backend/tests/e2e/conftest.py` — fixtures: browser, context, page, dev_server_ready, screenshot helper, token injection.
- `backend/tests/e2e/test_phase2_smoke.py` — Phase 2 UI smoke tests.
- `backend/tests/e2e/README.md` — how to run locally + prerequisites.

### Modified
- `backend/requirements-dev.txt` — add `pytest-playwright` if not present (`playwright` already in `requirements.txt`).

### Pre-flight (one-time, on each dev machine)
- `playwright install chromium` — downloads the Chromium binary the tests drive. ~150MB.

---

## Task 0 — Install Chromium binary and confirm Playwright is callable

**Files:** none yet — verification only.

- [ ] **Step 1: Install the Chromium binary**

```bash
cd /home/orbital/projects/pryzm/backend
./venv/bin/playwright install chromium
```

Expected: progress bars + a "Chromium ... already installed" or "downloaded" message. Takes 30-90 seconds first time.

- [ ] **Step 2: Confirm Playwright can launch a browser**

```bash
cd /home/orbital/projects/pryzm/backend
./venv/bin/python -c "from playwright.sync_api import sync_playwright; \
  p = sync_playwright().start(); \
  b = p.chromium.launch(headless=True); \
  page = b.new_page(); \
  page.goto('about:blank'); \
  print('ok:', page.url); \
  b.close(); \
  p.stop()"
```

Expected: `ok: about:blank` printed, no errors. If the launch errors with "missing dependencies" it'll print a helpful apt-get command — run that and retry.

- [ ] **Step 3: Verify the dev servers are accessible**

```bash
curl -s -o /dev/null -w "backend :8000 → %{http_code}\n" http://127.0.0.1:8000/health
curl -s -o /dev/null -w "frontend :3000 → %{http_code}\n" http://127.0.0.1:3000/
```

Both should return `200`. If not, start them (see CLAUDE.md or `reference-stack-commands` memory).

(No commit for Task 0 — it's local environment setup.)

---

## Task 1 — Harness infrastructure (conftest + README)

**Files:**
- Create: `backend/tests/e2e/__init__.py` (empty)
- Create: `backend/tests/e2e/conftest.py`
- Create: `backend/tests/e2e/README.md`
- Modify: `backend/requirements-dev.txt` — add `pytest-playwright==0.5.2` if helpful (optional; raw `playwright.sync_api` works without it but `pytest-playwright` provides nice fixtures).

### Step 1: Create the package marker

```bash
touch backend/tests/e2e/__init__.py
```

### Step 2: Write the conftest

Create `backend/tests/e2e/conftest.py`:

```python
"""Pytest fixtures for the e2e UI smoke harness.

Tests in this directory drive a headless Chromium browser against the running
dev servers (backend on :8000, frontend on :3000). The conftest provides:

- A session-scoped Playwright instance and Chromium browser.
- A per-test fresh `BrowserContext` (so cookies/localStorage don't leak).
- A `page` shortcut.
- A `dev_servers_ready` fixture that fails fast if either server is unreachable.
- An `inject_token` helper that pre-seeds localStorage to skip the TokenGate.
- A `screenshot` helper that writes captures to `backend/tests/e2e/_artifacts/`.

These tests are LOCAL ONLY today — no CI integration. Run them while the dev
servers are up:

    cd backend && ./venv/bin/pytest tests/e2e/ -v
"""
from __future__ import annotations

import os
import time
import urllib.request
from pathlib import Path
from typing import Iterator

import pytest
from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright


FRONTEND_URL = "http://127.0.0.1:3000"
BACKEND_URL = "http://127.0.0.1:8000"
ARTIFACTS_DIR = Path(__file__).parent / "_artifacts"


@pytest.fixture(scope="session", autouse=True)
def dev_servers_ready():
    """Fail fast if either dev server is unreachable. Backend /health must be 200;
    frontend root must respond."""
    for name, url in [("backend", f"{BACKEND_URL}/health"), ("frontend", f"{FRONTEND_URL}/")]:
        try:
            urllib.request.urlopen(url, timeout=2)
        except Exception as e:
            pytest.fail(
                f"{name} not reachable at {url}: {e}. Start it before running e2e tests.",
                pytrace=False,
            )


@pytest.fixture(scope="session")
def playwright_instance():
    pw = sync_playwright().start()
    yield pw
    pw.stop()


@pytest.fixture(scope="session")
def browser(playwright_instance) -> Iterator[Browser]:
    b = playwright_instance.chromium.launch(headless=True)
    yield b
    b.close()


@pytest.fixture
def context(browser: Browser) -> Iterator[BrowserContext]:
    """Fresh BrowserContext per test — no state leaks across tests."""
    ctx = browser.new_context()
    yield ctx
    ctx.close()


@pytest.fixture
def page(context: BrowserContext) -> Page:
    return context.new_page()


@pytest.fixture
def api_token() -> str:
    """Read PRYZM_API_TOKEN from .env. Tests assume the token is already valid."""
    env_path = Path(__file__).parent.parent.parent.parent / ".env"
    for line in env_path.read_text().splitlines():
        if line.startswith("PRYZM_API_TOKEN="):
            return line.split("=", 1)[1].strip()
    pytest.fail("PRYZM_API_TOKEN missing from .env", pytrace=False)


@pytest.fixture
def inject_token(page: Page, api_token: str):
    """Returns a callable that pre-seeds the token in localStorage, skipping
    TokenGate. Must be called BEFORE navigating to the app."""
    def _do() -> None:
        page.goto(f"{FRONTEND_URL}/")
        page.evaluate(
            f'() => localStorage.setItem("pryzm_api_token", "{api_token}")'
        )
    return _do


@pytest.fixture
def screenshot(page: Page, request):
    """Yields a callable that captures the page to _artifacts/<test_name>-<label>.png."""
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    captures = []

    def _capture(label: str) -> Path:
        safe = request.node.name.replace("[", "_").replace("]", "_")
        path = ARTIFACTS_DIR / f"{safe}-{label}.png"
        page.screenshot(path=path)
        captures.append(path)
        return path

    yield _capture
```

### Step 3: Add `_artifacts/` to `.gitignore`

Edit `.gitignore` to add:

```
backend/tests/e2e/_artifacts/
```

(near the existing test-cache exclusions).

### Step 4: Write the README

Create `backend/tests/e2e/README.md`:

```markdown
# E2E UI Smoke Harness

Playwright-driven smoke tests that exercise the real frontend against the real
backend in a headless Chromium browser.

## Prerequisites

One-time per dev machine:

```bash
cd backend
./venv/bin/playwright install chromium
```

The dev servers must be running:

```bash
# Terminal A
cd backend && ./venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Terminal B
cd frontend && npm run dev -- -H 0.0.0.0
```

## Run

```bash
cd backend
./venv/bin/pytest tests/e2e/ -v
```

Screenshots are written to `backend/tests/e2e/_artifacts/` (gitignored).

## Layout

- `conftest.py` — fixtures (browser, context, page, token injection, screenshot helper).
- `test_phaseN_smoke.py` — one file per merged phase, covering that phase's UI flows.
- `_artifacts/` — screenshot captures (gitignored).
```

### Step 5: Commit

```bash
cd /home/orbital/projects/pryzm
git add backend/tests/e2e/__init__.py backend/tests/e2e/conftest.py backend/tests/e2e/README.md .gitignore
git commit -m "test(e2e): playwright harness scaffolding with shared fixtures."
```

---

## Task 2 — Phase 2 UI smoke tests

**Files:**
- Create: `backend/tests/e2e/test_phase2_smoke.py`

### Test scope (Phase 2 behaviors that benefit from UI verification)

1. **TokenGate appears** with empty localStorage.
2. **TokenGate accepts a valid token** → main app loads.
3. **Settings panel** shows "Token configured" status + Change + Clear (NO input field pre-filled with the token value).
4. **DOM inspection of the token input** (when Change is clicked) shows `value=""`, not the stored token.
5. **Authorization header** is present on a request to `/workspaces`.
6. **Clearing the token** → TokenGate reappears on reload.

Cross-workspace 404 enforcement is already covered by the HTTP smoke probes in `tests/smoke/`; we don't duplicate it at the UI level.

### Step 1: Write the test file

Create `backend/tests/e2e/test_phase2_smoke.py`:

```python
"""UI smoke tests for Phase 2: auth gate + token UX.

Each test starts from a fresh BrowserContext (cookies/localStorage cleared).
Screenshots are saved to _artifacts/ for human review.
"""
from playwright.sync_api import Page, expect

FRONTEND_URL = "http://127.0.0.1:3000"


def test_token_gate_appears_on_empty_localstorage(page: Page, screenshot):
    page.goto(FRONTEND_URL)
    expect(page.get_by_text("Configure API token")).to_be_visible(timeout=5000)
    expect(page.get_by_placeholder("Paste token")).to_be_visible()
    screenshot("gate-visible")


def test_token_save_loads_app(page: Page, api_token: str, screenshot):
    page.goto(FRONTEND_URL)
    page.get_by_placeholder("Paste token").fill(api_token)
    page.get_by_role("button", name="Save and continue").click()
    # The TokenGate unmounts and the ChatProvider tree mounts. We wait for the
    # sidebar to appear by looking for one of its stable text labels.
    page.wait_for_load_state("networkidle", timeout=10000)
    # The gate's "Configure API token" heading must no longer be visible.
    expect(page.get_by_text("Configure API token")).not_to_be_visible()
    screenshot("app-loaded")


def test_authorization_header_on_workspace_request(page: Page, inject_token, api_token: str):
    """Pre-seed the token, navigate, and intercept a backend request to verify
    the Authorization header is present and matches the configured token."""
    captured = {}

    def _on_request(req):
        if "/workspaces" in req.url and "Authorization" in req.headers:
            captured["header"] = req.headers["Authorization"]

    inject_token()
    page.on("request", _on_request)
    page.reload()
    page.wait_for_load_state("networkidle", timeout=10000)

    assert "header" in captured, "no /workspaces request captured"
    assert captured["header"] == f"Bearer {api_token}", (
        f"unexpected Authorization header: {captured['header']!r}"
    )


def test_settings_token_status_does_not_expose_value(
    page: Page, inject_token, api_token: str, screenshot,
):
    """Per the no-secrets-in-DOM rule: the Settings panel shows a status, not
    an input pre-filled with the actual token value."""
    inject_token()
    page.reload()
    page.wait_for_load_state("networkidle", timeout=10000)

    # Open the Settings modal. Adapt the selector to the actual trigger — the
    # button is typically labeled "Settings" or has a gear icon. If the
    # button isn't reachable by name, fall back to a CSS selector.
    settings_trigger = page.get_by_role("button", name="Settings")
    if settings_trigger.count() == 0:
        # Fallback: look for the gear icon button in the sidebar.
        settings_trigger = page.locator('[aria-label*="ettings" i]').first
    settings_trigger.click()

    # "Token configured" status text must be visible.
    expect(page.get_by_text("Token configured")).to_be_visible(timeout=3000)

    # CRITICAL: no input field with the actual token value in the DOM.
    # Any input in the Settings modal must have value="" (empty) or not be
    # bound to the stored token.
    inputs = page.locator('input[type="password"]')
    for i in range(inputs.count()):
        value = inputs.nth(i).input_value()
        assert value != api_token, (
            f"input #{i} has the stored token as its value attribute "
            "— Phase 2 hardening regression"
        )

    screenshot("settings-token-configured")


def test_change_button_reveals_empty_input(
    page: Page, inject_token, api_token: str, screenshot,
):
    """Clicking Change reveals an empty input; the stored token still isn't
    bound to its value."""
    inject_token()
    page.reload()
    page.wait_for_load_state("networkidle", timeout=10000)

    settings_trigger = page.get_by_role("button", name="Settings")
    if settings_trigger.count() == 0:
        settings_trigger = page.locator('[aria-label*="ettings" i]').first
    settings_trigger.click()

    page.get_by_role("button", name="Change").click()

    new_input = page.locator('input[type="password"]').first
    expect(new_input).to_be_visible(timeout=2000)
    assert new_input.input_value() == "", (
        "Change-mode input is pre-filled — must start empty"
    )
    screenshot("settings-change-mode")


def test_clear_token_brings_back_gate(page: Page, inject_token, screenshot):
    inject_token()
    page.reload()
    page.wait_for_load_state("networkidle", timeout=10000)

    settings_trigger = page.get_by_role("button", name="Settings")
    if settings_trigger.count() == 0:
        settings_trigger = page.locator('[aria-label*="ettings" i]').first
    settings_trigger.click()

    page.get_by_role("button", name="Clear").click()
    # Some apps close the modal on Clear; others stay open. Either way, reload.
    page.reload()
    expect(page.get_by_text("Configure API token")).to_be_visible(timeout=5000)
    screenshot("gate-reappeared-after-clear")
```

### Step 2: Run the tests

```bash
cd /home/orbital/projects/pryzm/backend
./venv/bin/pytest tests/e2e/ -v
```

Expected: all 6 tests pass. Screenshots in `tests/e2e/_artifacts/` (gitignored, just for human review).

If a selector misses (e.g. the Settings button is reachable by a different role/name in the actual UI), adjust the selector to match. Document the adjustment.

### Step 3: Commit

```bash
cd /home/orbital/projects/pryzm
git add backend/tests/e2e/test_phase2_smoke.py
git commit -m "test(e2e): phase 2 UI smoke — token gate + auth header + settings hardening."
```

---

## Task 3 — Final review + PR

- [ ] **Step 1: Full sweep**

```bash
git log main..HEAD --oneline    # → 2 commits
git diff main..HEAD --stat       # → ~7 files
```

Expected: just the new e2e/ directory + .gitignore + requirements-dev.txt (if you added pytest-playwright).

- [ ] **Step 2: Run both test suites one more time**

```bash
cd /home/orbital/projects/pryzm/backend
./venv/bin/pytest tests/ -v
```

Expected: 40 existing + 6 new e2e = 46/46 pass.

- [ ] **Step 3: Push the branch**

```bash
git push -u origin chore/ui-smoke-harness
```

- [ ] **Step 4: Open PR**

**Title:** `chore(tests): playwright UI smoke harness + phase-2 smoke tests`

**Body:**

```markdown
## Summary

Adds a Playwright-driven UI smoke harness so each phase's end-to-end browser verification is scripted instead of manual.

### Why

Phase 2's manual browser checks (TokenGate appearance, auth header propagation, Settings hardening, file upload, message edit/delete) were time-consuming and easy to skip. As we add phases that change frontend behavior (Phase 5 especially), manual coverage doesn't scale. Future phase plans will include an "e2e UI smoke" task that extends `tests/e2e/` with that phase's flows.

### Scope

- `backend/tests/e2e/` directory with conftest fixtures (browser lifecycle, dev-server readiness, token injection, screenshot capture).
- `tests/e2e/test_phase2_smoke.py` — 6 tests covering Phase 2 behaviors: TokenGate appears on empty localStorage, valid token loads app, Authorization header on requests, Settings status-and-edit doesn't expose stored token, Change reveals empty input, Clear → TokenGate reappears.
- `tests/e2e/README.md` — setup + run instructions.
- `_artifacts/` gitignored — screenshot captures for human review.

### Explicitly NOT in this PR

- CI integration — local-run only for now.
- Visual regression baseline — screenshots are just for human inspection.
- Cross-browser testing — Chromium only.
- Frontend lint/typecheck integration into the harness.

### Test plan

- [x] `pytest tests/ -v` — 46/46 pass (40 existing + 6 new).
- [x] `playwright install chromium` works locally.
- [x] Screenshots written to `_artifacts/` and gitignored.

### Notes

- Following PRs (`refactor/phase-N-*`) each add a `tests/e2e/test_phaseN_smoke.py` file covering that phase's frontend-visible changes.
- The harness reads `PRYZM_API_TOKEN` from `.env` and injects it into localStorage via Playwright's `page.evaluate`. Tests therefore implicitly require the dev backend to be running with the same token.
```

- [ ] **Step 5: Squash and merge** per the convention.

---

## Success criteria for the whole chore

- A single command (`pytest tests/e2e/ -v`) runs the UI smoke suite.
- Each Phase 2 behavior the user manually verified before merging Phase 2 is now scripted.
- Screenshots are produced for every test so a human can spot-check visually.
- Future phase plans gain a clearly-defined "extend e2e" task with low marginal cost (~30-50 lines per phase).

---

## Related memory

- [[project-ui-smoke-harness]] — the plan-of-plan rationale.
- [[reference-stack-commands]] — uvicorn + npm commands the tests depend on.
- [[feedback-env-changes-need-restart]] — relevant if .env changes (e.g., token rotation) cause e2e tests to fail.
- [[feedback-karpathy-for-subagents]] — implementation agents executing this plan get Karpathy guidelines in their brief.
