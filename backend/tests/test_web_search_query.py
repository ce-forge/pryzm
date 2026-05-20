"""Unit tests for the query-refinement helper used by web_search."""
from __future__ import annotations

import httpx
import pytest

from tools._web_query import refine_query


@pytest.mark.asyncio
async def test_refine_returns_model_output_stripped(monkeypatch):
    """Model returns a rewritten query — the helper returns it with surrounding
    whitespace and quotes stripped."""
    async def fake_generate(client, prompt, model, options=None):
        return '  "NRL round 12 May 2026 fixtures"\n'
    monkeypatch.setattr("tools._web_query.llm_server.generate", fake_generate)

    async with httpx.AsyncClient() as c:
        out = await refine_query(c, "what is the nrl shecudle this week", today="2026-05-21")
    assert out == "NRL round 12 May 2026 fixtures"


@pytest.mark.asyncio
async def test_refine_takes_first_line_only(monkeypatch):
    """If the model rambles past one line, only the first line is used."""
    async def fake_generate(client, prompt, model, options=None):
        return "NRL fixtures round 12\nExplanation: I picked round 12 because..."
    monkeypatch.setattr("tools._web_query.llm_server.generate", fake_generate)

    async with httpx.AsyncClient() as c:
        out = await refine_query(c, "anything", today="2026-05-21")
    assert out == "NRL fixtures round 12"


@pytest.mark.asyncio
async def test_refine_falls_back_on_llm_error(monkeypatch):
    """Embedding service down → return the original query unchanged. Never
    block a tool turn just because the refinement model is unavailable."""
    async def failing_generate(client, prompt, model, options=None):
        raise RuntimeError("llm-server unreachable")
    monkeypatch.setattr("tools._web_query.llm_server.generate", failing_generate)

    async with httpx.AsyncClient() as c:
        out = await refine_query(c, "what is the nrl schedule", today="2026-05-21")
    assert out == "what is the nrl schedule"


@pytest.mark.asyncio
async def test_refine_falls_back_on_empty_model_output(monkeypatch):
    """An empty/whitespace-only response from the model is treated as a
    failure — return the raw query rather than an empty string."""
    async def empty_generate(client, prompt, model, options=None):
        return "   \n  "
    monkeypatch.setattr("tools._web_query.llm_server.generate", empty_generate)

    async with httpx.AsyncClient() as c:
        out = await refine_query(c, "anything specific", today="2026-05-21")
    assert out == "anything specific"


@pytest.mark.asyncio
async def test_refine_empty_input_returns_input():
    """No LLM call at all for empty/whitespace-only input."""
    async with httpx.AsyncClient() as c:
        assert await refine_query(c, "", today="2026-05-21") == ""
        assert await refine_query(c, "   ", today="2026-05-21") == "   "


@pytest.mark.asyncio
async def test_refine_passes_today_into_prompt(monkeypatch):
    """The supplied date should appear in the prompt the model sees, so
    queries like 'this week' can be year-anchored."""
    seen_prompt = {}
    async def capturing_generate(client, prompt, model, options=None):
        seen_prompt["prompt"] = prompt
        return "refined"
    monkeypatch.setattr("tools._web_query.llm_server.generate", capturing_generate)

    async with httpx.AsyncClient() as c:
        await refine_query(c, "nrl this week", today="2026-05-21")
    assert "2026-05-21" in seen_prompt["prompt"]
    assert "nrl this week" in seen_prompt["prompt"]
