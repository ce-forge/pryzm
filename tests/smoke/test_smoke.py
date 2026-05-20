"""Pryzm chat-surface smoke tests.

Each test owns a fresh browser context (no cookie / state leak between
tests). Run after starting the dev stack — see tests/smoke/README.md.
"""
from __future__ import annotations

import re
import time

from conftest import (
    chat_scroll_state,
    send_prompt,
    wait_for_overflow,
)


def test_login_renders_chat(authed_page) -> None:
    """The textarea is the unmissable signal that login succeeded and the
    chat shell mounted."""
    assert authed_page.locator("textarea").count() > 0


def test_message_send_produces_a_response(authed_page) -> None:
    """End-to-end ping. The reply must contain the word we asked for —
    catches a dead backend or a wired-up-wrong streaming pipeline."""
    send_prompt(authed_page, "Reply with the single word: pong.")
    # Even small-model turns finish within ~15s for a one-word answer.
    time.sleep(15)
    body = authed_page.locator("body").inner_text().lower()
    assert "pong" in body, f"no 'pong' in body tail: {body[-300:]!r}"


def test_admin_test_suite_button_hidden_for_non_admin(authed_page) -> None:
    """Regression guard for PR #118 — the terminal-icon button that opens
    the diagnostics test-suite menu must not render for non-admin users."""
    # The trigger is a button containing the lucide terminal SVG.
    terminal = authed_page.locator("button:has(svg.lucide-terminal)").count()
    assert terminal == 0, f"terminal button visible for non-admin: {terminal}"


def test_markdown_math_renders_via_katex(authed_page) -> None:
    """KaTeX should turn $...$ into rendered math. Regression for PR #118."""
    send_prompt(
        authed_page,
        "Reply with EXACTLY: 'Pythag: $a^2 + b^2 = c^2$' — nothing else.",
    )
    time.sleep(15)
    # rehype-katex wraps rendered math in `<span class="katex">`.
    katex = authed_page.locator("span.katex").count()
    assert katex >= 1, f"no katex elements rendered: count={katex}"


def test_markdown_code_block_renders(authed_page) -> None:
    """Fenced code should land in the CodeBlock component — verified by
    the Copy button it ships with."""
    send_prompt(
        authed_page,
        "Reply with EXACTLY a python code block containing `print('hi')`. "
        "No prose, no explanation.",
    )
    time.sleep(15)
    copy = authed_page.locator("button:has-text('Copy')").count()
    assert copy >= 1, "no Copy button found — code block didn't render"


def test_autoscroll_follows_streaming_content(authed_page) -> None:
    """During a streaming response the scroll position should track the
    growing scrollHeight. distance-from-bottom stays small. Regression
    guard for PR #117."""
    send_prompt(authed_page, "Write a 500-word essay about Python.", settle_s=0)
    # Stream needs a moment to start producing content past first frame.
    time.sleep(8)
    s = chat_scroll_state(authed_page)
    assert s is not None and s["distance"] < 50, (
        f"autoscroll not following stream: distance={s['distance'] if s else None}"
    )


def test_autoscroll_disables_on_wheel_up_and_reengages(authed_page) -> None:
    """The critical regression — three rounds of 'fixed autoscroll' missed
    this. Wheel-up must disable autoscroll; scrolling back to the bottom
    zone must re-engage it. Regression guard for PR #117."""
    send_prompt(
        authed_page,
        "Write a 1500-word essay about distributed systems.",
        settle_s=0,
    )
    wait_for_overflow(authed_page, min_overflow_px=400, timeout_s=45)

    # Wheel up via dispatchEvent so the wheel listener fires, plus the
    # actual scrollTop change so position visibly moves.
    authed_page.evaluate(
        """
        () => {
          const sc = document.querySelector('div.overflow-y-auto.overflow-x-hidden');
          sc.dispatchEvent(new WheelEvent('wheel', { deltaY: -400, bubbles: true }));
          sc.scrollTop = Math.max(0, sc.scrollTop - 400);
        }
        """
    )
    time.sleep(0.5)
    s_before = chat_scroll_state(authed_page)
    # Give the stream 3s to produce more content. distance should GROW
    # (content arrives, scrollTop holds) — autoscroll is disabled.
    time.sleep(3)
    s_after_wait = chat_scroll_state(authed_page)
    assert s_after_wait["distance"] >= s_before["distance"] - 10, (
        "autoscroll did not stay disabled after wheel-up: "
        f"distance went {s_before['distance']} → {s_after_wait['distance']}"
    )

    # Scroll back near the bottom (within the 150px re-engage zone).
    authed_page.evaluate(
        """
        () => {
          const sc = document.querySelector('div.overflow-y-auto.overflow-x-hidden');
          sc.scrollTop = sc.scrollHeight - sc.clientHeight - 30;
        }
        """
    )
    time.sleep(2)
    s_after = chat_scroll_state(authed_page)
    assert s_after["distance"] < 50, (
        f"autoscroll did not re-engage after scrolling to bottom: "
        f"distance={s_after['distance']}"
    )


def test_web_search_globe_pill(authed_page) -> None:
    """Regression guard for feat/web-search-v2: toggling the globe and asking
    a research-shaped question produces a collapsed "Searched: N sources" pill
    that expands to show structured source blocks, and the assistant reply
    contains [N] citation markers."""

    page = authed_page

    # The globe button renders only when the active workspace has web_search in
    # enabled_tools. aria-label is "Web search off" when disabled (initial).
    globe = page.get_by_role("button", name="Web search off")
    assert globe.count() >= 1, (
        "globe toggle not found — is web_search in the workspace's enabled_tools?"
    )
    globe.first.click()
    time.sleep(0.3)

    # Confirm the button flipped to "on".
    assert page.get_by_role("button", name="Web search on").count() >= 1, (
        "globe toggle did not switch to 'Web search on' after click"
    )

    send_prompt(
        page,
        "What is the latest stable release of Python? Give me the version number.",
    )

    # web_search fetches multiple pages — allow up to 60s total for the turn.
    time.sleep(60)

    # --- Pill must be present and collapsed by default ---
    pill = page.locator("button").filter(has_text="Searched:")
    assert pill.count() >= 1, "no 'Searched: ...' pill on the assistant turn"

    pill_text = pill.first.inner_text()

    # Source block must be hidden before expansion.
    assert page.locator("text=### Source [1]:").count() == 0, (
        "source block is visible before pill expansion — should be collapsed"
    )

    # --- Expand the pill ---
    pill.first.click()
    time.sleep(0.5)

    # Source block must now be visible.
    assert page.locator("text=### Source [1]:").count() >= 1, (
        "source block not visible after expanding the pill"
    )

    # --- Assistant message must contain [N] citation markers ---
    body = page.locator("body").inner_text()
    assert re.search(r"\[\d+\]", body), (
        f"no [N] citation markers in page body — model may not have cited sources. "
        f"pill was: {pill_text!r}; body tail: {body[-400:]!r}"
    )
