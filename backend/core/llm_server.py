"""OpenAI-compatible LLM server wrapper.

Speaks /v1/chat/completions, /v1/embeddings, /v1/models — the de facto
standard wire format adopted by llama-server (via llama-swap), vLLM,
LM Studio, etc. This is NOT a multi-backend abstraction; it's one module
talking to one server (llama-swap in front of llama.cpp).

Exposes chat / generate / embed / list_models. Response payloads are
adapted in here so callers see a normalised `{message, prompt_eval_count,
eval_count, ...}` dict.

`DEFAULT_CHAT_MODEL` / `DEFAULT_SMALL_CHAT_MODEL` are the catalog endpoints.
The per-request router (`core/llm_router.py`) picks between them for
user-facing chat; internal callers (`generate_title`, `condense_chat_memory`)
import them directly.
"""
from __future__ import annotations

import json
import time
from typing import Any, AsyncIterator

import httpx

from config import settings
from core.llm_metrics import emit_chat_metric, emit_embed_metric

BASE_URL = settings.LLM_SERVER_URL.strip().rstrip("/")

DEFAULT_CHAT_MODEL = "gemma-4-E4B-it"
DEFAULT_SMALL_CHAT_MODEL = "gemma-4-E2B-it"
DEFAULT_EMBED_MODEL = "nomic-embed-text-v1.5"


def _raise_for_status_with_body(resp) -> None:
    """Call resp.raise_for_status(); on HTTPStatusError, augment the message
    with the upstream body so users see *why* llama-server returned 4xx/5xx
    (e.g. "exceeds the available context size") instead of just the status.

    llama-server returns JSON of shape `{"error": {"message": "...", ...}}` —
    we surface `error.message`. For non-JSON bodies we fall back to the raw
    text, truncated to keep the message readable.
    """
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        try:
            body = resp.json()
            detail = (body.get("error") or {}).get("message") or body.get("detail")
        except Exception:
            detail = None
        if not detail:
            text = (resp.text or "").strip()
            detail = text[:400] + ("…" if len(text) > 400 else "")
        if detail:
            raise httpx.HTTPStatusError(
                f"{exc} — {detail}",
                request=exc.request,
                response=exc.response,
            ) from None
        raise


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

    # llama-server's streaming terminal event ships `timings` but NOT the
    # standard `usage` block — so when chat_stream() adapts the final
    # event for metrics, `usage.prompt_tokens` is missing. Fall back to
    # `timings.prompt_n` / `timings.predicted_n` (same token counts under
    # different names) so audit + metrics actually see non-zero token
    # numbers on streaming turns.
    prompt_tokens = int(usage.get("prompt_tokens", timings.get("prompt_n", 0)))
    completion_tokens = int(usage.get("completion_tokens", timings.get("predicted_n", 0)))
    return {
        "message": message,
        "prompt_eval_count": prompt_tokens,
        "eval_count": completion_tokens,
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
    _raise_for_status_with_body(resp)
    duration_s = time.perf_counter() - t0
    adapted = _adapt_chat_response(resp.json())
    emit_chat_metric(model=model, response=adapted, fallback_duration_s=duration_s)
    return adapted


async def chat_stream(
    client: httpx.AsyncClient,
    messages: list,
    tools: list | None,
    model: str,
    options: dict | None = None,
) -> AsyncIterator[dict]:
    """POST /v1/chat/completions with stream=True. Yields one dict per
    upstream SSE event with the shape of `choices[0].delta` plus an optional
    `finish_reason` when the terminal event carries one.

    The first upstream event is always the role marker
    (`{role: "assistant", content: None}`); the terminal event has an empty
    delta and `finish_reason` set. The caller can use either signal to
    detect end-of-stream. The terminal event's `timings`/`usage` are
    consumed here to emit a single `llm.metric` line, matching the non-
    streaming `chat()` semantics — one metric per agentic-loop iteration."""
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": True,
    }
    if tools is not None:
        payload["tools"] = tools
    if options:
        for k, v in options.items():
            if k == "num_ctx":
                payload["max_tokens"] = v
            else:
                payload[k] = v

    url = f"{BASE_URL}/v1/chat/completions"
    t0 = time.perf_counter()
    final_event: dict | None = None

    async with client.stream(
        "POST", url, json=payload, timeout=settings.LLM_TIMEOUT_SECONDS,
    ) as resp:
        if resp.status_code >= 400:
            # raise_for_status_with_body reads .text which is unavailable
            # mid-stream — pull the body manually so the error matches the
            # detail the non-streaming path surfaces.
            body_bytes = await resp.aread()
            try:
                body = json.loads(body_bytes)
                detail = (body.get("error") or {}).get("message") or body.get("detail")
            except Exception:
                detail = None
            if not detail:
                text = body_bytes.decode(errors="replace").strip()
                detail = text[:400] + ("…" if len(text) > 400 else "")
            raise httpx.HTTPStatusError(
                f"{resp.status_code} {detail or 'streaming error'}",
                request=resp.request, response=resp,
            )

        async for line in resp.aiter_lines():
            line = line.strip()
            if not line or not line.startswith("data: "):
                continue
            payload_str = line[6:]
            if payload_str == "[DONE]":
                break
            try:
                event = json.loads(payload_str)
            except json.JSONDecodeError:
                continue
            choices = event.get("choices") or []
            if not choices:
                continue
            choice = choices[0]
            delta = choice.get("delta") or {}
            finish = choice.get("finish_reason")

            if finish is not None:
                final_event = event

            out: dict = dict(delta)
            if finish is not None:
                out["finish_reason"] = finish
            yield out

    duration_s = time.perf_counter() - t0

    # Emit the metric once after the stream closes. _adapt_chat_response
    # pulls usage + timings from the top level of the event, which the
    # terminal event carries even though its `delta` is empty.
    if final_event is not None:
        adapted = _adapt_chat_response(final_event)
    else:
        adapted = {
            "message": {},
            "prompt_eval_count": 0,
            "eval_count": 0,
            "prompt_eval_duration": 0,
            "eval_duration": 0,
            "total_duration": int(duration_s * 1_000_000_000),
        }
    emit_chat_metric(model=model, response=adapted, fallback_duration_s=duration_s)


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
    _raise_for_status_with_body(resp)
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
    _raise_for_status_with_body(resp)
    duration_s = time.perf_counter() - t0
    emit_embed_metric(model=model, char_count=len(text), duration_s=duration_s)
    data = resp.json()
    return data["data"][0]["embedding"]


def embed_sync(text: str, model: str) -> list[float]:
    """Sync embedding helper for tool dispatch paths that run outside the
    async loop (e.g. search_chunks_sync). Shares the same wire format as
    `embed` so a future change to the embeddings endpoint only edits one
    place."""
    import requests
    url = f"{BASE_URL}/v1/embeddings"
    payload = {"model": model, "input": text}
    t0 = time.perf_counter()
    resp = requests.post(url, json=payload, timeout=30.0)
    resp.raise_for_status()
    duration_s = time.perf_counter() - t0
    emit_embed_metric(model=model, char_count=len(text), duration_s=duration_s)
    return resp.json()["data"][0]["embedding"]


async def list_models(client: httpx.AsyncClient) -> list[str]:
    """GET /v1/models. Returns the list of model ids. llama-swap reports its
    configured models here; the order matches infra/llama-swap-config.yaml."""
    url = f"{BASE_URL}/v1/models"
    resp = await client.get(url, timeout=5.0)
    _raise_for_status_with_body(resp)
    return [m["id"] for m in resp.json().get("data", [])]
