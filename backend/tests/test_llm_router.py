"""Unit tests for core/llm_router.py."""
from __future__ import annotations

import pathlib

import pytest

from core.llm_router import (
    HeuristicRouter,
    Tier,
    build_catalog_from_yaml,
    get_router,
    init_router,
)


# Mirrors the current infra/llama-swap-config.yaml without parsing the file.
_REAL_CATALOG: dict[str, set[str]] = {
    "gemma-4-E2B-it": set(),
    "gemma-4-E4B-it": set(),
    "nomic-embed-text-v1.5": {"embedding"},
}


# ---------------------------------------------------------------------------
# build_catalog_from_yaml
# ---------------------------------------------------------------------------

def test_build_catalog_from_real_yaml():
    repo_root = pathlib.Path(__file__).resolve().parent.parent.parent
    catalog = build_catalog_from_yaml(repo_root / "infra" / "llama-swap-config.yaml")
    assert "gemma-4-E2B-it" in catalog
    assert "gemma-4-E4B-it" in catalog
    assert "nomic-embed-text-v1.5" in catalog
    assert catalog["nomic-embed-text-v1.5"] == {"embedding"}
    assert catalog["gemma-4-E2B-it"] == set()
    assert catalog["gemma-4-E4B-it"] == set()


# ---------------------------------------------------------------------------
# _partition_chat_models — picks endpoints, excludes embedding
# ---------------------------------------------------------------------------

def test_partition_excludes_embedding_and_picks_endpoints():
    r = HeuristicRouter(_REAL_CATALOG)
    assert r.small == "gemma-4-E2B-it"
    assert r.large == "gemma-4-E4B-it"


def test_partition_raises_when_no_size_hint():
    bad_catalog = {"frontier-model": set(), "tiny": set()}
    with pytest.raises(ValueError, match="no parseable size hint"):
        HeuristicRouter(bad_catalog)


def test_partition_raises_with_fewer_than_two_chat_models():
    only_one = {"gemma-4-E4B-it": set(), "nomic-embed-text-v1.5": {"embedding"}}
    with pytest.raises(ValueError, match="at least 2 chat models"):
        HeuristicRouter(only_one)


def test_partition_uses_numeric_size_hint_not_substring():
    # Hypothetical future catalog: 1B, 4B, 7B. Endpoints should be 1B and 7B,
    # not whatever happens to appear alphabetically.
    future = {
        "frontier-7b-instruct": set(),
        "midrange-4b-instruct": set(),
        "tiny-1b-instruct": set(),
    }
    r = HeuristicRouter(future)
    assert r.small == "tiny-1b-instruct"
    assert r.large == "frontier-7b-instruct"


# ---------------------------------------------------------------------------
# _pick_tier — every branch
# ---------------------------------------------------------------------------

@pytest.fixture
def router() -> HeuristicRouter:
    return HeuristicRouter(_REAL_CATALOG)


def test_pick_tier_default_is_small(router):
    tier, reason = router._pick_tier("hi", [], [])
    assert tier is Tier.SMALL
    assert reason == "default"


def test_pick_tier_attachment_forces_large(router):
    tier, reason = router._pick_tier("hi", [], ["any.pdf"])
    assert tier is Tier.LARGE
    assert reason == "attachments"


def test_pick_tier_long_prompt_forces_large(router):
    long_prompt = "x" * 501
    tier, reason = router._pick_tier(long_prompt, [], [])
    assert tier is Tier.LARGE
    assert reason == "prompt_len>500"


def test_pick_tier_code_fence_forces_large(router):
    tier, reason = router._pick_tier("see ```py\nprint(1)\n```", [], [])
    assert tier is Tier.LARGE
    assert reason == "code_fence"


@pytest.mark.parametrize("verb", ["compare", "analyze", "plan", "design", "summarize"])
def test_pick_tier_complex_verb_forces_large(router, verb):
    tier, reason = router._pick_tier(f"please {verb} these", [], [])
    assert tier is Tier.LARGE
    assert reason == "complex_verb"


def test_pick_tier_long_history_forces_large(router):
    history = [{"role": "user", "content": "x"}] * 9
    tier, reason = router._pick_tier("ok", history, [])
    assert tier is Tier.LARGE
    assert reason == "history>8"


def test_pick_tier_short_history_stays_small(router):
    history = [{"role": "user", "content": "x"}] * 8
    tier, reason = router._pick_tier("ok", history, [])
    assert tier is Tier.SMALL
    assert reason == "default"


# ---------------------------------------------------------------------------
# pick() — end-to-end returns the right model id
# ---------------------------------------------------------------------------

def test_pick_small_returns_small_model(router):
    model, tier, reason = router.pick("hi", [], [])
    assert model == "gemma-4-E2B-it"
    assert tier is Tier.SMALL


def test_pick_large_returns_large_model(router):
    model, tier, reason = router.pick("x" * 600, [], [])
    assert model == "gemma-4-E4B-it"
    assert tier is Tier.LARGE


# ---------------------------------------------------------------------------
# init_router / get_router lifecycle
# ---------------------------------------------------------------------------

def test_init_then_get_returns_initialised_singleton():
    r = init_router(_REAL_CATALOG)
    assert get_router() is r


def test_get_router_raises_when_uninitialised(monkeypatch):
    import core.llm_router as mod
    monkeypatch.setattr(mod, "_router_singleton", None)
    with pytest.raises(RuntimeError, match="not initialised"):
        get_router()
