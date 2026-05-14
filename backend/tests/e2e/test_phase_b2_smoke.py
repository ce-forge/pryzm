"""Phase B2 e2e probe — verifies the router emits an `llm.route` line with the
expected tier when /analyze is invoked.

Reads the live backend log at /tmp/pryzm_backend.log because the pryzm.llm
logger writes structured key=value lines there. Each test snapshots the log
length before the request and asserts on what got appended after.

These tests hit the real backend + real llama-swap. Cold model swap can take
1-2 minutes, so generous per-test timeouts. They're slow but they validate
the routing decision under the real wire format, which a TestClient + mock
cannot.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

import httpx
import pytest

BACKEND_URL = "http://127.0.0.1:8000"
BACKEND_LOG = Path("/tmp/pryzm_backend.log")

# Long enough that the request can complete even with a cold model swap.
ANALYZE_TIMEOUT_S = 180


@pytest.fixture
def api_token() -> str:
    env_path = Path(__file__).parent.parent.parent.parent / ".env"
    for line in env_path.read_text().splitlines():
        if line.startswith("PRYZM_API_TOKEN="):
            return line.split("=", 1)[1].strip()
    pytest.fail("PRYZM_API_TOKEN missing from .env", pytrace=False)


def _snapshot_log_bytes() -> int:
    return BACKEND_LOG.stat().st_size if BACKEND_LOG.exists() else 0


def _read_log_since(byte_offset: int) -> str:
    with BACKEND_LOG.open("rb") as f:
        f.seek(byte_offset)
        return f.read().decode("utf-8", errors="replace")


def _send_analyze(token: str, prompt: str) -> None:
    """POST /analyze and drain the SSE stream until it closes."""
    with httpx.Client(timeout=ANALYZE_TIMEOUT_S) as client:
        with client.stream(
            "POST",
            f"{BACKEND_URL}/analyze",
            params={"workspace": "personal"},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={"prompt": prompt},
        ) as resp:
            resp.raise_for_status()
            for _ in resp.iter_lines():
                pass


_ROUTE_LINE_RE = re.compile(
    r"llm\.route model=(\S+) tier=(\S+) reason=(\S+) prompt_len=(\d+)"
)


def _find_route_line(log_chunk: str) -> tuple[str, str, str, int] | None:
    """Returns (model, tier, reason, prompt_len) for the most recent route line
    in the chunk, or None if no route line is present."""
    matches = _ROUTE_LINE_RE.findall(log_chunk)
    if not matches:
        return None
    model, tier, reason, prompt_len = matches[-1]
    return model, tier, reason, int(prompt_len)


def test_short_prompt_routes_to_small(api_token: str):
    offset = _snapshot_log_bytes()
    _send_analyze(api_token, "hi")
    # Tiny grace window for the route log to flush after the request returns.
    time.sleep(0.5)
    chunk = _read_log_since(offset)
    route = _find_route_line(chunk)
    assert route is not None, f"no llm.route line in new log chunk:\n{chunk[-2000:]}"
    model, tier, reason, prompt_len = route
    assert tier == "small", f"expected tier=small for short prompt, got tier={tier} (reason={reason})"
    assert model == "gemma-4-E2B-it", f"expected small model, got {model}"


def test_long_prompt_routes_to_large(api_token: str):
    offset = _snapshot_log_bytes()
    # Trigger the prompt_len>500 branch with deterministic content.
    long_prompt = "Please give a brief summary of the following text. " + ("lorem ipsum " * 60)
    assert len(long_prompt) > 500
    _send_analyze(api_token, long_prompt)
    time.sleep(0.5)
    chunk = _read_log_since(offset)
    route = _find_route_line(chunk)
    assert route is not None, f"no llm.route line in new log chunk:\n{chunk[-2000:]}"
    model, tier, reason, prompt_len = route
    assert tier == "large", f"expected tier=large for long prompt, got tier={tier} (reason={reason})"
    # Two valid reasons either of which would route to large: prompt_len>500
    # or complex_verb ("summarize" / "summary"). Accept both — the spec says
    # the prompt routes to large, not specifically *why* via which heuristic.
    assert reason in {"prompt_len>500", "complex_verb"}, f"unexpected reason={reason}"
    assert model == "gemma-4-E4B-it", f"expected large model, got {model}"
