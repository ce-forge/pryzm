"""Single-shot LLM call: generate a short chat title from the first message.

Lives apart from the agentic loop because it isn't part of streaming, the
tool dispatch, or the routing decision — just a one-token-budget call
that produces 1-5 words. Uses the always-on small chat model so it can't
get stuck behind a cold-load.
"""
from __future__ import annotations

import re

import httpx

from core import llm_server
from core.engine_config import EngineConfig
from core.prompt_manager import MICRO_PROMPTS


async def generate_title(
    client: httpx.AsyncClient,
    prompt: str,
    *,
    engine_config: EngineConfig,
) -> str:
    """Make a 1-5 word title for the chat from the user's first message.

    Falls back to the first 3 words of the prompt (or a generic default)
    when the model errors or returns nothing useful. `engine_config` is
    accepted for caller-side consistency with the agentic loop's
    signatures, though the title pass uses the always-on small model
    rather than the routed tier.
    """
    clean_prompt = re.sub(r"\[Attached_File:.*?\]", "", prompt).strip()
    if not clean_prompt:
        return MICRO_PROMPTS["title_document_default"]

    system_prompt = (
        f"{MICRO_PROMPTS['title_generator_system']} Message: {clean_prompt}"
    )

    try:
        text = await llm_server.generate(
            client, prompt=system_prompt,
            model=llm_server.DEFAULT_SMALL_CHAT_MODEL,
            options={"num_ctx": 4096},
        )
        text = text.strip(' \n"\'*.')
        if not text:
            return MICRO_PROMPTS["title_default"]
        # Cap to 5 words plus ellipsis — a 6-word model title is usually
        # better than the first 3 words of the prompt, but a 20-word
        # title pushes the sidebar layout around.
        title_words = text.split()
        if len(title_words) > 5:
            text = " ".join(title_words[:5]) + "..."
        return text
    except Exception:
        words = clean_prompt.split()
        return " ".join(words[:3]) + "..." if len(words) > 3 else MICRO_PROMPTS["title_default"]
