"""e2e probe — verifies GET /api/admin/models against the live backend,
with the live llama-swap providing the `/running` data.

No POST/DELETE here: those mutate the real YAML and SIGHUP the container.
Mutation paths are covered by the in-process unit tests in
tests/test_admin_models.py.
"""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest

BACKEND_URL = "http://127.0.0.1:8000"


@pytest.fixture
def api_token() -> str:
    env_path = Path(__file__).parent.parent.parent.parent / ".env"
    for line in env_path.read_text().splitlines():
        if line.startswith("PRYZM_API_TOKEN="):
            return line.split("=", 1)[1].strip()
    pytest.fail("PRYZM_API_TOKEN missing from .env", pytrace=False)


def test_list_models_against_live_backend(api_token: str):
    headers = {"Authorization": f"Bearer {api_token}"}
    res = httpx.get(f"{BACKEND_URL}/api/admin/models", headers=headers, timeout=5.0)
    assert res.status_code == 200, res.text
    rows = res.json()
    by_id = {r["id"]: r for r in rows}
    # The three default models from the canonical infra/llama-swap-config.yaml.
    assert "gemma-4-E2B-it" in by_id
    assert "gemma-4-E4B-it" in by_id
    assert "nomic-embed-text-v1.5" in by_id

    # Shape checks
    e2b = by_id["gemma-4-E2B-it"]
    # E2B was moved to always-on in Phase C tuning; the e4b chat model
    # is the canonical "chat group" entry now.
    assert e2b["group"] in {"chat", "always-on"}
    assert e2b["repo"] == "bartowski/google_gemma-4-E2B-it-GGUF"
    assert e2b["quant"] == "Q4_K_M"
    assert isinstance(e2b["loaded"], bool)

    e4b = by_id["gemma-4-E4B-it"]
    assert e4b["group"] == "chat"

    nomic = by_id["nomic-embed-text-v1.5"]
    assert nomic["group"] == "always-on"
    assert "embedding" in nomic["tags"]


def test_list_models_unauth_returns_401():
    res = httpx.get(f"{BACKEND_URL}/api/admin/models", timeout=5.0)
    assert res.status_code == 401
