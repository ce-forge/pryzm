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
        return '  "NRL schedule this week"\n'
    monkeypatch.setattr("tools._web_query.llm_server.generate", fake_generate)

    async with httpx.AsyncClient() as c:
        out = await refine_query(c, "what is the nrl shecudle this week")
    assert out == "NRL schedule this week"


@pytest.mark.asyncio
async def test_refine_takes_first_line_only(monkeypatch):
    """If the model rambles past one line, only the first line is used."""
    async def fake_generate(client, prompt, model, options=None):
        return "NRL schedule this week\nExplanation: I dropped 'what is'..."
    monkeypatch.setattr("tools._web_query.llm_server.generate", fake_generate)

    async with httpx.AsyncClient() as c:
        out = await refine_query(c, "anything")
    assert out == "NRL schedule this week"


@pytest.mark.asyncio
async def test_refine_falls_back_on_llm_error(monkeypatch):
    """Refinement service down → return the original query unchanged. Never
    block a tool turn just because the refinement model is unavailable."""
    async def failing_generate(client, prompt, model, options=None):
        raise RuntimeError("llm-server unreachable")
    monkeypatch.setattr("tools._web_query.llm_server.generate", failing_generate)

    async with httpx.AsyncClient() as c:
        out = await refine_query(c, "what is the nrl schedule")
    assert out == "what is the nrl schedule"


@pytest.mark.asyncio
async def test_refine_falls_back_on_empty_model_output(monkeypatch):
    """An empty/whitespace-only response from the model is treated as a
    failure — return the raw query rather than an empty string."""
    async def empty_generate(client, prompt, model, options=None):
        return "   \n  "
    monkeypatch.setattr("tools._web_query.llm_server.generate", empty_generate)

    async with httpx.AsyncClient() as c:
        out = await refine_query(c, "anything specific")
    assert out == "anything specific"


@pytest.mark.asyncio
async def test_refine_empty_input_returns_input():
    """No LLM call at all for empty/whitespace-only input."""
    async with httpx.AsyncClient() as c:
        assert await refine_query(c, "") == ""
        assert await refine_query(c, "   ") == "   "


@pytest.mark.asyncio
async def test_refine_does_not_inject_dates_in_prompt(monkeypatch):
    """Refinement preserves the user's time references verbatim — does NOT
    add today's date or rewrite "this week" / "last month" into explicit
    months. SearxNG ranks on the user's wording, not ours."""
    seen_prompt = {}
    async def capturing_generate(client, prompt, model, options=None):
        seen_prompt["prompt"] = prompt
        return "refined"
    monkeypatch.setattr("tools._web_query.llm_server.generate", capturing_generate)

    async with httpx.AsyncClient() as c:
        await refine_query(c, "nrl this week")
    # The user's phrasing is present in the prompt; the rules tell the model
    # not to substitute dates for time references.
    assert "nrl this week" in seen_prompt["prompt"]
    # No "Today is YYYY-MM-DD" line in the preprompt.
    assert "today is" not in seen_prompt["prompt"].lower()
