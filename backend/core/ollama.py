"""Ollama HTTP wrapper.

All Ollama-specific HTTP shape lives here. Consumers import from this module
instead of calling `httpx` / `requests` directly. This is NOT an abstract
interface — it's hygiene. The future llama.cpp swap introduces the abstract
client at that point; today it's just one module talking to Ollama.

The shared httpx.AsyncClient is owned by FastAPI's lifespan (see main.py).
Callers obtain it via the get_http_client dependency in core.deps or directly
from `request.app.state.http_client`.

T0 ships only the stub signatures — T1 fills them in.
"""
from __future__ import annotations

from typing import AsyncIterator

import httpx

from config import settings


BASE_URL = settings.OLLAMA_URL.strip().rstrip("/")


async def chat_stream(
    client: httpx.AsyncClient,
    messages: list,
    tools: list | None,
    model: str,
) -> AsyncIterator[dict]:
    """Stream the /api/chat response. Implementation lands in T1."""
    raise NotImplementedError("chat_stream lands in Task 1")
    yield  # makes this a generator function so the AsyncIterator return type holds


async def embed(client: httpx.AsyncClient, text: str, model: str) -> list[float]:
    """Return an embedding vector for `text`. Implementation lands in T1."""
    raise NotImplementedError("embed lands in Task 1")


async def list_models(client: httpx.AsyncClient) -> list[str]:
    """Return the list of installed Ollama model tags. Implementation lands in T1."""
    raise NotImplementedError("list_models lands in Task 1")


async def generate(
    client: httpx.AsyncClient,
    prompt: str,
    model: str,
    options: dict | None = None,
) -> str:
    """Single-shot /api/generate call (used by condense + title). Lands in T1."""
    raise NotImplementedError("generate lands in Task 1")
