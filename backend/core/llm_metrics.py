"""Per-request LLM performance metric emission.

Three small helpers + two contextvars. Helpers emit one structured log
line per LLM call (chat / generate / embed). The line is key=value formatted
on the `pryzm.llm` logger so it's grep-able from the backend log and
machine-parseable by the perf-comparison harness.

Workspace and session ids are threaded via contextvars so call sites at
the HTTP layer don't need to plumb identifiers down through every LLM
call. Set them once with `set_request_context(...)` at the request boundary;
the emitters pick them up automatically.

Emitted log line shape:
    llm.metric model=<m> prompt_tokens=<n> completion_tokens=<n>
        ttft_ms=<n> duration_ms=<n> tokens_per_sec=<n.nn>
        workspace_id=<id> session_id=<id>
    llm.embed_metric model=<m> char_count=<n> duration_ms=<n>
        workspace_id=<id> session_id=<id>
"""
from __future__ import annotations

import contextvars
import logging

_logger = logging.getLogger("pryzm.llm")

_workspace_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "pryzm_llm_workspace_id", default=""
)
_session_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "pryzm_llm_session_id", default=""
)


def set_request_context(*, workspace_id: str, session_id: str) -> None:
    """Sets per-request identifiers used by subsequent metric emissions on the
    same asyncio task. Call once at the top of each request that will trigger
    LLM activity."""
    _workspace_id.set(workspace_id or "")
    _session_id.set(session_id or "")


def emit_chat_metric(
    *,
    model: str,
    response: dict,
    fallback_duration_s: float,
) -> None:
    """Logs a single 'llm.metric' line. Prefers Ollama's native nanosecond
    timing fields; falls back to the wall-clock seconds the caller passes in
    if Ollama omitted them.

    Tokens/sec is computed from eval_count / eval_duration, NOT from
    completion_tokens / total_duration — the latter would penalise the model
    for prompt-eval time it doesn't control."""
    prompt_tokens = int(response.get("prompt_eval_count", 0))
    completion_tokens = int(response.get("eval_count", 0))

    prompt_eval_ns = int(response.get("prompt_eval_duration", 0))
    eval_ns = int(response.get("eval_duration", 0))
    total_ns = int(response.get("total_duration", 0))

    ttft_ms = prompt_eval_ns // 1_000_000 if prompt_eval_ns else 0
    duration_ms = total_ns // 1_000_000 if total_ns else int(fallback_duration_s * 1000)
    tokens_per_sec = (
        (completion_tokens * 1_000_000_000.0) / eval_ns
        if eval_ns and completion_tokens
        else 0.0
    )

    _logger.info(
        "llm.metric model=%s prompt_tokens=%d completion_tokens=%d "
        "ttft_ms=%d duration_ms=%d tokens_per_sec=%.2f "
        "workspace_id=%s session_id=%s",
        model, prompt_tokens, completion_tokens,
        ttft_ms, duration_ms, tokens_per_sec,
        _workspace_id.get(), _session_id.get(),
    )


def emit_embed_metric(
    *,
    model: str,
    char_count: int,
    duration_s: float,
) -> None:
    """Logs a single 'llm.embed_metric' line. Embeddings don't have a
    streaming-vs-prompt-eval split, so duration is wall-clock only."""
    _logger.info(
        "llm.embed_metric model=%s char_count=%d duration_ms=%d "
        "workspace_id=%s session_id=%s",
        model, char_count, int(duration_s * 1000),
        _workspace_id.get(), _session_id.get(),
    )
