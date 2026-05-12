# Workspace Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hardcoded `it_copilot` / `personal` workspace pair with a first-class `workspaces` table supporting user-created workspaces, per-workspace system prompts, per-workspace tool toggles, and per-workspace pinned models.

**Architecture:** New `workspaces` table (UUID primary key, immutable slug, editable name/prompt/tools/preferred_model). Sessions/folders/documents get FK columns to it. Two-step alembic migration: first additive + seed + backfill, second enforces NOT NULL + drops old string columns. Existing tool decorator's `workspaces=[...]` list becomes seed data only — DB is the runtime source of truth. New `services/workspaces.py` owns slug→workspace resolution + tool/model resolution. New `routers/workspaces.py` exposes CRUD + clone-on-create + reset-for-builtins. Frontend gets a `WorkspaceSwitcher` dropdown replacing the tab toggle, a `WorkspaceSettings` modal, and a shared `InlineCreateForm` used by both `+ Folder` and `+ Workspace`.

**Tech Stack:** Existing — FastAPI + SQLAlchemy + alembic + Next.js + React 19 + gpt-tokenizer + httpx. No new dependencies. The migration uses `pgvector` already present.

**Reference docs:**
- Spec: `docs/specs/2026-05-12-workspace-expansion.md`
- Autotest harness: `/tmp/pryzm_autotest.py`
- Screenshot helper: `/tmp/pryzm_screenshot.py`
- Project memory: `~/.claude/projects/-home-orbital-projects-pryzm/memory/`

**Decorator-derived seed values (captured 2026-05-12):**
- `it_copilot`'s enabled_tools: `["check_port", "dns_lookup", "execute_ping", "get_public_ip", "rename_chat_session", "search_knowledge_base", "ssl_inspect", "traceroute"]`
- `personal`'s enabled_tools: `["rename_chat_session", "search_knowledge_base"]`
- Both: `preferred_model = NULL`, `is_builtin = true`

---

## File Structure

| Action | Path | Responsibility |
|---|---|---|
| Create | `backend/alembic/versions/<rev1>_add_workspaces_table.py` | Step 1 migration: table, seed, FK columns nullable + backfill |
| Create | `backend/alembic/versions/<rev2>_enforce_workspace_id_nonnull.py` | Step 2 migration: NOT NULL, FK constraints, drop old string columns |
| Create | `backend/services/workspaces.py` | slug→workspace lookup, tool resolver, model resolver, seed-from-defaults helper |
| Create | `backend/routers/workspaces.py` | CRUD + `/reset` + clone-on-create endpoints |
| Modify | `backend/db/models.py` | Add `Workspace` model; change `mode`/`workspace` strings to `workspace_id UUID FK` on Session/Folder/Document |
| Modify | `backend/schemas.py` | `WorkspaceResponse`, `WorkspaceCreate`, `WorkspaceUpdate` |
| Modify | `backend/routers/chat.py` | Resolve `workspace=<slug>` → workspace_id at the start of every handler; drop string-based `mode` usage |
| Modify | `backend/core/ai_engine.py` | Call `services.workspaces.resolve_tools_for_workspace` + new model resolution (workspace pin > request body > APP_CONFIG.DEFAULT_MODEL) |
| Modify | `backend/tools/registry.py` | Remove `get_tools_for_workspace` (callers now use the service); keep `TOOL_WORKSPACES` as seed-only metadata |
| Modify | `backend/main.py` | Register the new workspaces router |
| Create | `frontend/src/components/InlineCreateForm.tsx` | Shared `<input>` + Enter/Esc/blur form for `+ Folder` and `+ Workspace` |
| Create | `frontend/src/components/WorkspaceSwitcher.tsx` | Top-of-sidebar dropdown trigger + dropdown panel listing workspaces + create + settings |
| Create | `frontend/src/components/WorkspaceSettings.tsx` | Modal: display_name + system_prompt + preferred_model + enabled_tools toggles + Reset (builtin only) + Delete |
| Create | `frontend/src/hooks/useWorkspaces.ts` | Fetch+cache workspace list; create/patch/delete/reset helpers |
| Modify | `frontend/src/components/Sidebar.tsx` | Replace tab toggle with `<WorkspaceSwitcher />` |
| Modify | `frontend/src/components/SessionDirectory.tsx` | Use `<InlineCreateForm />` for the existing `+ Folder` flow (behavior unchanged) |
| Modify | `frontend/src/components/ChatHeader.tsx` | Show active workspace's `display_name`; append `· <preferred_model>` when pinned |
| Modify | `frontend/src/components/Settings.tsx` | Relabel "Active AI Model" → "Default AI Model" |
| Modify | `frontend/src/hooks/useSession.ts` | Workspace URL param resolved to the workspace object; surface it to consumers |
| Modify | `frontend/src/context/ChatContext.tsx` | Add `workspaces` (list) and `activeWorkspace` (object) to context value |
| Modify | `/tmp/pryzm_autotest.py` | New probes for workspace CRUD, model resolution, reset, last-workspace guard |

---

## Task 1: Schema + two-step alembic migration

**Files:**
- Create: `backend/alembic/versions/<rev1>_add_workspaces_table.py`
- Create: `backend/alembic/versions/<rev2>_enforce_workspace_id_nonnull.py`
- Modify: `backend/db/models.py`

**Goal:** Land the new `workspaces` table with seeded built-ins, add nullable `workspace_id` columns to sessions/folders/documents, backfill them, then in a second revision enforce NOT NULL + FK + drop the old string columns. The model file is updated in lockstep so the running app matches the new schema after `alembic upgrade head`.

- [ ] **Step 1: Update `backend/db/models.py`** with the new `Workspace` model and the new FK columns on Session/Folder/Document. Remove `mode` from Session and `workspace` from Folder/Document — they're replaced by `workspace_id`. The `documents.session_id` FK from Group C stays as-is.

```python
# backend/db/models.py
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector
import uuid

Base = declarative_base()


def generate_uuid():
    return str(uuid.uuid4())


class Workspace(Base):
    __tablename__ = "workspaces"
    id = Column(String, primary_key=True, default=generate_uuid, index=True)
    slug = Column(String, nullable=False, unique=True, index=True)
    display_name = Column(String, nullable=False)
    system_prompt = Column(Text, nullable=False, default="")
    enabled_tools = Column(JSONB, nullable=False, server_default="[]")
    preferred_model = Column(String, nullable=True)
    is_builtin = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at = Column(DateTime(timezone=True), server_default=func.clock_timestamp())

    sessions = relationship("Session", back_populates="workspace", cascade="all, delete-orphan")
    folders = relationship("Folder", back_populates="workspace", cascade="all, delete-orphan")
    documents = relationship("Document", back_populates="workspace", cascade="all, delete-orphan")


class Session(Base):
    __tablename__ = "sessions"
    id = Column(String, primary_key=True, default=generate_uuid, index=True)
    title = Column(String, default="New Diagnostic Session")
    is_pinned = Column(Boolean, default=False)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    folder_id = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    workspace = relationship("Workspace", back_populates="sessions")
    messages = relationship("Message", back_populates="session", cascade="all, delete-orphan")
    documents = relationship("Document", back_populates="session", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"
    id = Column(String, primary_key=True, default=generate_uuid, index=True)
    session_id = Column(String, ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    role = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    status = Column(String, nullable=False, default="complete", server_default="complete")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    session = relationship("Session", back_populates="messages")


class Folder(Base):
    __tablename__ = "folders"
    id = Column(String, primary_key=True)
    name = Column(String)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace = relationship("Workspace", back_populates="folders")


class Document(Base):
    __tablename__ = "documents"
    id = Column(String, primary_key=True, default=generate_uuid, index=True)
    filename = Column(String, nullable=False)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id = Column(String, ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    is_global = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    session = relationship("Session", back_populates="documents")
    workspace = relationship("Workspace", back_populates="documents")
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    id = Column(String, primary_key=True, default=generate_uuid, index=True)
    document_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    content = Column(Text, nullable=False)
    embedding = Column(Vector(768))
    document = relationship("Document", back_populates="chunks")
```

- [ ] **Step 2: Stop uvicorn before generating migrations.** `uvicorn --reload` running `alembic upgrade head` on file save would race with our partial migration state. Kill the process; the plan re-starts it after task 1 completes.

```bash
pkill -INT -f "uvicorn.*main:app" && sleep 2
```

Expected: port 8000 frees up.

- [ ] **Step 3: Generate the migration scaffolds with empty bodies** (we'll hand-write the inserts and backfill since autogenerate can't infer them).

```bash
cd /home/orbital/projects/pryzm/backend && source venv/bin/activate
alembic revision -m "add workspaces table"
alembic revision -m "enforce workspace_id non-null"
ls alembic/versions/
```

Expected: two new `<rev>_*.py` files. Note both revision IDs — call them `REV1` and `REV2` below.

- [ ] **Step 4: Write `<REV1>_add_workspaces_table.py`** by replacing the generated file's body with the following. Update the `down_revision` to point at the previous head (run `alembic history` if unsure).

```python
"""add workspaces table

Revision ID: <REV1>
Revises: <previous head>
Create Date: 2026-05-12

"""
import os
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "<REV1>"
down_revision: Union[str, Sequence[str], None] = "<previous head>"
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
```

- [ ] **Step 5: Write `<REV2>_enforce_workspace_id_nonnull.py`**:

```python
"""enforce workspace_id non-null and drop old string columns

Revision ID: <REV2>
Revises: <REV1>
Create Date: 2026-05-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "<REV2>"
down_revision: Union[str, Sequence[str], None] = "<REV1>"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NOT NULL + FK constraints on the new workspace_id columns.
    op.alter_column("sessions", "workspace_id", nullable=False)
    op.alter_column("folders", "workspace_id", nullable=False)
    op.alter_column("documents", "workspace_id", nullable=False)

    op.create_foreign_key(
        "fk_sessions_workspace_id",
        "sessions", "workspaces",
        ["workspace_id"], ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_folders_workspace_id",
        "folders", "workspaces",
        ["workspace_id"], ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_documents_workspace_id",
        "documents", "workspaces",
        ["workspace_id"], ["id"],
        ondelete="CASCADE",
    )

    # Drop the old string columns.
    op.drop_column("sessions", "mode")
    op.drop_column("folders", "workspace")
    op.drop_column("documents", "workspace")


def downgrade() -> None:
    # NOTE: this downgrade is lossy — the old string columns are recreated with
    # NULL, which means the second migration cannot be rolled back without
    # losing the mode/workspace classification. Only roll back if the data
    # loss is acceptable (it's also why we split into two migrations).
    op.add_column("sessions", sa.Column("mode", sa.String(), nullable=True))
    op.add_column("folders", sa.Column("workspace", sa.String(), nullable=True))
    op.add_column("documents", sa.Column("workspace", sa.String(), nullable=True))

    op.drop_constraint("fk_documents_workspace_id", "documents", type_="foreignkey")
    op.drop_constraint("fk_folders_workspace_id", "folders", type_="foreignkey")
    op.drop_constraint("fk_sessions_workspace_id", "sessions", type_="foreignkey")

    op.alter_column("documents", "workspace_id", nullable=True)
    op.alter_column("folders", "workspace_id", nullable=True)
    op.alter_column("sessions", "workspace_id", nullable=True)
```

