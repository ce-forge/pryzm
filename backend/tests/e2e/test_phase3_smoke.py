"""UI smoke tests for async streaming, concurrency, error envelope.

Each test starts from a fresh BrowserContext (cookies/localStorage cleared).
Screenshots saved to _artifacts/ for human review.

Selector notes (no data-testid attributes in this codebase):
  - Chat input: textarea[placeholder="Ask Pryzm anything..."]
  - Assistant content: ReactMarkdown renders <p> tags inside the chat container.
    User messages sit inside a bg-[#2f2f2f] pill; assistant messages are bare
    <p> tags directly under the max-w-3xl chat container. We detect non-empty
    content by scanning <p> elements in the main scroll container.
  - Processing indicator: <span> text "Processing" shown by ProcessingAnimation
    while the backend is still generating (no content yet in the bubble).
"""
import time

from playwright.sync_api import Browser, Page

FRONTEND_URL = "http://127.0.0.1:3000"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _open_app_with_token(page: Page, token: str) -> None:
    """Navigate to / and inject the token, then reload so the app initialises."""
    page.goto(FRONTEND_URL)
    page.evaluate(f'() => localStorage.setItem("pryzm_api_token", "{token}")')
    page.reload()
    page.wait_for_load_state("networkidle", timeout=10_000)


def _send_chat_message(page: Page, text: str) -> None:
    """Fill the chat textarea and press Enter to submit."""
    textarea = page.locator('textarea[placeholder="Ask Pryzm anything..."]')
    textarea.wait_for(state="visible", timeout=5_000)
    textarea.fill(text)
    textarea.press("Enter")


# Waits until at least one <p> in the chat scroll area holds non-whitespace text.
# The page has two .custom-scrollbar elements: the sidebar (first) and the chat
# area (second, which also has overflow-x-hidden). We target the chat one
# explicitly so the sidebar's session list doesn't trigger a false positive.
_ASSISTANT_HAS_CONTENT = """
() => {
    const els = Array.from(document.querySelectorAll('.custom-scrollbar'));
    const chatEl = els.find(el => el.className.includes('overflow-x-hidden'));
    if (!chatEl) return false;
    const paragraphs = chatEl.querySelectorAll('p');
    for (const p of paragraphs) {
        if ((p.textContent || '').trim().length > 0) return true;
    }
    return false;
}
"""


# ---------------------------------------------------------------------------
# Test 1: streaming path end-to-end
# ---------------------------------------------------------------------------

def test_chat_streams_in_personal_workspace(page: Page, api_token: str, screenshot):
    """Send a message in the personal workspace and verify the assistant bubble
    appears with streamed content. Exercises the full async streaming path
    end-to-end."""
    _open_app_with_token(page, api_token)

    page.goto(f"{FRONTEND_URL}/?workspace=personal")
    page.wait_for_load_state("networkidle", timeout=10_000)

    _send_chat_message(page, "Say hi.")

    # Wait for a <p> tag with real content to appear inside the scrollable
    # chat container. Timeout is generous because cold model load can be
    # slow on the dev machine.
    page.wait_for_function(_ASSISTANT_HAS_CONTENT, timeout=60_000)

    screenshot("chat-streamed")


# ---------------------------------------------------------------------------
# Test 2: concurrent chats — the headline async win
# ---------------------------------------------------------------------------

def test_concurrent_chats_overlap(browser: Browser, api_token: str):
    """Fire chats in two browser contexts simultaneously and verify BOTH complete.

    The backend serves chat requests concurrently — two requests should not
    serialise. We don't assert a strict timing threshold (too sensitive to
    cold-load variance) but we DO assert that both contexts reach a non-empty
    assistant response, which proves neither request starved the other.
    """
    ctx_a = browser.new_context()
    ctx_b = browser.new_context()
    try:
        page_a = ctx_a.new_page()
        page_b = ctx_b.new_page()

        _open_app_with_token(page_a, api_token)
        _open_app_with_token(page_b, api_token)

        page_a.goto(f"{FRONTEND_URL}/?workspace=personal")
        page_b.goto(f"{FRONTEND_URL}/?workspace=it_copilot")
        page_a.wait_for_load_state("networkidle", timeout=10_000)
        page_b.wait_for_load_state("networkidle", timeout=10_000)

        # Fire both chats back-to-back with minimal gap.
        start = time.time()
        _send_chat_message(page_a, "Say hi.")
        _send_chat_message(page_b, "Say hi.")

        # Each page must independently reach a non-empty assistant response.
        page_a.wait_for_function(_ASSISTANT_HAS_CONTENT, timeout=90_000)
        page_b.wait_for_function(_ASSISTANT_HAS_CONTENT, timeout=90_000)
        elapsed = time.time() - start

        print(f"\n[concurrency] both chats completed in {elapsed:.1f}s")

        artifacts_dir = __file__.replace("test_phase3_smoke.py", "_artifacts")
        page_a.screenshot(
            path=f"{artifacts_dir}/test_concurrent_chats_overlap-page-a.png"
        )
        page_b.screenshot(
            path=f"{artifacts_dir}/test_concurrent_chats_overlap-page-b.png"
        )
    finally:
        ctx_a.close()
        ctx_b.close()


# ---------------------------------------------------------------------------
# Test 3: error envelope renders clean ⚠ UI
# ---------------------------------------------------------------------------

def test_error_envelope_shows_clean_error_ui(page: Page, api_token: str, screenshot):
    """When the backend emits an error envelope the frontend must render the
    message as '⚠ <reason>'. Bare engine-error strings must not surface.

    Uses Playwright route interception to inject a synthetic NDJSON response so
    this test runs without touching the live LLM backend.
    """
    _open_app_with_token(page, api_token)
    page.goto(f"{FRONTEND_URL}/?workspace=personal")
    page.wait_for_load_state("networkidle", timeout=10_000)

    # Intercept the /analyze fetch and return a minimal error envelope.
    def _handle_route(route):
        body = (
            '{"status":"started","session_id":"sim-err-001"}\n'
            '{"error":"Simulated Ollama failure.","code":"ollama_unreachable"}\n'
        )
        route.fulfill(
            status=200,
            headers={"content-type": "application/x-ndjson"},
            body=body,
        )

    # /analyze takes a ?workspace= query param; use ** suffix so the glob
    # matches the full URL including query parameters.
    page.route("**/analyze**", _handle_route)
    _send_chat_message(page, "Trigger an error.")

    # The frontend hook converts the error envelope into '⚠ Simulated Ollama failure.'
    # and writes it into the assistant message bubble via setMessageCache.
    page.wait_for_function(
        """
        () => {
            const txt = document.body.textContent || "";
            return txt.includes("Simulated Ollama failure");
        }
        """,
        timeout=10_000,
    )

    body_text = page.evaluate("() => document.body.textContent || ''")

    # The frontend error-envelope handler renders failures with a ⚠ prefix.
    assert "⚠" in body_text, (
        "⚠ prefix not found — frontend error-envelope handler may not be active"
    )

    # Bare engine-error strings must not leak through to the user.
    assert "[Engine Error:" not in body_text, (
        "Raw [Engine Error:] string surfaced to the user"
    )

    screenshot("error-envelope")
    page.unroute("**/analyze**")
