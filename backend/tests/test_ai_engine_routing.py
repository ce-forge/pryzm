"""Tests for the tier-hint override path in the chat engine — when a mode
declares a tag-based tier override, the engine picks the tagged model instead
of the router's heuristic choice."""
from __future__ import annotations

from core.ai_engine import _resolve_routed_model
from core.llm_router import HeuristicRouter


def test_resolve_routed_model_uses_web_tagged_model_when_hint_is_web():
    catalog = {"small-2b": {"web"}, "large-26b": {"reasoning"}}
    router = HeuristicRouter(catalog)
    model_id, reason = _resolve_routed_model(
        router, tier_hint="web", default_model_id="large-26b", default_reason="default",
    )
    assert model_id == "small-2b"
    assert reason == "mode_tier_override:web"


def test_resolve_routed_model_falls_back_when_no_tagged_model():
    catalog = {"small-2b": set(), "large-26b": {"reasoning"}}
    router = HeuristicRouter(catalog)
    model_id, reason = _resolve_routed_model(
        router, tier_hint="web", default_model_id="large-26b", default_reason="default",
    )
    assert model_id == "large-26b"
    assert reason == "default"


def test_resolve_routed_model_passthrough_when_no_hint():
    catalog = {"small-2b": {"web"}, "large-26b": {"reasoning"}}
    router = HeuristicRouter(catalog)
    model_id, reason = _resolve_routed_model(
        router, tier_hint=None, default_model_id="large-26b", default_reason="complex_verb",
    )
    assert model_id == "large-26b"
    assert reason == "complex_verb"