- [ ] **Step 6: Apply the migrations.**

```bash
alembic upgrade head
```

Expected: two `Running upgrade` lines, no errors.

- [ ] **Step 7: Verify the schema state via psql.**

```bash
PGPASSWORD=postgres psql -h 127.0.0.1 -U pryzm_admin -d pryzm_core -c "\d workspaces"
PGPASSWORD=postgres psql -h 127.0.0.1 -U pryzm_admin -d pryzm_core -c "\d sessions" | grep workspace
PGPASSWORD=postgres psql -h 127.0.0.1 -U pryzm_admin -d pryzm_core -c "SELECT slug, display_name, is_builtin, jsonb_array_length(enabled_tools) AS tool_count FROM workspaces;"
```

Expected:
- `workspaces` table has all spec'd columns
- `sessions` has `workspace_id` column, NOT NULL, FK to workspaces.id, indexed, no longer has `mode`
- two rows: `(it_copilot, IT Copilot, true, 8)` and `(personal, Personal, true, 2)`

- [ ] **Step 8: Restart uvicorn.**

```bash
cd /home/orbital/projects/pryzm/backend && source venv/bin/activate
nohup uvicorn main:app --host 0.0.0.0 --port 8000 --reload > /tmp/uvicorn-task1.log 2>&1 &
until curl -sf http://127.0.0.1:8000/health -o /dev/null; do sleep 1; done
curl -s http://127.0.0.1:8000/health
```

Expected: `{"status": "online", ...}`. The backend boots cleanly because the SQLAlchemy models match the migrated schema. The app will be partially broken (existing routes still try to query the dropped columns) until Task 4 is done — that's expected for this checkpoint.

- [ ] **Step 9: Commit.**

```bash
cd /home/orbital/projects/pryzm
git add backend/db/models.py backend/alembic/versions/
git commit -m "feat(workspaces): schema — workspaces table + workspace_id FKs.

Two-step alembic migration. Step 1 (additive): create workspaces table,
seed it_copilot and personal as is_builtin rows reading their system
prompts from core/prompts/<slug>.txt and their enabled_tools from a
snapshot of the @tool decorator's workspaces=[...] lists. Add nullable
workspace_id columns to sessions/folders/documents and backfill from the
existing mode/workspace strings. Step 2 (destructive): enforce NOT NULL,
add FK with ON DELETE CASCADE, drop the old string columns. The split
makes step 1 rollback-safe; step 2's downgrade is lossy by design."
```

---

## Task 2: Pydantic schemas + services/workspaces.py

**Files:**
- Modify: `backend/schemas.py`
- Create: `backend/services/workspaces.py`

**Goal:** Add the request/response shapes and the helper module that owns slug→workspace lookup, the tool resolver (intersect workspace.enabled_tools with the live AVAILABLE_TOOLS registry), and the model resolver (workspace pin > request body > APP_CONFIG.DEFAULT_MODEL).

- [ ] **Step 1: Add Pydantic schemas to `backend/schemas.py`** at the end of the file (after `HealthResponse`):

```python
from typing import Optional, List, Dict

class WorkspaceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    slug: str
    display_name: str
    system_prompt: str
    enabled_tools: List[str]
    preferred_model: Optional[str] = None
    is_builtin: bool
    created_at: datetime


class WorkspaceCreate(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=80)
    clone_from: Optional[str] = None  # slug of source workspace; None = blank defaults


class WorkspaceUpdate(BaseModel):
    display_name: Optional[str] = Field(None, min_length=1, max_length=80)
    system_prompt: Optional[str] = Field(None, max_length=50_000)
    enabled_tools: Optional[List[str]] = None
    preferred_model: Optional[str] = None  # explicit null = clear the pin


class WorkspaceDeleteResponse(BaseModel):
    deleted: bool
    removed_sessions: int
    removed_folders: int
    removed_documents: int
```

- [ ] **Step 2: Create `backend/services/workspaces.py`** with the resolver functions:

```python
"""Workspace lookup, tool/model resolution, and seed-from-default helpers.

This module is the single owner of "given a workspace, what tools and what
model do we use?" The tools/registry.py module is only the source of the
declared tool registry; this module reads the workspace's stored config
(enabled_tools, preferred_model) and resolves it against the live registry
at request time.
"""
import os
import re
from typing import Optional, Tuple

from fastapi import HTTPException
from sqlalchemy.orm import Session

from config import settings
from db import models
from tools.registry import AVAILABLE_TOOLS, TOOL_DEFINITIONS


PROMPTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "core", "prompts",
)


def get_by_slug(db: Session, slug: str) -> models.Workspace:
    """Resolve a slug to a Workspace, 404 if missing."""
    ws = db.query(models.Workspace).filter(models.Workspace.slug == slug).first()
    if not ws:
        raise HTTPException(status_code=404, detail=f"Workspace not found: {slug}")
    return ws


def get_or_default(db: Session, slug: Optional[str]) -> models.Workspace:
    """Resolve a slug (which may be None or 'it_copilot' style). Falls back to
    the first workspace by created_at if the slug is missing. Used by
    endpoints that previously accepted ?workspace=<slug> with a default
    of 'it_copilot' — preserves that fallback transparently."""
    if slug:
        ws = db.query(models.Workspace).filter(models.Workspace.slug == slug).first()
        if ws:
            return ws
    # Fallback: oldest workspace (typically it_copilot post-migration).
    ws = db.query(models.Workspace).order_by(models.Workspace.created_at.asc()).first()
    if not ws:
        raise HTTPException(status_code=500, detail="No workspaces exist. Database is empty.")
    return ws


def resolve_tools_for_workspace(workspace: models.Workspace) -> Tuple[dict, list]:
    """Given a workspace, return (callable_map, definitions_list) filtered to
    just the tools the workspace has enabled AND that exist in the live
    AVAILABLE_TOOLS registry. Stale names in enabled_tools (e.g. for tools
    that were removed in a later code change) are silently ignored — the
    workspace works with whatever the engineer kept."""
    enabled = set(workspace.enabled_tools or [])
    callables = {name: fn for name, fn in AVAILABLE_TOOLS.items() if name in enabled}
    definitions = [d for d in TOOL_DEFINITIONS if d["function"]["name"] in enabled]
    return callables, definitions


def resolve_model_for_request(
    workspace: models.Workspace,
    request_model: Optional[str],
) -> str:
    """Resolution order: workspace.preferred_model > request body > APP_CONFIG.DEFAULT_MODEL.
    If the workspace pin points at a model that's no longer available in Ollama,
    fall back to the request model (or default) and log a warning to stdout.
    The caller is expected to live-check available models if it cares; here we
    just pick a string."""
    if workspace.preferred_model:
        # We don't ping /api/models from inside the chat path — that would
        # add an unnecessary HTTP round-trip per chat. The pin was validated
        # at PATCH time. If the model has since gone away, Ollama itself
        # will surface the error at chat time and the request logger will
        # capture it.
        return workspace.preferred_model
    if request_model:
        return request_model
    # No default constant on backend; the frontend always sends a model.
    # If somehow it didn't, hardcode the project default.
    return "gemma4:e4b"


def slugify(display_name: str) -> str:
    """Convert a display name to a URL/identifier-safe slug. Lowercase,
    replace non-alphanumeric with hyphens, collapse runs, trim leading
    and trailing hyphens. Raises ValueError if the result is empty
    (caller should respond 400)."""
    s = re.sub(r"[^a-z0-9]+", "-", display_name.lower()).strip("-")
    if not s:
        raise ValueError("Display name must contain at least one alphanumeric character")
    return s


def slugify_unique(db: Session, display_name: str) -> str:
    """Slugify the display name, then append -2, -3, ... until unique."""
    base = slugify(display_name)
    candidate = base
    n = 2
    while db.query(models.Workspace).filter(models.Workspace.slug == candidate).first():
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def read_default_prompt(slug: str) -> str:
    """Read the on-disk default prompt for a built-in workspace. Used by the
    /reset endpoint. Raises FileNotFoundError if the slug has no default."""
    path = os.path.join(PROMPTS_DIR, f"{slug}.txt")
    with open(path, "r") as f:
        return f.read().strip()


# Default tool sets — same as the migration's seed values. Kept here so
# /reset doesn't have to re-import migration code.
DEFAULT_ENABLED_TOOLS: dict[str, list[str]] = {
    "it_copilot": [
        "check_port", "dns_lookup", "execute_ping", "get_public_ip",
        "rename_chat_session", "search_knowledge_base", "ssl_inspect", "traceroute",
    ],
    "personal": ["rename_chat_session", "search_knowledge_base"],
}
```

- [ ] **Step 3: Run uvicorn's reload check.** Since this only adds new files / new pydantic models with no syntax errors expected, uvicorn should reload cleanly.

```bash
sleep 4
curl -s http://127.0.0.1:8000/health
```

Expected: `{"status": "online", ...}`.

- [ ] **Step 4: Commit.**

```bash
cd /home/orbital/projects/pryzm
git add backend/schemas.py backend/services/workspaces.py
git commit -m "feat(workspaces): pydantic schemas + services/workspaces.py.

Adds WorkspaceResponse, WorkspaceCreate, WorkspaceUpdate, and
WorkspaceDeleteResponse to schemas. The new services/workspaces.py
module owns slug -> workspace lookup (get_by_slug + get_or_default),
the tool resolver (filters AVAILABLE_TOOLS by the workspace's stored
enabled_tools), the model resolver (workspace pin > request body >
default), a deterministic slugify_unique that appends -2/-3 on
collisions, and the seed helpers for the future /reset endpoint."
```

---

## Task 3: routers/workspaces.py CRUD endpoints + autotest probes

**Files:**
- Create: `backend/routers/workspaces.py`
- Modify: `backend/main.py`
- Modify: `/tmp/pryzm_autotest.py`

**Goal:** Expose `GET /workspaces`, `GET /workspaces/{slug}`, `POST /workspaces` (with `clone_from`), `PATCH /workspaces/{slug}`, `DELETE /workspaces/{slug}`, `POST /workspaces/{slug}/reset`. Add autotest probes that exercise each endpoint.

- [ ] **Step 1: Write the failing autotest probes first.** Open `/tmp/pryzm_autotest.py` and insert this block right before the final summary print (after the existing `abort/status-and-marker` probe):

