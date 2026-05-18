"""UI smoke for the async-ingestion flow (spec: 2026-05-15-async-ingestion).

Asserts the network shape and pill state machine that PR 3 introduced:
  - POST /upload returns 202 (not 200) and the body carries a
    `document_id` + `status:'processing'`.
  - The frontend opens an EventSource on /uploads/{id}/events to learn
    the terminal state.
  - The upload pill renders an indeterminate spinner during the
    `processing` window and flips to the emerald-success border once
    the SSE `ready` event arrives.
  - The submit button stays disabled through both the upload-in-flight
    AND the processing windows.

Two run modes:

- **Fast** (recommended for repeated runs): launch the backend with
  `PRYZM_TEST_STUB_VLM=1`. The captioning call short-circuits to a
  canned string. Each test settles in under a second.
- **Real VLM**: leave the env var unset. Tests still pass — they're
  asserting the contract, not the speed — but each one takes 10-30s
  on a warm captioning model and longer on cold-swap. The timeouts
  below accommodate both modes.
"""
from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Page, expect


FRONTEND_URL = "http://127.0.0.1:3000"
FIXTURE_IMG = Path(__file__).parent / "fixtures" / "images.jpeg"
# Generous because cold-swap on the vision model takes 20-30s on first
# use. With the stub flag set on the backend these effectively become
# sub-second checks.
SETTLE_TIMEOUT_MS = 60_000


def test_upload_returns_202_with_processing_status(
    page: Page, login_via_ui, screenshot,
):
    """The POST /upload network round-trip should resolve as 202 (not
    200) with a body containing `document_id` and `status:'processing'`.
    Asserting at the network layer because the body shape is the
    contract between PR 3's backend flip and PR 3's frontend pill."""
    login_via_ui()

    upload_response: dict = {}

    def _on_response(resp):
        if resp.request.method == "POST" and resp.url.endswith("/upload"):
            upload_response["status"] = resp.status
            try:
                upload_response["body"] = resp.json()
            except Exception:
                upload_response["body"] = None

    page.on("response", _on_response)

    page.locator('input[type="file"]').set_input_files(str(FIXTURE_IMG))

    # Give the request a moment to land. The stubbed pipeline is fast
    # but we still need the SSE round-trip to complete before assert.
    page.wait_for_function(
        '() => document.querySelector("div.border-emerald-500\\\\/30") !== null',
        timeout=SETTLE_TIMEOUT_MS,
    )

    assert upload_response.get("status") == 202, upload_response
    body = upload_response.get("body") or {}
    assert body.get("status") == "processing", body
    assert body.get("document_id"), body
    screenshot("upload-202")


def test_sse_subscription_opens_for_document(
    page: Page, login_via_ui, screenshot,
):
    """After /upload returns 202 the frontend should immediately open
    an EventSource on /uploads/<doc_id>/events. Asserting at the
    network layer so we catch a regression that the pill state
    machine alone wouldn't surface (e.g. if it polled instead)."""
    login_via_ui()

    sse_urls: list[str] = []

    def _on_request(req):
        if "/uploads/" in req.url and "/events" in req.url:
            sse_urls.append(req.url)

    page.on("request", _on_request)

    page.locator('input[type="file"]').set_input_files(str(FIXTURE_IMG))

    # Wait for the pill to settle so we know the SSE request has been
    # fired and consumed.
    page.locator('div.border-emerald-500\\/30').first.wait_for(
        state="visible", timeout=SETTLE_TIMEOUT_MS
    )

    assert sse_urls, "no GET /uploads/<id>/events was issued by the frontend"
    # EventSource sends the pryzm_session cookie automatically; auth is
    # via cookie, not URL token. The URL still carries `?workspace=` so
    # the backend can scope the doc to the caller's workspace.
    assert "workspace=" in sse_urls[0], sse_urls
    screenshot("sse-opened")


def test_pill_transitions_uploading_processing_success(
    page: Page, login_via_ui, screenshot,
):
    """The pill should pass through both the determinate progress ring
    (bytes uploading) and the indeterminate spin (server processing)
    before settling at emerald-success. With the stub the processing
    window is tiny — we assert the start state and the terminal state
    rather than catching the transition mid-flight (which is flaky on
    fast hardware regardless of how the test is written)."""
    login_via_ui()
    page.locator('input[type="file"]').set_input_files(str(FIXTURE_IMG))

    # Thumbnail appears immediately (blob URL, no network).
    page.locator('img[alt=""].rounded.object-cover').first.wait_for(
        state="visible", timeout=5_000
    )
    # Some form of progress indicator (determinate ring OR animate-spin)
    # is visible at first.
    page.locator('svg.animate-spin, svg circle[stroke-dasharray]').first.wait_for(
        state="visible", timeout=5_000
    )
    screenshot("pill-in-progress")

    # Terminal: emerald success border.
    page.locator('div.border-emerald-500\\/30').first.wait_for(
        state="visible", timeout=SETTLE_TIMEOUT_MS
    )
    # And the spinner is gone.
    expect(page.locator('svg.animate-spin')).to_have_count(0, timeout=2_000)
    screenshot("pill-success")


def test_send_button_gated_through_processing_window(
    page: Page, login_via_ui, screenshot,
):
    """The send-gate must keep the submit button disabled across the full
    'pending → uploading → processing → success' arc, not just while bytes
    are flying. If the gate is too narrow the user can submit a prompt
    while the doc is mid-embed, the auto-RAG path misses the chunk, and
    they get a worse answer than if they'd waited."""
    login_via_ui()
    page.locator('textarea[placeholder="Ask Pryzm anything..."]').fill(
        "describe the image"
    )
    page.locator('input[type="file"]').set_input_files(str(FIXTURE_IMG))

    submit = page.locator('button[type="submit"]').first
    # Immediately after the file lands, before SSE has resolved.
    expect(submit).to_be_disabled(timeout=5_000)
    screenshot("send-gated-during-processing")

    # Then the pill settles and the button comes back.
    page.locator('div.border-emerald-500\\/30').first.wait_for(
        state="visible", timeout=SETTLE_TIMEOUT_MS
    )
    expect(submit).to_be_enabled(timeout=2_000)
