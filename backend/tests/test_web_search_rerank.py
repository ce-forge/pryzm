"""Unit tests for the embedding-based rerank helper used by web_search."""
from __future__ import annotations

import pytest

from tools._web_rerank import (
    cosine_similarity,
    rerank_chunks_by_query,
    split_into_chunks,
)


def test_split_into_chunks_one_short_para():
    text = "Just one short paragraph here."
    chunks = split_into_chunks(text, target_chars=400)
    assert chunks == ["Just one short paragraph here."]


def test_split_into_chunks_multiple_paragraphs():
    text = "Para one is here.\n\nPara two is here.\n\nPara three is here."
    chunks = split_into_chunks(text, target_chars=400)
    assert len(chunks) == 3
    assert chunks[0] == "Para one is here."


def test_split_into_chunks_long_paragraph_split_at_sentences():
    sent = "This is a sentence about testing. " * 30  # ~990 chars in one paragraph
    chunks = split_into_chunks(sent, target_chars=200)
    assert len(chunks) > 1
    for c in chunks:
        # Each chunk should be roughly target-sized (allow some slack since we
        # don't split mid-sentence).
        assert len(c) < 400


def test_split_into_chunks_empty_returns_empty():
    assert split_into_chunks("", target_chars=400) == []
    assert split_into_chunks("   \n\n   ", target_chars=400) == []


def test_cosine_similarity_identical_vectors():
    v = [1.0, 2.0, 3.0]
    assert cosine_similarity(v, v) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal():
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_similarity_zero_vector():
    assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0
    assert cosine_similarity([], [1.0]) == 0.0


@pytest.mark.asyncio
async def test_rerank_picks_query_relevant_chunks(monkeypatch):
    """The chunks closest to the query embedding should be selected first."""
    chunks = [
        "The Raiders play the Dolphins on Thursday night at GIO Stadium.",
        "Sponsored: best fantasy sports apps of 2026.",
        "Bulldogs vs Storm Friday kickoff 7:50pm.",
    ]
    query = "NRL fixtures this round"

    # Synthetic embeddings: index-0 vectors point in one direction (NRL match
    # info), index-1 points orthogonally (sponsored ad), index-2 also NRL.
    fake_vecs = {
        query: [1.0, 0.0],
        chunks[0]: [0.9, 0.1],   # close to query
        chunks[1]: [0.0, 1.0],   # orthogonal
        chunks[2]: [0.85, 0.15], # close to query
    }

    async def fake_embed(client, text, model):
        return fake_vecs[text]

    monkeypatch.setattr("tools._web_rerank.llm_server.embed", fake_embed)

    import httpx
    async with httpx.AsyncClient() as c:
        # Budget=110: fits both NRL chunks (63+40=103) but not the third.
        # Greedy picks Raiders first (highest sim), then Bulldogs, then
        # Sponsored would exceed budget and is dropped.
        picked = await rerank_chunks_by_query(
            c, chunks, query, char_budget=110,
        )

    # Both NRL chunks should be picked; sponsored ad should be dropped.
    joined = " ".join(picked)
    assert "Raiders" in joined
    assert "Bulldogs" in joined
    assert "Sponsored" not in joined


@pytest.mark.asyncio
async def test_rerank_preserves_original_order(monkeypatch):
    """Selected chunks come back in original document order, not similarity
    order — gives the model a coherent narrative."""
    chunks = ["First.", "Second.", "Third."]
    query = "anything"

    # Inverse-relevance: the LAST chunk is most similar to the query.
    fake_vecs = {
        query: [1.0],
        chunks[0]: [0.2],
        chunks[1]: [0.5],
        chunks[2]: [0.9],
    }

    async def fake_embed(client, text, model):
        return fake_vecs[text]
    monkeypatch.setattr("tools._web_rerank.llm_server.embed", fake_embed)

    import httpx
    async with httpx.AsyncClient() as c:
        picked = await rerank_chunks_by_query(c, chunks, query, char_budget=100)

    # All three fit under the budget; assert they come back in original order.
    assert picked == ["First.", "Second.", "Third."]


@pytest.mark.asyncio
async def test_rerank_falls_back_to_truncation_on_embed_failure(monkeypatch):
    """If the embed service errors, return chunks in original order up to
    char_budget. No re-ranking, but no synthesis blocker either."""
    chunks = ["Chunk A.", "Chunk B.", "Chunk C."]

    async def failing_embed(client, text, model):
        raise RuntimeError("embed model down")

    monkeypatch.setattr("tools._web_rerank.llm_server.embed", failing_embed)

    import httpx
    async with httpx.AsyncClient() as c:
        picked = await rerank_chunks_by_query(c, chunks, "anything", char_budget=20)

    # All three are under 20 total chars combined ("Chunk A.Chunk B.Chunk C." = 24)
    # so we should get the first ~2-3 chunks in order.
    assert picked[0] == "Chunk A."
    # No reranking, original order preserved.


@pytest.mark.asyncio
async def test_rerank_empty_chunks_returns_empty():
    import httpx
    async with httpx.AsyncClient() as c:
        out = await rerank_chunks_by_query(c, [], "anything", char_budget=100)
    assert out == []