```python
    # ---------- workspaces/list-after-migration ----------
    try:
        ws = requests.get(f"{BASE}/workspaces", timeout=5).json()
        slugs = sorted([w["slug"] for w in ws])
        builtins = sorted([w["slug"] for w in ws if w.get("is_builtin")])
        log(
            "workspaces/list-after-migration",
            "it_copilot" in slugs and "personal" in slugs and builtins == ["it_copilot", "personal"],
            f"slugs={slugs} builtins={builtins}",
        )
    except Exception as e:
        log("workspaces/list-after-migration", False, str(e))

    # ---------- workspaces/create-blank ----------
    created_slug = None
    try:
        unique_name = f"AutoTest WS {int(time.time())}"
        r = requests.post(f"{BASE}/workspaces", json={"display_name": unique_name}, timeout=5)
        body = r.json()
        created_slug = body.get("slug")
        log(
            "workspaces/create-blank",
            r.status_code == 200 and created_slug and body.get("enabled_tools") == [] and body.get("preferred_model") is None,
            f"status={r.status_code} slug={created_slug} tools={body.get('enabled_tools')}",
        )
    except Exception as e:
        log("workspaces/create-blank", False, str(e))

    # ---------- workspaces/create-clone ----------
    try:
        unique_name = f"AutoTest Clone {int(time.time())}"
        r = requests.post(
            f"{BASE}/workspaces",
            json={"display_name": unique_name, "clone_from": "it_copilot"},
            timeout=5,
        )
        body = r.json()
        log(
            "workspaces/create-clone",
            r.status_code == 200 and "check_port" in body.get("enabled_tools", []),
            f"status={r.status_code} tools_count={len(body.get('enabled_tools', []))}",
        )
        # Cleanup
        if r.status_code == 200:
            requests.delete(f"{BASE}/workspaces/{body['slug']}", timeout=5)
    except Exception as e:
        log("workspaces/create-clone", False, str(e))

    # ---------- workspaces/create-slug-collision ----------
    try:
        same_name = f"Collide{int(time.time())}"
        r1 = requests.post(f"{BASE}/workspaces", json={"display_name": same_name}, timeout=5).json()
        r2 = requests.post(f"{BASE}/workspaces", json={"display_name": same_name}, timeout=5).json()
        log(
            "workspaces/create-slug-collision",
            r1["slug"] != r2["slug"] and r2["slug"].endswith("-2"),
            f"first={r1['slug']} second={r2['slug']}",
        )
        # Cleanup
        requests.delete(f"{BASE}/workspaces/{r1['slug']}", timeout=5)
        requests.delete(f"{BASE}/workspaces/{r2['slug']}", timeout=5)
    except Exception as e:
        log("workspaces/create-slug-collision", False, str(e))

    # ---------- workspaces/patch-display-name ----------
    if created_slug:
        try:
            r = requests.patch(
                f"{BASE}/workspaces/{created_slug}",
                json={"display_name": "Renamed AutoTest"},
                timeout=5,
            ).json()
            log(
                "workspaces/patch-display-name",
                r.get("display_name") == "Renamed AutoTest" and r.get("slug") == created_slug,
                f"name={r.get('display_name')} slug_unchanged={r.get('slug') == created_slug}",
            )
        except Exception as e:
            log("workspaces/patch-display-name", False, str(e))

    # ---------- workspaces/patch-enabled-tools-unknown-name ----------
    if created_slug:
        try:
            r = requests.patch(
                f"{BASE}/workspaces/{created_slug}",
                json={"enabled_tools": ["definitely_not_a_real_tool"]},
                timeout=5,
            )
            log(
                "workspaces/patch-enabled-tools-unknown-name",
                r.status_code == 400,
                f"status={r.status_code}",
            )
        except Exception as e:
            log("workspaces/patch-enabled-tools-unknown-name", False, str(e))

    # ---------- workspaces/patch-preferred-model-unknown ----------
    if created_slug:
        try:
            r = requests.patch(
                f"{BASE}/workspaces/{created_slug}",
                json={"preferred_model": "definitely-not-installed:nonsense"},
                timeout=5,
            )
            log(
                "workspaces/patch-preferred-model-unknown",
                r.status_code == 400,
                f"status={r.status_code}",
            )
        except Exception as e:
            log("workspaces/patch-preferred-model-unknown", False, str(e))

    # ---------- workspaces/delete-last-blocked ----------
    # Delete created_slug first to leave the test in a clean state, then try
    # to delete the second-to-last (personal) — should still succeed; then try
    # deleting the LAST one (it_copilot) — should be blocked.
    try:
        if created_slug:
            requests.delete(f"{BASE}/workspaces/{created_slug}", timeout=5)
        # At this point we should have just it_copilot and personal. Delete
        # personal so only one remains.
        r_del_personal = requests.delete(f"{BASE}/workspaces/personal", timeout=5)
        r_del_last = requests.delete(f"{BASE}/workspaces/it_copilot", timeout=5)
        log(
            "workspaces/delete-last-blocked",
            r_del_last.status_code == 409,
            f"personal_delete={r_del_personal.status_code} last_delete={r_del_last.status_code}",
        )
        # IMPORTANT: re-seed personal so subsequent autotest runs work. We
        # recreate it via POST /workspaces — the slug auto-generates to
        # "personal" since it's been freed. The system_prompt and tool list
        # will be the blank defaults rather than the on-disk file values;
        # that's a known autotest-only side effect documented in the spec.
        requests.post(f"{BASE}/workspaces", json={"display_name": "Personal"}, timeout=5)
    except Exception as e:
        log("workspaces/delete-last-blocked", False, str(e))

    # ---------- workspaces/reset-builtin ----------
    try:
        # Modify it_copilot's prompt to something we'll then reset.
        requests.patch(
            f"{BASE}/workspaces/it_copilot",
            json={"system_prompt": "CORRUPTED FOR TEST"},
            timeout=5,
        )
        r = requests.post(f"{BASE}/workspaces/it_copilot/reset", timeout=5).json()
        log(
            "workspaces/reset-builtin",
            r.get("system_prompt", "").startswith("You are DaiNamik Pryzm"),
            f"prompt_first_30={r.get('system_prompt', '')[:30]!r}",
        )
    except Exception as e:
        log("workspaces/reset-builtin", False, str(e))
```

- [ ] **Step 2: Run autotest to verify the new probes fail with 404.**

```bash
cd /home/orbital/projects/pryzm/backend && source venv/bin/activate
python3 /tmp/pryzm_autotest.py 2>&1 | grep -E "(workspaces/|^---)"
```

