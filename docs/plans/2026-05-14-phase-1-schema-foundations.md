# Phase 1 — Schema Foundations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Implementation agents must apply Karpathy guidelines: minimum code, no speculative abstractions, surgical changes, verifiable success criteria.

**Goal:** Land Phase 1 of the codebase remediation — five Alembic migrations and a small pytest harness — so the data layer's *shape* is ready for the consumer-side refactors in Phases 2–5.

**Architecture:** One Alembic revision per logical change (revertable independently). Each revision ships with a pytest test that exercises both `upgrade()` and `downgrade()` against an ephemeral test DB. The test harness is intentionally minimal — a single conftest with a session-scoped DB fixture, no async, no factories, no factory_boy. Schema model classes in `backend/db/models.py` are updated alongside each migration so the SQLAlchemy ORM keeps matching the actual schema.

**Tech stack:** Alembic 1.18, SQLAlchemy 2.0 (sync), pgvector 0.4, Postgres 15 in Docker, pytest. No new runtime dependencies; pytest is dev-only.

**Spec reference:** [`docs/specs/2026-05-14-codebase-remediation.md`](../specs/2026-05-14-codebase-remediation.md) — read the "Phase 1 — Schema Foundations" section before starting.

**Branch:** `refactor/phase-1-schema-foundations` (already exists; the spec is already committed on it as `4aea646`).

**Parent migration head:** `b880f5d1c619` (enforce_workspace_id_non_null). All five new revisions branch from this lineage.

---

## File Map

### Created
- `backend/requirements-dev.txt` — dev-only deps (pytest, pytest-cov).
- `backend/tests/__init__.py` — empty marker.
- `backend/tests/conftest.py` — shared fixtures: ephemeral test DB, alembic config, revision helper.
- `backend/tests/test_migration_engine_config.py` — Revision A test.
- `backend/tests/test_migration_chunks_workspace_id.py` — Revision B test.
- `backend/tests/test_migration_role_check.py` — Revision C test.
- `backend/tests/test_migration_embedding_index.py` — Revision D test.
- `backend/tests/test_migration_minor_constraints.py` — Revision E test.
- `backend/alembic/versions/c0a1_add_workspace_engine_config.py` — Revision A.
- `backend/alembic/versions/c0a2_add_chunks_workspace_id.py` — Revision B.
- `backend/alembic/versions/c0a3_add_role_check.py` — Revision C.
- `backend/alembic/versions/c0a4_add_embedding_index.py` — Revision D.
- `backend/alembic/versions/c0a5_minor_constraints.py` — Revision E.

(Alembic revision IDs in the filenames above are placeholders. Use `alembic revision -m "<message>"` to generate real IDs — see Task 1 Step 3.)

### Modified
- `backend/db/models.py` — add `Workspace.engine_config`, `DocumentChunk.workspace_id`, role CHECK constraint, default fixes.
- `.gitignore` — add `backend/.pytest_cache/` if not already covered (usually yes).

### Untouched
- `backend/main.py`, all `routers/`, all `services/`, all `tools/`, all frontend. Consumer-side changes land in Phases 2–5.

---

## Pre-flight (do once before Task 0)

The test harness uses a **separate Postgres database** called `pryzm_test` in the same `pryzm_db` container (not a new container). Each test run drops + recreates the database, so production data in `pryzm_core` is never touched.

Verify the container is running and create the test database manually before the first test:

```bash
docker ps | grep pryzm_db                        # ensure container is up
docker exec -it pryzm_db psql -U pryzm_admin -d postgres -c "CREATE DATABASE pryzm_test;"
docker exec -it pryzm_db psql -U pryzm_admin -d pryzm_test -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

Expected: `CREATE DATABASE` then `CREATE EXTENSION` (or `NOTICE: extension "vector" already exists, skipping`).

If `pryzm_db` is not running:

```bash
docker-compose up -d
```

---

## Task 0 — Pytest infrastructure

**Files:**
- Create: `backend/requirements-dev.txt`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/test_migrations_smoke.py`

The smoke test in this task just verifies the fixture infrastructure works — it does not test any new migration. The actual migration tests come in Tasks 1–5.

- [ ] **Step 1: Write the failing smoke test**

Create `backend/tests/__init__.py` (empty file).

Create `backend/tests/test_migrations_smoke.py`:

```python
"""Smoke test for the test-DB fixture infrastructure.

This test passes as soon as the conftest can spin up an ephemeral test DB,
run alembic to head, and hand back a working SQLAlchemy connection.
"""
from sqlalchemy import text


def test_db_at_head_exposes_workspaces_table(db_at_head):
    engine = db_at_head
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'workspaces'"
        ))
        assert result.scalar() == "workspaces"


def test_db_at_revision_can_walk_history(db_at_revision):
    engine = db_at_revision("b880f5d1c619")
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT version_num FROM alembic_version"
        ))
        assert result.scalar() == "b880f5d1c619"
```

