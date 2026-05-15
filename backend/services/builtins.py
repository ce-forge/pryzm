"""Single source of truth for builtin workspace seeds.

Replaces the three parallel DEFAULT_* dicts in services/workspaces.py
(enabled_tools, display_names, colors). The seed migration and the reset
endpoint both read from here.

Adding a new builtin: append to BUILTIN_WORKSPACES. The reset endpoint
treats anything with is_builtin=True as resettable; a workspace's slug
must match a registry entry's slug for the reset to find canonical defaults.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BuiltinWorkspace:
    slug: str
    display_name: str
    color: str
    system_prompt_file: str   # filename in backend/core/prompts/
    enabled_tools: list[str]
    engine_config: dict


BUILTIN_WORKSPACES: list[BuiltinWorkspace] = [
    BuiltinWorkspace(
        slug="it_copilot",
        display_name="IT Copilot",
        color="blue",
        system_prompt_file="it_copilot.txt",
        enabled_tools=[
            "check_port", "dns_lookup", "execute_ping", "get_public_ip",
            "rename_chat_session", "search_knowledge_base", "ssl_inspect", "traceroute",
            "web_search",
        ],
        engine_config={"backend": "llama_cpp"},
    ),
    BuiltinWorkspace(
        slug="personal",
        display_name="Personal",
        color="orange",
        system_prompt_file="personal.txt",
        enabled_tools=["rename_chat_session", "search_knowledge_base", "web_search"],
        engine_config={"backend": "llama_cpp"},
    ),
]


def get_builtin(slug: str) -> BuiltinWorkspace | None:
    """Look up a builtin by slug; None if not registered."""
    for b in BUILTIN_WORKSPACES:
        if b.slug == slug:
            return b
    return None
