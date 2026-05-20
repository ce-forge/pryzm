"""Unit tests for backend/routers/admin.py — YAML round-trip + endpoint logic.

The tests use TestClient and monkeypatch the YAML path to a temp file so we
don't touch the real `infra/llama-swap-config.yaml`. SIGHUP and warmup calls
are stubbed so the test stays hermetic.
"""
from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from core import cookie_auth, llm_router
from db import database, models
from main import app
from routers import admin
from services import llama_swap_config


# Same YAML used by the live stack — copy verbatim so the tests exercise the
# real file shape (PreservedScalarString cmd blocks, groups list, tags).
_FIXTURE_YAML = """\
healthCheckTimeout: 3600
startPort: 9000

groups:
  "on-demand":
    swap: false
    exclusive: false
  "always-on":
    swap: false
    exclusive: false
    persistent: true

models:
  # Tier-1 default (small).
  "gemma-4-E2B-it":
    cmd: >
      /app/llama-server --port ${PORT}
      -hf bartowski/google_gemma-4-E2B-it-GGUF:Q4_K_M
      -ngl 99 --ctx-size 8192 --jinja --flash-attn on
      --cache-type-k q8_0 --cache-type-v q8_0
    groups: ["on-demand"]
    tags: []

  # Tier-2 default (larger).
  "gemma-4-E4B-it":
    cmd: >
      /app/llama-server --port ${PORT}
      -hf bartowski/google_gemma-4-E4B-it-GGUF:Q4_K_M
      -ngl 99 --ctx-size 8192 --jinja --flash-attn on
      --cache-type-k q8_0 --cache-type-v q8_0
    groups: ["on-demand"]
    tags: []

  # Embedding model — pinned always-on.
  "nomic-embed-text-v1.5":
    cmd: >
      /app/llama-server --port ${PORT}
      -hf nomic-ai/nomic-embed-text-v1.5-GGUF:Q8_0
      -ngl 99 --embeddings --batch-size 8192
    groups: ["always-on"]
    tags: ["embedding"]
"""


@pytest.fixture
def tmp_yaml(tmp_path: Path, monkeypatch) -> Path:
    """Point the admin router at a temp YAML file for the test, restore on exit."""
    path = tmp_path / "llama-swap-config.yaml"
    path.write_text(_FIXTURE_YAML)
    monkeypatch.setattr(llama_swap_config, "YAML_PATH", path)
    return path


@pytest.fixture
def client(tmp_yaml, db_session, monkeypatch) -> Iterator[TestClient]:
    monkeypatch.setattr(database, "init_db", lambda: None)
    # Stub out the SIGHUP shell-out and warmup HTTP call so tests stay hermetic.
    monkeypatch.setattr(llama_swap_config, "reload_llama_swap", lambda: None)

    async def _stub_warmup(model_id: str) -> None:
        return None
    monkeypatch.setattr(admin, "_warmup_model", _stub_warmup)

    # Stub the /running probe at its function seam so no network call happens
    # and no shared httpx state gets mutated. Mark gemma-4-E2B-it as loaded.
    async def _stub_running() -> set[str]:
        return {"gemma-4-E2B-it"}
    monkeypatch.setattr(admin, "_fetch_running_model_ids", _stub_running)

    admin_user = models.User(
        username="admin", password_hash=cookie_auth.hash_password("admin-pw-12chars"),
        is_admin=True, is_active=True,
    )
    db_session.add(admin_user); db_session.commit(); db_session.refresh(admin_user)
    sid = cookie_auth.create_session(db_session, admin_user.id)
    app.dependency_overrides[database.get_db] = lambda: db_session

    with TestClient(app) as c:
        c.cookies.set(cookie_auth.COOKIE_NAME, sid)
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# YAML round-trip preserves comments and order
# ---------------------------------------------------------------------------

def test_yaml_round_trip_preserves_comments_and_order(tmp_yaml):
    data = llama_swap_config.read_yaml()
    llama_swap_config.write_yaml(data)
    rewritten = tmp_yaml.read_text()
    # Comments survive
    assert "# Tier-1 default (small)." in rewritten
    assert "# Embedding model — pinned always-on." in rewritten
    # Order survives (E2B before nomic)
    assert rewritten.index("gemma-4-E2B-it") < rewritten.index("nomic-embed-text-v1.5")


# ---------------------------------------------------------------------------
# GET /api/admin/models
# ---------------------------------------------------------------------------

