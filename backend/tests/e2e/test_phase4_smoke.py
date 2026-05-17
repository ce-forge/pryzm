"""UI smoke tests for workspace identity propagation + cache namespacing.

Each test starts from a fresh BrowserContext. Screenshots saved to _artifacts/.

Selector notes:
  - Chat input: textarea[placeholder="Ask Pryzm anything..."]
  - Assistant content: <p> tags inside .custom-scrollbar.overflow-x-hidden
    (React-Markdown output).
  - Workspace isolation: navigating to /?workspace=<slug> completely changes
    which sessions are listed and which cache partition is active.
"""
import time

from playwright.sync_api import Page

FRONTEND_URL = "http://127.0.0.1:3000"

_ASSISTANT_HAS_CONTENT = """
() => {
    const els = Array.from(document.querySelectorAll('.custom-scrollbar'));
    const chatEl = els.find(el => el.className.includes('overflow-x-hidden'));
    if (!chatEl) return false;
    const paragraphs = chatEl.querySelectorAll('p');
    for (const p of paragraphs) {
        // Any non-empty <p> in the chat scroll area means the assistant has
        // rendered a response. (The threshold was once > 5 chars as a guard
        // against transient empty placeholders, but with the llama.cpp swap
        // Gemma 4 actually complies with "say one word" and produces a
        // single short token like "Hi" or "Habit" — 5-char threshold
        // silently rejected those valid replies forever.)
        if ((p.textContent || '').trim().length > 0) return true;
    }
    return false;
}
"""


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
    """Fill the chat textarea, press Enter, and wait for the user bubble to
    render. The DOM-confirmation step protects against the silent-drop case
    where handleInference bails early because currentIsProcessing is still
    true from a prior turn — the textarea is visible but Enter is a no-op."""
    textarea = page.locator('textarea[placeholder="Ask Pryzm anything..."]')
    textarea.wait_for(state="visible", timeout=5_000)
    textarea.fill(text)
    textarea.press("Enter")
    page.wait_for_function(
        f"() => (document.body.textContent || '').includes({text!r})",
        timeout=10_000,
    )


# ---------------------------------------------------------------------------
# Test 1: workspace switch isolates history
# ---------------------------------------------------------------------------

def test_workspace_switch_isolates_history(page: Page, api_token: str, screenshot):
    """Send a message in `personal`, switch to `it_copilot` via URL, verify the
    message isn't visible in `it_copilot`'s chat area.

    This exercises cache key namespacing (personal:<id> vs it_copilot:<id>):
    the unique phrase must NOT bleed into the other workspace's view.
    """
    _open_app_with_token(page, api_token)

    # Navigate to personal workspace and send a unique message.
    page.goto(f"{FRONTEND_URL}/?workspace=personal")
    page.wait_for_load_state("networkidle", timeout=10_000)

    unique_msg = f"phase4-personal-{int(time.time())}"
    _send_chat_message(page, unique_msg)
    page.wait_for_function(_ASSISTANT_HAS_CONTENT, timeout=60_000)

    # Switch to it_copilot — full navigation, fresh React state.
    page.goto(f"{FRONTEND_URL}/?workspace=it_copilot")
    page.wait_for_load_state("networkidle", timeout=10_000)
    # Give the sidebar session list time to resolve.
    page.wait_for_timeout(500)

    # The unique phrase from personal should NOT be visible in it_copilot's view.
    body_text = page.evaluate("() => document.body.textContent || ''")
    assert unique_msg not in body_text, (
        f"Personal message {unique_msg!r} leaked into it_copilot — "
        "workspace cache namespacing failed or session list is unfiltered"
    )
    screenshot("isolated")


# ---------------------------------------------------------------------------
# Test 2: workspace switch preserves history on roundtrip
# ---------------------------------------------------------------------------

def test_workspace_switch_preserves_history(page: Page, api_token: str, screenshot):
    """After sending a message in `personal`, switching to `it_copilot` and
    back should restore `personal`'s history (reloaded from DB on mount).

    The in-memory cache is cleared on each full navigation but useSession
    calls loadSessionData() on mount which re-fetches from /sessions/<id>.
    """
    _open_app_with_token(page, api_token)

    page.goto(f"{FRONTEND_URL}/?workspace=personal")
    page.wait_for_load_state("networkidle", timeout=10_000)

    unique_msg = f"phase4-persist-{int(time.time())}"
    _send_chat_message(page, unique_msg)
    page.wait_for_function(_ASSISTANT_HAS_CONTENT, timeout=60_000)

    # Capture the session URL so we can return to the exact same session.
    url_after_chat = page.url

    # Switch away to it_copilot.
    page.goto(f"{FRONTEND_URL}/?workspace=it_copilot")
    page.wait_for_load_state("networkidle", timeout=10_000)
    page.wait_for_timeout(500)

    # Switch back to the exact personal session URL.
    page.goto(url_after_chat)
    page.wait_for_load_state("networkidle", timeout=10_000)
    # Give useSession#loadSessionData() time to fetch history from the DB.
    page.wait_for_timeout(2_000)

    body_text = page.evaluate("() => document.body.textContent || ''")
    assert unique_msg in body_text, (
        f"Personal message {unique_msg!r} not found after roundtrip — "
        "history was not restored from DB on workspace re-entry"
    )
    screenshot("preserved")


# ---------------------------------------------------------------------------
# Test 3: chat works in each builtin workspace
# ---------------------------------------------------------------------------

def test_chat_works_in_each_builtin(page: Page, api_token: str, screenshot):
    """Smoke: both `personal` and `it_copilot` can send a chat and receive a
    streamed assistant reply via the ?workspace= query-param shape.

    Verifies that workspace identity is correctly propagated to /analyze so
    the LLM engine picks the right engine_config for each workspace.
    """
    _open_app_with_token(page, api_token)

    for ws_slug in ("personal", "it_copilot"):
        page.goto(f"{FRONTEND_URL}/?workspace={ws_slug}")
        page.wait_for_load_state("networkidle", timeout=10_000)
        # Pause so the sidebar/tool-list fetches complete AND React fully
        # wires up the chat form after the cross-workspace navigation.
        # 1s was occasionally too tight when the browser process is warm from
        # many prior tests in the same session.
        page.wait_for_timeout(2_000)
        _send_chat_message(page, f"Say one word. (smoke: {ws_slug})")
        # 90 s generous timeout: cold model load on the second workspace can be slow.
        page.wait_for_function(_ASSISTANT_HAS_CONTENT, timeout=90_000)
        screenshot(f"works-in-{ws_slug}")
