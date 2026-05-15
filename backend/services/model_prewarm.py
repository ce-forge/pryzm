"""Pre-warm always-on llama-swap models at backend startup.

`always-on` in llama-swap config means "don't evict once loaded", not
"load at startup" — models stay lazy until the first request hits
them. Without pre-warming, the first user message after a backend
restart pays the model-load cost (10-30s for a small Gemma, longer
for E4B + embeddings).

This module sends one trivial inference at each always-on model so
llama-swap loads them into VRAM before any user traffic arrives. The
work runs as a background task off the FastAPI lifespan; the server
accepts traffic immediately, and warmup completes shortly after.

Best-effort by design: a failing pre-warm logs at WARN and moves on
rather than crashing startup.
"""
from __future__ import annotations

import logging
from typing import Iterable

import httpx

_logger = logging.getLogger(__name__)


# Pre-warm requests need to outlast a model's cold-load window. The
# default httpx timeout (5s) is far too short — embeddings can take
# 30s+ to download + load on first run. Use a generous ceiling here;
# llama-swap's own healthCheckTimeout (3600s) is the real backstop.
_WARMUP_TIMEOUT_SECONDS = 300.0


def _is_embedding_model(tags: set[str]) -> bool:
    """Embeddings models go to /v1/embeddings; chat models go to
    /v1/chat/completions. We tag the embed model with `embedding` in
    the YAML, so use that as the discriminator."""
    return "embedding" in tags


async def warm_model(
    client: httpx.AsyncClient,
    llm_server_url: str,
    model_id: str,
    tags: set[str],
) -> None:
    """Send one trivial request to load `model_id`. Logs at INFO on
    success, WARN on failure. Never raises — callers fan out across
    all always-on models and want each to be independent."""
    base = llm_server_url.strip().rstrip("/")
    if _is_embedding_model(tags):
        url = f"{base}/v1/embeddings"
        payload: dict = {"model": model_id, "input": "."}
    else:
        url = f"{base}/v1/chat/completions"
        # max_tokens=1 keeps the response cheap. The model still has
        # to be loaded into VRAM either way; the load cost is what
        # we're paying for here.
        payload = {
            "model": model_id,
            "messages": [{"role": "user", "content": "."}],
            "max_tokens": 1,
        }
    try:
        resp = await client.post(url, json=payload, timeout=_WARMUP_TIMEOUT_SECONDS)
        resp.raise_for_status()
        _logger.info("pre-warm OK: %s", model_id)
    except Exception as e:
        _logger.warning("pre-warm failed for %s: %s", model_id, e)


async def warm_always_on(
    client: httpx.AsyncClient,
    llm_server_url: str,
    models: Iterable[tuple[str, set[str]]],
) -> None:
    """Warm every model in `models`. Runs them sequentially because
    llama-swap loads one at a time anyway (single GPU, swap=true on
    the chat group). Parallel calls would just queue inside llama-swap.

    Independence matters: if `gemma-4-E2B-it` fails to load, we still
    want the embedding model to be warm by the time a user opens the
    chat UI and triggers auto-RAG.
    """
    for model_id, tags in models:
        await warm_model(client, llm_server_url, model_id, tags)
