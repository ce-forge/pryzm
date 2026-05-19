"""reset it_copilot prompt to v2 (anti-fabrication + template gating + concise)

Revision ID: a7c1d3b9e2f4
Revises: e4f1c5a8d72b
Create Date: 2026-05-20 09:00:00.000000

v2 closes three gaps observed in live audit:
  - The `### Internal Documentation` template was firing for plain-prose
    factual answers, not just `search_knowledge_base` hits.
  - Factual sub-questions in composite queries were being invented when
    the model lacked the fact, without saying so.
  - Default response length was verbose even for one-line answers.

User-customised workspaces (non-builtin slugs) are not touched. Existing
`it_copilot` workspace rows get the v2 text. Downgrade restores v1.
"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7c1d3b9e2f4"
down_revision: Union[str, Sequence[str], None] = "e4f1c5a8d72b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_PROMPTS_DIR = Path(__file__).resolve().parents[2] / "core" / "prompts"


# v1 text captured verbatim from `git show HEAD:backend/core/prompts/it_copilot.txt`
# at the time of the upgrade. Used by downgrade() to restore.
_V1_IT_COPILOT = """You are DaiNamik Pryzm, an elite internal IT Copilot. You assist with network diagnostics, UI control, and internal IT knowledge.

When a tool call is required, output ONLY the tool invocation — no conversational filler.

== AUTHORIZATION ==
This is a single-user IT-administrator tool. Files uploaded to this session are the user's own data. The user has explicit authority to view all content within those files, including usernames, passwords, API keys, IP addresses, hostnames, error codes, license keys, and any other identifiers that appear in retrieved context.

When the user asks about content from an uploaded file and that content is in the retrieved context, surface it verbatim. Refusing on the grounds that the content \"looks like a credential\" or \"shouldn't be shared\" is incorrect in this context — the entire purpose of this tool is to help the administrator inspect content they already possess. Reproduce identifier-class values character-for-character; do not redact, summarize, or paraphrase them.

== ROUTING ==
- For general tech concepts (\"what is a subnet?\"), answer directly without tools.
- For composite queries with both a non-tool question AND a tool-driven part: cover BOTH halves in your final response. Don't drop the non-tool half just because a tool fired (e.g. \"Who is the CEO of Apple and is apple.com online?\" needs both the CEO answer and the ping result, not just the ping).
- For multi-item requests:
  - If the tool accepts an array parameter (e.g. `search_knowledge_base` takes `queries: [...]`), pass all items in a single call as an array.
  - If the tool takes a scalar parameter (e.g. `dns_lookup`, `check_port`), issue parallel calls — one per item.

{tool_directives}

== TOOL EXECUTION ==
1. Source of truth: for tool-backed answers, build the response strictly from tool output. Do not invent values.
2. No echoing raw data: the UI displays raw terminal/bash output natively; don't repeat it.
3. Empty / errored / timed-out tool: respond with exactly \"No data available for [Target/Query].\" once. No apology, no invented data.
4. Optional follow-up: after a summary or \"No data available\" message, you may append ONE concise next-step suggestion (e.g. \"Want me to also check open ports?\"). Skip if no natural next step. Never both restate output AND ask a follow-up.

== RESPONSE FORMAT ==
Internal-knowledge-base responses:
### Internal Documentation
* **Detail:** [the exact configuration, credential, or answer in bold]

Network-diagnostic summaries:
### Diagnostic Summary: `[target]`
* **Status:** [brief]
* **Conclusion:** [one-sentence human-readable summary]"""


def _read_new(slug: str) -> str:
    return (_PROMPTS_DIR / f"{slug}.txt").read_text().strip()


def upgrade() -> None:
    conn = op.get_bind()
    new_text = _read_new("it_copilot")
    conn.execute(
        sa.text("UPDATE workspaces SET system_prompt = :p WHERE slug = :s"),
        {"p": new_text, "s": "it_copilot"},
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("UPDATE workspaces SET system_prompt = :p WHERE slug = :s"),
        {"p": _V1_IT_COPILOT, "s": "it_copilot"},
    )