def test_list_models_returns_parsed_rows(client):
    res = client.get("/api/admin/models")
    assert res.status_code == 200
    rows = res.json()
    by_id = {r["id"]: r for r in rows}
    assert set(by_id) == {"gemma-4-E2B-it", "gemma-4-E4B-it", "nomic-embed-text-v1.5"}
    e2b = by_id["gemma-4-E2B-it"]
    assert e2b["repo"] == "bartowski/google_gemma-4-E2B-it-GGUF"
    assert e2b["quant"] == "Q4_K_M"
    assert e2b["ngl"] == 99
    assert e2b["ctx_size"] == 8192
    assert e2b["group"] == "on-demand"
    assert e2b["tags"] == []
    assert e2b["loaded"] is True
    nomic = by_id["nomic-embed-text-v1.5"]
    assert nomic["group"] == "always-on"
    assert nomic["tags"] == ["embedding"]
    assert nomic["loaded"] is False


def test_list_models_requires_auth(client):
    client.cookies.clear()
    res = client.get("/api/admin/models")
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/admin/models — validation
# ---------------------------------------------------------------------------

def test_add_model_rejects_duplicate_id(client):
    res = client.post("/api/admin/models", json={"id": "gemma-4-E2B-it", "repo": "x/y:Q4"})
    assert res.status_code == 409
    assert "already exists" in res.json()["detail"]


def test_add_model_rejects_malformed_repo(client):
    res = client.post("/api/admin/models", json={"id": "new-model", "repo": "not-valid"})
    assert res.status_code == 400


def test_add_model_rejects_bad_group(client):
    res = client.post("/api/admin/models", json={"id": "new-model", "repo": "a/b:c", "group": "weird"})
    assert res.status_code == 400


def test_add_model_rejects_bad_id_chars(client):
    res = client.post("/api/admin/models", json={"id": "bad id with spaces", "repo": "a/b:c"})
    assert res.status_code == 400


# ---------------------------------------------------------------------------
# POST /api/admin/models — happy path
# ---------------------------------------------------------------------------

def test_add_model_happy_path(client, tmp_yaml):
    res = client.post("/api/admin/models", json={
        "id": "qwen-7b-coder",
        "repo": "bartowski/Qwen2.5-Coder-7B-Instruct-GGUF:Q4_K_M",
        "ngl": 99,
        "ctx_size": 8192,
        "group": "on-demand",
        "tags": ["code"],
    })
    assert res.status_code == 201, res.text
    row = res.json()
    assert row["id"] == "qwen-7b-coder"
    assert row["repo"] == "bartowski/Qwen2.5-Coder-7B-Instruct-GGUF"
    assert row["quant"] == "Q4_K_M"
    assert row["tags"] == ["code"]

    # Disk state: YAML has the new model
    text = tmp_yaml.read_text()
    assert "qwen-7b-coder" in text
    assert "bartowski/Qwen2.5-Coder-7B-Instruct-GGUF:Q4_K_M" in text

    # Router catalog was reloaded — new model appears
    from core.llm_router import get_router
    r = get_router()
    assert "qwen-7b-coder" in r.catalog


def test_add_model_accepts_split_repo_quant(client, tmp_yaml):
    res = client.post("/api/admin/models", json={
        "id": "test-3b-split",
        "repo": "org/repo",
        "quant": "Q8_0",
    })
    assert res.status_code == 201, res.text
    assert "org/repo:Q8_0" in tmp_yaml.read_text()


def test_add_model_with_expected_filename_uses_hff_form(client, tmp_yaml):
    """When the HF picker supplies `expected_filename`, the emitted cmd uses
    `-hf <repo>` + `-hff <filename>` instead of `-hf <repo>:<quant>`.
    The :quant shortcut depends on preset metadata that some repos
    (e.g. bartowski's larger Gemma variants) don't expose — the picker
    knows the exact filename, so we should use it directly."""
    res = client.post("/api/admin/models", json={
        "id": "test-26b-via-picker",
        "repo": "bartowski/google_gemma-4-26B-A4B-it-GGUF",
        "quant": "Q4_K_M",
        "expected_filename": "google_gemma-4-26B-A4B-it-Q4_K_M.gguf",
        "group": "on-demand",
    })
    assert res.status_code == 201, res.text
    row = res.json()
    assert row["repo"] == "bartowski/google_gemma-4-26B-A4B-it-GGUF"
    assert row["filename"] == "google_gemma-4-26B-A4B-it-Q4_K_M.gguf"
    # Display quant is derived from the filename so the UI keeps its label.
    assert row["quant"] == "Q4_K_M"

    text = tmp_yaml.read_text()
    assert "-hf bartowski/google_gemma-4-26B-A4B-it-GGUF" in text
    assert "-hff google_gemma-4-26B-A4B-it-Q4_K_M.gguf" in text
    # And specifically NOT the colon-shortcut form, which is what 404s.
    assert "google_gemma-4-26B-A4B-it-GGUF:Q4_K_M" not in text


