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

import httpx

from config import settings
from core import llm_server


class InvalidImage(Exception):
    """Raised when the upstream rejects the bytes as an image."""


_SUPPORTED_MIME = {"image/jpeg", "image/png", "image/webp"}

_SYSTEM_PROMPT = (
    "You are an image-description tool for a knowledge base. Write a "
    "detailed paragraph (3-6 sentences) describing the image: what it "
    "shows, any visible text verbatim, technical specifics, and anything "
    "a later search query might match. No preamble, no thinking out loud."
)

_USER_TEXT = "Describe this image for our knowledge base."


def _data_url(image_bytes: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(image_bytes).decode('ascii')}"


async def describe(
    client: httpx.AsyncClient,
    image_bytes: bytes,
    mime: str,
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
        model=settings.IMAGE_CAPTION_MODEL,
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
    return content