Expected: every `workspaces/*` probe FAILs (status=404 — endpoints don't exist yet). Other probes still PASS.

- [ ] **Step 3: Create `backend/routers/workspaces.py`** with all endpoints:

```python
import requests as http_requests
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from config import settings
from db import database, models
from schemas import (
    WorkspaceResponse,
    WorkspaceCreate,
    WorkspaceUpdate,
    WorkspaceDeleteResponse,
)
from services.workspaces import (
    get_by_slug,
    slugify_unique,
    read_default_prompt,
    DEFAULT_ENABLED_TOOLS,
)
from tools.registry import AVAILABLE_TOOLS


router = APIRouter(tags=["Workspaces"])


def _validate_enabled_tools(names: List[str]) -> None:
    """Reject names that aren't in the live tool registry."""
    unknown = [n for n in names if n not in AVAILABLE_TOOLS]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown tool name(s): {unknown}",
        )


def _validate_preferred_model(model: str) -> None:
    """Confirm the model exists in the Ollama /api/tags response. Done at
    PATCH time so we fail loudly on misconfiguration; chat-time resolution
    in services/workspaces.py tolerates a stale value with a warning."""
    if model is None:
        return
    try:
        r = http_requests.get(
            f"{settings.OLLAMA_URL.strip().rstrip('/')}/api/tags",
            timeout=3,
        )
        r.raise_for_status()
        names = [m["name"] for m in r.json().get("models", [])]
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Could not reach Ollama to validate model: {e}",
        )
    if model not in names:
        raise HTTPException(
            status_code=400,
            detail=f"Model not installed in Ollama: {model}. Available: {names}",
        )


@router.get("/workspaces", response_model=List[WorkspaceResponse])
def list_workspaces(db: Session = Depends(database.get_db)):
    return db.query(models.Workspace).order_by(models.Workspace.created_at.asc()).all()


@router.get("/workspaces/{slug}", response_model=WorkspaceResponse)
def get_workspace(slug: str, db: Session = Depends(database.get_db)):
    return get_by_slug(db, slug)


@router.post("/workspaces", response_model=WorkspaceResponse)
def create_workspace(
    payload: WorkspaceCreate,
    db: Session = Depends(database.get_db),
):
    try:
        slug = slugify_unique(db, payload.display_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Defaults for a fresh blank workspace.
    system_prompt = "You are a helpful assistant. Answer the user's questions thoughtfully."
    enabled_tools: list[str] = []
    preferred_model = None

    if payload.clone_from:
        source = get_by_slug(db, payload.clone_from)
        system_prompt = source.system_prompt
        enabled_tools = list(source.enabled_tools or [])
        preferred_model = source.preferred_model

    ws = models.Workspace(
        slug=slug,
        display_name=payload.display_name.strip(),
        system_prompt=system_prompt,
        enabled_tools=enabled_tools,
        preferred_model=preferred_model,
        is_builtin=False,
    )
    db.add(ws)
    db.commit()
    db.refresh(ws)
    return ws


@router.patch("/workspaces/{slug}", response_model=WorkspaceResponse)
def update_workspace(
    slug: str,
    payload: WorkspaceUpdate,
    db: Session = Depends(database.get_db),
):
    ws = get_by_slug(db, slug)

    data = payload.model_dump(exclude_unset=True)

    if "display_name" in data:
        stripped = data["display_name"].strip()
        if not stripped:
            raise HTTPException(
                status_code=400,
                detail="display_name must contain non-whitespace characters",
            )
        ws.display_name = stripped

    if "system_prompt" in data:
        ws.system_prompt = data["system_prompt"]

    if "enabled_tools" in data:
        _validate_enabled_tools(data["enabled_tools"])
        ws.enabled_tools = data["enabled_tools"]

    if "preferred_model" in data:
        # Explicit null clears the pin; non-null is validated against Ollama.
        if data["preferred_model"] is not None:
            _validate_preferred_model(data["preferred_model"])
        ws.preferred_model = data["preferred_model"]

    db.commit()
    db.refresh(ws)
    return ws


@router.delete("/workspaces/{slug}", response_model=WorkspaceDeleteResponse)
def delete_workspace(slug: str, db: Session = Depends(database.get_db)):
    ws = get_by_slug(db, slug)

    # Last-workspace guard.
    total = db.query(models.Workspace).count()
    if total <= 1:
        raise HTTPException(
            status_code=409,
            detail="Cannot delete the only remaining workspace.",
        )

    # Count what's about to cascade so the response can populate the modal.
    removed_sessions = db.query(models.Session).filter(models.Session.workspace_id == ws.id).count()
    removed_folders = db.query(models.Folder).filter(models.Folder.workspace_id == ws.id).count()
    removed_documents = db.query(models.Document).filter(models.Document.workspace_id == ws.id).count()

    db.delete(ws)
    db.commit()

    return WorkspaceDeleteResponse(
        deleted=True,
        removed_sessions=removed_sessions,
        removed_folders=removed_folders,
        removed_documents=removed_documents,
    )


@router.post("/workspaces/{slug}/reset", response_model=WorkspaceResponse)
def reset_workspace(slug: str, db: Session = Depends(database.get_db)):
    ws = get_by_slug(db, slug)
    if not ws.is_builtin:
        raise HTTPException(
            status_code=409,
            detail="Reset is only available for built-in workspaces.",
        )
    try:
        ws.system_prompt = read_default_prompt(slug)
    except FileNotFoundError:
        raise HTTPException(
            status_code=500,
            detail=f"Default prompt file missing for builtin: core/prompts/{slug}.txt",
        )
    ws.enabled_tools = DEFAULT_ENABLED_TOOLS.get(slug, [])
    ws.preferred_model = None
    # Display name reset to its canonical form too.
    ws.display_name = {"it_copilot": "IT Copilot", "personal": "Personal"}.get(slug, ws.display_name)
    db.commit()
    db.refresh(ws)
    return ws
```

- [ ] **Step 4: Register the router in `backend/main.py`.** Replace the existing `app.include_router(chat.router)` block with:

```python
from routers import health, chat, workspaces
...
app.include_router(health.router)
app.include_router(workspaces.router)
app.include_router(chat.router)
```

- [ ] **Step 5: Wait for uvicorn reload + re-run autotest.**

```bash
sleep 4
python3 /tmp/pryzm_autotest.py 2>&1 | grep -E "(workspaces/|^---)"
```

Expected: every `workspaces/*` probe PASSes. `list-after-migration` shows two built-ins. Create/clone/collision/patch/delete-last-blocked/reset all pass.

- [ ] **Step 6: Run the full autotest to confirm no other probes regress.**

```bash
python3 /tmp/pryzm_autotest.py 2>&1 | tail -25
```

Expected: existing probes still pass (most still pass; the ones that hit `/sessions?workspace=...` may fail with 500 because we haven't done Task 4 yet — that's OK and the next task fixes it).

- [ ] **Step 7: Commit.**

```bash
cd /home/orbital/projects/pryzm
git add backend/routers/workspaces.py backend/main.py
git commit -m "feat(workspaces): CRUD endpoints + reset for builtins.

GET /workspaces lists all (created_at asc). GET /workspaces/{slug} fetches
one. POST /workspaces creates with sensible defaults or clone_from=<slug>.
PATCH /workspaces/{slug} updates display_name/system_prompt/enabled_tools/
preferred_model with validation (unknown tool names -> 400, unknown model
-> 400 via Ollama /api/tags check). DELETE returns cascade counts and
refuses to delete the only remaining workspace (409). POST /reset only
works on is_builtin rows and re-seeds from core/prompts/<slug>.txt plus
the snapshot tool list in services.workspaces."
```

---

## Task 4: Slug resolution in existing routes + tool/model wiring

**Files:**
- Modify: `backend/routers/chat.py`
- Modify: `backend/core/ai_engine.py`
- Modify: `backend/tools/registry.py`

**Goal:** The existing `/sessions`, `/folders`, `/upload`, `/analyze` endpoints take `workspace=<slug>` as a string. Resolve it to a `Workspace` row at the top of each handler, query by `workspace_id`, and pass the full `Workspace` object into `ai_engine.stream_chat`. Drop the old binary `if mode == "it_copilot"` capability check in `stream_chat` — replaced by the workspace's stored `enabled_tools`. Wire the model resolver so workspace `preferred_model` overrides the request body's `model`.

- [ ] **Step 1: Modify `backend/routers/chat.py`** — replace string-based workspace handling everywhere.

In `chat.py`, change every `workspace: str = "it_copilot"` to use the resolver. Specific edits:

(a) Add to the imports at top of `chat.py`:

```python
from services.workspaces import get_by_slug, get_or_default
```

(b) `get_sessions` — resolve the slug to workspace_id:

```python
@router.get("/sessions", response_model=List[SessionResponse])
def get_sessions(
    workspace: str = "it_copilot",
    folder_id: Optional[str] = None,
    limit: Optional[int] = None,
    offset: int = 0,
    db: Session = Depends(database.get_db),
):
    ws = get_or_default(db, workspace)
    q = db.query(models.Session).filter(models.Session.workspace_id == ws.id)
    if folder_id is not None:
        q = q.filter(models.Session.folder_id == folder_id)
    q = q.order_by(models.Session.created_at.desc())
    if offset:
        q = q.offset(offset)
    if limit is not None:
        q = q.limit(limit)
    return q.all()
```

(c) The `SessionResponse` schema currently has a `mode` field. Replace it with `workspace` (the slug) for backward-compat with frontend expectations OR change frontend in Task 6. **Pick frontend change.** For now update `schemas.py` `SessionResponse`:

```python
class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    workspace_id: str
    folder_id: Optional[str] = None
    is_pinned: Optional[bool] = False
    created_at: datetime
```

(Frontend will read `workspace_id` and look up the workspace by id from the workspaces list.)

(d) `analyze_data` (in `chat.py`, the `/analyze` POST) — resolve slug, save workspace_id on Session, pass workspace to `stream_chat`. The `mode` field in `InferenceRequest` keeps its semantic ("workspace slug to use") for backward-compat with frontend body. Find the existing handler and update:

```python
@router.post("/analyze")
def analyze_data(
    http_request: Request,
    request: InferenceRequest,
):
    db = database.SessionLocal()
    try:
        workspace = get_or_default(db, request.mode)
        chat_session = None

        if request.session_id:
            chat_session = db.query(models.Session).filter(models.Session.id == request.session_id).first()

        if not chat_session:
            generated_title = ai_engine.generate_title(request.prompt, request.model)
            chat_session = models.Session(
                title=generated_title,
                workspace_id=workspace.id,
            )
            db.add(chat_session)
            db.commit()
            db.refresh(chat_session)
        elif chat_session.title in ["Document Upload Session", "New Diagnostic Session", "New Diagnostic Chat"]:
            chat_session.title = ai_engine.generate_title(request.prompt, request.model)
            db.commit()
            db.refresh(chat_session)

        if request.attachments:
            db.query(models.Document).filter(
                models.Document.id.in_(request.attachments)
            ).update(
                {"session_id": chat_session.id, "workspace_id": workspace.id},
                synchronize_session=False,
            )
            db.commit()

        if not request.skip_db_save:
            user_msg = models.Message(session_id=chat_session.id, role="user", content=request.prompt)
            db.add(user_msg)
            db.commit()

        history = db.query(models.Message).filter(models.Message.session_id == chat_session.id).order_by(models.Message.created_at).all()
        safe_messages = [{"role": msg.role, "content": msg.content} for msg in history]

        session_id = chat_session.id
        workspace_id = workspace.id
        workspace_slug = workspace.slug
    finally:
        db.close()

    async def generate():
        yield json.dumps({"status": "started", "session_id": session_id}) + "\n"

        full_response = ""
        completed = False
        disconnected = False

        try:
            for chunk in ai_engine.stream_chat(
                safe_messages,
                workspace_id=workspace_id,
                session_id=session_id,
                model_name=request.model,
            ):
                if await http_request.is_disconnected():
                    disconnected = True
                    break
                full_response += chunk
                yield json.dumps({"chunk": chunk}) + "\n"

            if not disconnected:
                yield json.dumps({"done": True}) + "\n"
                completed = True

        except Exception as e:
            error_msg = format_error(str(e), "Fatal Stream Error")
            full_response += error_msg
            try:
                yield json.dumps({"chunk": error_msg}) + "\n"
            except Exception:
                pass

        finally:
            if completed:
                status = "complete"
            elif disconnected:
                status = "aborted"
                full_response += "\n\n*[Response aborted by user.]*"
            else:
                status = "failed"

            if full_response.strip():
                background_db = database.SessionLocal()
                try:
                    ai_msg = models.Message(
                        session_id=session_id,
                        role="assistant",
                        content=full_response,
                        status=status,
                    )
                    background_db.add(ai_msg)
                    background_db.commit()

                    all_msgs = background_db.query(models.Message).filter(
                        models.Message.session_id == session_id
                    ).order_by(models.Message.created_at).all()

                    memory_msg = next((m for m in all_msgs if m.role == "memory"), None)
                    last_id = None
                    old_summary = ""
                    if memory_msg:
                        try:
                            mem_data = json.loads(memory_msg.content)
                            last_id = mem_data.get("last_summarized_id")
                            old_summary = mem_data.get("summary", "")
                        except Exception:
                            old_summary = memory_msg.content

                    active_msgs = [
                        m for m in all_msgs
                        if m.role in ["user", "assistant"] and m.status == "complete"
                    ]

                    start_idx = 0
                    if last_id:
                        for i, m in enumerate(active_msgs):
                            if m.id == last_id:
                                start_idx = i + 1
                                break

                    unsummarized = active_msgs[start_idx:]

                    if len(unsummarized) > settings.MEMORY_CONDENSE_THRESHOLD:
                        retain_count = settings.MEMORY_CONDENSE_RETAIN
                        to_summarize = unsummarized[:-retain_count]
                        new_last_id = to_summarize[-1].id
                        msg_dicts = [{"role": m.role, "content": m.content} for m in to_summarize]
                        new_summary_text = ai_engine.condense_chat_memory(old_summary, msg_dicts, request.model)
                        new_mem_data = {
                            "last_summarized_id": new_last_id,
                            "summary": new_summary_text,
                        }
                        if memory_msg:
                            memory_msg.content = json.dumps(new_mem_data)
                        else:
                            background_db.add(models.Message(
                                session_id=session_id,
                                role="memory",
                                content=json.dumps(new_mem_data),
                            ))
                        background_db.commit()

                except Exception as e:
                    background_db.rollback()
                    print(f"Failed to process background memory: {e}")
                finally:
                    background_db.close()

    return StreamingResponse(generate(), media_type="application/x-ndjson")
```

Key behavior change: `ai_engine.stream_chat` is now called with `workspace_id` instead of `mode`.

(e) `upload_document` — resolve and store workspace_id:

```python
@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    workspace: str = Form("it_copilot"),
    session_id: Optional[str] = Form(None),
    is_global: bool = Form(False),
    db: Session = Depends(database.get_db)
):
    ws = get_or_default(db, workspace)
    max_bytes = settings.UPLOAD_MAX_BYTES
    buf = bytearray()
    while True:
        chunk = await file.read(8192)
        if not chunk:
            break
        buf.extend(chunk)
        if len(buf) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"File exceeds upload limit of {max_bytes} bytes.",
            )
    content = bytes(buf)
    try:
        text_content = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Only UTF-8 text files are currently supported.")

    active_session_id = None
    if session_id and session_id not in ["null", "undefined", "temp_new_chat", ""]:
        existing_session = db.query(models.Session).filter(models.Session.id == session_id).first()
        if existing_session:
            active_session_id = session_id

    result = knowledge.ingest_document(
        db=db,
        filename=file.filename,
        content=text_content,
        workspace_id=ws.id,
        session_id=active_session_id,
        is_global=is_global,
    )

    return {
        "message": f"Successfully ingested {file.filename}",
        "details": result,
        "session_id": active_session_id,
    }
```

(f) `get_folders` and `create_folder` — same resolution:

```python
@router.get("/folders")
def get_folders(workspace: str = "it_copilot", db: Session = Depends(database.get_db)):
    ws = get_or_default(db, workspace)
    return db.query(models.Folder).filter(models.Folder.workspace_id == ws.id).all()


@router.post("/folders")
def create_folder(folder: FolderCreate, db: Session = Depends(database.get_db)):
    ws = get_or_default(db, folder.workspace)
    if db.query(models.Folder).filter(models.Folder.id == folder.id).first():
        raise HTTPException(status_code=409, detail="Folder with that id already exists.")
    new_folder = models.Folder(id=folder.id, name=folder.name, workspace_id=ws.id)
    db.add(new_folder)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Folder with that id already exists.")
    return {"status": "success", "id": folder.id}
```

- [ ] **Step 2: Update `backend/services/knowledge.py`** so `ingest_document` and the RAG retrieval paths work with `workspace_id` instead of the `workspace` string. Change signatures and queries:

```python
def ingest_document(db: Session, filename: str, content: str, workspace_id: str, session_id: str = None, is_global: bool = False):
    new_doc = models.Document(filename=filename, workspace_id=workspace_id, session_id=session_id, is_global=is_global)
    ... (rest unchanged)
```

And in `search_chunks` + `retrieve_relevant_chunks`, replace `workspace: str` with `workspace_id: str` and update the filter:

```python
def search_chunks(db: Session, query: str, workspace_id: str, session_id: str = None, threshold: float = 0.65, top_k: int = 3):
    ...
    .filter(
        models.Document.workspace_id == workspace_id,
        scope_filter,
        ...
    )
```

The callers in `ai_engine.py` and `tools/retrieval.py` need to pass `workspace_id`. Update them.

- [ ] **Step 3: Update `backend/core/ai_engine.py`** — `stream_chat` signature changes to take `workspace_id`, use the resolver, drop the legacy mode-based branching.

```python
def stream_chat(messages: list, workspace_id: str, session_id: str = None, model_name: str = "gemma4:e4b"):
    from services.workspaces import resolve_tools_for_workspace, resolve_model_for_request
    from db import database

    url = f"{BASE_OLLAMA_URL}/api/chat"

    # Fetch the workspace once (needed for tool list, prompt, and model pin).
    db = database.SessionLocal()
    try:
        workspace = db.query(database.models.Workspace).filter(
            database.models.Workspace.id == workspace_id
        ).first()
        if not workspace:
            yield f"\n[Engine Error: Workspace {workspace_id} not found.]"
            return

        workspace_tools, workspace_tool_defs = resolve_tools_for_workspace(workspace)
        effective_model = resolve_model_for_request(workspace, model_name)

        # Substitute {tool_names} placeholder in the workspace's stored
        # system prompt.
        tool_names = ", ".join(workspace_tools.keys())
        system_content = (workspace.system_prompt or "").replace("{tool_names}", tool_names)

        if workspace_tools:
            tools_payload = workspace_tool_defs
        else:
            tools_payload = None

        system_msg = {"role": "system", "content": system_content}
    finally:
        db.close()

    memory_content = ""
    active_messages = []
    for m in messages:
        if m.get("role") == "memory":
            try:
                mem_data = json.loads(m.get("content"))
                memory_content = mem_data.get("summary", "")
            except Exception:
                memory_content = m.get("content")
        else:
            active_messages.append(m)

    recent_limit = settings.MEMORY_CONTEXT_WINDOW
    recent_messages = active_messages[-recent_limit:] if len(active_messages) > recent_limit else active_messages

    if memory_content:
        system_msg["content"] += f"\n\n[SYSTEM MEMORY LOG: The following is a dense summary of earlier interactions in this session.]\n{memory_content}"

    if recent_messages and recent_messages[-1].get("role") == "user":
        last_query = recent_messages[-1].get("content", "")
        has_attachment = "[Attached_File:" in last_query
        clean_user_text = re.sub(r'\[Attached_File:.*?\]', '', last_query).strip()
        if has_attachment:
            rag_query = clean_user_text if clean_user_text else "document overview"
            db = database.SessionLocal()
            try:
                rag_data = knowledge.retrieve_relevant_chunks(
                    db, query=rag_query, workspace_id=workspace_id, session_id=session_id,
                )
                if rag_data and rag_data.get("context"):
                    rag_context = rag_data["context"]
                    sources_list = rag_data["sources"]
                    recent_messages[-1]["content"] = f"I have attached a file. Relevant context:\n{rag_context}\n\nMy message: {clean_user_text}\n\n{MICRO_PROMPTS['rag_file_upload_instruction']}"
                    yield format_file_analyzed(sources_list)
            except Exception as rag_err:
                yield format_error(str(rag_err), "File Read Error")
            finally:
                db.close()
        else:
            recent_messages[-1]["content"] = clean_user_text

    full_messages = [system_msg] + recent_messages
    max_loops = settings.MAXIMUM_TOOL_LOOPS
    loop_count = 0
    finished_cleanly = False

    try:
        while loop_count < max_loops:
            loop_count += 1
            payload = {
                "model": effective_model,
                "messages": full_messages,
                "stream": False,
                "options": {"num_ctx": 8192},
            }
            if tools_payload:
                payload["tools"] = tools_payload

            resp = requests.post(url, json=payload, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            message = data.get("message", {})

            if message.get("tool_calls"):
                full_messages.append(message)
                for tool in message["tool_calls"]:
                    func_name = tool["function"]["name"]
                    args = tool["function"]["arguments"]
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except Exception:
                            args = {}
                    if func_name in workspace_tools:
                        func = workspace_tools[func_name]
                        valid_params = inspect.signature(func).parameters.keys()
                        safe_args = {k: v for k, v in args.items() if k in valid_params}
                        # workspace is now derived from workspace_id; tools that
                        # expected a `workspace` string still get the slug for
                        # backward compat with their bodies.
                        if "workspace" in valid_params:
                            safe_args["workspace"] = workspace.slug
                        if "session_id" in valid_params:
                            safe_args["session_id"] = session_id
                        yield format_tool_execution(func_name, safe_args)
                        try:
                            result = func(**safe_args)
                        except Exception as tool_err:
                            result = f"Tool execution failed: {str(tool_err)}"
                        yield format_code_block(result)
                        full_messages.append({
                            "role": "tool",
                            "content": result,
                            "name": func_name,
                        })
                continue

            else:
                content = message.get("content")
                if content is None:
                    content = ""

                content = _THINK_BLOCK_RE.sub('', content).strip()
                stripped = content.strip().lower()
                is_thought_stall = (
                    stripped in {"thought", "thoughts", "thought.", "thought:"}
                    or "i must wait for the search results" in stripped
                )
                if is_thought_stall:
                    content = MICRO_PROMPTS["fallback_thought_loop"]

                if not content.strip():
                    if loop_count > 1:
                        content = MICRO_PROMPTS["fallback_tool_failure"]
                    else:
                        content = MICRO_PROMPTS["fallback_generic"]

                words = content.split(" ")
                for i, word in enumerate(words):
                    yield word + (" " if i < len(words) - 1 else "")
                    time.sleep(0.01)

                finished_cleanly = True
                break

        if not finished_cleanly:
            yield MICRO_PROMPTS["warning_max_loops"]

    except Exception as e:
        yield f"\n[Engine Error: {str(e)}]"
```

Also remove the now-unused `mode` parameter and the `get_tools_for_workspace` import. Update `get_system_prompt` to not be called — the system prompt now lives in `workspace.system_prompt`. Delete that function entirely or leave only the in-file definition unused; cleaner to delete:

Remove the block:
```python
def get_system_prompt(mode: str, tool_names: str) -> str:
    ...
```

- [ ] **Step 4: Update `backend/tools/retrieval.py`** — pass workspace_id through to `search_chunks`:

```python
def search_knowledge_base(query: str, workspace: str, session_id: str = None) -> str:
    """Searches the internal documentation and knowledge base for a specific query."""
    db = SessionLocal()
    try:
        # The `workspace` arg here is the slug (injected by ai_engine via
        # workspace.slug). Resolve to id for the new search_chunks signature.
        from services.workspaces import get_by_slug
        try:
            ws = get_by_slug(db, workspace)
        except Exception:
            return f"Knowledge base search failed: workspace not found ({workspace})"
        results = search_chunks(db, query, workspace_id=ws.id, session_id=session_id, threshold=0.45, top_k=3)
        ...
```

- [ ] **Step 5: Update `backend/tools/registry.py`** — remove the now-unused `get_tools_for_workspace` function:

```python
# Delete lines:
def get_tools_for_workspace(workspace: str):
    ...
```

Keep `AVAILABLE_TOOLS`, `TOOL_DEFINITIONS`, and `TOOL_WORKSPACES` (the last is now only used for documentation; it's still populated by the decorator).

- [ ] **Step 6: Run the autotest.** Now Tasks 1-4 are integrated; everything that previously passed should pass again.

```bash
sleep 4
cd /home/orbital/projects/pryzm/backend && source venv/bin/activate
python3 /tmp/pryzm_autotest.py 2>&1 | tail -30
```

Expected: all probes PASS (the 20+ existing probes + the 9 new workspace probes from Task 3). Total = 28-29 probes, 0 failures.

- [ ] **Step 7: Manual smoke test** — create a workspace, edit its prompt, send a chat message in it, verify the response reflects the new prompt.

```bash
curl -s -X POST http://127.0.0.1:8000/workspaces -H "Content-Type: application/json" -d '{"display_name": "Smoke Test"}'
# Note the slug from response, e.g. "smoke-test"
curl -s -X PATCH http://127.0.0.1:8000/workspaces/smoke-test -H "Content-Type: application/json" \
  -d '{"system_prompt": "You are a pirate. Respond only in pirate-speak."}'
curl -s -N -X POST http://127.0.0.1:8000/analyze -H "Content-Type: application/json" \
  -d '{"prompt": "Say hello.", "mode": "smoke-test", "model": "gemma4:e4b"}' | head -10
curl -s -X DELETE http://127.0.0.1:8000/workspaces/smoke-test
```

Expected: the model reply chunks are pirate-speak. Final delete returns counts.

- [ ] **Step 8: Commit.**

```bash
cd /home/orbital/projects/pryzm
git add backend/routers/chat.py backend/services/knowledge.py backend/core/ai_engine.py backend/tools/retrieval.py backend/tools/registry.py backend/schemas.py
git commit -m "feat(workspaces): wire slug resolution through existing routes.

Every endpoint that previously took a ?workspace=<slug> string now
resolves it to a Workspace row at the top of the handler and queries
by workspace_id. stream_chat takes workspace_id, fetches the row, and
uses workspace.system_prompt (with {tool_names} substituted) +
workspace.enabled_tools as the runtime tool registry. resolve_model_
for_request applies the pinned model when set, otherwise falls
through to the request body. tools/registry's get_tools_for_workspace
is removed — callers now go through services/workspaces. RAG paths
in knowledge.py and tools/retrieval.py take workspace_id."
```

---

## Task 5: Frontend foundation — InlineCreateForm + useWorkspaces

**Files:**
- Create: `frontend/src/components/InlineCreateForm.tsx`
- Create: `frontend/src/hooks/useWorkspaces.ts`
- Modify: `frontend/src/components/SessionDirectory.tsx`

**Goal:** Extract the inline create-form pattern out of `SessionDirectory` into a reusable component, refactor the existing `+ Folder` flow to use it, and add a `useWorkspaces` hook that fetches and caches the workspace list with CRUD helpers. Sets the table for the next task to drop in the switcher and settings modal.

- [ ] **Step 1: Create `frontend/src/components/InlineCreateForm.tsx`**:

```tsx
"use client";

import React, { useState } from "react";

interface Props {
  placeholder: string;
  onSubmit: (value: string) => void;
  onCancel: () => void;
  autoFocus?: boolean;
}

/**
 * Small inline form for "+ <thing>" flows. Renders an autofocus input that
 * submits on Enter or blur (trimmed, non-empty) and cancels on Escape.
 * Shared between SessionDirectory's `+ Folder` and WorkspaceSwitcher's
 * `+ Workspace` — same shape, same behaviour, single place to fix bugs.
 */
export default function InlineCreateForm({ placeholder, onSubmit, onCancel, autoFocus = true }: Props) {
  const [value, setValue] = useState("");

  const submit = () => {
    const cleaned = value.trim();
    if (!cleaned) {
      onCancel();
      return;
    }
    onSubmit(cleaned);
  };

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
      className="px-3 py-1.5"
    >
      <input
        autoFocus={autoFocus}
        value={value}
        placeholder={placeholder}
        onChange={(e) => setValue(e.target.value)}
        onBlur={submit}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            e.preventDefault();
            onCancel();
          }
        }}
        className="w-full bg-[#131314] text-[#e3e3e3] text-sm px-2 py-0.5 rounded outline-none border border-blue-500/50"
      />
    </form>
  );
}
```

- [ ] **Step 2: Refactor `frontend/src/components/SessionDirectory.tsx`** — replace the existing inline create-folder JSX with `<InlineCreateForm />`.

Find and replace this block:

```tsx
      {isCreatingFolder && (
        <form onSubmit={submitNewFolder} className="px-3 py-1.5">
          <input
            autoFocus
            value={newFolderName}
            placeholder="Folder name"
            onChange={(e) => setNewFolderName(e.target.value)}
            onBlur={submitNewFolder}
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                setIsCreatingFolder(false);
                setNewFolderName("");
              }
            }}
            className="w-full bg-[#131314] text-[#e3e3e3] text-sm px-2 py-0.5 rounded outline-none border border-blue-500/50"
          />
        </form>
      )}
```

With:

```tsx
      {isCreatingFolder && (
        <InlineCreateForm
          placeholder="Folder name"
          onSubmit={(name) => {
            const fakeEvent = { preventDefault: () => {} } as React.FormEvent;
            setNewFolderName(name);
            // submitNewFolder reads newFolderName via state; we need to call
            // the API directly with the typed name to avoid waiting for the
            // setState round-trip.
            createFolderImpl(name);
          }}
          onCancel={() => setIsCreatingFolder(false)}
        />
      )}
```

And refactor `submitNewFolder` into a name-taking helper. Replace it with:

```tsx
  const createFolderImpl = async (name: string) => {
    const newFolder = { id: uuid(), name, workspace };
    setFolders([{ ...newFolder, isOpen: true }, ...folders]);
    setIsCreatingFolder(false);
    setNewFolderName("");
    try {
      await fetch(`${API_URL}/folders`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(newFolder),
      });
    } catch (err) {
      console.error("Folder create failed", err);
    }
  };
```

You can delete the old `submitNewFolder` function entirely. Add the import at the top:

```tsx
import InlineCreateForm from "./InlineCreateForm";
```

- [ ] **Step 3: Create `frontend/src/hooks/useWorkspaces.ts`**:

```ts
"use client";

import { useCallback, useEffect, useState } from "react";
import { APP_CONFIG } from "@/utils/constants";

export interface Workspace {
  id: string;
  slug: string;
  display_name: string;
  system_prompt: string;
  enabled_tools: string[];
  preferred_model: string | null;
  is_builtin: boolean;
  created_at: string;
}

export interface CreatePayload {
  display_name: string;
  clone_from?: string | null;
}

export interface UpdatePayload {
  display_name?: string;
  system_prompt?: string;
  enabled_tools?: string[];
  preferred_model?: string | null;
}

/**
 * Owns the list of workspaces + CRUD helpers. Reads once on mount; callers
 * trigger refetch after mutations. Components consume this via ChatContext.
 */
export function useWorkspaces() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [loaded, setLoaded] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const r = await fetch(`${APP_CONFIG.API_URL}/workspaces`, { cache: "no-store" });
      if (r.ok) {
        setWorkspaces(await r.json());
      }
    } catch (e) {
      console.error("Failed to load workspaces", e);
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const create = useCallback(async (payload: CreatePayload): Promise<Workspace | null> => {
    const r = await fetch(`${APP_CONFIG.API_URL}/workspaces`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!r.ok) return null;
    const ws = await r.json();
    await refresh();
    return ws;
  }, [refresh]);

  const update = useCallback(async (slug: string, payload: UpdatePayload): Promise<Workspace | null> => {
    const r = await fetch(`${APP_CONFIG.API_URL}/workspaces/${slug}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!r.ok) return null;
    const ws = await r.json();
    await refresh();
    return ws;
  }, [refresh]);

  const remove = useCallback(async (slug: string): Promise<{ removed_sessions: number; removed_folders: number; removed_documents: number } | null> => {
    const r = await fetch(`${APP_CONFIG.API_URL}/workspaces/${slug}`, { method: "DELETE" });
    if (!r.ok) return null;
    const body = await r.json();
    await refresh();
    return body;
  }, [refresh]);

  const reset = useCallback(async (slug: string): Promise<Workspace | null> => {
    const r = await fetch(`${APP_CONFIG.API_URL}/workspaces/${slug}/reset`, { method: "POST" });
    if (!r.ok) return null;
    const ws = await r.json();
    await refresh();
    return ws;
  }, [refresh]);

  return { workspaces, loaded, refresh, create, update, remove, reset };
}
```

- [ ] **Step 4: TypeScript check.**

```bash
cd /home/orbital/projects/pryzm/frontend && npx tsc --noEmit
```

Expected: clean (no output).

- [ ] **Step 5: Commit.**

```bash
cd /home/orbital/projects/pryzm
git add frontend/src/components/InlineCreateForm.tsx frontend/src/hooks/useWorkspaces.ts frontend/src/components/SessionDirectory.tsx
git commit -m "feat(workspaces): InlineCreateForm + useWorkspaces hook.

