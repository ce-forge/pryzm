"""Headless chromium browser singleton for the web_search tool's page fetcher.

One browser per backend process. Each fetch allocates a fresh context (no
cookie/state leak between fetches) and closes it on completion. The browser
itself is created lazily on first use and closed on app shutdown via the
lifespan hook in main.py.
"""
from __future__ import annotations

import asyncio
from typing import Optional

from playwright.async_api import Browser, BrowserContext, async_playwright


_playwright = None
_browser: Optional[Browser] = None
_lock = asyncio.Lock()


async def get_browser() -> Browser:
    """Return the singleton chromium browser, launching it on first call.
    Thread-safe via an asyncio lock — concurrent first calls collapse to one
    launch."""
    global _playwright, _browser
    async with _lock:
        if _browser is None or not _browser.is_connected():
            _playwright = await async_playwright().start()
            _browser = await _playwright.chromium.launch(headless=True)
        return _browser


async def shutdown_browser() -> None:
    """Close the browser and stop the playwright driver. Called from the
    FastAPI lifespan on app shutdown."""
    global _playwright, _browser
    if _browser is not None:
        try:
            await _browser.close()
        finally:
            _browser = None
    if _playwright is not None:
        try:
            await _playwright.stop()
        finally:
            _playwright = None


_BLOCKED_RESOURCE_TYPES = {"font", "image", "media", "stylesheet"}


async def new_context() -> BrowserContext:
    """Build a fresh browser context with cosmetic resources blocked. Caller
    is responsible for closing the returned context."""
    browser = await get_browser()
    ctx = await browser.new_context(
        viewport={"width": 1920, "height": 1080},
        accept_downloads=False,
        reduced_motion="reduce",
        # A real-product UA so naive bot-detection lets us through.
        user_agent="Pryzm/1.0 (+self-hosted IT copilot)",
    )

    async def _route(route, request):
        if request.resource_type in _BLOCKED_RESOURCE_TYPES:
            await route.abort()
        else:
            await route.continue_()

    await ctx.route("**/*", _route)
    return ctx
