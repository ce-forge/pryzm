"""Unit tests for the sentence-aware truncation used by the web_search tool's
per-page body cap. The helper walks sentence boundaries and stops before
exceeding the char cap; a single sentence longer than the cap is hard-cut at
the cap with an ellipsis."""
from __future__ import annotations

from tools._web_truncate import truncate_to_sentences


def test_returns_unchanged_when_under_cap():
    body = "First sentence. Second sentence."
    assert truncate_to_sentences(body, max_chars=200) == body


def test_drops_trailing_sentence_to_stay_under_cap():
    body = "Sentence one is here. Sentence two is here. Sentence three is here."
    out = truncate_to_sentences(body, max_chars=45)
    assert out == "Sentence one is here. Sentence two is here."
    assert len(out) <= 45


def test_hard_cuts_a_single_oversized_sentence():
    body = "A" * 200 + ". Short follow-up."
    out = truncate_to_sentences(body, max_chars=50)
    assert out.endswith("…")
    assert len(out) <= 50


def test_handles_question_and_exclamation_endings():
    body = "Question one? Answer two! Statement three. Statement four."
    out = truncate_to_sentences(body, max_chars=30)
    assert out == "Question one? Answer two!"


def test_empty_input_returns_empty():
    assert truncate_to_sentences("", max_chars=100) == ""
    assert truncate_to_sentences("   ", max_chars=100) == "   "
