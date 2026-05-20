"""Sentence-aware truncation for web_search page bodies.

The web_search tool caps each fetched page's extracted text at a configurable
char limit so the synthesis prompt stays inside the model's context window.
We prefer sentence-boundary cuts so the model never has to read a half-finished
sentence; if a single sentence already exceeds the cap, we hard-cut with an
ellipsis so the budget is honored.
"""
from __future__ import annotations

import re


_SENTENCE_END = re.compile(r'(?<=[.!?])\s+')


def truncate_to_sentences(text: str, max_chars: int) -> str:
    """Return at most `max_chars` chars of `text`, cut on a sentence boundary
    when possible. A single sentence longer than `max_chars` is hard-cut and
    suffixed with `…`. Whitespace-only or empty input is returned unchanged.

    Sentence detection is best-effort. The regex treats every `.`, `!`, `?`
    followed by whitespace as a boundary, so abbreviations (`Mr.`, `U.S.`,
    `e.g.`) produce fragment splits. The output still respects `max_chars`,
    but fragments may appear in place of whole sentences. Good enough for
    extracted web-page text feeding an LLM synthesis prompt; revisit if
    a more demanding caller arrives.
    """
    if not text or not text.strip():
        return text
    if len(text) <= max_chars:
        return text

    sentences = _SENTENCE_END.split(text)
    out: list[str] = []
    used = 0
    for sent in sentences:
        # +1 for the separator we'll join with (space).
        addition = len(sent) + (1 if out else 0)
        if used + addition > max_chars:
            break
        out.append(sent)
        used += addition

    if out:
        return " ".join(out)

    # Single oversized sentence — hard-cut with ellipsis.
    return text[: max_chars - 1].rstrip() + "…"
