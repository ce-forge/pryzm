"""add workspaces table

Revision ID: 58c8b7524030
Revises: 99647b177e47
Create Date: 2026-05-12

"""
import os
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "58c8b7524030"
down_revision: Union[str, Sequence[str], None] = "99647b177e47"
branch_labels = None
depends_on = None


# Hardcoded seed values so the migration is self-contained and doesn't depend
# on importing live runtime code that may evolve. If new tools are added later
# they won't be auto-enabled in built-ins — that's deliberate: tool enablement
# is config, not code, after this migration.
IT_COPILOT_TOOLS = [
    "check_port",
    "dns_lookup",
    "execute_ping",
    "get_public_ip",
    "rename_chat_session",
    "search_knowledge_base",
    "ssl_inspect",
    "traceroute",
]
PERSONAL_TOOLS = ["rename_chat_session", "search_knowledge_base"]

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROMPTS_DIR = os.path.join(BACKEND_DIR, "core", "prompts")


def _read_prompt(name: str) -> str:
    path = os.path.join(PROMPTS_DIR, f"{name}.txt")
    with open(path, "r") as f:
        return f.read().strip()


def upgrade() -> None:
    # 1. Create workspaces table.
    op.create_table(
        "workspaces",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("enabled_tools", JSONB(), nullable=False, server_default="[]"),
        sa.Column("preferred_model", sa.String(), nullable=True),
        sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("clock_timestamp()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_workspaces_id", "workspaces", ["id"])
    op.create_index("ix_workspaces_slug", "workspaces", ["slug"])

    # 2. Seed the two built-ins. UUIDs are deterministic-by-position so the
    # backfill below can reference them without a SELECT round-trip.
    it_id = str(uuid.uuid4())
    personal_id = str(uuid.uuid4())
    workspaces = sa.table(
        "workspaces",
        sa.column("id", sa.String),
        sa.column("slug", sa.String),
        sa.column("display_name", sa.String),
        sa.column("system_prompt", sa.Text),
        sa.column("enabled_tools", JSONB),
        sa.column("preferred_model", sa.String),
        sa.column("is_builtin", sa.Boolean),
    )
    op.bulk_insert(
        workspaces,
        [
            {
                "id": it_id,
                "slug": "it_copilot",
                "display_name": "IT Copilot",
                "system_prompt": _read_prompt("it_copilot"),
                "enabled_tools": IT_COPILOT_TOOLS,
                "preferred_model": None,
                "is_builtin": True,
            },
            {
                "id": personal_id,
                "slug": "personal",
                "display_name": "Personal",
                "system_prompt": _read_prompt("personal"),
                "enabled_tools": PERSONAL_TOOLS,
                "preferred_model": None,
                "is_builtin": True,
            },
        ],
    )

    # 3. Add workspace_id columns to sessions/folders/documents, nullable for
    # now; backfill below, then the second migration enforces NOT NULL + FK.
    op.add_column("sessions", sa.Column("workspace_id", sa.String(), nullable=True))
    op.add_column("folders", sa.Column("workspace_id", sa.String(), nullable=True))
    op.add_column("documents", sa.Column("workspace_id", sa.String(), nullable=True))

    op.create_index("ix_sessions_workspace_id", "sessions", ["workspace_id"])
    op.create_index("ix_folders_workspace_id", "folders", ["workspace_id"])
    op.create_index("ix_documents_workspace_id", "documents", ["workspace_id"])

    # 4. Backfill from the old string columns. Any row whose old string didn't
    # match a known built-in (shouldn't happen in practice) gets assigned to
    # it_copilot defensively so the NOT NULL constraint in the next migration
    # doesn't fail.
    op.execute(sa.text(f"UPDATE sessions SET workspace_id = '{it_id}' WHERE mode = 'it_copilot'"))
    op.execute(sa.text(f"UPDATE sessions SET workspace_id = '{personal_id}' WHERE mode = 'personal'"))
    op.execute(sa.text(f"UPDATE sessions SET workspace_id = '{it_id}' WHERE workspace_id IS NULL"))

    op.execute(sa.text(f"UPDATE folders SET workspace_id = '{it_id}' WHERE workspace = 'it_copilot'"))
    op.execute(sa.text(f"UPDATE folders SET workspace_id = '{personal_id}' WHERE workspace = 'personal'"))
    op.execute(sa.text(f"UPDATE folders SET workspace_id = '{it_id}' WHERE workspace_id IS NULL"))

    op.execute(sa.text(f"UPDATE documents SET workspace_id = '{it_id}' WHERE workspace = 'it_copilot'"))
    op.execute(sa.text(f"UPDATE documents SET workspace_id = '{personal_id}' WHERE workspace = 'personal'"))
    op.execute(sa.text(f"UPDATE documents SET workspace_id = '{it_id}' WHERE workspace_id IS NULL"))


def downgrade() -> None:
    op.drop_index("ix_documents_workspace_id", table_name="documents")
    op.drop_index("ix_folders_workspace_id", table_name="folders")
    op.drop_index("ix_sessions_workspace_id", table_name="sessions")
    op.drop_column("documents", "workspace_id")
    op.drop_column("folders", "workspace_id")
    op.drop_column("sessions", "workspace_id")
    op.drop_index("ix_workspaces_slug", table_name="workspaces")
    op.drop_index("ix_workspaces_id", table_name="workspaces")
    op.drop_table("workspaces")
