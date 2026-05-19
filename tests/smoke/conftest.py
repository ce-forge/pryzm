"""Smoke-test fixtures.

Drives the live dev stack via Playwright (headless Chromium from the
backend venv — no new toolchain). Each test gets a fresh browser
context, so cookies / scroll state don't leak between tests.

Credentials are pulled from environment variables to keep them out of
git. The fixture skips with a clear message if they're missing.
"""
from __future__ import annotations

import os
import time
from typing import Any

import pytest
from playwright.sync_api import Page, sync_playwright

URL = os.environ.get("PRYZM_SMOKE_URL", "http://localhost:3000")


def _required(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        pytest.skip(
            f"{name} not set — export it before running the smoke suite. "
            "See tests/smoke/README.md."
        )
    return val


@pytest.fixture(scope="session")
def _browser():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture
def page(_browser) -> Page:
    ctx = _browser.new_context(viewport={"width": 1280, "height": 800})
    page = ctx.new_page()
    yield page
    ctx.close()


@pytest.fixture
def authed_page(page: Page) -> Page:
    """A logged-in page parked on the chat shell, ready to send a prompt."""
    user = _required("PRYZM_SMOKE_USER")
    pw = _required("PRYZM_SMOKE_PASS")
    page.goto(URL, timeout=15000)
    page.wait_for_load_state("networkidle")
    if page.locator("input[type='password']").count() > 0:
        page.locator("input").nth(0).fill(user)
        page.locator("input[type='password']").fill(pw)
        page.locator("button[type='submit']").click()
        page.wait_for_load_state("networkidle")
    page.wait_for_selector("textarea", timeout=10_000)
    # Land on a fresh chat so tests don't share session history.
    new_chat = page.locator("text=New chat")
    if new_chat.count() > 0:
        new_chat.first.click()
        time.sleep(0.5)
    return page


# ---------- Helpers shared across tests ----------


def send_prompt(page: Page, text: str, settle_s: float = 0.3) -> None:
    """Type a prompt into the chat input and submit. Small settle so the
    test code that follows can immediately observe the stream starting."""
    ta = page.locator("textarea").first
    ta.click()
    ta.fill(text)
    ta.press("Enter")
    time.sleep(settle_s)


def chat_scroll_state(page: Page) -> dict[str, Any] | None:
    """Read scroll geometry of the chat feed (NOT the sidebar). The chat
    feed uniquely combines overflow-y-auto with overflow-x-hidden."""
    return page.evaluate(
        """
        () => {
          const sc = document.querySelector('div.overflow-y-auto.overflow-x-hidden');
          if (!sc) return null;
          return {
            scrollTop: sc.scrollTop,
            scrollHeight: sc.scrollHeight,
            clientHeight: sc.clientHeight,
            distance: sc.scrollHeight - sc.scrollTop - sc.clientHeight,
          };
        }
        """
    )


def wait_for_overflow(page: Page, min_overflow_px: int = 400, timeout_s: int = 45) -> dict[str, Any]:
    """Block until the chat content exceeds the viewport height by
    `min_overflow_px`. Required before scroll-based assertions — at the
    start of a turn the content fits the viewport, so wheel events have
    nothing to do."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        s = chat_scroll_state(page)
        if s and (s["scrollHeight"] - s["clientHeight"]) > min_overflow_px:
            return s
        time.sleep(1)
    raise TimeoutError(f"chat content didn't overflow {min_overflow_px}px in {timeout_s}s")