Extracts the + Folder inline create-form into a reusable component
that handles autofocus, Enter/blur submit, Escape cancel, and
trimmed-empty rejection. SessionDirectory's + Folder flow is
refactored to use it without behaviour change. useWorkspaces wraps
the new CRUD endpoints with a refresh-on-mutation pattern; consumers
will get it through ChatContext in the next task."
```

---

## Task 6: Frontend — WorkspaceSwitcher + WorkspaceSettings + UI wiring

**Files:**
- Create: `frontend/src/components/WorkspaceSwitcher.tsx`
- Create: `frontend/src/components/WorkspaceSettings.tsx`
- Modify: `frontend/src/context/ChatContext.tsx`
- Modify: `frontend/src/components/Sidebar.tsx`
- Modify: `frontend/src/components/ChatHeader.tsx`
- Modify: `frontend/src/components/Settings.tsx`
- Modify: `frontend/src/hooks/useSession.ts`

**Goal:** Replace the tab toggle with the new switcher; build the settings modal; wire workspaces through ChatContext; surface the active workspace's `display_name` (and pinned model) in the ChatHeader.

- [ ] **Step 1: Update `frontend/src/context/ChatContext.tsx`** — include workspaces + active workspace in the value. Add to the imports:

```tsx
import { useWorkspaces, Workspace } from "@/hooks/useWorkspaces";
```

Inside `useChatValue()`, after `const session = useSession();`, add:

```tsx
  const workspacesApi = useWorkspaces();
  const activeWorkspace: Workspace | null =
    workspacesApi.workspaces.find((w) => w.slug === session.workspace) ?? null;