- [ ] **Step 2: Run the smoke test to verify it fails**

```bash
cd backend
pytest tests/test_migrations_smoke.py -v
```

Expected: `ERROR ... fixture 'db_at_head' not found` (or similar — pytest not installed yet, or fixtures missing).

- [ ] **Step 3: Create `backend/requirements-dev.txt` and install**

```
pytest==8.3.4
pytest-cov==6.0.0
```

```bash
cd backend
pip install -r requirements-dev.txt
```

Expected: `Successfully installed pytest-8.3.4 pytest-cov-6.0.0 ...`

- [ ] **Step 4: Write the conftest**

Create `backend/tests/conftest.py`:

```python
"""Shared pytest fixtures for migration and DB-integration tests.

Uses a separate Postgres database `pryzm_test` in the same pryzm_db Docker
container. The fixture drops + recreates the database at session start so each
test run begins from a known empty state.
"""
import os
import urllib.parse

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from config import settings


TEST_DB_NAME = "pryzm_test"


def _test_database_url() -> str:
    """Build a DATABASE_URL for the test DB, reusing dev credentials."""
    safe_password = urllib.parse.quote_plus(settings.DB_PASSWORD)
    return (
        f"postgresql://{settings.DB_USER}:{safe_password}"
        f"@{settings.DB_HOST}:{settings.DB_PORT}/{TEST_DB_NAME}"
    )


def _admin_url() -> str:
    """Build a DATABASE_URL for the postgres admin DB (used to CREATE/DROP)."""
    safe_password = urllib.parse.quote_plus(settings.DB_PASSWORD)
    return (
        f"postgresql://{settings.DB_USER}:{safe_password}"
        f"@{settings.DB_HOST}:{settings.DB_PORT}/postgres"
    )


@pytest.fixture(scope="session")
def reset_test_db():
    """Drop + recreate the test DB once per pytest session. Yields the URL."""
    admin_engine = create_engine(_admin_url(), isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB_NAME}"))
        conn.execute(text(f"CREATE DATABASE {TEST_DB_NAME}"))
    admin_engine.dispose()

    test_engine = create_engine(_test_database_url(), isolation_level="AUTOCOMMIT")
    with test_engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    test_engine.dispose()

    yield _test_database_url()


@pytest.fixture
def alembic_cfg(reset_test_db):
    """Alembic config pointed at the test DB. Re-created per test."""
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", reset_test_db)
    cfg.set_main_option(
        "script_location",
        os.path.join(os.path.dirname(__file__), "..", "alembic"),
    )
    return cfg


@pytest.fixture
def db_at_revision(alembic_cfg, reset_test_db):
    """Return a function that resets the DB to a specific revision."""
    def _go(revision: str):
        command.downgrade(alembic_cfg, "base")
        command.upgrade(alembic_cfg, revision)
        engine = create_engine(reset_test_db)
        return engine

    return _go


@pytest.fixture
def db_at_head(db_at_revision):
    """DB migrated to head."""
    return db_at_revision("head")
```

- [ ] **Step 5: Run smoke test to verify it passes**

```bash
cd backend
pytest tests/test_migrations_smoke.py -v
```

Expected:
```
tests/test_migrations_smoke.py::test_db_at_head_exposes_workspaces_table PASSED
tests/test_migrations_smoke.py::test_db_at_revision_can_walk_history PASSED
```

- [ ] **Step 6: Commit**

```bash
cd ..
git add backend/requirements-dev.txt backend/tests/__init__.py backend/tests/conftest.py backend/tests/test_migrations_smoke.py
git commit -m "test: pytest harness with ephemeral pryzm_test DB."
```

---

## Task 1 — Revision A: `workspaces.engine_config` (JSONB)

Adds a `JSONB` column holding the inference engine config (`{"backend": "ollama", "model": "<name>"}`). Backfills from `preferred_model`. Sets NOT NULL with a server default. `preferred_model` is NOT dropped here — that lands at the end of Phase 4 once readers have migrated.

**Files:**
- Create: `backend/alembic/versions/<new>_add_workspace_engine_config.py`
- Modify: `backend/db/models.py` (Workspace class — add `engine_config`)
- Create: `backend/tests/test_migration_engine_config.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_migration_engine_config.py`:

