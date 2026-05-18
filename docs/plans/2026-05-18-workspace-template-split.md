# Workspace/Template Table Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Apply Karpathy discipline at every step: simplicity, surgical changes, verifiable goals.

**Goal:** Split the workspaces table into two — `workspace_templates` (admin-managed blueprints) and `workspaces` (user-owned instances). Drop `is_template` and `is_builtin` columns. Add per-user `position` ordering. Eliminate the recurring "forgot to filter is_template" bug class.

**Architecture:** Single alembic migration creates the new table, copies template rows out (preserving ids so existing FK refs stay valid), then drops the now-empty template rows and the obsolete columns/indexes from `workspaces`. SQLAlchemy models follow. Every code site that previously filtered `is_template` becomes simpler. The reset endpoint reworks from `is_builtin`-gated to `template_id`-gated.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic, same as auth phases. No new dependencies.

**Reference spec:** `docs/specs/2026-05-18-workspace-template-split.md`.

**Phase A+B artifacts assumed:** auth foundation merged. Workspaces have `user_id`, `template_id`, `is_template`, `is_builtin`, `owner_can_edit`. Bootstrap admin exists.

---

## File map

| File | Action | Purpose |
|---|---|---|
| `backend/alembic/versions/<rev>_split_workspace_templates.py` | Create | Schema migration |
| `backend/db/models.py` | Modify | Add WorkspaceTemplate; drop is_template/is_builtin from Workspace; add position; re-point template_id FK |
| `backend/core/bootstrap.py` | Modify | Read templates from WorkspaceTemplate, instantiate into Workspace |
| `backend/core/workspace_access.py` | Modify | Drop is_template filter from workspace_query_dep |
| `backend/routers/admin_templates.py` | Modify | All queries switch to WorkspaceTemplate model |
| `backend/routers/workspaces.py` | Modify | Drop _validate_resettable; rework reset; add PATCH /workspaces/{slug}/position; order by position |
| `backend/services/workspaces.py` | Modify | Delete get_or_default (unused after PR #80) |
| `backend/schemas.py` | Modify | Add PositionUpdate request model |
| `backend/tests/test_migration_split_workspace_templates.py` | Create | Migration smoke |
| `backend/tests/test_workspace_position.py` | Create | Position column + ordering + PATCH endpoint |
| `backend/tests/test_workspace_reset_endpoint.py` | Create | Reset reworked |
| `backend/tests/<various>` | Modify | Update fixtures that used `is_template=True` to use WorkspaceTemplate model |

---

## Task 0: Branch setup

The branch `feat/workspace-template-split` already exists (created when the spec was committed).

- [ ] **Step 1: Verify branch**
```bash
cd /home/orbital/projects/pryzm && git status --short && git branch --show-current
```
Expected: `On branch feat/workspace-template-split`, working tree clean (spec already committed).

---

## Task 1: Schema migration — split workspace_templates

**Files:**
- Create: `backend/alembic/versions/<rev>_split_workspace_templates.py`
- Create: `backend/tests/test_migration_split_workspace_templates.py`

- [ ] **Step 1: Generate revision**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/alembic revision -m "split_workspace_templates"
```

Confirm `down_revision` resolves to whatever the current head is (likely `f0d03905ddc4` from Phase B — verify with `./venv/bin/alembic current`).

- [ ] **Step 2: Migration body**

```python
"""split_workspace_templates

Creates workspace_templates table. Copies template rows out preserving ids
so existing workspaces.template_id FK refs stay valid. Drops is_template,
is_builtin, and Phase A's partial unique indexes from workspaces. Adds
position column. Repoints template_id FK to workspace_templates.

Revision ID: <auto>
Revises: <auto>
"""
from alembic import op
import sqlalchemy as sa


revision = "<auto>"
down_revision = "<auto>"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create workspace_templates
    op.create_table(
        "workspace_templates",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("enabled_tools", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("color", sa.String(), nullable=True),
        sa.Column("engine_config", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_unique_constraint("uq_workspace_templates_slug", "workspace_templates", ["slug"])

    # 2. Copy template rows out (preserve id so existing FK refs stay valid)
    op.execute("""
        INSERT INTO workspace_templates (id, slug, display_name, system_prompt, enabled_tools, color, engine_config, created_at)
        SELECT id, slug, display_name, system_prompt, enabled_tools, color, engine_config, created_at
        FROM workspaces
        WHERE is_template = TRUE;
    """)

    # 3. Drop existing template_id FK so we can repoint it
    op.drop_constraint("fk_workspaces_template_id", "workspaces", type_="foreignkey")

    # 4. Delete template rows from workspaces
    op.execute("DELETE FROM workspaces WHERE is_template = TRUE;")

    # 5. Drop Phase A partial unique indexes
    op.execute("DROP INDEX IF EXISTS ix_workspaces_slug_template_partial;")
    op.execute("DROP INDEX IF EXISTS ix_workspaces_user_slug_instance_partial;")
    # Names may differ — the Phase A migration created two partial unique indexes
    # on workspaces; verify the actual index names with \\di in psql and adjust.

    # 6. Drop is_template and is_builtin columns
    op.drop_column("workspaces", "is_template")
    op.drop_column("workspaces", "is_builtin")

    # 7. Add new simple unique constraint
    op.create_unique_constraint("uq_workspaces_user_slug", "workspaces", ["user_id", "slug"])

    # 8. Re-create template_id FK pointing at workspace_templates
    op.create_foreign_key(
        "fk_workspaces_template_id",
        "workspaces", "workspace_templates",
        ["template_id"], ["id"],
        ondelete="SET NULL",
    )

    # 9. Add position column
    op.add_column("workspaces", sa.Column("position", sa.Integer(), nullable=False, server_default="0"))
    op.create_index("ix_workspaces_user_position", "workspaces", ["user_id", "position"])


def downgrade() -> None:
    # Drop position
    op.drop_index("ix_workspaces_user_position", "workspaces")
    op.drop_column("workspaces", "position")

    # Drop the simple unique
    op.drop_constraint("uq_workspaces_user_slug", "workspaces", type_="unique")

    # Drop the FK so we can repoint
    op.drop_constraint("fk_workspaces_template_id", "workspaces", type_="foreignkey")

    # Re-add columns
    op.add_column("workspaces", sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("workspaces", sa.Column("is_template", sa.Boolean(), nullable=False, server_default=sa.text("false")))

    # Copy templates back into workspaces
    op.execute("""
        INSERT INTO workspaces (id, slug, display_name, system_prompt, enabled_tools, color, engine_config, created_at, is_template, is_builtin, user_id, template_id, owner_can_edit)
        SELECT id, slug, display_name, system_prompt, enabled_tools, color, engine_config, created_at, TRUE, TRUE, NULL, NULL, FALSE
        FROM workspace_templates;
    """)

    # Repoint FK to workspaces.id
    op.create_foreign_key(
        "fk_workspaces_template_id",
        "workspaces", "workspaces",
        ["template_id"], ["id"],
        ondelete="SET NULL",
    )

    # Restore Phase A partial unique indexes
    op.execute("""
        CREATE UNIQUE INDEX ix_workspaces_slug_template_partial
        ON workspaces (slug) WHERE is_template = TRUE;
    """)
    op.execute("""
        CREATE UNIQUE INDEX ix_workspaces_user_slug_instance_partial
        ON workspaces (user_id, slug) WHERE is_template = FALSE AND user_id IS NOT NULL;
    """)

    # Drop workspace_templates
    op.drop_constraint("uq_workspace_templates_slug", "workspace_templates", type_="unique")
    op.drop_table("workspace_templates")
```

**Note:** the partial-unique-index names from Phase A may differ. Before running, verify with `psql \\di workspaces*` and adjust the `DROP INDEX IF EXISTS` lines accordingly.

- [ ] **Step 3: Migration smoke test**

Create `backend/tests/test_migration_split_workspace_templates.py`:

```python
"""Workspace/template split migration: schema + data preservation."""
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import NullPool

from tests.conftest import _test_database_url


def test_split_workspace_templates(db_at_revision, alembic_cfg):
    from alembic import command

    # Pre-state: at the previous head
    engine = db_at_revision("<previous-head-revision-id>")
    inspector = inspect(engine)
    assert "workspace_templates" not in inspector.get_table_names()
    workspace_cols = {c["name"] for c in inspector.get_columns("workspaces")}
    assert "is_template" in workspace_cols
    assert "is_builtin" in workspace_cols
    engine.dispose()

    # Seed: one template, one user, one instance pointing at the template
    engine = create_engine(_test_database_url(), poolclass=NullPool)
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO users (id, username, password_hash, is_admin, is_active, can_create_workspaces, created_at)
            VALUES ('u-1', 'admin', 'dummy', TRUE, TRUE, TRUE, NOW());
        """))
        conn.execute(text("""
            INSERT INTO workspaces (id, slug, display_name, system_prompt, enabled_tools, color, engine_config, is_builtin, is_template, user_id, template_id, owner_can_edit, created_at)
            VALUES ('t-1', 'tmpl-x', 'Tmpl X', 'tmpl prompt', '[]'::jsonb, NULL, '{"backend":"llama_cpp"}'::jsonb, TRUE, TRUE, NULL, NULL, FALSE, NOW()),
                   ('w-1', 'tmpl-x', 'Inst X', 'inst prompt', '[]'::jsonb, NULL, '{"backend":"llama_cpp"}'::jsonb, FALSE, FALSE, 'u-1', 't-1', TRUE, NOW());
        """))
    engine.dispose()

    # Upgrade
    command.upgrade(alembic_cfg, "head")

    engine = create_engine(_test_database_url(), poolclass=NullPool)
    inspector = inspect(engine)

    # workspace_templates exists with the migrated row
    assert "workspace_templates" in inspector.get_table_names()
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id, slug, display_name FROM workspace_templates")).fetchall()
    assert len(rows) == 1 and rows[0].id == "t-1" and rows[0].slug == "tmpl-x"

    # is_template / is_builtin gone from workspaces
    workspace_cols = {c["name"] for c in inspector.get_columns("workspaces")}
    assert "is_template" not in workspace_cols
    assert "is_builtin" not in workspace_cols
    assert "position" in workspace_cols

    # Instance row survives in workspaces with template_id intact
    with engine.connect() as conn:
        instances = conn.execute(text("SELECT id, slug, template_id FROM workspaces")).fetchall()
    assert len(instances) == 1 and instances[0].id == "w-1" and instances[0].template_id == "t-1"

    # FK points to workspace_templates now
    fks = inspector.get_foreign_keys("workspaces")
    template_fk = next(fk for fk in fks if "template_id" in fk["constrained_columns"])
    assert template_fk["referred_table"] == "workspace_templates"

    # Downgrade restores prior shape
    command.downgrade(alembic_cfg, "<previous-head-revision-id>")
    engine.dispose()
    engine = create_engine(_test_database_url(), poolclass=NullPool)
    inspector = inspect(engine)
    assert "workspace_templates" not in inspector.get_table_names()
    workspace_cols = {c["name"] for c in inspector.get_columns("workspaces")}
    assert "is_template" in workspace_cols
    engine.dispose()
```

Replace `<previous-head-revision-id>` with the actual prior head (run `./venv/bin/alembic history | head -3` after generating the new revision).

- [ ] **Step 4: Run migration test**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest tests/test_migration_split_workspace_templates.py -v
```

If it fails on the `DROP INDEX IF EXISTS` because the index name is wrong, query the actual names with `psql -c "\\di workspaces*"` against the test DB and update the migration.

- [ ] **Step 5: Apply to dev DB**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/alembic upgrade head
```

Verify with `\\d workspaces` and `\\d workspace_templates` in psql.

- [ ] **Step 6: Commit**

```bash
cd /home/orbital/projects/pryzm && git add backend/alembic/versions/ backend/tests/test_migration_split_workspace_templates.py && \
git commit -m "feat(schema): split workspaces/workspace_templates + add position"
```

---

## Task 2: SQLAlchemy models

**Files:**
- Modify: `backend/db/models.py`

- [ ] **Step 1: Add WorkspaceTemplate class**

Place near other top-level entities, before relationship definitions:

```python
class WorkspaceTemplate(Base):
    __tablename__ = "workspace_templates"

    id = Column(String, primary_key=True, default=generate_uuid, index=True)
    slug = Column(String, nullable=False, unique=True, index=True)
    display_name = Column(String, nullable=False)
    system_prompt = Column(Text, nullable=False, default="")
    enabled_tools = Column(JSON, nullable=False, default=list)
    color = Column(String, nullable=True)
    engine_config = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
```

`Text` and `JSON` should already be imported.

- [ ] **Step 2: Update Workspace class**

In the existing `Workspace` class:
- **Delete** `is_template = Column(...)` line
- **Delete** `is_builtin = Column(...)` line
- **Change** `template_id` to reference `workspace_templates.id`:
  ```python
  template_id = Column(String, ForeignKey("workspace_templates.id", ondelete="SET NULL"), nullable=True, index=True)
  ```
- **Add** `position = Column(Integer, nullable=False, default=0, index=True)`

- [ ] **Step 3: Smoke test import**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/python -c "from db.models import User, Workspace, WorkspaceTemplate, Session, Folder; print([c.name for c in Workspace.__table__.columns])"
```

Expected: column list excludes `is_template`/`is_builtin`, includes `position`.

- [ ] **Step 4: Commit**

```bash
cd /home/orbital/projects/pryzm && git add backend/db/models.py && \
git commit -m "feat(models): add WorkspaceTemplate; drop is_template/is_builtin; add position"
```

---

## Task 3: Bootstrap reads from WorkspaceTemplate

**Files:**
- Modify: `backend/core/bootstrap.py`
- Modify: `backend/tests/test_bootstrap_admin.py`

- [ ] **Step 1: Update `_instantiate_templates_for`**

Replace the body in `backend/core/bootstrap.py`:

```python
def _instantiate_templates_for(db: DbSession, user: models.User) -> None:
    templates = db.query(models.WorkspaceTemplate).all()
    for tmpl in templates:
        instance = models.Workspace(
            slug=tmpl.slug,
            display_name=tmpl.display_name,
            system_prompt=tmpl.system_prompt,
            enabled_tools=list(tmpl.enabled_tools or []),
            is_template=... # GONE — column doesn't exist anymore
            template_id=tmpl.id,
            user_id=user.id,
            owner_can_edit=True,
            engine_config=dict(tmpl.engine_config or {}),
        )
        db.add(instance)
    db.commit()
```

Remove the `is_builtin=tmpl.is_builtin` line and the `is_template=False` line — both columns are gone.

- [ ] **Step 2: Update `_backfill_orphan_data`**

Find the line in `_backfill_orphan_data` that references `is_template`:

```python
db.query(models.Workspace).filter(
    models.Workspace.user_id.is_(None),
    models.Workspace.is_template.is_(False),  # ← drop this line
).update({"user_id": user.id}, synchronize_session=False)
```

Becomes:

```python
db.query(models.Workspace).filter(
    models.Workspace.user_id.is_(None),
).update({"user_id": user.id}, synchronize_session=False)
```

- [ ] **Step 3: Update bootstrap test fixtures**

Find tests in `backend/tests/test_bootstrap_admin.py` that seed a `Workspace(is_template=True, ...)`. Change those to seed a `WorkspaceTemplate(...)` instead.

- [ ] **Step 4: Run bootstrap tests**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest tests/test_bootstrap_admin.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
cd /home/orbital/projects/pryzm && git add backend/core/bootstrap.py backend/tests/test_bootstrap_admin.py && \
git commit -m "feat(bootstrap): read templates from WorkspaceTemplate model"
```

---

## Task 4: Simplify workspace_query_dep

**Files:**
- Modify: `backend/core/workspace_access.py`
- Modify: `backend/tests/test_workspace_query_dep.py`

- [ ] **Step 1: Drop is_template filter**

In `workspace_query_dep`, remove the `is_template.is_(False)` clause:

```python
def workspace_query_dep(
    workspace: str = Query(...),
    user: models.User = Depends(current_user),
    db: DbSession = Depends(database.get_db),
) -> models.Workspace:
    ws = (
        db.query(models.Workspace)
        .filter(
            models.Workspace.slug == workspace,
            models.Workspace.user_id == user.id,
        )
        .first()
    )
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    return ws
```

- [ ] **Step 2: Drop the corresponding test**

In `backend/tests/test_workspace_query_dep.py`, the test `test_workspace_query_dep_skips_templates` no longer applies (templates aren't in the workspaces table). Delete it.

- [ ] **Step 3: Run tests**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest tests/test_workspace_query_dep.py -v
```

Expected: 2 remaining tests pass.

- [ ] **Step 4: Commit**

```bash
cd /home/orbital/projects/pryzm && git add backend/core/workspace_access.py backend/tests/test_workspace_query_dep.py && \
git commit -m "feat(workspace): drop is_template filter from workspace_query_dep"
```

---

## Task 5: Switch admin_templates router to WorkspaceTemplate

**Files:**
- Modify: `backend/routers/admin_templates.py`
- Modify: `backend/tests/test_admin_templates_router.py`

- [ ] **Step 1: Replace all `models.Workspace` references with `models.WorkspaceTemplate`**

In `backend/routers/admin_templates.py`, the router queries templates and operates on them. Replace:
- `models.Workspace` queries that filtered `is_template=True` → `models.WorkspaceTemplate` (no filter needed)
- `models.Workspace(..., is_template=True, user_id=None, ...)` constructors → `models.WorkspaceTemplate(...)` (no is_template / is_builtin / user_id / template_id / owner_can_edit fields)
- The `instantiate` endpoint stays the same shape but creates `models.Workspace(...)` without `is_template`/`is_builtin`

Specific changes:
- `list_templates`: `db.query(models.WorkspaceTemplate).all()`
- `create_template`: dup check on `db.query(models.WorkspaceTemplate).filter_by(slug=payload.slug)`; INSERT into `WorkspaceTemplate`
- `get_template`: filter on `WorkspaceTemplate.id`
- `update_template`: same
- `delete_template`: delete from `WorkspaceTemplate`; FK ON DELETE SET NULL handles instance cleanup
- `instantiate_template`: lookup template via `WorkspaceTemplate`; INSERT into `Workspace` without is_template/is_builtin
- `push_template`: lookup template; UPDATE settings on `Workspace.template_id = ?`

- [ ] **Step 2: Update test fixtures**

In `backend/tests/test_admin_templates_router.py`, every `models.Workspace(..., is_template=True, ...)` becomes `models.WorkspaceTemplate(...)`. Drop fields that don't exist on the template model.

- [ ] **Step 3: Run tests**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest tests/test_admin_templates_router.py -v
```

Expected: 6 passed.

- [ ] **Step 4: Commit**

```bash
cd /home/orbital/projects/pryzm && git add backend/routers/admin_templates.py backend/tests/test_admin_templates_router.py && \
git commit -m "feat(admin): templates router uses WorkspaceTemplate model"
```

---

## Task 6: User workspaces router — reset rework + position endpoint + ordering

**Files:**
- Modify: `backend/routers/workspaces.py`
- Modify: `backend/schemas.py`
- Create: `backend/tests/test_workspace_reset_endpoint.py`
- Create: `backend/tests/test_workspace_position.py`

- [ ] **Step 1: Add PositionUpdate schema**

In `backend/schemas.py`:

```python
class PositionUpdate(BaseModel):
    position: int
```

- [ ] **Step 2: Drop `_validate_resettable` and rework reset endpoint**

In `backend/routers/workspaces.py`:

- Delete `_validate_resettable` function and its callers
- Find the reset endpoint (likely `POST /workspaces/{slug}/reset` or similar). Rework:

```python
@router.post("/workspaces/{slug}/reset", response_model=WorkspaceResponse)
def reset_workspace(
    workspace: models.Workspace = Depends(workspace_query_dep),
    db: Session = Depends(database.get_db),
):
    if workspace.template_id is None:
        raise HTTPException(
            status_code=400,
            detail="Workspace has no template to reset from.",
        )
    tmpl = db.query(models.WorkspaceTemplate).filter_by(id=workspace.template_id).first()
    if tmpl is None:
        raise HTTPException(status_code=404, detail="Template no longer exists.")
    workspace.system_prompt = tmpl.system_prompt
    workspace.enabled_tools = list(tmpl.enabled_tools or [])
    workspace.color = tmpl.color
    workspace.engine_config = dict(tmpl.engine_config or {})
    db.commit()
    db.refresh(workspace)
    return _to_response(workspace)
```

Note: the existing `_to_response` may include `is_builtin` — drop that line since the column is gone.

- [ ] **Step 3: Update listing endpoint to order by position**

In `list_workspaces`, change `order_by` to:

```python
.order_by(models.Workspace.position.asc(), models.Workspace.created_at.asc())
```

- [ ] **Step 4: Add PATCH /workspaces/{slug}/position endpoint**

```python
@router.patch("/workspaces/{slug}/position", response_model=WorkspaceResponse)
def update_workspace_position(
    payload: PositionUpdate,
    workspace: models.Workspace = Depends(workspace_query_dep),
    user: models.User = Depends(cookie_auth.current_user),
    db: Session = Depends(database.get_db),
):
    if payload.position < 0:
        raise HTTPException(status_code=400, detail="position must be non-negative")
    new_pos = payload.position
    old_pos = workspace.position
    if new_pos == old_pos:
        return _to_response(workspace)

    # Shift other workspaces in this user's set to make room
    if new_pos < old_pos:
        # Moving up: bump everything in [new_pos, old_pos) down by 1
        db.query(models.Workspace).filter(
            models.Workspace.user_id == user.id,
            models.Workspace.id != workspace.id,
            models.Workspace.position >= new_pos,
            models.Workspace.position < old_pos,
        ).update({"position": models.Workspace.position + 1}, synchronize_session=False)
    else:
        # Moving down: bump everything in (old_pos, new_pos] up by 1
        db.query(models.Workspace).filter(
            models.Workspace.user_id == user.id,
            models.Workspace.id != workspace.id,
            models.Workspace.position > old_pos,
            models.Workspace.position <= new_pos,
        ).update({"position": models.Workspace.position - 1}, synchronize_session=False)

    workspace.position = new_pos
    db.commit()
    db.refresh(workspace)
    return _to_response(workspace)
```

- [ ] **Step 5: Update create_workspace and any `_to_response` to drop is_builtin**

`_to_response`: remove `is_builtin=workspace.is_builtin`.
`create_workspace`: remove any `is_builtin=...` or `is_template=...` from the constructor (columns don't exist anymore).
Constructor should also set `position` — likely `position=` next available value for the user (max + 1) or just leave default 0 (last; reorder later).

- [ ] **Step 6: Tests for reset**

Create `backend/tests/test_workspace_reset_endpoint.py`:

```python
"""POST /workspaces/{slug}/reset re-copies settings from template."""
import pytest
from fastapi.testclient import TestClient

from core import cookie_auth
from db import database, models
from main import app


def test_reset_workspace_from_template(db_session, monkeypatch):
    admin = models.User(username="admin", password_hash=cookie_auth.hash_password("admin-pw-12chars"),
                       is_admin=True, is_active=True)
    db_session.add(admin); db_session.commit(); db_session.refresh(admin)
    tmpl = models.WorkspaceTemplate(
        id="t-1", slug="t-1", display_name="T", system_prompt="ORIGINAL",
        enabled_tools=["get_local_time"], engine_config={"backend": "llama_cpp"},
    )
    ws = models.Workspace(
        slug="t-1", display_name="T", system_prompt="EDITED",
        enabled_tools=[], engine_config={"backend": "llama_cpp"},
        user_id=admin.id, template_id="t-1", owner_can_edit=True,
    )
    db_session.add_all([tmpl, ws]); db_session.commit()

    sid = cookie_auth.create_session(db_session, admin.id)
    monkeypatch.setattr("config.settings.PRYZM_API_TOKEN", "test-token")
    app.dependency_overrides[database.get_db] = lambda: db_session
    try:
        c = TestClient(app)
        c.cookies.set(cookie_auth.COOKIE_NAME, sid)
        r = c.post("/workspaces/t-1/reset")
        assert r.status_code == 200, r.text
        db_session.expire_all()
        refreshed = db_session.query(models.Workspace).filter_by(slug="t-1", user_id=admin.id).one()
        assert refreshed.system_prompt == "ORIGINAL"
        assert refreshed.enabled_tools == ["get_local_time"]
    finally:
        app.dependency_overrides.clear()


def test_reset_workspace_without_template_returns_400(db_session, monkeypatch):
    admin = models.User(username="admin", password_hash=cookie_auth.hash_password("admin-pw-12chars"),
                       is_admin=True, is_active=True)
    db_session.add(admin); db_session.commit(); db_session.refresh(admin)
    ws = models.Workspace(
        slug="orphan", display_name="O", system_prompt="x",
        enabled_tools=[], engine_config={"backend": "llama_cpp"},
        user_id=admin.id, template_id=None,
    )
    db_session.add(ws); db_session.commit()

    sid = cookie_auth.create_session(db_session, admin.id)
    monkeypatch.setattr("config.settings.PRYZM_API_TOKEN", "test-token")
    app.dependency_overrides[database.get_db] = lambda: db_session
    try:
        c = TestClient(app)
        c.cookies.set(cookie_auth.COOKIE_NAME, sid)
        r = c.post("/workspaces/orphan/reset")
        assert r.status_code == 400
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 7: Tests for position**

Create `backend/tests/test_workspace_position.py`:

```python
"""Workspace position column + reorder endpoint + listing order."""
import pytest
from fastapi.testclient import TestClient

from core import cookie_auth
from db import database, models
from main import app


def _seed_three(db_session):
    admin = models.User(username="admin", password_hash=cookie_auth.hash_password("admin-pw-12chars"),
                       is_admin=True, is_active=True)
    db_session.add(admin); db_session.commit(); db_session.refresh(admin)
    for i, slug in enumerate(["a", "b", "c"]):
        db_session.add(models.Workspace(
            slug=slug, display_name=slug.upper(), system_prompt="",
            enabled_tools=[], engine_config={"backend": "llama_cpp"},
            user_id=admin.id, position=i,
        ))
    db_session.commit()
    return admin


def test_list_workspaces_orders_by_position(db_session, monkeypatch):
    admin = _seed_three(db_session)
    sid = cookie_auth.create_session(db_session, admin.id)
    monkeypatch.setattr("config.settings.PRYZM_API_TOKEN", "test-token")
    app.dependency_overrides[database.get_db] = lambda: db_session
    try:
        c = TestClient(app)
        c.cookies.set(cookie_auth.COOKIE_NAME, sid)
        r = c.get("/workspaces")
        assert r.status_code == 200
        slugs = [w["slug"] for w in r.json()]
        assert slugs == ["a", "b", "c"]
    finally:
        app.dependency_overrides.clear()


def test_patch_position_moves_workspace_up(db_session, monkeypatch):
    admin = _seed_three(db_session)
    sid = cookie_auth.create_session(db_session, admin.id)
    monkeypatch.setattr("config.settings.PRYZM_API_TOKEN", "test-token")
    app.dependency_overrides[database.get_db] = lambda: db_session
    try:
        c = TestClient(app)
        c.cookies.set(cookie_auth.COOKIE_NAME, sid)
        # Move 'c' (position=2) to position=0
        r = c.patch("/workspaces/c/position", json={"position": 0})
        assert r.status_code == 200
        r = c.get("/workspaces")
        slugs = [w["slug"] for w in r.json()]
        assert slugs == ["c", "a", "b"]
    finally:
        app.dependency_overrides.clear()


def test_patch_position_moves_workspace_down(db_session, monkeypatch):
    admin = _seed_three(db_session)
    sid = cookie_auth.create_session(db_session, admin.id)
    monkeypatch.setattr("config.settings.PRYZM_API_TOKEN", "test-token")
    app.dependency_overrides[database.get_db] = lambda: db_session
    try:
        c = TestClient(app)
        c.cookies.set(cookie_auth.COOKIE_NAME, sid)
        # Move 'a' (position=0) to position=2
        r = c.patch("/workspaces/a/position", json={"position": 2})
        assert r.status_code == 200
        r = c.get("/workspaces")
        slugs = [w["slug"] for w in r.json()]
        assert slugs == ["b", "c", "a"]
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 8: Run tests**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest tests/test_workspace_reset_endpoint.py tests/test_workspace_position.py -v
```

- [ ] **Step 9: Commit**

```bash
cd /home/orbital/projects/pryzm && git add backend/routers/workspaces.py backend/schemas.py backend/tests/test_workspace_reset_endpoint.py backend/tests/test_workspace_position.py && \
git commit -m "feat(workspaces): rework reset endpoint, add position ordering"
```

---

## Task 7: Delete get_or_default and audit imports

**Files:**
- Modify: `backend/services/workspaces.py`

- [ ] **Step 1: Delete `get_or_default`**

Open `backend/services/workspaces.py`, find and delete the `get_or_default` function.

- [ ] **Step 2: Audit imports**

```bash
cd /home/orbital/projects/pryzm && git grep -n "get_or_default" backend/
```

Expected: no matches (PR #80 already removed all consumers). If any remain, fix them by porting to either `workspace_query_dep` or an inline user-scoped filter.

- [ ] **Step 3: Commit**

```bash
cd /home/orbital/projects/pryzm && git add backend/services/workspaces.py && \
git commit -m "chore(workspaces): delete dead get_or_default helper"
```

---

## Task 8: Cross-cutting test fixture updates

Many tests across `backend/tests/` seed `Workspace(is_template=True, ...)` directly. After Task 2 these constructor calls will fail because the column is gone.

- [ ] **Step 1: Find affected tests**

```bash
cd /home/orbital/projects/pryzm && git grep -n "is_template=\|is_builtin=" backend/tests/
```

- [ ] **Step 2: Update each**

For each match:
- `Workspace(is_template=True, ...)` → `WorkspaceTemplate(...)` (drop the user_id, owner_can_edit, template_id fields too)
- `Workspace(is_template=False, ...)` → drop the `is_template=False` keyword
- `Workspace(..., is_builtin=...)` → drop the `is_builtin=` keyword
- Any assertion `workspace.is_template == X` → if `X=True`, replace with `isinstance(workspace, WorkspaceTemplate)` (or just delete the assertion if it was redundant)

- [ ] **Step 3: Full backend test sweep**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest -q --ignore=tests/test_image_upload.py --ignore=tests/test_upload_sse.py
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
cd /home/orbital/projects/pryzm && git add backend/tests/ && \
git commit -m "test: update fixtures to use WorkspaceTemplate model"
```

---

## Task 9: Full test sweep + manual smoke

- [ ] **Step 1: Full suite**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest -q --ignore=tests/test_image_upload.py --ignore=tests/test_upload_sse.py
```

All pass.

- [ ] **Step 2: Verify dev DB at latest migration**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/alembic current
```

Should show the new split migration as head.

- [ ] **Step 3: Restart dev backend with bootstrap env set**

```bash
lsof -ti tcp:8000 | xargs -r kill
sleep 2
cd /home/orbital/projects/pryzm/backend && ./venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --reload --reload-delay 2 &
```

- [ ] **Step 4: Smoke**

```bash
PRYZM_TOKEN=$(grep ^PRYZM_API_TOKEN /home/orbital/projects/pryzm/.env | cut -d'=' -f2-)
curl -s -H "Authorization: Bearer $PRYZM_TOKEN" http://127.0.0.1:8000/workspaces | head -c 400
curl -s -H "Authorization: Bearer $PRYZM_TOKEN" http://127.0.0.1:8000/api/admin/templates | head -c 400
```

Expected: workspace list returns user's workspaces (ordered by position), templates list returns the two builtin templates.

- [ ] **Step 5: Manual UI check (if frontend running)**

Refresh the browser. Workspaces should appear in sidebar in position order. Existing chats still accessible.

---

## Task 10: Push branch + open PR

- [ ] **Step 1: Push**

```bash
cd /home/orbital/projects/pryzm && git push -u origin feat/workspace-template-split
```

- [ ] **Step 2: Open PR**

```bash
gh pr create --base main --head feat/workspace-template-split \
  --title "feat(workspaces): split workspace_templates table + drop is_template/is_builtin + position" \
  --body "$(cat <<'EOF'
Refactor following the recurring is_template-filter bug class.

## Schema
- New table workspace_templates (admin-managed blueprints)
- Workspaces table loses is_template, is_builtin, and the partial unique indexes from Phase A
- Adds workspaces.position for per-user ordering
- template_id FK repointed at workspace_templates with ON DELETE SET NULL

## Code cleanup
- workspace_query_dep loses the is_template filter (no longer relevant)
- All admin templates endpoints switched to the WorkspaceTemplate model
- bootstrap.py reads templates from the new table
- Reset endpoint reworked from is_builtin-gated to template_id-gated (re-copy from template)
- New PATCH /workspaces/{slug}/position for sidebar/login ordering
- Dead get_or_default helper deleted

Detail in docs/specs/2026-05-18-workspace-template-split.md.
Plan in docs/plans/2026-05-18-workspace-template-split.md.
EOF
)"
```

- [ ] **Step 3: Leave PR for review** (no auto-merge unless user authorizes)

---

## Self-review

Spec coverage:

- Schema split ✓ Task 1, 2
- Drop is_template/is_builtin ✓ Tasks 1, 2
- Position column + ordering ✓ Tasks 1, 6
- workspace_templates table with kept fields ✓ Task 1, 2
- Reset endpoint rework ✓ Task 6
- Listing order by position ✓ Task 6
- PATCH position endpoint ✓ Task 6
- Bootstrap update ✓ Task 3
- Admin templates router migration ✓ Task 5
- workspace_query_dep simplification ✓ Task 4
- get_or_default deletion ✓ Task 7
- Test fixture migration ✓ Task 8

Known under-specified spots:

- Task 1: partial-unique-index names from Phase A — verify with `\\di workspaces*` in psql before assuming.
- Task 2: existing `Text`/`JSON` imports — confirm before adding.
- Task 5: existing `_template_dict` helper in admin_templates router — may need to drop is_template/is_builtin from its output shape.
- Task 6: create_workspace position default — leave as 0 (last) initially; sidebar UX can be tuned later.
- Task 8: the exact list of tests to update depends on what's in tree at the time. Run the grep first, then patch.