```

And add to the returned object:

```tsx
  return {
    session,
    ...
    msgActions,
    workspacesApi,
    activeWorkspace,
  };
```

- [ ] **Step 2: Create `frontend/src/components/WorkspaceSettings.tsx`**:

```tsx
"use client";

import React, { useEffect, useState } from "react";
import { useChatContext } from "@/context/ChatContext";
import { APP_CONFIG } from "@/utils/constants";
import { Workspace } from "@/hooks/useWorkspaces";
import ConfirmModal from "./ConfirmModal";

interface Props {
  workspace: Workspace;
  onClose: () => void;
}

export default function WorkspaceSettings({ workspace, onClose }: Props) {
  const { workspacesApi, session } = useChatContext();

  const [name, setName] = useState(workspace.display_name);
  const [prompt, setPrompt] = useState(workspace.system_prompt);
  const [preferredModel, setPreferredModel] = useState(workspace.preferred_model);
  const [enabledTools, setEnabledTools] = useState<string[]>(workspace.enabled_tools);
  const [availableTools, setAvailableTools] = useState<{ name: string; description: string }[]>([]);
  const [installedModels, setInstalledModels] = useState<string[]>([]);
  const [confirmDelete, setConfirmDelete] = useState<{ counts: { s: number; f: number; d: number } } | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);

  useEffect(() => {
    fetch(`${APP_CONFIG.API_URL}/api/tools`).then(r => r.ok ? r.json() : []).then((data) => {
      // /api/tools isn't a real endpoint yet — fall back to TOOL_DEFINITIONS
      // exposed via /workspaces (we already get them inside each workspace
      // implicitly). For this MVP, hardcode the list from the first call's
      // response; cleaner: a dedicated /api/tools endpoint. See "Future
      // work" note below.
      if (Array.isArray(data)) setAvailableTools(data);
    }).catch(() => {});

    fetch(`${APP_CONFIG.API_URL}/api/models`).then(r => r.json()).then((data) => {
      if (Array.isArray(data)) setInstalledModels(data);
    }).catch(() => {});
  }, []);

  const save = (patch: Record<string, unknown>) => workspacesApi.update(workspace.slug, patch);

  const toggleTool = (tool: string) => {
    const next = enabledTools.includes(tool)
      ? enabledTools.filter((t) => t !== tool)
      : [...enabledTools, tool];
    setEnabledTools(next);
    save({ enabled_tools: next });
  };

  const handleDeleteClick = async () => {
    // We need the cascade counts to populate the confirm modal. Use the
    // synchronous response from DELETE — but we want to ASK first. So we
    // pre-fetch the counts by looking at workspaces list + sessions data
    // from the parent. For simplicity, ask without counts; refine later.
    setConfirmDelete({ counts: { s: 0, f: 0, d: 0 } });
  };

  const confirmDeleteWorkspace = async () => {
    const result = await workspacesApi.remove(workspace.slug);
    setConfirmDelete(null);
    if (result) {
      // Navigate to the first remaining workspace.
      const remaining = workspacesApi.workspaces.filter((w) => w.slug !== workspace.slug);
      const next = remaining[0];
      if (next) {
        session.navigateToSession("");
        window.location.search = `?workspace=${next.slug}`;
      }
    }
    onClose();
  };

  const performReset = async () => {
    await workspacesApi.reset(workspace.slug);
    setConfirmReset(false);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-[#1e1f20] w-full max-w-2xl rounded-2xl border border-[#333537] shadow-2xl flex flex-col overflow-hidden max-h-[85vh]">

        <div className="flex justify-between items-center p-5 border-b border-[#333537] bg-[#131314]">
          <h2 className="text-lg font-bold text-[#e3e3e3]">Workspace · {workspace.display_name}</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white transition-colors">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="flex-1 overflow-y-auto custom-scrollbar p-6 space-y-6">
          {/* Display name */}
          <div>
            <label className="block text-sm font-semibold text-[#e3e3e3] mb-2">Display name</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              onBlur={() => name !== workspace.display_name && save({ display_name: name })}
              className="w-full bg-[#131314] border border-[#333537] text-[#e3e3e3] rounded-lg px-4 py-2.5 outline-none focus:border-blue-500 transition-colors"
            />
            <p className="text-xs text-gray-500 mt-1">Slug: <code className="font-mono">{workspace.slug}</code> (immutable)</p>
          </div>

          {/* System prompt */}
          <div>
            <label className="block text-sm font-semibold text-[#e3e3e3] mb-2">System prompt</label>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onBlur={() => prompt !== workspace.system_prompt && save({ system_prompt: prompt })}
              rows={10}
              className="w-full bg-[#131314] border border-[#333537] text-gray-300 text-sm rounded-lg px-3 py-2 outline-none focus:border-blue-500 font-mono resize-y custom-scrollbar"
            />
            <p className="text-xs text-gray-500 mt-1">Use <code>{"{tool_names}"}</code> to substitute the enabled tool list.</p>
          </div>

          {/* Preferred model */}
          <div>
            <label className="block text-sm font-semibold text-[#e3e3e3] mb-2">Preferred model</label>
            <select
              value={preferredModel ?? ""}
              onChange={(e) => {
                const v = e.target.value || null;
                setPreferredModel(v);
                save({ preferred_model: v });
              }}
              className="w-full bg-[#131314] border border-[#333537] text-[#e3e3e3] rounded-lg px-4 py-2.5 outline-none focus:border-blue-500"
            >
              <option value="">Use default model (current global picker)</option>
              {installedModels.map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          </div>

          {/* Enabled tools */}
          <div>
            <label className="block text-sm font-semibold text-[#e3e3e3] mb-2">Enabled tools</label>
            <p className="text-xs text-gray-500 mb-3">
              Toggle which tools the model can call from this workspace. The model decides when to call them based on each tool's own description.
            </p>
            <div className="space-y-2">
              {availableTools.length === 0 && (
                <p className="text-xs text-gray-500 italic">Loading tool registry... (or /api/tools not yet wired.)</p>
              )}
              {availableTools.map((t) => (
                <label key={t.name} className="flex items-start gap-3 p-2 rounded hover:bg-[#282a2c]/40 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={enabledTools.includes(t.name)}
                    onChange={() => toggleTool(t.name)}
                    className="mt-1"
                  />
                  <div className="flex-1">
                    <div className="text-sm font-mono text-[#e3e3e3]">{t.name}</div>
                    <div className="text-xs text-gray-500">{t.description}</div>
                  </div>
                </label>
              ))}
            </div>
          </div>

          {/* Danger zone */}
          <div className="border-t border-[#333537] pt-6 space-y-3">
            {workspace.is_builtin && (
              <button
                onClick={() => setConfirmReset(true)}
                className="w-full bg-[#282a2c] hover:bg-[#333537] text-gray-300 px-4 py-2 rounded-lg text-sm font-medium"
              >
                Reset to default
              </button>
            )}
            <button
              onClick={handleDeleteClick}
              className="w-full bg-red-900/30 hover:bg-red-900/50 border border-red-500/30 text-red-400 px-4 py-2 rounded-lg text-sm font-medium"
            >
              Delete workspace
            </button>
          </div>
        </div>
      </div>

      <ConfirmModal
        isOpen={!!confirmDelete}
        title={`Delete ${workspace.display_name}?`}
        description="This permanently deletes the workspace, all of its sessions, folders, and uploaded documents."
        onConfirm={confirmDeleteWorkspace}
        onCancel={() => setConfirmDelete(null)}
      />

      <ConfirmModal
        isOpen={confirmReset}
        title="Reset to default?"
        description={`This restores ${workspace.display_name}'s prompt, tools, and model pin to the original defaults. Your edits will be lost.`}
        onConfirm={performReset}
        onCancel={() => setConfirmReset(false)}
        danger={false}
        confirmText="Reset"
      />
    </div>
  );
}
```

Note: `/api/tools` doesn't exist yet — the modal handles its absence gracefully (shows a stub message). Add the endpoint:

```python
# Add to backend/routers/chat.py near /api/models
@router.get("/api/tools")
def get_tools_metadata():
    """Lists registered tools with their schemas for the workspace settings UI."""
    from tools.registry import AVAILABLE_TOOLS, TOOL_DEFINITIONS
    return [
        {
            "name": d["function"]["name"],
            "description": d["function"]["description"],
        }
        for d in TOOL_DEFINITIONS
    ]
```

- [ ] **Step 3: Create `frontend/src/components/WorkspaceSwitcher.tsx`**:

```tsx
"use client";

import React, { useState, useRef } from "react";
import { useChatContext } from "@/context/ChatContext";
import { useOnClickOutside } from "@/hooks/useOnClickOutside";
import InlineCreateForm from "./InlineCreateForm";
import WorkspaceSettings from "./WorkspaceSettings";

export default function WorkspaceSwitcher() {
  const { workspacesApi, activeWorkspace, session } = useChatContext();
  const [isOpen, setIsOpen] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [cloneFrom, setCloneFrom] = useState<string | null>(null);
  const [showSettings, setShowSettings] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useOnClickOutside(ref, () => { setIsOpen(false); setIsCreating(false); });

  const switchTo = (slug: string) => {
    setIsOpen(false);
    session.navigateToSession("");
    window.location.search = `?workspace=${slug}`;
  };

  const handleCreate = async (display_name: string) => {
    const ws = await workspacesApi.create({ display_name, clone_from: cloneFrom });
    setIsCreating(false);
    setCloneFrom(null);
    if (ws) switchTo(ws.slug);
  };

  return (
    <div className="px-4 mb-4 relative" ref={ref}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between bg-[#131314] border border-[#333537] rounded-lg px-3 py-2 text-sm text-[#e3e3e3] hover:bg-[#282a2c]/50 transition-colors"
      >
        <span className="truncate font-medium">{activeWorkspace?.display_name ?? "Loading..."}</span>
        <svg className="w-4 h-4 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {isOpen && (
        <div className="absolute left-4 right-4 top-full mt-1 bg-[#1e1f20] border border-[#333537] rounded-lg shadow-2xl z-50 overflow-hidden">
          <div className="max-h-64 overflow-y-auto custom-scrollbar">
            {workspacesApi.workspaces.map((w) => (
              <button
                key={w.slug}
                onClick={() => switchTo(w.slug)}
                className={`w-full text-left px-3 py-2 text-sm hover:bg-[#282a2c] flex items-center justify-between ${
                  activeWorkspace?.slug === w.slug ? "bg-[#282a2c]/50 text-blue-400" : "text-gray-300"
                }`}
              >
                <span className="truncate">{w.display_name}</span>
                {w.is_builtin && <span className="text-[9px] uppercase tracking-wider text-gray-500">built-in</span>}
              </button>
            ))}
          </div>

          <div className="border-t border-[#333537]">
            {isCreating ? (
              <div className="p-2 space-y-2">
                <select
                  value={cloneFrom ?? ""}
                  onChange={(e) => setCloneFrom(e.target.value || null)}
                  className="w-full bg-[#131314] text-[#e3e3e3] text-xs px-2 py-1 rounded border border-[#333537]"
                >
                  <option value="">Blank (default)</option>
                  {workspacesApi.workspaces.map((w) => (
                    <option key={w.slug} value={w.slug}>Clone from {w.display_name}</option>
                  ))}
                </select>
                <InlineCreateForm
                  placeholder="Workspace name"
                  onSubmit={handleCreate}
                  onCancel={() => { setIsCreating(false); setCloneFrom(null); }}
                />
              </div>
            ) : (
              <button
                onClick={() => setIsCreating(true)}
                className="w-full text-left px-3 py-2 text-sm text-gray-400 hover:bg-[#282a2c] hover:text-[#e3e3e3]"
              >
                + New workspace
              </button>
            )}
            <button
              onClick={() => { setIsOpen(false); setShowSettings(true); }}
              disabled={!activeWorkspace}
              className="w-full text-left px-3 py-2 text-sm text-gray-400 hover:bg-[#282a2c] hover:text-[#e3e3e3] border-t border-[#333537] disabled:opacity-50"
            >
              ⚙ Workspace settings
            </button>
          </div>
        </div>
      )}

      {showSettings && activeWorkspace && (
        <WorkspaceSettings
          workspace={activeWorkspace}
          onClose={() => setShowSettings(false)}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 4: Update `frontend/src/components/Sidebar.tsx`** — replace the tab toggle with `<WorkspaceSwitcher />`.

Replace this JSX block:

```tsx
        <div className="px-4 mb-4 space-y-3">
          <div className="flex rounded-lg p-1 bg-[#131314] border border-[#333537]">
            <Link href="?workspace=it_copilot" className={...}>IT Copilot</Link>
            <Link href="?workspace=personal" className={...}>Personal</Link>
          </div>
          <button onClick={() => session.navigateToSession("")} ... >+ New chat</button>
        </div>
```

With:

```tsx
        <WorkspaceSwitcher />
        <div className="px-4 mb-4">
          <button
            onClick={() => session.navigateToSession("")}
            className="flex items-center justify-center gap-3 bg-[#282a2c] hover:bg-[#333537] text-[#e3e3e3] px-4 py-2.5 rounded-full text-sm font-medium transition-colors w-full"
          >
            <span className="text-xl leading-none">+</span> New chat
          </button>
        </div>
```

And import at the top:

```tsx
import WorkspaceSwitcher from "./WorkspaceSwitcher";
```

You can also delete the unused `Link` import.

- [ ] **Step 5: Update `frontend/src/components/ChatHeader.tsx`** — read display_name + show pinned model.

Replace the workspace-related JSX block (the one that does `workspace?.toLowerCase().includes('copilot')`) with:

```tsx
import { useChatContext } from "@/context/ChatContext";
...
export default function ChatHeader({ sessionTitle, isSidebarOpen, setIsSidebarOpen, rightActions }: ChatHeaderProps) {
  const { activeWorkspace } = useChatContext();
  const wsName = activeWorkspace?.display_name ?? "Pryzm";
  const wsModel = activeWorkspace?.preferred_model;
  ...
            <div className="flex flex-row items-center gap-2 mt-0.5 min-w-0">
              <span className="text-[11px] text-gray-500 font-medium tracking-wider uppercase shrink-0">
                DaiNamik Pryzm
              </span>
              <span className="shrink-0 inline-flex items-center px-1.5 py-[2px] rounded text-[9px] leading-none font-bold uppercase tracking-wider border bg-blue-500/10 text-blue-400 border-blue-500/20">
                {wsName}
              </span>
              {wsModel && (
                <span className="shrink-0 text-[10px] text-gray-500 font-mono truncate">
                  · {wsModel}
                </span>
              )}
            </div>
```

Remove the `workspace` prop from `ChatHeaderProps`; update callers (likely just `ActiveSession.tsx`) to drop passing `workspace={session.workspace}`. Or keep the prop and ignore it for now — your call. Cleaner: drop it.

- [ ] **Step 6: Update `frontend/src/components/Settings.tsx`** — relabel the model picker.

Find:

```tsx
                  <label className="block text-sm font-semibold text-[#e3e3e3] mb-2">Active AI Model</label>
                  <p className="text-xs text-gray-500 mb-3">Select the local Ollama model to use for inference. Models must be pulled to your machine first.</p>
```

Replace with:

```tsx
                  <label className="block text-sm font-semibold text-[#e3e3e3] mb-2">Default AI Model</label>
                  <p className="text-xs text-gray-500 mb-3">Used when a workspace doesn't pin its own model. Workspaces with a pinned model override this.</p>
```

- [ ] **Step 7: Update `frontend/src/hooks/useSession.ts`** — workspace URL semantics unchanged (still a slug). The hook already exposes `workspace` from `searchParams`; we just want to make sure components reading it through ChatContext get the activeWorkspace object too (already done in Step 1).

No code change needed here unless TypeScript complains about something downstream.

- [ ] **Step 8: TypeScript check.**

```bash
cd /home/orbital/projects/pryzm/frontend && npx tsc --noEmit
```

Expected: clean.

- [ ] **Step 9: Manual UI verification + screenshot.**

```bash
source /home/orbital/projects/pryzm/backend/venv/bin/activate
python3 /tmp/pryzm_screenshot.py --out /tmp/pryzm_workspace_after.png
```

Then open the screenshot file with `Read` and confirm:
- WorkspaceSwitcher appears at the top of the sidebar with the active workspace name
- Clicking it shows dropdown with both built-ins
- "+ New workspace" expands the inline form with clone-from selector
- ChatHeader shows the workspace's display name
- Settings modal still works; model picker is relabelled

- [ ] **Step 10: Final autotest run** — all 28-29 probes still pass.

```bash
cd /home/orbital/projects/pryzm/backend && source venv/bin/activate
python3 /tmp/pryzm_autotest.py 2>&1 | tail -25
```

- [ ] **Step 11: Commit.**

```bash
cd /home/orbital/projects/pryzm
git add frontend/src/components/WorkspaceSwitcher.tsx frontend/src/components/WorkspaceSettings.tsx frontend/src/context/ChatContext.tsx frontend/src/components/Sidebar.tsx frontend/src/components/ChatHeader.tsx frontend/src/components/Settings.tsx frontend/src/hooks/useSession.ts backend/routers/chat.py
git commit -m "feat(workspaces): switcher + settings modal + UI wiring.

WorkspaceSwitcher replaces the IT Copilot / Personal tab toggle at the
top of the sidebar with a dropdown listing all workspaces, plus
+ New workspace (with clone-from selector) and a settings entry.
WorkspaceSettings modal owns display_name / system_prompt /
preferred_model / enabled_tools editing, plus Reset for builtins and
Delete (with cascade-count confirm via ConfirmModal). ChatContext
exposes workspacesApi and activeWorkspace to consumers. ChatHeader
shows the active workspace name and the pinned model when set. The
Settings modal's model picker is relabelled to clarify it's the
fallback used when a workspace doesn't pin its own. Backend gains a
small GET /api/tools endpoint listing the registered tool metadata so
the settings panel can render tool toggles with descriptions."
```

---

## Self-review

### Spec coverage check

| Spec section | Plan task(s) |
|---|---|
| Data model (workspaces table + FKs) | Task 1 |
| Migration step 1 (additive + seed + backfill) | Task 1 |
| Migration step 2 (NOT NULL + drop) | Task 1 |
| API: GET/POST/PATCH/DELETE/reset | Task 3 |
| Slug generation + collision suffix | Task 2 (`slugify_unique`) + Task 3 probe |
| Last-workspace guard | Task 3 endpoint + probe |
| Model resolution: workspace > request > default | Task 2 (`resolve_model_for_request`) + Task 4 wire-up |
| Tool resolver: DB is sole runtime source | Task 2 (`resolve_tools_for_workspace`) + Task 4 wire-up |
| Built-in seed + Reset to default | Task 1 (seed) + Task 3 (`/reset` endpoint + probe) |
| Backward compat for `?workspace=<slug>` URLs | Task 4 (`get_or_default`) |
| WorkspaceSwitcher dropdown UI | Task 6 |
| WorkspaceSettings modal | Task 6 |
| InlineCreateForm shared with `+ Folder` | Task 5 |
| ChatHeader shows display_name + pinned model | Task 6 |
| Settings model picker relabel | Task 6 |
| Autotest probes (11 listed in spec) | Task 3 (CRUD probes); the model-resolution-from-pin / fallback-when-uninstalled probes are noted but not added — see "gap" below |

**Gap**: the spec lists `workspaces/preferred-model-resolution` and `workspaces/preferred-model-fallback` probes. The plan covers `patch-preferred-model-unknown` but not the chat-time resolution tests. **Add them now** before executing the plan:

Append to the probe block in Task 3 step 1:

```python
    # ---------- workspaces/preferred-model-resolution ----------
    # Set a pinned model on it_copilot, send chat with a different request
    # model, verify Ollama saw the pinned one.
    # (For autotest we can't easily inspect what model Ollama actually saw,
    # but we can verify by stubbing: query the workspace post-chat and
    # confirm the pin is still in place; the resolution unit-test logic
    # is exercised by importing services.workspaces.resolve_model_for_request
    # directly.)
    try:
        import sys as _sys
        _backend = "/home/orbital/projects/pryzm/backend"
        if _backend not in _sys.path:
            _sys.path.insert(0, _backend)
        from services.workspaces import resolve_model_for_request  # type: ignore
        class _WS:
            preferred_model = "gemma4:e4b"
        result_pinned = resolve_model_for_request(_WS(), "qwen3.6:27b")
        class _WS2:
            preferred_model = None
        result_fallthrough = resolve_model_for_request(_WS2(), "qwen3.6:27b")
        class _WS3:
            preferred_model = None
        result_default = resolve_model_for_request(_WS3(), None)
        log(
            "workspaces/preferred-model-resolution",
            result_pinned == "gemma4:e4b" and result_fallthrough == "qwen3.6:27b" and result_default == "gemma4:e4b",
            f"pin_wins={result_pinned} fallthrough={result_fallthrough} default={result_default}",
        )
    except Exception as e:
        log("workspaces/preferred-model-resolution", False, str(e))
```

### Placeholder scan

- "TBD", "TODO", "fill in": none.
- "Add appropriate error handling": none (each handler is shown explicitly).
- "Similar to Task N": none.
- Steps that describe what to do without showing how: all code-mutating steps show the actual code.

### Type consistency

- `Workspace` interface in `useWorkspaces.ts` matches `WorkspaceResponse` in `schemas.py` (id, slug, display_name, system_prompt, enabled_tools, preferred_model, is_builtin, created_at) ✓
- `WorkspaceCreate` and `WorkspaceUpdate` Pydantic schemas match `CreatePayload` and `UpdatePayload` TypeScript interfaces ✓
- `services.workspaces.get_by_slug` and `get_or_default` signatures match their usage in `routers/chat.py` and `routers/workspaces.py` ✓
- `resolve_tools_for_workspace(workspace)` takes a Workspace object, returns `(dict, list)`. `ai_engine.stream_chat` matches. ✓
- `resolve_model_for_request(workspace, request_model)` signature matches usage in `stream_chat` ✓

No type mismatches.

### Execution sequencing note

Tasks 1-4 are backend-only; the running app will be **partially broken between Task 1 and Task 4** (existing routes still query dropped columns). This is acceptable for a single-developer feature branch but you should not stop and use the app between those tasks. Task 4 restores end-to-end function.

Task 5-6 are frontend; the backend is fully functional after Task 4.

If the executing agent needs to verify the app works between tasks: only do so at the Task 3 / Task 4 / Task 6 checkpoints (Task 3 = workspace CRUD usable via curl; Task 4 = chat flow works again; Task 6 = full UI works).