```python
"""Verifies migration A: workspaces.engine_config (JSONB)."""
import json

from sqlalchemy import text


def _seed_old_row(engine, slug: str, preferred_model: str | None):
    """Insert a workspace row at the pre-migration schema."""
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO workspaces (id, slug, display_name, system_prompt,
                                    enabled_tools, preferred_model, is_builtin)
            VALUES (:id, :slug, :name, '', '[]'::jsonb, :pm, false)
        """), {"id": slug, "slug": slug, "name": slug, "pm": preferred_model})


def test_backfill_populates_engine_config_from_preferred_model(db_at_revision):
    # Start at parent revision (no engine_config column yet).
    engine = db_at_revision("b880f5d1c619")
    _seed_old_row(engine, "alpha", "gemma4:e4b")
    _seed_old_row(engine, "beta", None)

    # Apply migration A.
    from alembic.config import Config
    from alembic import command
    import os
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", str(engine.url))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    command.upgrade(cfg, "+1")

    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT slug, engine_config FROM workspaces ORDER BY slug"
        )).all()

    alpha_cfg = rows[0][1]
    beta_cfg = rows[1][1]
    # alpha had preferred_model "gemma4:e4b"; beta had NULL → default fallback.
    assert alpha_cfg == {"backend": "ollama", "model": "gemma4:e4b"}
    assert beta_cfg == {"backend": "ollama", "model": "gemma4:e4b"}


def test_engine_config_is_not_null_after_migration(db_at_head):
    engine = db_at_head
    # A fresh insert that omits engine_config must fall back to server default.
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO workspaces (id, slug, display_name, system_prompt,
                                    enabled_tools, is_builtin)
            VALUES ('test1', 'test-slug', 'test', '', '[]'::jsonb, false)
        """))
        cfg = conn.execute(text("SELECT engine_config FROM workspaces WHERE id = 'test1'")).scalar()
    assert cfg == {"backend": "ollama", "model": "gemma4:e4b"}


def test_engine_config_rejects_null(db_at_head):
    import pytest as _pytest
    from sqlalchemy.exc import IntegrityError

    engine = db_at_head
    with _pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO workspaces (id, slug, display_name, system_prompt,
                                        enabled_tools, is_builtin, engine_config)
                VALUES ('test2', 'test-null', 'x', '', '[]'::jsonb, false, NULL)
            """))


def test_downgrade_restores_pre_migration_state(db_at_revision):
    # Apply, then unapply, and verify the column is gone.
    engine = db_at_revision("+1 from b880f5d1c619")  # placeholder for the alembic walk
    # See Step 5 for the actual canonical revision id once generated.
```

(The placeholder revision string in the last test will be replaced after Step 3 generates a real revision id.)

- [ ] **Step 2: Run to verify failure**

```bash
cd backend
pytest tests/test_migration_engine_config.py -v
```

Expected: tests fail with `KeyError: 'engine_config'` or `UndefinedColumn: column "engine_config" does not exist` — because the migration doesn't exist yet.

- [ ] **Step 3: Generate the alembic revision and write the migration**

```bash
cd backend
alembic revision -m "add_workspace_engine_config"
```

This creates a new file in `backend/alembic/versions/<hash>_add_workspace_engine_config.py`. Record the hash; you'll need it.

Open the file. Replace the auto-generated body with:

```python
"""add workspace engine_config

Revision ID: <will be set by alembic>
Revises: b880f5d1c619
Create Date: ...

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "<keep what alembic generated>"
down_revision: Union[str, Sequence[str], None] = "b880f5d1c619"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DEFAULT_ENGINE_CONFIG = '{"backend": "ollama", "model": "gemma4:e4b"}'


def upgrade() -> None:
    # 1. Add column, nullable for now so the backfill can populate it.
    op.add_column(
        "workspaces",
        sa.Column("engine_config", JSONB(astext_type=sa.Text()), nullable=True),
    )

    # 2. Backfill: existing rows get {"backend": "ollama", "model": <preferred_model>}.
    #    If preferred_model IS NULL, fall back to the server default model.
    op.execute(
        """
        UPDATE workspaces
        SET engine_config = jsonb_build_object(
            'backend', 'ollama',
            'model', COALESCE(preferred_model, 'gemma4:e4b')
        )
        WHERE engine_config IS NULL
        """
    )

    # 3. Lock down: NOT NULL + server default for future inserts that omit it.
    op.alter_column(
        "workspaces", "engine_config",
        existing_type=JSONB(astext_type=sa.Text()),
        nullable=False,
        server_default=sa.text(f"'{DEFAULT_ENGINE_CONFIG}'::jsonb"),
    )


def downgrade() -> None:
    op.drop_column("workspaces", "engine_config")
```

Update `backend/db/models.py` — add `engine_config` to `Workspace` (around line 23, alongside `enabled_tools`):

