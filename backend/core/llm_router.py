"""Per-request LLM router.

Phase B2 of the LLM swap. Heuristic two-tier picker: short, simple, single-turn
prompts route to the smaller chat model; long, code-bearing, multi-turn, or
complex-verb prompts route to the larger model.

The router holds the model catalog parsed from `infra/llama-swap-config.yaml`
on startup. Capability tags filter chat candidates (today, only `"embedding"`
is meaningful — it excludes the embedding model). Tier assignment is then a
fall-through rule list inside `_pick_tier`.

Module-level singleton because `stream_chat` is an async generator without
direct access to `app.state`. Call `init_router(catalog)` from the FastAPI
lifespan; `get_router()` raises if init was skipped.
"""
from __future__ import annotations

import pathlib
import re
from enum import Enum
from typing import Optional

import yaml


class Tier(Enum):
    SMALL = "small"
    LARGE = "large"


# Matches "4b", "E2B", "E4B", "1.5b" — extracts the numeric size hint from a
# model id. Used to sort chat models by size so the picker doesn't have to
# hardcode catalog membership.
_SIZE_HINT_RE = re.compile(r"(\d+(?:\.\d+)?)[bB]", re.IGNORECASE)


class HeuristicRouter:
    # Verbs that consistently mean "this is a non-trivial reasoning task."
    # Substring match in lowercased prompt — past tense ("compared") matches
    # too, which is fine; over-promotion is cheaper than under-promotion.
    COMPLEX_VERBS = {
        "compare", "analyze", "plan", "design", "evaluate",
        "synthesize", "summarize", "write a", "implement", "debug",
    }

    def __init__(self, catalog: dict[str, set[str]]):
        self.catalog = catalog
        self.small, self.large = self._partition_chat_models()

    def _partition_chat_models(self) -> tuple[str, str]:
        chat_models = [m for m, tags in self.catalog.items() if "embedding" not in tags]
        if len(chat_models) < 2:
            raise ValueError(
                f"Router needs at least 2 chat models (small + large); catalog has {len(chat_models)}"
            )
        sized: list[tuple[float, str]] = []
        for model_id in chat_models:
            match = _SIZE_HINT_RE.search(model_id)
            if not match:
                raise ValueError(
                    f"Chat model '{model_id}' has no parseable size hint (e.g., '4b', 'E4B'); router cannot tier it"
                )
            sized.append((float(match.group(1)), model_id))
        sized.sort()
        return sized[0][1], sized[-1][1]

    def pick(
        self,
        prompt: str,
        history: list[dict],
        attachments: list,
    ) -> tuple[str, Tier, str]:
        """Returns (model_id, tier, reason_keyword)."""
        tier, reason = self._pick_tier(prompt, history, attachments)
        model = self.large if tier is Tier.LARGE else self.small
        return model, tier, reason

    def _pick_tier(
        self,
        prompt: str,
        history: list[dict],
        attachments: list,
    ) -> tuple[Tier, str]:
        if attachments:
            return Tier.LARGE, "attachments"
        if len(prompt) > 500:
            return Tier.LARGE, "prompt_len>500"
        if "```" in prompt:
            return Tier.LARGE, "code_fence"
        lower = prompt.lower()
        if any(verb in lower for verb in self.COMPLEX_VERBS):
            return Tier.LARGE, "complex_verb"
        if len(history) > 8:
            return Tier.LARGE, "history>8"
        return Tier.SMALL, "default"


def build_catalog_from_yaml(path: str | pathlib.Path) -> dict[str, set[str]]:
    """Parses `infra/llama-swap-config.yaml` into {model_id -> set(tags)}.
    Missing or null `tags:` becomes an empty set."""
    with open(path) as f:
        cfg = yaml.safe_load(f) or {}
    return {
        model_id: set(model_cfg.get("tags") or [])
        for model_id, model_cfg in (cfg.get("models") or {}).items()
    }


_router_singleton: Optional[HeuristicRouter] = None


def init_router(catalog: dict[str, set[str]]) -> HeuristicRouter:
    """Called once from the FastAPI lifespan. Subsequent calls re-initialise
    (useful for tests AND for the admin router after a YAML mutation)."""
    global _router_singleton
    _router_singleton = HeuristicRouter(catalog)
    return _router_singleton


def reload_router_from_yaml(yaml_path: str | pathlib.Path) -> HeuristicRouter:
    """Re-read the catalog from disk and rebuild the singleton. Called by the
    admin router after a model is added/removed so subsequent stream_chat
    calls see the updated catalog without restarting the worker."""
    return init_router(build_catalog_from_yaml(yaml_path))


def get_router() -> HeuristicRouter:
    if _router_singleton is None:
        raise RuntimeError("llm_router not initialised — call init_router() in app startup")
    return _router_singleton
