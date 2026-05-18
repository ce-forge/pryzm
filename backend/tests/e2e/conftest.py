"""Pytest fixtures for the e2e UI smoke harness.

Tests in this directory drive a headless Chromium browser against the running
dev servers (backend on :8000, frontend on :3000). The conftest provides:

- A session-scoped Playwright instance and Chromium browser.
- A per-test fresh `BrowserContext` (so cookies/localStorage don't leak).
- A `page` shortcut.
- A `dev_servers_ready` fixture that fails fast if either server is unreachable.
- A `session_cookie` fixture that logs in via /api/auth/login and returns the
  pryzm_session cookie value for tests that hit the backend directly.
- A `screenshot` helper that writes captures to `backend/tests/e2e/_artifacts/`.

These tests are LOCAL ONLY today — no CI integration. Run them while the dev
servers are up:

    cd backend && ./venv/bin/pytest tests/e2e/ -v
"""
from __future__ import annotations

import os
import urllib.request
from pathlib import Path
from typing import Iterator

import httpx
import pytest
from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright


FRONTEND_URL = "http://127.0.0.1:3000"
BACKEND_URL = "http://127.0.0.1:8000"
ARTIFACTS_DIR = Path(__file__).parent / "_artifacts"


@pytest.fixture(scope="session", autouse=True)
def dev_servers_ready():
    """Fail fast if either dev server is unreachable. Backend /health must be 200;
    frontend root must respond."""
    for name, url in [
        ("backend", f"{BACKEND_URL}/health"),
        ("frontend", f"{FRONTEND_URL}/"),
    ]:
        try:
            urllib.request.urlopen(url, timeout=2)
        except Exception as e:
            pytest.fail(
                f"{name} not reachable at {url}: {e}. "
                "Start it before running e2e tests.",
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
    """Read PRYZM_API_TOKEN from .env. Used by legacy e2e tests that still
    drive the localStorage-based TokenGate flow. New backend-direct tests
    should depend on `session_cookie` instead."""
    env_path = Path(__file__).parent.parent.parent.parent / ".env"
    for line in env_path.read_text().splitlines():
        if line.startswith("PRYZM_API_TOKEN="):
            return line.split("=", 1)[1].strip()
    pytest.fail("PRYZM_API_TOKEN missing from .env", pytrace=False)


@pytest.fixture
def inject_token(page: Page, api_token: str):
    """Returns a callable that pre-seeds the token in localStorage, skipping
    TokenGate. Used by legacy e2e tests that drive the browser UI."""
    def _do() -> None:
        page.goto(f"{FRONTEND_URL}/")
        page.evaluate(
            f'() => localStorage.setItem("pryzm_api_token", "{api_token}")'
        )
    return _do


@pytest.fixture(scope="session")
def session_cookie() -> str:
    """Log in to the running backend and return the pryzm_session cookie value.

    Credentials come from env vars PRYZM_E2E_USERNAME / PRYZM_E2E_PASSWORD
    (default admin / admin). Configure these in .env if your bootstrap admin
    uses other credentials."""
    username = os.environ.get("PRYZM_E2E_USERNAME", "admin")
    password = os.environ.get("PRYZM_E2E_PASSWORD", "admin")
    resp = httpx.post(
        f"{BACKEND_URL}/api/auth/login",
        json={"username": username, "password": password},
        timeout=5.0,
    )
    if resp.status_code != 200:
        pytest.fail(
            f"Login failed for user={username!r}: HTTP {resp.status_code} {resp.text}. "
            "Set PRYZM_E2E_USERNAME / PRYZM_E2E_PASSWORD in your environment.",
            pytrace=False,
        )
    sid = resp.cookies.get("pryzm_session")
    if not sid:
        pytest.fail("Login succeeded but no pryzm_session cookie was returned.", pytrace=False)
    return sid


@pytest.fixture
def screenshot(page: Page, request):
    """Yields a callable that captures the page to _artifacts/<test_name>-<label>.png."""
    ARTIFACTS_DIR.mkdir(exist_ok=True)

    def _capture(label: str) -> Path:
        safe = request.node.name.replace("[", "_").replace("]", "_")
        path = ARTIFACTS_DIR / f"{safe}-{label}.png"
        page.screenshot(path=path)
        return path

    return _capture