```python
class Workspace(Base):
    __tablename__ = "workspaces"
    id = Column(String, primary_key=True, default=generate_uuid, index=True)
    slug = Column(String, nullable=False, unique=True, index=True)
    display_name = Column(String, nullable=False)
    system_prompt = Column(Text, nullable=False, default="")
    enabled_tools = Column(JSONB, nullable=False, server_default="[]")
    engine_config = Column(
        JSONB,
        nullable=False,
        server_default='{"backend": "ollama", "model": "gemma4:e4b"}',
    )
    preferred_model = Column(String, nullable=True)  # DEPRECATED — drops at end of Phase 4
    is_builtin = Column(Boolean, nullable=False, default=False, server_default="false")
    color = Column(String(32), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.clock_timestamp())
    # ... relationships unchanged
```

Now update the placeholder revision string in `test_migration_engine_config.py:test_downgrade_restores_pre_migration_state` to use the real revision hash you got from `alembic revision`. Replace the test body with:

```python
def test_downgrade_restores_pre_migration_state(reset_test_db, alembic_cfg):
    from alembic import command
    from sqlalchemy import create_engine

    # Walk to the new revision, then back one step.
    command.downgrade(alembic_cfg, "base")
    command.upgrade(alembic_cfg, "head")  # at A
    command.downgrade(alembic_cfg, "-1")  # back to parent

    engine = create_engine(reset_test_db)
    with engine.connect() as conn:
        col_exists = conn.execute(text("""
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'workspaces' AND column_name = 'engine_config'
        """)).scalar()
    assert col_exists is None
```

- [ ] **Step 4: Run to verify the migration passes**

```bash
cd backend
pytest tests/test_migration_engine_config.py -v
```

Expected: all four tests pass.

Also verify the up/down/up roundtrip from the CLI:

```bash
alembic upgrade head && alembic downgrade -1 && alembic upgrade head
```

Expected: three successful `INFO` lines from alembic ending in `Running upgrade ... -> <new_revision_id>, add_workspace_engine_config`.

- [ ] **Step 5: Commit**

```bash
cd ..
git add backend/alembic/versions/*_add_workspace_engine_config.py backend/db/models.py backend/tests/test_migration_engine_config.py
git commit -m "feat(schema): workspaces.engine_config JSONB with ollama-default backfill."
```

This is the end of Task 1. **Each subsequent task is its own PR** per the spec's "one PR per migration revision" rule for Phase 1. When you open the PR for Task 1, the success criterion is: `pytest tests/test_migration_engine_config.py -v` passes AND the alembic up/down/up roundtrip succeeds AND the test added in this task passes when run in isolation.

---

## Task 2 — Revision B: `document_chunks.workspace_id`

Adds a `workspace_id` FK on `document_chunks` so chunk queries can filter by workspace without joining through `documents`. Backfills from parent `Document.workspace_id`. Sets NOT NULL + adds a composite index.

**Files:**
- Create: `backend/alembic/versions/<new>_add_chunks_workspace_id.py`
- Modify: `backend/db/models.py` (DocumentChunk class — add `workspace_id`)
- Create: `backend/tests/test_migration_chunks_workspace_id.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_migration_chunks_workspace_id.py`:

```python
"""Verifies migration B: document_chunks.workspace_id FK + NOT NULL + index."""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


def _seed_workspace(engine, slug: str = "ws1") -> str:
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO workspaces (id, slug, display_name, system_prompt,
                                    enabled_tools, is_builtin)
            VALUES (:id, :slug, 'x', '', '[]'::jsonb, false)
        """), {"id": slug, "slug": slug})
    return slug


def _seed_document(engine, doc_id: str, workspace_id: str) -> str:
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO documents (id, filename, workspace_id, is_global)
            VALUES (:id, 'f.txt', :ws, false)
        """), {"id": doc_id, "ws": workspace_id})
    return doc_id


def test_workspace_id_backfilled_from_parent_document(db_at_revision):
    # Walk to A so engine_config exists, then seed pre-B state.
    engine = db_at_revision("head")  # head is currently A
    ws = _seed_workspace(engine, "ws-backfill")
    doc = _seed_document(engine, "doc-1", ws)
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO document_chunks (id, document_id, content)
            VALUES ('chunk-1', :doc, 'hello')
        """), {"doc": doc})

    # Apply B.
    from alembic.config import Config
    from alembic import command
    import os
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", str(engine.url))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    command.upgrade(cfg, "+1")

    with engine.connect() as conn:
        chunk_ws = conn.execute(text(
            "SELECT workspace_id FROM document_chunks WHERE id = 'chunk-1'"
        )).scalar()
    assert chunk_ws == ws


def test_workspace_id_is_not_null_after_migration(db_at_head):
    engine = db_at_head
    ws = _seed_workspace(engine, "ws-null-test")
    doc = _seed_document(engine, "doc-null", ws)
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO document_chunks (id, document_id, content)
                VALUES ('chunk-null', :doc, 'oops')
            """), {"doc": doc})  # no workspace_id; should fail NOT NULL


def test_index_exists(db_at_head):
    engine = db_at_head
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT indexname FROM pg_indexes
            WHERE tablename = 'document_chunks'
              AND indexname = 'ix_chunks_workspace_document'
        """)).scalar()
    assert rows == "ix_chunks_workspace_document"


def test_downgrade_drops_column_and_index(reset_test_db, alembic_cfg):
    from alembic import command
    from sqlalchemy import create_engine

    command.downgrade(alembic_cfg, "base")
    command.upgrade(alembic_cfg, "head")
    command.downgrade(alembic_cfg, "-1")

    engine = create_engine(reset_test_db)
    with engine.connect() as conn:
        col = conn.execute(text("""
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'document_chunks' AND column_name = 'workspace_id'
        """)).scalar()
        idx = conn.execute(text("""
            SELECT 1 FROM pg_indexes
            WHERE indexname = 'ix_chunks_workspace_document'
        """)).scalar()
    assert col is None
    assert idx is None
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend
pytest tests/test_migration_chunks_workspace_id.py -v
```

