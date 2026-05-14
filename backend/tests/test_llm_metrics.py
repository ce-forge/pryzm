"""Unit tests for the LLM metric emission helpers."""
import logging

import pytest

from core.llm_metrics import (
    emit_chat_metric,
    emit_embed_metric,
    set_request_context,
)


@pytest.fixture(autouse=True)
def _propagate_pryzm_llm_to_caplog():
    """main.py attaches its own handler to the `pryzm.llm` logger and sets
    `propagate = False` so metric lines don't double-emit in production.
    `caplog` relies on records propagating up to the root logger, so when
    main is imported earlier in a combined test run, our records here get
    swallowed before caplog sees them. Flip propagate on for the duration
    of each test; restore on teardown."""
    logger = logging.getLogger("pryzm.llm")
    original = logger.propagate
    logger.propagate = True
    try:
        yield
    finally:
        logger.propagate = original


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
    empty strings (not None) so the log line is still well-formed.

    Uses copy_context to isolate from earlier tests in the same process that
    already called set_request_context."""
    import contextvars
    import threading

    def _emit():
        with caplog.at_level(logging.INFO, logger="pryzm.llm"):
            emit_chat_metric(model="m", response={"prompt_eval_count": 0, "eval_count": 0}, fallback_duration_s=1.0)

    # copy_context inherits current values, but .run inside an isolated copy
    # means subsequent .set() in the helpers won't leak. To get the *unset*
    # behavior we want, we need a context where the ContextVars were never
    # set on this task. Easiest: spawn a thread, since each thread has its
    # own context that starts at the ContextVar defaults.
    err = []

    def _thread_target():
        try:
            _emit()
        except Exception as e:
            err.append(e)

    t = threading.Thread(target=_thread_target)
    t.start()
    t.join()
    assert not err, err

    msg = _capture(caplog)[0].getMessage()
    # The fields are present with empty values (no None, no missing key).
    assert msg.rstrip().endswith("workspace_id= session_id=")


def test_snapshot_records_last_chat_metric(caplog):
    """get_last_chat_snapshot returns the most recent emit_chat_metric values
    for the current asyncio task (used by /analyze's final SSE chunk)."""
    from core.llm_metrics import get_last_chat_snapshot

    set_request_context(workspace_id="w", session_id="s")
    response = {
        "prompt_eval_count": 50,
        "eval_count": 100,
        "prompt_eval_duration": 200_000_000,
        "eval_duration": 1_000_000_000,
        "total_duration": 1_200_000_000,
    }
    emit_chat_metric(model="m", response=response, fallback_duration_s=1.2)

    snap = get_last_chat_snapshot()
    assert snap["model"] == "m"
    assert snap["prompt_tokens"] == 50
    assert snap["completion_tokens"] == 100
    assert snap["ttft_ms"] == 200
    assert snap["duration_ms"] == 1200
    assert snap["tokens_per_sec"] == 100.0
