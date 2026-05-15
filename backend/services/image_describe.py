"""VLM-based image description.

Replaces the rapidocr-based seam from PR #21. The captioning step now runs
through the existing llama-server (`llm_server.chat`) using a
vision-capable model. The function signature is intentionally identical
to the old `ocr.extract_text` so call sites (today: `/upload`) didn't
need to change shape; only the import.

Why a separate module: keeps the upload endpoint thin and gives a single
location to revise the captioning prompt, change the captioning model, or
tune temperature without touching the router. See
`docs/specs/2026-05-15-image-upload-vlm.md` for the broader design.
"""
from __future__ import annotations

import base64
import logging
import os

import httpx

from config import settings
from core import llm_server
from core.llm_router import get_router

_logger = logging.getLogger(__name__)


# Test-only stub gate. When `PRYZM_TEST_STUB_VLM=1` is set in the
# backend process's env, `describe()` returns a canned caption
# immediately and never hits llama-server. This is read at call
# time (not import) so smoke tests can flip it without restarting.
# Production deployments leave the variable unset; the env-var name
# is namespaced with `TEST_` so it's obviously not a runtime knob.
_STUB_CAPTION = (
    "EXTRACTED TEXT\n"
    "Top bar: 'Pryzm Smoke Test Fixture'\n"
    "Body: 'BACKUP SERVICE FAILED', 'Code: 0x80070005', "
    "'Device: LAPTOP-042', 'Target: nas01-share-daily'\n\n"
    "CONTEXT\n"
    "Synthetic IT-error-dialog fixture used by the async-ingestion "
    "smoke harness. Returned directly without hitting the VLM."
)


class InvalidImage(Exception):
    """Raised when the upstream rejects the bytes as an image."""


_SUPPORTED_MIME = {"image/jpeg", "image/png", "image/webp"}

# The caption is the SOLE record of the image's content once the upload
# completes — there's no re-attach at chat time. Bias the prompt heavily
# toward verbatim text extraction because the IT-copilot use case is
# dominated by screenshots, error dialogs, terminal output, device
# labels, configuration screens, and similar text-heavy content. For
# the rarer non-text image (a photograph, a chart) the prompt still
# falls through to a description path.
_SYSTEM_PROMPT = (
    "You describe images for an IT knowledge base. A separate OCR "
    "engine handles verbatim text transcription — your job is "
    "structure and context, NOT character-by-character text reading.\n"
    "\n"
    "Output one or two short paragraphs covering:\n"
    "- What kind of screen/image this is (Windows error dialog, "
    "network monitoring console, terminal session, mobile app UI, "
    "physical device label, photograph of hardware, etc.).\n"
    "- The layout: top bar, sidebar, dialog body, tables, buttons, "
    "form fields, indicators. Describe each by its ROLE and POSITION.\n"
    "- Visual details a text search wouldn't surface: colors, icons, "
    "status indicators (red/green dots, warning triangles, progress "
    "bars), the apparent state of UI elements (selected vs disabled, "
    "errored vs normal).\n"
    "- For non-UI images (hardware photos, diagrams without legible "
    "text), describe subject, layout, what's visible, identifying "
    "features.\n"
    "\n"
    "CRITICAL: do NOT transcribe verbatim text content. Do not "
    "reproduce error codes, IP addresses, usernames, version strings, "
    "or any specific text strings — that's OCR's job, not yours. "
    "Refer to text by its role (e.g., 'an error code is displayed', "
    "'the username field is populated', 'a timestamp is visible in "
    "the top-right'), not its content. Including verbatim text in "
    "your output is a failure mode we are explicitly trying to avoid.\n"
    "\n"
    "No preamble, no 'I see' or 'this image shows' filler. Start "
    "directly with the description."
)


# Used in the fallback path when OCR finds nothing — preserves the
# original verbatim-extraction behavior so we never store an empty
# caption on text-light images OCR can't read.
_FALLBACK_VERBATIM_PROMPT = (
    "You analyze images for a knowledge base. Output every piece of "
    "visible text verbatim, then a short context paragraph describing "
    "what the screen or image is. Note position information (top bar, "
    "dialog body, row N, etc.) alongside the text. No preamble."
)

_USER_TEXT = "Analyze this image for the knowledge base."


def _data_url(image_bytes: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(image_bytes).decode('ascii')}"


async def describe(
    client: httpx.AsyncClient,
    image_bytes: bytes,
    mime: str,
    *,
    verbatim_fallback: bool = False,
) -> str:
    """Send the image to the captioning model and return a paragraph
    describing it. The returned string is what gets chunked + embedded
    into the RAG store as if it were the document's text.

    Raises InvalidImage if `mime` isn't in the supported set; we keep
    that gate here (not at the router) so the seam owns its contract.
    Network/timeout errors propagate to the caller, which maps them to
    the right HTTP status.
    """
    if mime not in _SUPPORTED_MIME:
        raise InvalidImage(f"Unsupported image MIME: {mime}")

    # Test-only short-circuit. Set PRYZM_TEST_STUB_VLM=1 when running
    # the e2e smoke harness so the upload pill flips quickly without
    # cold-loading a 4B-param vision model. Never set in production.
    if os.environ.get("PRYZM_TEST_STUB_VLM") == "1":
        return _STUB_CAPTION

    # Source of truth for the captioning model is the `vision` tag in
    # llama-swap-config.yaml — pick whichever chat model carries it.
    # If no model has the tag we can't caption; surface a clear error
    # the upload endpoint can translate to a 503.
    model = get_router().vision_capable_model()
    if model is None:
        raise InvalidImage(
            "No vision-capable model is available — tag a chat model "
            "with 'vision' in infra/llama-swap-config.yaml."
        )

    system_prompt = _FALLBACK_VERBATIM_PROMPT if verbatim_fallback else _SYSTEM_PROMPT
    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": _USER_TEXT},
                {"type": "image_url", "image_url": {"url": _data_url(image_bytes, mime)}},
            ],
        },
    ]
    options = {
        "temperature": settings.IMAGE_CAPTION_TEMPERATURE,
        "max_tokens": settings.IMAGE_CAPTION_MAX_TOKENS,
    }
    response = await llm_server.chat(
        client,
        messages=messages,
        tools=None,
        model=model,
        options=options,
    )

    message = response.get("message") or {}
    content = (message.get("content") or "").strip()
    if not content:
        # Gemma-4 sometimes routes the answer through `reasoning_content`
        # when it decides the task warrants thinking. Fall back to that
        # field so we don't surface an empty caption for what was
        # actually a successful generation.
        content = (message.get("reasoning_content") or "").strip()
    # Pair with ocr_extract's text log so the full captioning output
    # is greppable in backend logs.
    _logger.info("image_describe: caption content:\n%s", content)
    return content