Expected: failures referencing the missing `workspace_id` column or `ix_chunks_workspace_document` index.

- [ ] **Step 3: Generate the migration and write it**

```bash
cd backend
alembic revision -m "add_chunks_workspace_id"
```

Open the new file. Set `down_revision` to **the previous task's revision hash** (Task 1's). Replace the body with:

```python
"""add document_chunks.workspace_id

Revision ID: <generated>
Revises: <Task 1's revision id>
Create Date: ...

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "<generated>"
down_revision: Union[str, Sequence[str], None] = "<Task 1's id>"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Nullable column so backfill can populate it.
    op.add_column(
        "document_chunks",
        sa.Column("workspace_id", sa.String(), nullable=True),
    )

    # 2. Backfill from parent document.
    op.execute(
        """
        UPDATE document_chunks dc
        SET workspace_id = d.workspace_id
        FROM documents d
        WHERE dc.document_id = d.id
        """
    )

    # 3. NOT NULL.
    op.alter_column("document_chunks", "workspace_id", nullable=False)

    # 4. FK with CASCADE delete (matches existing workspace FK conventions).
    op.create_foreign_key(
        "fk_chunks_workspace_id",
        "document_chunks", "workspaces",
        ["workspace_id"], ["id"],
        ondelete="CASCADE",
    )

    # 5. Composite index for (workspace_id, document_id) lookups.
    op.create_index(
        "ix_chunks_workspace_document",
        "document_chunks",
        ["workspace_id", "document_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_chunks_workspace_document", table_name="document_chunks")
    op.drop_constraint("fk_chunks_workspace_id", "document_chunks", type_="foreignkey")
    op.drop_column("document_chunks", "workspace_id")
```

Update `backend/db/models.py` — `DocumentChunk` class:

```python
class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    id = Column(String, primary_key=True, default=generate_uuid, index=True)
    document_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    workspace_id = Column(
        String,
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    content = Column(Text, nullable=False)
    embedding = Column(Vector(768))
    document = relationship("Document", back_populates="chunks")
```

(Note: the `index=True` on `workspace_id` is implicit because of the named composite index. Some teams keep both for clarity; pick one and move on.)

- [ ] **Step 4: Run to verify the migration passes**

```bash
cd backend
pytest tests/test_migration_chunks_workspace_id.py -v
alembic upgrade head && alembic downgrade -1 && alembic upgrade head
```

Expected: all four tests pass; alembic roundtrip succeeds.

- [ ] **Step 5: Commit**

```bash
cd ..
git add backend/alembic/versions/*_add_chunks_workspace_id.py backend/db/models.py backend/tests/test_migration_chunks_workspace_id.py
git commit -m "feat(schema): document_chunks.workspace_id FK with backfill + composite index."
```

---

## Task 3 — Revision C: `messages.role` CHECK constraint

Adds `CHECK (role IN ('user', 'assistant', 'tool', 'memory'))`. SQLAlchemy declares `Enum(..., native_enum=False)` so the ORM and the DB constraint agree. Native Postgres ENUMs are avoided per the spec — CHECKs are cheap to drop/replace.

**Files:**
- Create: `backend/alembic/versions/<new>_add_role_check.py`
- Modify: `backend/db/models.py` (Message class)
- Create: `backend/tests/test_migration_role_check.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_migration_role_check.py`:

