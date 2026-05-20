"""Embedding-based relevance reranking for web_search extracted content.

After trafilatura extracts main content from a fetched page, the text often
contains relevant material mixed with off-topic sections (sidebars, "what's on
today" widgets, related-articles). This module splits the body into
paragraph-sized chunks, embeds each chunk plus the user's query, ranks by
cosine similarity, and returns only the top chunks fitting under a char
budget. Drops semantically irrelevant content that length-based truncation
can't catch.

The chat-ui project (huggingface/chat-ui) uses the same approach — see
`src/lib/server/websearch/embed/embed.ts`. Our flat-text version is simpler
than their markdown-tree variant but has the same core mechanic.
"""
from __future__ import annotations

import asyncio
import math
import re

import httpx

from core import llm_server


# Paragraph splitter: split on blank lines first. Long paragraphs further split
# at sentence boundaries to keep chunks paragraph-sized (target 300-500 chars).
_PARAGRAPH_SEP = re.compile(r'\n\s*\n')
_SENTENCE_END = re.compile(r'(?<=[.!?])\s+')


def split_into_chunks(text: str, target_chars: int = 400) -> list[str]:
    """Split `text` into roughly `target_chars`-sized chunks at paragraph
    boundaries, further splitting any paragraph that exceeds the target by
    sentence boundaries. Returns non-empty chunks only."""
    if not text or not text.strip():
        return []
    out: list[str] = []
    for para in _PARAGRAPH_SEP.split(text):
        para = para.strip()
        if not para:
            continue
        if len(para) <= target_chars * 1.5:
            out.append(para)
            continue
        # Long paragraph — pack sentences into target-sized chunks.
        sentences = _SENTENCE_END.split(para)
        buf: list[str] = []
        buf_len = 0
        for sent in sentences:
            sent = sent.strip()
            if not sent:
                continue
            if buf and buf_len + len(sent) > target_chars:
                out.append(" ".join(buf))
                buf, buf_len = [sent], len(sent)
            else:
                buf.append(sent)
                buf_len += len(sent) + 1
        if buf:
            out.append(" ".join(buf))
    return out


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors. Returns 0.0 if either is
    zero-length (shouldn't happen with real embeddings but defensive)."""
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


async def rerank_chunks_by_query(
    client: httpx.AsyncClient,
    chunks: list[str],
    query: str,
    char_budget: int,
    *,
    model: str = llm_server.DEFAULT_EMBED_MODEL,
) -> list[str]:
    """Embed `chunks` and `query`, return chunks sorted by cosine similarity
    descending, taking enough to fill `char_budget`. Preserves the original
    order of selected chunks in the returned list so the model gets a coherent
    narrative (not similarity-shuffled fragments).

    On embedding failure for any reason, returns the original `chunks`
    untouched up to the char budget — degrades gracefully rather than blocking
    the synthesis turn."""
    if not chunks:
        return []
    # Single-chunk pages: nothing to rerank.
    if len(chunks) == 1:
        only = chunks[0]
        return [only[:char_budget]] if len(only) > char_budget else [only]

    try:
        # Embed query + all chunks in parallel.
        embeddings = await asyncio.gather(
            llm_server.embed(client, query, model),
            *(llm_server.embed(client, c, model) for c in chunks),
        )
    except Exception:
        # Fall back to original-order truncation.
        out: list[str] = []
        used = 0
        for c in chunks:
            if used + len(c) > char_budget:
                break
            out.append(c)
            used += len(c)
        return out

    query_vec = embeddings[0]
    chunk_vecs = embeddings[1:]

    scored = [
        (i, cosine_similarity(query_vec, vec))
        for i, vec in enumerate(chunk_vecs)
    ]
    # Sort by similarity descending.
    scored.sort(key=lambda pair: -pair[1])

    # Greedily pick highest-scoring chunks until char budget hits.
    picked_idx: set[int] = set()
    total = 0
    for idx, _score in scored:
        chunk_len = len(chunks[idx])
        if total + chunk_len > char_budget:
            if not picked_idx:
                # Always take at least one chunk so the source isn't empty.
                picked_idx.add(idx)
            break
        picked_idx.add(idx)
        total += chunk_len

    # Return in original order.
    return [chunks[i] for i in sorted(picked_idx)]
