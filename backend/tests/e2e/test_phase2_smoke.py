"""UI smoke tests for the auth gate + token UX.

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
    page.wait_for_load_state("networkidle", timeout=10000)
    expect(page.get_by_text("Configure API token")).not_to_be_visible()
    screenshot("app-loaded")


def test_authorization_header_on_workspace_request(page: Page, inject_token, api_token: str):
    """Pre-seed the token, navigate, and intercept a backend request to verify
    the Authorization header is present and matches the configured token."""
    captured = {}

    def _on_request(req):
        if "/workspaces" in req.url:
            auth = req.headers.get("authorization") or req.headers.get("Authorization")
            if auth:
                captured["header"] = auth

    inject_token()
    page.on("request", _on_request)
    page.reload()
    page.wait_for_load_state("networkidle", timeout=10000)

    assert "header" in captured, (
        "no /workspaces request with Authorization header captured — "
        "check that the frontend makes a /workspaces call on load"
    )
    assert captured["header"] == f"Bearer {api_token}", (
        f"unexpected Authorization header: {captured['header']!r}"
    )


def test_settings_token_status_does_not_expose_value(
    page: Page, inject_token, api_token: str, screenshot,
):
    """Per the no-secrets-in-DOM rule: the Settings panel shows a status text,
    not an input pre-filled with the actual token value."""
    inject_token()
    page.reload()
    page.wait_for_load_state("networkidle", timeout=10000)

    # The Settings button is in the sidebar with visible text "Settings".
    # get_by_role("button", name=...) matches via the accessible name from the
    # inner <span>Settings</span>.
    page.get_by_role("button", name="Settings").click()

    expect(page.get_by_text("Token configured")).to_be_visible(timeout=3000)

    # CRITICAL: no password input has the stored token as its value.
    inputs = page.locator('input[type="password"]')
    for i in range(inputs.count()):
        value = inputs.nth(i).input_value()
        assert value != api_token, (
            f"input #{i} has the stored token as its value attribute"
        )
    screenshot("settings-token-configured")


def test_change_button_reveals_empty_input(
    page: Page, inject_token, api_token: str, screenshot,
):
    """Clicking Change reveals a password input whose value is empty (not the
    stored token)."""
    inject_token()
    page.reload()
    page.wait_for_load_state("networkidle", timeout=10000)

    page.get_by_role("button", name="Settings").click()

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

    page.get_by_role("button", name="Settings").click()

    page.get_by_role("button", name="Clear").click()
    # After clearing, reload to force the page to re-evaluate localStorage.
    page.reload()
    expect(page.get_by_text("Configure API token")).to_be_visible(timeout=5000)
    screenshot("gate-reappeared-after-clear")