```python
"""Verifies migration C: messages.role CHECK constraint."""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


def _seed_session(engine) -> str:
    """Create the minimum scaffold (workspace + session) for a message insert."""
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO workspaces (id, slug, display_name, system_prompt,
                                    enabled_tools, is_builtin)
            VALUES ('ws-c', 'ws-c', 'x', '', '[]'::jsonb, false)
        """))
        conn.execute(text("""
            INSERT INTO sessions (id, title, workspace_id)
            VALUES ('sess-c', 't', 'ws-c')
        """))
    return "sess-c"


def test_each_valid_role_inserts(db_at_head):
    engine = db_at_head
    sess = _seed_session(engine)
    for role in ("user", "assistant", "tool", "memory"):
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO messages (id, session_id, role, content)
                VALUES (:id, :sess, :role, 'x')
            """), {"id": f"m-{role}", "sess": sess, "role": role})


def test_invalid_role_rejected(db_at_head):
    engine = db_at_head
    sess = _seed_session(engine)
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO messages (id, session_id, role, content)
                VALUES ('m-bad', :sess, 'garbage', 'x')
            """), {"sess": sess})


def test_downgrade_drops_constraint(reset_test_db, alembic_cfg):
    from alembic import command
    from sqlalchemy import create_engine

    command.downgrade(alembic_cfg, "base")
    command.upgrade(alembic_cfg, "head")
    command.downgrade(alembic_cfg, "-1")

    engine = create_engine(reset_test_db)
    with engine.connect() as conn:
        constraint = conn.execute(text("""
            SELECT 1 FROM information_schema.table_constraints
            WHERE table_name = 'messages' AND constraint_name = 'messages_role_check'
        """)).scalar()
    assert constraint is None
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend
pytest tests/test_migration_role_check.py -v
```

Expected: `test_invalid_role_rejected` FAILS (no constraint exists → bad role inserts succeed).

- [ ] **Step 3: Generate the migration and write it**

```bash
cd backend
alembic revision -m "add_role_check"
```

Open the new file. Set `down_revision` to Task 2's revision hash. Body:

```python
"""add messages.role CHECK constraint

Revision ID: <generated>
Revises: <Task 2's id>
Create Date: ...

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "<generated>"
down_revision: Union[str, Sequence[str], None] = "<Task 2's id>"
branch_labels = None
depends_on = None


VALID_ROLES = ("user", "assistant", "tool", "memory")


def upgrade() -> None:
    # Assert preconditions: no existing row violates the new constraint.
    # If this fails, the migration aborts before mutating schema — the operator
    # then has to fix the data and re-run.
    bad = op.get_bind().execute(
        sa.text(
            "SELECT count(*) FROM messages WHERE role NOT IN :roles"
        ).bindparams(sa.bindparam("roles", expanding=True)),
        {"roles": list(VALID_ROLES)},
    ).scalar()
    if bad:
        raise RuntimeError(
            f"Cannot add role CHECK: {bad} messages have a role outside "
            f"{VALID_ROLES}. Fix the data and re-run."
        )

    op.create_check_constraint(
        "messages_role_check",
        "messages",
        f"role IN {VALID_ROLES}",
    )


def downgrade() -> None:
    op.drop_constraint("messages_role_check", "messages", type_="check")
```

Update `backend/db/models.py` — `Message` class:

```python
from sqlalchemy import Enum  # add this import alongside the others

class Message(Base):
    __tablename__ = "messages"
    id = Column(String, primary_key=True, default=generate_uuid, index=True)
    session_id = Column(String, ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    role = Column(
        Enum("user", "assistant", "tool", "memory",
             name="messages_role_check",
             native_enum=False,
             create_constraint=False),  # alembic owns the constraint, not the ORM
        nullable=False,
    )
    content = Column(Text, nullable=False)
    status = Column(String, nullable=False, default="complete", server_default="complete")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    session = relationship("Session", back_populates="messages")
```

The `create_constraint=False` is important — without it, SQLAlchemy's `create_all` would also try to create the constraint, conflicting with alembic.

- [ ] **Step 4: Run to verify the migration passes**

```bash
cd backend
pytest tests/test_migration_role_check.py -v
alembic upgrade head && alembic downgrade -1 && alembic upgrade head
```

Expected: all three tests pass; alembic roundtrip succeeds.

- [ ] **Step 5: Commit**

```bash
cd ..
git add backend/alembic/versions/*_add_role_check.py backend/db/models.py backend/tests/test_migration_role_check.py
git commit -m "feat(schema): messages.role CHECK constraint (user|assistant|tool|memory)."
```

---

## Task 4 — Revision D: pgvector `ivfflat` index

Creates a cosine-distance ANN index on `document_chunks.embedding`. `lists=100` is reasonable for tens of thousands of chunks. `CREATE INDEX CONCURRENTLY` avoids locking writes.

