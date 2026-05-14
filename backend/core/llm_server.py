"""OpenAI-compatible LLM server wrapper.

Speaks /v1/chat/completions, /v1/embeddings, /v1/models — the de facto
standard wire format adopted by llama-server (via llama-swap), vLLM,
LM Studio, etc. This is NOT a multi-backend abstraction; it's one module
talking to one server (llama-swap in front of llama.cpp). The wire format
just happens to be the standard one because so many tools already speak it.

The module exposes the same function signatures the previous Ollama wrapper
had — chat / generate / embed / list_models — so ai_engine and friends
keep their existing call shapes. Response payloads are adapted in here so
callers continue to see the Ollama-shaped `{message, prompt_eval_count,
eval_count, ...}` dict on chat/generate.

`DEFAULT_CHAT_MODEL` / `DEFAULT_SMALL_CHAT_MODEL` are the catalog endpoints.
Phase B2's router (`core/llm_router.py`) picks between them per request for
user-facing chat; internal callers (`generate_title`, `condense_chat_memory`)
import them directly.
"""
from __future__ import annotations

import time
from typing import Any, AsyncIterator

import httpx

from config import settings
from core.llm_metrics import emit_chat_metric, emit_embed_metric

BASE_URL = settings.LLM_SERVER_URL.strip().rstrip("/")

DEFAULT_CHAT_MODEL = "gemma-4-E4B-it"
DEFAULT_SMALL_CHAT_MODEL = "gemma-4-E2B-it"
DEFAULT_EMBED_MODEL = "nomic-embed-text-v1.5"


def _adapt_chat_response(data: dict) -> dict:
    """Translate OpenAI chat-completion response shape into the legacy
    Ollama shape ai_engine consumes.

    OpenAI:  {choices: [{message: {role, content, tool_calls?}}], usage: {prompt_tokens, completion_tokens, ...}, timings: {prompt_ms, predicted_ms, ...}}
    Ollama:  {message: {role, content, tool_calls?}, prompt_eval_count, eval_count, prompt_eval_duration, eval_duration, total_duration}

    The `timings` block is llama-server's OpenAI extension — it carries
    millisecond-precision split timings for prompt eval and generation.
    Map them into Ollama's nanosecond-precision fields so Phase A's metric
    emitter computes a real tokens_per_sec; if `timings` is absent (a
    different OpenAI-compatible backend), all timing fields are 0 and the
    metric emitter falls back to caller-measured wall clock for duration_ms
    only."""
    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message", {})
    usage = data.get("usage", {}) or {}
    timings = data.get("timings", {}) or {}

    prompt_ms = float(timings.get("prompt_ms", 0))
    predicted_ms = float(timings.get("predicted_ms", 0))

    return {
        "message": message,
        "prompt_eval_count": int(usage.get("prompt_tokens", 0)),
        "eval_count": int(usage.get("completion_tokens", 0)),
        "prompt_eval_duration": int(prompt_ms * 1_000_000),
        "eval_duration": int(predicted_ms * 1_000_000),
        "total_duration": int((prompt_ms + predicted_ms) * 1_000_000),
    }


async def chat(
    client: httpx.AsyncClient,
    messages: list,
    tools: list | None,
    model: str,
    options: dict | None = None,
) -> dict:
    """POST /v1/chat/completions (non-streaming). Returns an Ollama-shaped dict
    for compatibility with ai_engine. Emits an 'llm.metric' line per call."""
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
    }
    if tools is not None:
        payload["tools"] = tools
    if options:
        # llama-server accepts options as top-level fields (temperature, top_p,
        # num_ctx → max_tokens-ish), not nested. Forward verbatim; unknown keys
        # are ignored by the server.
        for k, v in options.items():
            if k == "num_ctx":
                payload["max_tokens"] = v   # rough analog; llama-server's own
                                            # --ctx-size flag is the actual ceiling
            else:
                payload[k] = v

    url = f"{BASE_URL}/v1/chat/completions"
    t0 = time.perf_counter()
    resp = await client.post(url, json=payload, timeout=settings.LLM_TIMEOUT_SECONDS)
    resp.raise_for_status()
    duration_s = time.perf_counter() - t0
    adapted = _adapt_chat_response(resp.json())
    emit_chat_metric(model=model, response=adapted, fallback_duration_s=duration_s)
    return adapted


async def generate(
    client: httpx.AsyncClient,
    prompt: str,
    model: str,
    options: dict | None = None,
) -> str:
    """Single-shot text completion. llama-server has no /api/generate analog;
    we wrap /v1/chat/completions with a single user message. Returns the
    response text only. Emits an 'llm.metric' line per call."""
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }
    if options:
        for k, v in options.items():
            if k == "num_ctx":
                payload["max_tokens"] = v
            else:
                payload[k] = v

    url = f"{BASE_URL}/v1/chat/completions"
    t0 = time.perf_counter()
    resp = await client.post(url, json=payload, timeout=settings.LLM_TIMEOUT_SECONDS)
    resp.raise_for_status()
    duration_s = time.perf_counter() - t0
    data = resp.json()
    adapted = _adapt_chat_response(data)
    emit_chat_metric(model=model, response=adapted, fallback_duration_s=duration_s)
    return adapted["message"].get("content", "")


async def embed(client: httpx.AsyncClient, text: str, model: str) -> list[float]:
    """POST /v1/embeddings. Returns the embedding vector. Emits an
    'llm.embed_metric' line per call."""
    url = f"{BASE_URL}/v1/embeddings"
    payload = {"model": model, "input": text}
    t0 = time.perf_counter()
    resp = await client.post(url, json=payload, timeout=30.0)
    resp.raise_for_status()
    duration_s = time.perf_counter() - t0
    emit_embed_metric(model=model, char_count=len(text), duration_s=duration_s)
    data = resp.json()
    return data["data"][0]["embedding"]


async def list_models(client: httpx.AsyncClient) -> list[str]:
    """GET /v1/models. Returns the list of model ids. llama-swap reports its
    configured models here; the order matches infra/llama-swap-config.yaml."""
    url = f"{BASE_URL}/v1/models"
    resp = await client.get(url, timeout=5.0)
    resp.raise_for_status()
    return [m["id"] for m in resp.json().get("data", [])]
