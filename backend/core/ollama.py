"""Ollama HTTP wrapper.

All Ollama-specific HTTP shape lives here. Consumers import from this module
instead of calling `httpx` / `requests` directly. This is NOT an abstract
interface — it's hygiene. The future llama.cpp swap introduces the abstract
client at that point; today it's just one module talking to Ollama.

The shared httpx.AsyncClient is owned by FastAPI's lifespan (see main.py).
Callers obtain it via the get_http_client dependency in core.deps or directly
from `request.app.state.http_client`.
"""
from __future__ import annotations

import json
import time
from typing import AsyncIterator

import httpx

from config import settings
from core.llm_metrics import emit_chat_metric


BASE_URL = settings.OLLAMA_URL.strip().rstrip("/")


async def chat_stream(
    client: httpx.AsyncClient,
    messages: list,
    tools: list | None,
    model: str,
) -> AsyncIterator[dict]:
    """POST /api/chat with stream=True. Yields parsed JSON chunks (one per NDJSON line).

    If `tools` is None, the field is omitted from the payload (some smaller
    models don't handle empty tool arrays).
    """
    payload: dict = {"model": model, "messages": messages, "stream": True}
    if tools is not None:
        payload["tools"] = tools

    url = f"{BASE_URL}/api/chat"
    async with client.stream("POST", url, json=payload) as resp:
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                # Ollama can emit partial/malformed lines under load — skip
                # them rather than crashing the stream.
                continue


async def embed(client: httpx.AsyncClient, text: str, model: str) -> list[float]:
    """POST /api/embeddings. Returns the embedding vector."""
    url = f"{BASE_URL}/api/embeddings"
    payload = {"model": model, "prompt": text}
    resp = await client.post(url, json=payload, timeout=30.0)
    resp.raise_for_status()
    return resp.json()["embedding"]


async def list_models(client: httpx.AsyncClient) -> list[str]:
    """GET /api/tags. Returns the list of installed model names."""
    url = f"{BASE_URL}/api/tags"
    resp = await client.get(url, timeout=5.0)
    resp.raise_for_status()
    return [m["name"] for m in resp.json().get("models", [])]


async def chat(
    client: httpx.AsyncClient,
    messages: list,
    tools: list | None,
    model: str,
    options: dict | None = None,
) -> dict:
    """POST /api/chat with stream=False. Returns the full message dict.

    Used by ai_engine.stream_chat — the engine receives the whole payload first,
    then fake-streams it word-by-word. If `tools` is None, the field is omitted.

    Emits an 'llm.metric' log line on every successful call.
    """
    payload: dict = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"num_ctx": 8192},
    }
    if tools is not None:
        payload["tools"] = tools
    if options:
        payload["options"].update(options)

    url = f"{BASE_URL}/api/chat"
    t0 = time.perf_counter()
    resp = await client.post(url, json=payload, timeout=120.0)
    resp.raise_for_status()
    duration_s = time.perf_counter() - t0
    data = resp.json()
    emit_chat_metric(model=model, response=data, fallback_duration_s=duration_s)
    return data


async def generate(
    client: httpx.AsyncClient,
    prompt: str,
    model: str,
    options: dict | None = None,
) -> str:
    """POST /api/generate (non-streaming). Returns the response text.

    Used by ai_engine.condense_chat_memory and ai_engine.generate_title — short,
    single-shot completions where streaming is overhead. Emits an 'llm.metric'
    line per call (the chat-shape extractor works fine here — /api/generate's
    response carries the same prompt_eval_count / eval_count / *_duration fields)."""
    url = f"{BASE_URL}/api/generate"
    payload: dict = {"model": model, "prompt": prompt, "stream": False}
    if options:
        payload["options"] = options
    t0 = time.perf_counter()
    resp = await client.post(url, json=payload, timeout=60.0)
    resp.raise_for_status()
    duration_s = time.perf_counter() - t0
    data = resp.json()
    emit_chat_metric(model=model, response=data, fallback_duration_s=duration_s)
    return data["response"]
