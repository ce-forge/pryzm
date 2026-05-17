"""VLM-based image captioning.

One vision-language model produces both verbatim text extraction and
the structural description in a single call. The chosen model is
whichever chat model carries the `vision` tag in llama-swap-config.yaml;
swap models by re-tagging — no code change.
"""
from __future__ import annotations

import base64
import logging
import os
import time

import httpx

from config import settings
from core import llm_server
from core.llm_router import get_router

_logger = logging.getLogger(__name__)


# Test-only stub. PRYZM_TEST_STUB_VLM=1 returns this canned caption
# without hitting the model server.
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


# Prompt is domain-neutral on purpose: this service runs across every
# workspace's uploads, so domain framing belongs in the per-workspace
# prompts (core/prompts/{workspace}.txt). Examples are abstract, not
# concrete — small VLMs echo concrete example values into outputs when
# they can't see the image.
_SYSTEM_PROMPT = (
    "You caption images for a knowledge base. Output two sections, "
    "in this order:\n"
    "\n"
    "1. EXTRACTED TEXT — every visible character, verbatim, layout "
    "preserved. Reproduce identifiers, numbers, dates, and names "
    "exactly as shown.\n"
    "\n"
    "2. CONTEXT — one short paragraph: what the image is, plus any "
    "visual details a text search wouldn't surface (state indicators, "
    "colors, icons, spatial structure).\n"
    "\n"
    "If the image is not text-heavy (photo, diagram, scan with no "
    "readable text), skip section 1 and describe it in section 2.\n"
    "\n"
    "Start with the EXTRACTED TEXT heading. No preamble."
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
    started = time.perf_counter()
    response = await llm_server.chat(
        client,
        messages=messages,
        tools=None,
        model=model,
        options=options,
    )
    elapsed = time.perf_counter() - started

    message = response.get("message") or {}
    content = (message.get("content") or "").strip()
    if not content:
        # Some reasoning models route the answer through
        # `reasoning_content` when they decide to think. Fall back so
        # we don't surface an empty caption for a successful generation.
        content = (message.get("reasoning_content") or "").strip()
    _logger.info(
        "image_describe: model=%s elapsed=%.2fs caption_chars=%d",
        model, elapsed, len(content),
    )
    _logger.info("image_describe: caption content:\n%s", content)
    return content
