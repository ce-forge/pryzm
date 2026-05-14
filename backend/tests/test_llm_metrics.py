"""Unit tests for the LLM metric emission helpers."""
import logging

import pytest

from core.llm_metrics import (
    emit_chat_metric,
    emit_embed_metric,
    set_request_context,
)


def _capture(caplog):
    return [r for r in caplog.records if r.name == "pryzm.llm"]


def test_emit_chat_metric_extracts_ollama_fields(caplog):
    """Given a chat response with Ollama's standard timing fields, the metric
    line should carry the parsed values."""
    set_request_context(workspace_id="ws-1", session_id="s-1")
    response = {
        "prompt_eval_count": 312,
        "eval_count": 187,
        "prompt_eval_duration": 420_000_000,   # ns -> 420 ms
        "eval_duration": 4_410_000_000,        # ns -> 4410 ms
        "total_duration": 4_830_000_000,       # ns -> 4830 ms
    }
    with caplog.at_level(logging.INFO, logger="pryzm.llm"):
        emit_chat_metric(model="gemma4:e4b", response=response, fallback_duration_s=4.83)

    records = _capture(caplog)
    assert len(records) == 1
    msg = records[0].getMessage()
    assert "llm.metric" in msg
    assert "model=gemma4:e4b" in msg
    assert "prompt_tokens=312" in msg
    assert "completion_tokens=187" in msg
    assert "ttft_ms=420" in msg
    assert "duration_ms=4830" in msg
    # 187 tokens / 4.41s = 42.40 tps
    assert "tokens_per_sec=42.40" in msg
    assert "workspace_id=ws-1" in msg
    assert "session_id=s-1" in msg


def test_emit_chat_metric_falls_back_when_ollama_omits_timings(caplog):
    """Some Ollama versions omit duration fields under load. The helper falls
    back to the wall-clock seconds the caller measured."""
    set_request_context(workspace_id="ws-2", session_id="s-2")
    response = {"prompt_eval_count": 10, "eval_count": 5}  # no durations
    with caplog.at_level(logging.INFO, logger="pryzm.llm"):
        emit_chat_metric(model="m", response=response, fallback_duration_s=2.0)

    records = _capture(caplog)
    assert len(records) == 1
    msg = records[0].getMessage()
    assert "duration_ms=2000" in msg  # fallback
    assert "ttft_ms=0" in msg          # unknown -> 0
    assert "tokens_per_sec=0.00" in msg # cannot compute without eval_duration


def test_emit_embed_metric(caplog):
    set_request_context(workspace_id="ws-3", session_id="")
    with caplog.at_level(logging.INFO, logger="pryzm.llm"):
        emit_embed_metric(model="nomic-embed-text", char_count=423, duration_s=0.18)
    records = _capture(caplog)
    assert len(records) == 1
    msg = records[0].getMessage()
    assert "llm.embed_metric" in msg
    assert "model=nomic-embed-text" in msg
    assert "char_count=423" in msg
    assert "duration_ms=180" in msg
    assert "workspace_id=ws-3" in msg
    assert "session_id=" in msg


def test_context_defaults_when_unset(caplog):
    """If the request handler didn't call set_request_context, both fields are
    empty strings (not None) so the log line is still well-formed."""
    # Reset by setting to defaults
    set_request_context(workspace_id="", session_id="")
    response = {"prompt_eval_count": 0, "eval_count": 0}
    with caplog.at_level(logging.INFO, logger="pryzm.llm"):
        emit_chat_metric(model="m", response=response, fallback_duration_s=1.0)
    msg = _capture(caplog)[0].getMessage()
    assert "workspace_id=" in msg
    assert "session_id=" in msg
