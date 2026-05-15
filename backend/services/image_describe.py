"""VLM-based image captioning.

Single-call captioning: one vision-language model produces both the
verbatim text extraction and the structural description. Replaces the
previous hybrid RapidOCR + Gemma-4 pipeline (PR #66), which suffered
from multi-column layout collapse in the OCR step — value-label
relationships got lost when sidebar items at the same Y as form
values got mashed onto the same output line.

Qwen2-VL-2B is the captioning model. It's specifically benchmarked
on UI screenshots (VCR 81.45%) and documents (DocVQA 90.1, OCRBench
794), preserves layout in its training, and reads verbatim text
without language-prior pattern completion.

The captioning model is selected via the `vision` tag in
llama-swap-config.yaml — `services/image_describe.describe()` queries
the router for whichever chat model carries that tag. Swap models by
re-tagging in the YAML; no code change.
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


# Test-only stub for the e2e smoke harness. PRYZM_TEST_STUB_VLM=1 in
# the backend env returns this canned caption without hitting the
# model server, so the upload pill flips quickly during tests.
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


# Single-call prompt: extract verbatim text AND describe structure.
# The captioning model owns BOTH jobs — separate OCR is gone.
#
# Discovered (PR #66 → undone here) that splitting the work between
# RapidOCR (verbatim) and a structure-only VLM produced subtle
# layout-collapse bugs on multi-column forms. Qwen2-VL handles both
# concerns natively because it reads pixels with full spatial
# awareness.
_SYSTEM_PROMPT = (
    "You analyze images for an IT knowledge base. Most images are "
    "screenshots, error dialogs, terminal output, device labels, "
    "configuration screens, and similar text-heavy content where "
    "BOTH the verbatim text AND the visual structure matter.\n"
    "\n"
    "Output two sections, in this exact order:\n"
    "\n"
    "1. EXTRACTED TEXT — every piece of visible text VERBATIM, "
    "preserving layout cues. For form-style content, output as "
    "`Label: value` pairs so the relationship is unambiguous (e.g., "
    "`Username: admin`, `Password: nfsyg9yehhp9bt9x`, `Last Changed: "
    "over 2 years ago`). For sidebar nav and other list-style items, "
    "output each on its own line. For tables, preserve row+column "
    "structure. Read EVERY character precisely — usernames, IDs, "
    "error codes, IP addresses, version strings, file paths matter "
    "as exact strings, not paraphrases.\n"
    "\n"
    "2. CONTEXT — one short paragraph after the extracted text "
    "covering what the screen/image IS (Windows error dialog, "
    "network monitoring console, password manager view, terminal "
    "session, etc.), plus any visual details a text search wouldn't "
    "otherwise surface (colors, icons, status indicators, the "
    "apparent state of UI elements).\n"
    "\n"
    "If the image is NOT text-heavy (hardware photo, non-textual "
    "diagram), skip section 1 and describe its visual contents in "
    "section 2 with technical detail: subject, layout, identifying "
    "features.\n"
    "\n"
    "No preamble, no 'I see' or 'this image shows' filler. Start "
    "directly with the EXTRACTED TEXT heading."
)

_USER_TEXT = "Analyze this image for the knowledge base."


def _data_url(image_bytes: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(image_bytes).decode('ascii')}"


async def describe(
    client: httpx.AsyncClient,
    image_bytes: bytes,
    mime: str,
) -> str:
    """Send the image to the captioning model and return the merged
    EXTRACTED TEXT + CONTEXT caption. The returned string is what
    gets chunked + embedded into the RAG store as if it were the
    document's text.

    Raises InvalidImage if `mime` isn't in the supported set.
    Network/timeout errors propagate to the caller.
    """
    if mime not in _SUPPORTED_MIME:
        raise InvalidImage(f"Unsupported image MIME: {mime}")

    if os.environ.get("PRYZM_TEST_STUB_VLM") == "1":
        return _STUB_CAPTION

    # Captioning model resolves via the `vision` tag in llama-swap
    # config. Swap models by re-tagging the YAML; no code change.
    model = get_router().vision_capable_model()
    if model is None:
        raise InvalidImage(
            "No vision-capable model is available — tag a chat model "
            "with 'vision' in infra/llama-swap-config.yaml."
        )

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
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
        # Some reasoning models route the answer through
        # `reasoning_content` when they decide to think. Fall back so
        # we don't surface an empty caption for a successful generation.
        content = (message.get("reasoning_content") or "").strip()
    _logger.info("image_describe: caption content:\n%s", content)
    return content