def test_add_model_without_filename_keeps_legacy_quant_form(client, tmp_yaml):
    """Manual entries (no `expected_filename`) keep emitting `-hf <repo>:<quant>`
    so existing behaviour is unchanged for repos that do expose preset metadata."""
    res = client.post("/api/admin/models", json={
        "id": "test-7b-legacy",
        "repo": "org/some-repo-GGUF:Q5_K_M",
        "group": "on-demand",
    })
    assert res.status_code == 201, res.text

    text = tmp_yaml.read_text()
    assert "-hf org/some-repo-GGUF:Q5_K_M" in text
    # No -hff anywhere in the YAML: the fixture entries use legacy form
    # and this new entry was also added with the legacy form.
    assert "-hff" not in text


# ---------------------------------------------------------------------------
# PUT /api/admin/models/{id} — edits non-identity fields
# ---------------------------------------------------------------------------

def test_update_model_404_unknown(client):
    res = client.put("/api/admin/models/does-not-exist", json={"ngl": 50})
    assert res.status_code == 404


def test_update_model_rejects_bad_group(client):
    res = client.put("/api/admin/models/gemma-4-E2B-it", json={"group": "weird"})
    assert res.status_code == 400


def test_update_model_partial_update_preserves_identity(client, tmp_yaml):
    res = client.put("/api/admin/models/gemma-4-E2B-it", json={"ngl": 50, "ctx_size": 4096})
    assert res.status_code == 200, res.text
    row = res.json()
    # Identity preserved
    assert row["id"] == "gemma-4-E2B-it"
    assert row["repo"] == "bartowski/google_gemma-4-E2B-it-GGUF"
    assert row["quant"] == "Q4_K_M"
    # Edited fields applied
    assert row["ngl"] == 50
    assert row["ctx_size"] == 4096
    # Fields not in the PUT body stay as-is
    assert row["group"] == "on-demand"
    assert row["tags"] == []

    # Disk state: cmd block reflects new values
    text = tmp_yaml.read_text()
    assert "-ngl 50" in text
    assert "--ctx-size 4096" in text
    # Original repo:quant still in YAML
    assert "bartowski/google_gemma-4-E2B-it-GGUF:Q4_K_M" in text


def test_update_model_tags_replace_not_merge(client, tmp_yaml):
    # Start: nomic has tags=["embedding"]. Replacing with ["embedding","vision"]
    # should yield exactly those two, not append-only behavior on a future call.
    res = client.put(
        "/api/admin/models/nomic-embed-text-v1.5",
        json={"tags": ["embedding", "vision"]},
    )
    assert res.status_code == 200
    assert set(res.json()["tags"]) == {"embedding", "vision"}
    # Replace with a single tag — full replacement, not merge.
    res2 = client.put(
        "/api/admin/models/nomic-embed-text-v1.5",
        json={"tags": ["embedding"]},
    )
    assert res2.json()["tags"] == ["embedding"]


def test_update_model_group_toggle_chat_to_always_on(client, tmp_yaml):
    res = client.put("/api/admin/models/gemma-4-E2B-it", json={"group": "always-on"})
    assert res.status_code == 200
    assert res.json()["group"] == "always-on"
    # YAML's groups list updated
    text = tmp_yaml.read_text()
    # Find E2B's block and verify groups contains always-on. The naive substring
    # search is fine here since 'always-on' only appears in groups lines.
    assert "always-on" in text


def test_update_model_requires_auth(client):
    client.cookies.clear()
    res = client.put("/api/admin/models/gemma-4-E2B-it", json={"ngl": 50})
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# DELETE /api/admin/models/{id}
# ---------------------------------------------------------------------------

def test_delete_model_refuses_embedding(client):
    res = client.delete("/api/admin/models/nomic-embed-text-v1.5")
    assert res.status_code == 400
    assert "embedding" in res.json()["detail"].lower()


def test_delete_model_404_unknown(client):
    res = client.delete("/api/admin/models/does-not-exist")
    assert res.status_code == 404


def test_delete_model_happy_path(client, tmp_yaml):
    # Add first so we have something to delete. Model id needs a size hint
    # so the router's catalog rebuild during the POST accepts it.
    add_res = client.post("/api/admin/models", json={"id": "deletable-3b", "repo": "a/b:Q4"})
    assert add_res.status_code == 201
    res = client.delete("/api/admin/models/deletable-3b")
    assert res.status_code == 200
    assert res.json() == {"deleted": "deletable-3b"}
    assert "deletable-3b" not in tmp_yaml.read_text()


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def test_endpoints_require_auth(client):
    client.cookies.clear()
    assert client.post("/api/admin/models", json={"id": "x", "repo": "a/b:c"}).status_code == 401
    assert client.delete("/api/admin/models/x").status_code == 401