**Files:**
- Create: `backend/alembic/versions/<new>_add_embedding_index.py`
- Create: `backend/tests/test_migration_embedding_index.py`
- (No `db/models.py` change — indexes that aren't referenced as `Index(...)` declaratively can be created in alembic without ORM mirroring.)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_migration_embedding_index.py`:

```python
"""Verifies migration D: ivfflat index on document_chunks.embedding."""
from sqlalchemy import text


def test_index_exists_with_correct_method_and_opclass(db_at_head):
    engine = db_at_head
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT
                indexname,
                indexdef
            FROM pg_indexes
            WHERE tablename = 'document_chunks'
              AND indexname = 'ix_chunks_embedding'
        """)).first()
    assert rows is not None, "ix_chunks_embedding does not exist"
    name, defn = rows
    assert "ivfflat" in defn.lower()
    assert "vector_cosine_ops" in defn.lower()


def test_downgrade_drops_index(reset_test_db, alembic_cfg):
    from alembic import command
    from sqlalchemy import create_engine

    command.downgrade(alembic_cfg, "base")
    command.upgrade(alembic_cfg, "head")
    command.downgrade(alembic_cfg, "-1")

    engine = create_engine(reset_test_db)
    with engine.connect() as conn:
        idx = conn.execute(text("""
            SELECT 1 FROM pg_indexes WHERE indexname = 'ix_chunks_embedding'
        """)).scalar()
    assert idx is None
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend
pytest tests/test_migration_embedding_index.py -v
```

Expected: `assert rows is not None` fails — index doesn't exist yet.

- [ ] **Step 3: Generate the migration and write it**

```bash
cd backend
alembic revision -m "add_embedding_index"
```

Open the new file. Set `down_revision` to Task 3's hash. Body:

```python
"""add pgvector ivfflat index on document_chunks.embedding

Revision ID: <generated>
Revises: <Task 3's id>
Create Date: ...

"""
from typing import Sequence, Union

from alembic import op


revision: str = "<generated>"
down_revision: Union[str, Sequence[str], None] = "<Task 3's id>"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # CONCURRENTLY avoids locking writes; the operation runs outside a
    # transaction, so alembic must be configured to allow it via the
    # autocommit_block. For a single-statement migration this is fine.
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_chunks_embedding "
            "ON document_chunks USING ivfflat "
            "(embedding vector_cosine_ops) WITH (lists = 100)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_chunks_embedding")
```

The `autocommit_block()` is the standard alembic idiom for statements (like `CREATE INDEX CONCURRENTLY`) that can't run inside a transaction.

- [ ] **Step 4: Run to verify the migration passes**

```bash
cd backend
pytest tests/test_migration_embedding_index.py -v
alembic upgrade head && alembic downgrade -1 && alembic upgrade head
```

Expected: both tests pass; alembic roundtrip succeeds.

- [ ] **Step 5: Commit**

```bash
cd ..
git add backend/alembic/versions/*_add_embedding_index.py backend/tests/test_migration_embedding_index.py
git commit -m "feat(schema): ivfflat index on document_chunks.embedding."
```

---

## Task 5 — Revision E: minor constraints

Two changes batched: `messages.session_id NOT NULL` and `documents.is_global` gets a `server_default false`. Both are integrity fixes for shapes that should have been correct from the start.

**Files:**
- Create: `backend/alembic/versions/<new>_minor_constraints.py`
- Modify: `backend/db/models.py` (Message and Document classes)
- Create: `backend/tests/test_migration_minor_constraints.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_migration_minor_constraints.py`:

```python
"""Verifies migration E: messages.session_id NOT NULL + documents.is_global server_default."""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


def _seed_workspace(engine, slug: str = "ws-e") -> str:
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO workspaces (id, slug, display_name, system_prompt,
                                    enabled_tools, is_builtin)
            VALUES (:id, :slug, 'x', '', '[]'::jsonb, false)
        """), {"id": slug, "slug": slug})
    return slug


def test_messages_session_id_not_null(db_at_head):
    engine = db_at_head
    _seed_workspace(engine)
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO messages (id, role, content)
                VALUES ('m-orphan', 'user', 'x')
            """))


def test_documents_is_global_defaults_to_false_in_db(db_at_head):
    engine = db_at_head
    ws = _seed_workspace(engine)
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO documents (id, filename, workspace_id)
            VALUES ('doc-e', 'f.txt', :ws)
        """), {"ws": ws})
        val = conn.execute(text(
            "SELECT is_global FROM documents WHERE id = 'doc-e'"
        )).scalar()
    assert val is False


def test_downgrade_restores_nullable_session_id(reset_test_db, alembic_cfg):
    from alembic import command
    from sqlalchemy import create_engine

    command.downgrade(alembic_cfg, "base")
    command.upgrade(alembic_cfg, "head")
    command.downgrade(alembic_cfg, "-1")

    engine = create_engine(reset_test_db)
    with engine.connect() as conn:
        is_nullable = conn.execute(text("""
            SELECT is_nullable FROM information_schema.columns
            WHERE table_name = 'messages' AND column_name = 'session_id'
        """)).scalar()
    assert is_nullable == "YES"
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend
pytest tests/test_migration_minor_constraints.py -v
```

Expected: at least `test_messages_session_id_not_null` fails (NULL accepted today).

- [ ] **Step 3: Generate the migration and write it**

```bash
cd backend
alembic revision -m "minor_constraints"
```

Open the new file. Set `down_revision` to Task 4's hash. Body:

```python
"""minor constraint fixes

Revision ID: <generated>
Revises: <Task 4's id>
Create Date: ...

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "<generated>"
down_revision: Union[str, Sequence[str], None] = "<Task 4's id>"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Precondition: no orphan messages.
    bad = op.get_bind().execute(
        sa.text("SELECT count(*) FROM messages WHERE session_id IS NULL")
    ).scalar()
    if bad:
        raise RuntimeError(
            f"Cannot set messages.session_id NOT NULL: {bad} rows have NULL. "
            "Delete or fix the orphans and re-run."
        )

    op.alter_column("messages", "session_id", nullable=False)
    op.alter_column(
        "documents", "is_global",
        server_default=sa.text("false"),
    )


def downgrade() -> None:
    op.alter_column("documents", "is_global", server_default=None)
    op.alter_column("messages", "session_id", nullable=True)
```

Update `backend/db/models.py`:

```python
# Message class:
session_id = Column(
    String,
    ForeignKey("sessions.id", ondelete="CASCADE"),
    nullable=False,
    index=True,
)

# Document class:
is_global = Column(Boolean, default=False, server_default=sa.text("false"), nullable=False)
```

(You'll need to add `import sqlalchemy as sa` at the top of `models.py` if not already present. Or use `from sqlalchemy import false as sql_false` and pass `server_default=sql_false()`. The first form is more readable.)

- [ ] **Step 4: Run to verify the migration passes**

```bash
cd backend
pytest tests/ -v
alembic upgrade head && alembic downgrade -1 && alembic upgrade head
```

Expected: every test in `backend/tests/` passes (including the four from previous tasks); alembic roundtrip succeeds.

- [ ] **Step 5: Commit**

```bash
cd ..
git add backend/alembic/versions/*_minor_constraints.py backend/db/models.py backend/tests/test_migration_minor_constraints.py
git commit -m "feat(schema): messages.session_id NOT NULL + documents.is_global server_default."
```

---

## Final verification (run before opening any PR)

The five migrations form a chain. Walk the whole chain end-to-end to confirm linearity:

```bash
cd backend

# Reset the test DB to base.
pytest tests/test_migrations_smoke.py -v   # confirms the fixture infra still works
alembic upgrade head                       # walks all 5 migrations in order
alembic downgrade base                     # walks them all back
alembic upgrade head                       # walks them forward again
pytest tests/ -v                            # full suite passes
```

Expected: every command exits 0; the test suite shows all migration tests passing.

If any step fails: do **not** open a PR. Diagnose, fix, re-run. The chain must be roundtrip-clean.

---

## PR strategy

Per the spec, **Phase 1 is the only phase that uses one PR per migration revision**. So:

- PR 1: Task 0 (test harness setup).
- PR 2: Task 1 (engine_config).
- PR 3: Task 2 (chunks.workspace_id).
- PR 4: Task 3 (role CHECK).
- PR 5: Task 4 (embedding index).
- PR 6: Task 5 (minor constraints).

Each PR's success criterion is: its task's tests pass, alembic up/down/up roundtrip succeeds for the new revision, no test regressions across the full `backend/tests/` suite.

Branch convention: keep them all on `refactor/phase-1-schema-foundations`. Each PR rebases on top of the previous PR's merged head. After all six merge, Phase 1 is complete; cut `refactor/phase-2-auth-boundaries` from main for the next phase.

---

## Risks and rollback

- **Backfill precondition failure (Task 1 or Task 5):** the migrations assert that no existing rows violate the new constraint before applying. If a precondition fails, the migration aborts cleanly — no schema change is made. The operator fixes the data manually (`UPDATE` or `DELETE`) and re-runs.
- **ivfflat parameter tuning (Task 4):** `lists=100` is a starting point. If recall degrades or builds get slow, retune in a follow-up migration. The current migration is a no-op if the index already exists (`IF NOT EXISTS`).
- **Rollback:** every migration has a working `downgrade()`. `alembic downgrade -1` rolls back the most recent migration. The downgrade for Task 1 (`engine_config`) is lossy in the sense that custom `engine_config` values written between Phase 1 and Phase 4 will be lost on downgrade — but at this point in time no application code reads or writes `engine_config`, so the loss is theoretical.

---

## Related memory

- [[reference-stack-commands]] — how to run Postgres, backend, frontend day-to-day.
- [[reference-debug-tools]] — autotest + screenshot harnesses for Phases 2+.
- [[feedback-karpathy-for-subagents]] — implementation agents executing this plan get Karpathy guidelines in their brief.
