"""Unit tests for the startup model pre-warmer."""
from __future__ import annotations

import pathlib

import httpx
import pytest

from core import llm_router
from services import model_prewarm


def _yaml_at(tmp_path: pathlib.Path, content: str) -> pathlib.Path:
    p = tmp_path / "llama-swap-config.yaml"
    p.write_text(content)
    return p


# ---------------------------------------------------------------------------
# models_to_prewarm_from_yaml
# ---------------------------------------------------------------------------

def test_prewarm_yaml_includes_always_on_and_vision_tagged(tmp_path):
    """Pre-warm list includes anything in the `always-on` group OR
    tagged `vision`. The vision-tagged E4B (`chat` group, swappable)
    is included so the first image upload doesn't pay cold-load cost."""
    path = _yaml_at(tmp_path, """
models:
  "gemma-4-E2B-it":
    cmd: "x"
    groups: ["always-on"]
    tags: []
  "gemma-4-E4B-it":
    cmd: "x"
    groups: ["chat"]
    tags: ["vision"]
  "untagged-chat":
    cmd: "x"
    groups: ["chat"]
    tags: []
  "nomic-embed":
    cmd: "x"
    groups: ["always-on"]
    tags: ["embedding"]
""")
    out = llm_router.models_to_prewarm_from_yaml(path)
    out_ids = {model_id for model_id, _ in out}
    assert out_ids == {"gemma-4-E2B-it", "gemma-4-E4B-it", "nomic-embed"}
    assert "untagged-chat" not in out_ids


def test_prewarm_yaml_dedupes_always_on_plus_vision_model(tmp_path):
    """A model that's both always-on AND vision-tagged appears once."""
    path = _yaml_at(tmp_path, """
models:
  "vision-pinned":
    cmd: "x"
    groups: ["always-on"]
    tags: ["vision"]
""")
    out = llm_router.models_to_prewarm_from_yaml(path)
    assert len(out) == 1
    assert out[0][0] == "vision-pinned"
    assert "vision" in out[0][1]


def test_prewarm_yaml_preserves_tags(tmp_path):
    """Embedding tag in particular needs to survive — the pre-warmer
    uses it to pick /v1/embeddings vs /v1/chat/completions."""
    path = _yaml_at(tmp_path, """
models:
  "embed":
    cmd: "x"
    groups: ["always-on"]
    tags: ["embedding"]
""")
    out = llm_router.models_to_prewarm_from_yaml(path)
    assert out == [("embed", {"embedding"})]


def test_prewarm_yaml_handles_missing_groups_field(tmp_path):
    """A model with no groups/tags shouldn't blow up; just skip it.
    Defensive against partial config edits."""
    path = _yaml_at(tmp_path, """
models:
  "model-a":
    cmd: "x"
  "model-b":
    cmd: "x"
    groups: ~
  "model-c":
    cmd: "x"
    groups: ["always-on"]
""")
    out_ids = {m for m, _ in llm_router.models_to_prewarm_from_yaml(path)}
    assert out_ids == {"model-c"}


# ---------------------------------------------------------------------------
# warm_model / warm_models
# ---------------------------------------------------------------------------

class _StubTransport(httpx.AsyncBaseTransport):
    """Records request URLs + payloads, returns 200 by default."""
    def __init__(self):
        self.requests: list[tuple[str, dict]] = []
        self.fail_for: set[str] = set()

    async def handle_async_request(self, request):
        import json
        payload = json.loads(request.content.decode())
        self.requests.append((str(request.url), payload))
        if payload.get("model") in self.fail_for:
            return httpx.Response(500, json={"error": "boom"})
        return httpx.Response(200, json={"ok": True})


@pytest.mark.asyncio
async def test_warm_model_chat_hits_chat_completions(caplog):
    transport = _StubTransport()
    async with httpx.AsyncClient(transport=transport) as client:
        await model_prewarm.warm_model(client, "http://llama:9000", "gemma-chat", set())
    url, payload = transport.requests[0]
    assert url.endswith("/v1/chat/completions")
    assert payload["model"] == "gemma-chat"
    assert payload["max_tokens"] == 1


@pytest.mark.asyncio
async def test_warm_model_embedding_hits_embeddings():
    transport = _StubTransport()
    async with httpx.AsyncClient(transport=transport) as client:
        await model_prewarm.warm_model(
            client, "http://llama:9000", "nomic-embed", {"embedding"},
        )
    url, payload = transport.requests[0]
    assert url.endswith("/v1/embeddings")
    assert payload["model"] == "nomic-embed"


@pytest.mark.asyncio
async def test_warm_model_swallows_failure_and_logs(caplog):
    """Failing pre-warm must not raise; backend startup depends on it."""
    import logging
    transport = _StubTransport()
    transport.fail_for = {"broken-model"}
    async with httpx.AsyncClient(transport=transport) as client:
        with caplog.at_level(logging.WARNING, logger="services.model_prewarm"):
            await model_prewarm.warm_model(
                client, "http://llama:9000", "broken-model", set(),
            )
    assert any("pre-warm failed for broken-model" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_warm_models_runs_each_independently():
    """One failing model must not stop subsequent models from warming.
    Embedding model coming AFTER a failed chat model is the realistic
    case — we don't want auto-RAG to pay the embed-load cost just
    because the chat tier had a transient issue."""
    transport = _StubTransport()
    transport.fail_for = {"flaky-chat"}
    async with httpx.AsyncClient(transport=transport) as client:
        await model_prewarm.warm_models(
            client,
            "http://llama:9000",
            [("flaky-chat", set()), ("nomic-embed", {"embedding"})],
        )
    seen_models = [p["model"] for _, p in transport.requests]
    assert seen_models == ["flaky-chat", "nomic-embed"]
