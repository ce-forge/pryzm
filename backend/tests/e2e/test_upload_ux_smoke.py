"""UI smoke tests for the upload-pill / mobile-fix surface.

Covers the user-visible behavior that landed in PRs #32-#49: real
upload progress ring, image thumbnail, send-button gating while
uploads are in flight, hash-filename truncation, and the
document-delete fire when the user cancels a pill.

These exercise the real running stack (backend on :8000, frontend
on :3000, Postgres + llama-swap up). Each test is structured to
fail fast if the UX regresses without becoming flaky on the slow
captioning step (uploads block for ~2-5 s on a warm E4B).
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from playwright.sync_api import Page, expect


FRONTEND_URL = "http://127.0.0.1:3000"
FIXTURE_IMG = Path(__file__).parent / "fixtures" / "images.jpeg"


def _open_app_with_token(page: Page, token: str) -> None:
    page.goto(FRONTEND_URL)
    page.evaluate(f'() => localStorage.setItem("pryzm_api_token", "{token}")')
    page.reload()
    page.wait_for_load_state("networkidle", timeout=10_000)


def _attach_file(page: Page, path: Path) -> None:
    """Feed a file into the hidden <input type="file"> via Playwright,
    bypassing the native OS picker. Picker behavior is OS-level and
    not what we're testing here; what we're testing is the pill
    state machine that follows the file landing in the input."""
    file_input = page.locator('input[type="file"]')
    file_input.set_input_files(str(path))


def _pill_locator(page: Page):
    """The upload pill — match by the file thumbnail's <img alt=''>
    or the <span class='truncate ...'> wrapping the filename. The
    outer div is the smallest stable selector that contains both."""
    return page.locator('img[alt=""].rounded.object-cover, span.truncate.max-w-\\[120px\\]').first


# ---------------------------------------------------------------------------
# Pill state machine
# ---------------------------------------------------------------------------

def test_image_upload_pill_shows_thumbnail_and_progress_ring(
    page: Page, api_token: str, screenshot,
):
    """Pick the cat-photo fixture; before upload completes the pill
    should be rendering both the <img> thumbnail and the circular
    progress overlay."""
    _open_app_with_token(page, api_token)
    _attach_file(page, FIXTURE_IMG)

    # Thumbnail appears as soon as the blob URL is minted (no network
    # round-trip needed). Should be there well before the captioning
    # call returns.
    thumb = page.locator('img[alt=""].rounded.object-cover').first
    thumb.wait_for(state="visible", timeout=5_000)
    # The circular progress overlay should be visible during the upload
    # window. We accept either the determinate ring (still uploading
    # bytes) or the indeterminate spin (bytes done, backend captioning).
    ring = page.locator('svg.animate-spin, svg circle[stroke-dasharray]').first
    ring.wait_for(state="visible", timeout=5_000)
    screenshot("pill-uploading")


def test_image_upload_pill_settles_into_success_state(
    page: Page, api_token: str, screenshot,
):
    """Once captioning + ingestion complete, the pill loses its
    progress overlay and stays as just the thumbnail + filename in
    the emerald-success styling (border-emerald-500/30)."""
    _open_app_with_token(page, api_token)
    _attach_file(page, FIXTURE_IMG)

    # Wait for the emerald-success border to appear on the pill.
    # 60 s timeout accommodates a cold-swap E4B captioning call.
    pill = page.locator('div.border-emerald-500\\/30').first
    pill.wait_for(state="visible", timeout=60_000)
    screenshot("pill-success")


# ---------------------------------------------------------------------------
# Send button gate during upload
# ---------------------------------------------------------------------------

def test_send_button_disabled_while_upload_in_flight(
    page: Page, api_token: str, screenshot,
):
    """Pressing Send while bytes are flying or the backend is captioning
    races against the auto-RAG retrieval. The submit button must be
    `disabled` during that window."""
    _open_app_with_token(page, api_token)

    # Type something so the !prompt.trim() gate doesn't dominate the
    # `disabled` decision — we want to isolate the uploads-in-progress
    # contribution.
    textarea = page.locator('textarea[placeholder="Ask Pryzm anything..."]')
    textarea.fill("describe the cat")

    _attach_file(page, FIXTURE_IMG)

    # The submit button should be disabled right after the file lands
    # (status transitions through pending → uploading immediately).
    submit = page.locator('button[type="submit"]').first
    expect(submit).to_be_disabled(timeout=5_000)
    screenshot("send-disabled-during-upload")

    # Once captioning completes the pill flips to success and the
    # button should come back. Generous timeout for cold-swap.
    page.locator('div.border-emerald-500\\/30').first.wait_for(
        state="visible", timeout=60_000
    )
    expect(submit).to_be_enabled(timeout=2_000)


# ---------------------------------------------------------------------------
# Hash-named camera files are renamed at intake
# ---------------------------------------------------------------------------

def test_hash_named_file_is_renamed_in_pill(
    page: Page, api_token: str, tmp_path, screenshot,
):
    """Simulate a Samsung-camera capture by giving the file a 32-char
    hex base name. The pill should show <8-hex>.jpg, not the full
    hash, because processFiles wraps the File before it enters state."""
    hash_named = tmp_path / "6d40e499aade4d70836772d1235b3372.jpeg"
    hash_named.write_bytes(FIXTURE_IMG.read_bytes())

    _open_app_with_token(page, api_token)
    _attach_file(page, hash_named)

    # The visible pill filename should match a short pattern, not the
    # full 32-char hash. Allow for the truncation ellipsis too.
    label = page.locator('span.truncate.max-w-\\[120px\\]').first
    label.wait_for(state="visible", timeout=5_000)
    text = label.text_content() or ""
    assert re.match(r"^[a-f0-9]{8}\.jpeg$", text), (
        f"expected 8-hex.jpeg short form, got {text!r}"
    )
    screenshot("hash-rename")


# ---------------------------------------------------------------------------
# Removing a pill triggers DELETE /documents/<id>
# ---------------------------------------------------------------------------

def test_remove_pill_fires_document_delete(
    page: Page, api_token: str, screenshot,
):
    """The user clicks × on a successfully-uploaded pill before
    sending. The frontend should fire DELETE /documents/<id> so the
    Document, chunks, and disk file don't leak. We listen for the
    request rather than re-querying the DB so the test stays
    frontend-scoped."""
    _open_app_with_token(page, api_token)

    delete_requests: list[str] = []
    page.on("request", lambda req: (
        delete_requests.append(req.url)
        if req.method == "DELETE" and "/documents/" in req.url
        else None
    ))

    _attach_file(page, FIXTURE_IMG)

    # Wait until the pill is success-state (has a document_id assigned
    # in the upload state — that's what gates the DELETE call).
    page.locator('div.border-emerald-500\\/30').first.wait_for(
        state="visible", timeout=60_000
    )

    # Click the × on the pill. The button uses CancelIcon and sits to
    # the right of the filename inside the pill.
    cancel_btn = page.locator(
        'div.border-emerald-500\\/30 button'
    ).first
    cancel_btn.click()

    # Give the fire-and-forget DELETE a brief window to land.
    page.wait_for_timeout(500)

    assert any("/documents/" in url for url in delete_requests), (
        f"expected a DELETE /documents/<id> request; saw: {delete_requests!r}"
    )
    screenshot("pill-removed")


# ---------------------------------------------------------------------------
# Multi-image upload (sequential queue, both reach success)
# ---------------------------------------------------------------------------

def test_multiple_images_upload_sequentially_to_success(
    page: Page, api_token: str, tmp_path, screenshot,
):
    """Pick two images in a single picker action. processUploadQueue
    runs them sequentially (await per item); both pills should be
    visible immediately, both should reach success state, and the
    send button should stay disabled until both finish."""
    from PIL import Image, ImageDraw

    # Image 1: the cat fixture (general image).
    # Image 2: a synthetic text-heavy "error dialog" so the test
    # exercises the text-extraction-first prompt on at least one of
    # the two captions.
    text_img = tmp_path / "error_dialog.png"
    img = Image.new("RGB", (560, 280), "white")
    d = ImageDraw.Draw(img)
    d.text((20, 20), "BACKUP SERVICE FAILED", fill="black")
    d.text((20, 60), "Code: 0x80070005", fill="black")
    d.text((20, 100), "Device: LAPTOP-042", fill="black")
    d.text((20, 140), "Target: nas01-share-daily", fill="black")
    d.text((20, 180), "Fix: Restart VSS service", fill="black")
    d.text((20, 220), "[ Retry ]   [ Cancel ]", fill="black")
    img.save(text_img)

    _open_app_with_token(page, api_token)
    # Type something so the `!prompt.trim()` clause doesn't dominate the
    # submit button's disabled state — we want to assert specifically
    # on uploads-in-progress vs settled, not on empty-textarea.
    page.locator('textarea[placeholder="Ask Pryzm anything..."]').fill(
        "what's in these"
    )
    page.locator('input[type="file"]').set_input_files(
        [str(FIXTURE_IMG), str(text_img)]
    )

    # Both pills should appear right away (in any order — order isn't a
    # contract we're testing). Wait for at least 2 thumbnail/database-
    # icon slots inside the upload pill area.
    pills = page.locator('div.relative.w-7.h-7.shrink-0')
    pills.first.wait_for(state="visible", timeout=5_000)
    page.wait_for_function(
        '() => document.querySelectorAll("div.relative.w-7.h-7.shrink-0").length >= 2',
        timeout=5_000,
    )

    # Send must be blocked while either upload is in flight.
    submit = page.locator('button[type="submit"]').first
    expect(submit).to_be_disabled(timeout=5_000)
    screenshot("multi-uploading")

    # Both pills should flip to emerald-success eventually. 120 s
    # accommodates a cold E4B swap-in for the first upload + the
    # second sequential captioning behind it.
    page.wait_for_function(
        '() => document.querySelectorAll("div.border-emerald-500\\\\/30").length >= 2',
        timeout=120_000,
    )
    screenshot("multi-success")

    # And the send button should be back.
    expect(submit).to_be_enabled(timeout=2_000)


# ---------------------------------------------------------------------------
# Viewport — h-dvh prevents mobile chrome from covering the chat input
# ---------------------------------------------------------------------------

def test_full_height_containers_use_h_dvh_class(
    page: Page, api_token: str,
):
    """Full-height containers must use h-dvh (dynamic viewport height),
    not h-screen — the latter ignores mobile browser chrome. Asserting
    the class is on the right elements is sufficient; Tailwind's
    class-to-CSS mapping is stable and not worth re-testing here."""
    _open_app_with_token(page, api_token)

    body_class = page.locator("body").get_attribute("class") or ""
    assert "h-dvh" in body_class, f"<body> missing h-dvh: {body_class!r}"
    main_class = page.locator("main").get_attribute("class") or ""
    assert "h-dvh" in main_class, f"<main> missing h-dvh: {main_class!r}"
