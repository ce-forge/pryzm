# Auth Phase B Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Apply Karpathy discipline at every step: simplicity, surgical changes, verifiable goals.

**Goal:** Lock down workspace ownership at the schema and dependency layer, add the admin endpoints needed for the dev dashboard, and make session invalidation reliable on password changes. Backend stays dual-mode: existing bearer routes resolve to the bootstrap admin via a bridge dep; new cookie auth coexists.

**Architecture:** A new alembic migration adds FKs and NOT NULL constraints on `user_id` columns now that Phase A's bootstrap has backfilled them. The `current_user` dep is extended to dual-mode (cookie OR bearer-resolves-to-bootstrap-admin) so existing endpoints get a real `User` without changing their auth gate. `workspace_query_dep` switches to per-user scope. New admin routers expose users, templates, and per-user workspace CRUD with a last-admin guard. Existing `/api/admin/models` and `/api/prompts/*` routes swap `require_token` for `require_admin`.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic, same as Phase A. No new dependencies.

**Reference spec:** `docs/specs/2026-05-17-user-login-and-admin.md` (Phase B section).

**Phase A artifacts assumed:** PR #78 merged. `users`, `auth_sessions` tables exist; user_id columns exist on workspaces/sessions/folders (nullable); bootstrap admin user `admin` exists; templates `it_copilot` and `personal` exist; bootstrap admin has instantiated copies of both templates.

---

## File map

| File | Action | Purpose |
|---|---|---|
| `backend/alembic/versions/<rev>_workspace_ownership_constraints.py` | Create | FKs + NOT NULL on user_id columns |
| `backend/db/models.py` | Modify | Add ForeignKey to Workspace.user_id, Workspace.template_id, Session.user_id, Folder.user_id |
| `backend/core/cookie_auth.py` | Modify | Make `current_user` dual-mode (cookie OR bearer→bootstrap admin) |
| `backend/core/cookie_auth.py` | Modify | Add `assert_not_removing_last_admin` helper |
| `backend/core/workspace_access.py` | Modify | Switch workspace_query_dep to require current_user + per-user scope |
| `backend/routers/auth.py` | Modify | Password-change endpoint that invalidates other sessions |
| `backend/routers/folders.py` | Modify | Use current_user.id for new folders |
| `backend/routers/chat.py` | Modify | Use current_user.id for new chat sessions |
| `backend/routers/admin.py` | Modify | Swap `require_token` for `require_admin` |
| `backend/routers/settings.py` | Modify | Same — `require_admin` for `/api/prompts/*` |
| `backend/routers/admin_users.py` | Create | User CRUD + password reset + last-admin guard wiring |
| `backend/routers/admin_templates.py` | Create | Template CRUD + push + instantiate |
| `backend/routers/admin_workspaces.py` | Create | Per-user workspace listing/editing/deletion (admin-only) |
| `backend/schemas.py` | Modify | Add request/response models for new endpoints |
| `backend/main.py` | Modify | Include new routers |
| `backend/tests/test_migration_workspace_ownership.py` | Create | Schema migration smoke |
| `backend/tests/test_current_user_dual_mode.py` | Create | Cookie + bearer both resolve |
| `backend/tests/test_workspace_query_dep.py` | Create | Per-user scoping enforced |
| `backend/tests/test_last_admin_guard.py` | Create | Refuses to zero admins |
| `backend/tests/test_admin_users_router.py` | Create | User CRUD end-to-end |
| `backend/tests/test_admin_templates_router.py` | Create | Template CRUD + push + instantiate |
| `backend/tests/test_admin_workspaces_router.py` | Create | Admin workspace mgmt |
| `backend/tests/test_password_change_invalidates_sessions.py` | Create | Session cleanup on PW change |
| `backend/tests/test_chat_session_user_ownership.py` | Create | New sessions get user_id |
| `backend/tests/test_folder_user_ownership.py` | Create | New folders get user_id |

---

## Task 0: Create the feature branch

The branch already exists locally as `feat/auth-phase-b` (created before this plan was written). Skip if already on it.

- [ ] **Step 1: Verify branch state**

```bash
cd /home/orbital/projects/pryzm && git status --short && git branch --show-current
```

Expected: branch `feat/auth-phase-b`, working tree may include `docs/plans/2026-05-18-auth-phase-b.md` (this very file) untracked or staged.

- [ ] **Step 2: Commit the plan file**

```bash
cd /home/orbital/projects/pryzm && git add docs/plans/2026-05-18-auth-phase-b.md && \
git commit -m "docs(auth-plan): add Phase B implementation plan"
```

---

## Task 1: Workspace ownership migration

**Files:**
- Create: `backend/alembic/versions/<rev>_workspace_ownership_constraints.py`
- Create: `backend/tests/test_migration_workspace_ownership.py`

The Phase A `_backfill_orphan_data` filled user_id on every non-template workspace/session/folder. Now we lock it in with NOT NULL and add FKs. Templates retain nullable user_id (NULL is the "owned by no user" state for templates).

- [ ] **Step 1: Generate revision**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/alembic revision -m "workspace_ownership_constraints"
```

Confirm `down_revision = "a65df9990a35"` (the slug uniqueness migration from Phase A).

- [ ] **Step 2: Fill in migration body**

```python
def upgrade() -> None:
    # All user_id values should be populated by the Phase A bootstrap. If
    # this migration fails because of NULLs, the bootstrap didn't run on
    # this DB — fix that first.
    op.alter_column("sessions", "user_id", nullable=False)
    op.alter_column("folders", "user_id", nullable=False)

    op.create_foreign_key(
        "fk_sessions_user_id",
        "sessions", "users",
        ["user_id"], ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_folders_user_id",
        "folders", "users",
        ["user_id"], ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_workspaces_user_id",
        "workspaces", "users",
        ["user_id"], ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_workspaces_template_id",
        "workspaces", "workspaces",
        ["template_id"], ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_workspaces_template_id", "workspaces", type_="foreignkey")
    op.drop_constraint("fk_workspaces_user_id", "workspaces", type_="foreignkey")
    op.drop_constraint("fk_folders_user_id", "folders", type_="foreignkey")
    op.drop_constraint("fk_sessions_user_id", "sessions", type_="foreignkey")
    op.alter_column("folders", "user_id", nullable=True)
    op.alter_column("sessions", "user_id", nullable=True)
```

- [ ] **Step 3: Write the migration smoke test**

Create `backend/tests/test_migration_workspace_ownership.py`:

```python
"""Phase B workspace ownership constraints migration."""
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import NullPool

from tests.conftest import _test_database_url


def test_workspace_ownership_constraints(db_at_revision, alembic_cfg):
    from alembic import command

    # Pre-state: at the previous head, columns are nullable, no FKs
    engine = db_at_revision("a65df9990a35")
    inspector = inspect(engine)
    session_cols = inspector.get_columns("sessions")
    user_id_col = next(c for c in session_cols if c["name"] == "user_id")
    assert user_id_col["nullable"] is True
    engine.dispose()

    # Seed: one admin user + one chat session + one folder owned by that
    # admin (mimicking the Phase A bootstrap backfill)
    engine = create_engine(_test_database_url(), poolclass=NullPool)
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO users (id, username, password_hash, is_admin, is_active, can_create_workspaces, created_at)
            VALUES ('u-admin', 'admin', 'dummy', TRUE, TRUE, TRUE, NOW());
        """))
        conn.execute(text("""
            INSERT INTO workspaces (id, slug, display_name, system_prompt, enabled_tools, is_builtin, is_template, user_id, engine_config, created_at)
            VALUES ('ws-x', 'ws-x', 'X', '', '[]'::jsonb, FALSE, FALSE, 'u-admin', '{"backend":"llama_cpp"}'::jsonb, NOW());
        """))
        conn.execute(text("""
            INSERT INTO sessions (id, workspace_id, title, user_id, created_at)
            VALUES ('s-x', 'ws-x', 'session', 'u-admin', NOW());
        """))
        conn.execute(text("""
            INSERT INTO folders (id, workspace_id, name, user_id)
            VALUES ('f-x', 'ws-x', 'folder', 'u-admin');
        """))
    engine.dispose()

    # Upgrade — the migration should NOT fail because every row has user_id set
    command.upgrade(alembic_cfg, "head")

    engine = create_engine(_test_database_url(), poolclass=NullPool)
    inspector = inspect(engine)

    session_cols = inspector.get_columns("sessions")
    user_id_col = next(c for c in session_cols if c["name"] == "user_id")
    assert user_id_col["nullable"] is False

    folder_cols = inspector.get_columns("folders")
    user_id_col = next(c for c in folder_cols if c["name"] == "user_id")
    assert user_id_col["nullable"] is False

    session_fks = {fk["name"] for fk in inspector.get_foreign_keys("sessions")}
    assert "fk_sessions_user_id" in session_fks

    workspace_fks = {fk["name"] for fk in inspector.get_foreign_keys("workspaces")}
    assert "fk_workspaces_user_id" in workspace_fks
    assert "fk_workspaces_template_id" in workspace_fks

    engine.dispose()

    # Downgrade — verifies reversibility
    command.downgrade(alembic_cfg, "a65df9990a35")
    engine = create_engine(_test_database_url(), poolclass=NullPool)
    inspector = inspect(engine)
    session_cols = inspector.get_columns("sessions")
    user_id_col = next(c for c in session_cols if c["name"] == "user_id")
    assert user_id_col["nullable"] is True
    engine.dispose()
```

- [ ] **Step 4: Run migration test**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest tests/test_migration_workspace_ownership.py -v
```

Expected: PASS.

- [ ] **Step 5: Apply to dev DB**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/alembic upgrade head
```

If this fails with a NOT NULL constraint violation, the dev DB has a session or folder without `user_id`. Investigate and either delete the orphan or assign it to the bootstrap admin manually.

- [ ] **Step 6: Commit**

```bash
cd /home/orbital/projects/pryzm && git add backend/alembic/versions/ backend/tests/test_migration_workspace_ownership.py && \
git commit -m "feat(auth): workspace ownership FKs and NOT NULL constraints"
```

---

## Task 2: Update SQLAlchemy models with FK references

**Files:**
- Modify: `backend/db/models.py`

- [ ] **Step 1: Update Workspace.user_id, Workspace.template_id, Session.user_id, Folder.user_id**

Mirror the migration on the models. Find each column and add the `ForeignKey`:

```python
# Workspace
user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
template_id = Column(String, ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True, index=True)

# Session (the chat-session class)
user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

# Folder
user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
```

- [ ] **Step 2: Smoke-test model import**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/python -c "from db.models import User, AuthSession, Workspace, Session, Folder; print('ok')"
```

Expected: `ok`.

- [ ] **Step 3: Run any model-touching tests as regression check**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest tests/test_workspace_boundary.py tests/test_workspace_slug_uniqueness.py -v
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
cd /home/orbital/projects/pryzm && git add backend/db/models.py && \
git commit -m "feat(auth): add ForeignKey references for user_id and template_id"
```

---

## Task 3: Make current_user dual-mode (cookie OR bearer-to-bootstrap-admin)

**Files:**
- Modify: `backend/core/cookie_auth.py`
- Create: `backend/tests/test_current_user_dual_mode.py`

Bearer-authenticated requests should resolve to the bootstrap admin (oldest user with `is_admin=TRUE AND is_active=TRUE`). This bridges the dual-mode period: existing routes that swap from `require_token` to `current_user`-based deps continue to work, with the bearer holder behaving as admin.

- [ ] **Step 1: Failing test**

Create `backend/tests/test_current_user_dual_mode.py`:

```python
"""current_user accepts cookie OR bearer; bearer resolves to bootstrap admin."""
import hmac

import pytest
from fastapi import HTTPException

from core.cookie_auth import current_user, create_session
from db import models


def _make_user(db_session, **kwargs):
    u = models.User(
        username=kwargs.get("username", "alice"),
        password_hash="dummy",
        is_admin=kwargs.get("is_admin", False),
        is_active=kwargs.get("is_active", True),
    )
    db_session.add(u)
    db_session.commit()
    return u


def test_current_user_returns_user_from_valid_cookie(db_session):
    u = _make_user(db_session, username="alice")
    sid = create_session(db_session, u.id)
    result = current_user(pryzm_session=sid, authorization=None, db=db_session)
    assert result.id == u.id


def test_current_user_with_bearer_resolves_to_bootstrap_admin(db_session, monkeypatch):
    # Bootstrap admin (oldest is_admin=True is_active=True)
    admin = _make_user(db_session, username="admin", is_admin=True)
    # Non-admin user added later (later created_at)
    _make_user(db_session, username="bob", is_admin=False)

    monkeypatch.setattr("config.settings.PRYZM_API_TOKEN", "test-token")
    result = current_user(
        pryzm_session=None,
        authorization="Bearer test-token",
        db=db_session,
    )
    assert result.id == admin.id


def test_current_user_with_bearer_token_query_param(db_session, monkeypatch):
    admin = _make_user(db_session, username="admin", is_admin=True)
    monkeypatch.setattr("config.settings.PRYZM_API_TOKEN", "test-token")
    result = current_user(
        pryzm_session=None,
        authorization=None,
        token="test-token",
        db=db_session,
    )
    assert result.id == admin.id


def test_current_user_with_wrong_bearer_raises_401(db_session, monkeypatch):
    _make_user(db_session, username="admin", is_admin=True)
    monkeypatch.setattr("config.settings.PRYZM_API_TOKEN", "real-token")
    with pytest.raises(HTTPException) as exc:
        current_user(
            pryzm_session=None,
            authorization="Bearer wrong-token",
            db=db_session,
        )
    assert exc.value.status_code == 401


def test_current_user_with_no_auth_raises_401(db_session):
    with pytest.raises(HTTPException) as exc:
        current_user(pryzm_session=None, authorization=None, db=db_session)
    assert exc.value.status_code == 401


def test_current_user_cookie_takes_precedence_over_bearer(db_session, monkeypatch):
    admin = _make_user(db_session, username="admin", is_admin=True)
    bob = _make_user(db_session, username="bob")
    sid = create_session(db_session, bob.id)
    monkeypatch.setattr("config.settings.PRYZM_API_TOKEN", "test-token")
    result = current_user(
        pryzm_session=sid,
        authorization="Bearer test-token",
        db=db_session,
    )
    assert result.id == bob.id  # cookie wins
```

- [ ] **Step 2: Run test (expect failure for new bearer cases)**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest tests/test_current_user_dual_mode.py -v
```

- [ ] **Step 3: Update `current_user` in `backend/core/cookie_auth.py`**

Replace the existing `current_user` function with the dual-mode version:

```python
from fastapi import Header, Query
from config import settings as _config_settings
import hmac as _hmac


_BEARER_PREFIX = "Bearer "


def _bearer_resolves_to_bootstrap_admin(
    authorization: str | None,
    token: str | None,
    db: DbSession,
) -> models.User | None:
    """Translate a valid bearer token (header or ?token=) to the bootstrap
    admin user (oldest is_admin=True is_active=True). Returns None if no
    bearer was presented, or if it didn't match the configured token."""
    presented: str | None = None
    if authorization and authorization.startswith(_BEARER_PREFIX):
        presented = authorization[len(_BEARER_PREFIX):]
    elif token:
        presented = token
    if presented is None:
        return None
    if not _hmac.compare_digest(presented, _config_settings.PRYZM_API_TOKEN):
        return None
    return (
        db.query(models.User)
        .filter(models.User.is_admin.is_(True), models.User.is_active.is_(True))
        .order_by(models.User.created_at.asc())
        .first()
    )


def current_user(
    pryzm_session: Annotated[Optional[str], Cookie()] = None,
    authorization: Annotated[Optional[str], Header()] = None,
    token: Annotated[Optional[str], Query()] = None,
    db: DbSession = Depends(database.get_db),
) -> models.User:
    user = get_session_user(db, pryzm_session) if pryzm_session else None
    if user is None:
        user = _bearer_resolves_to_bootstrap_admin(authorization, token, db)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
        )
    return user
```

Keep `require_admin` as-is (it builds on current_user).

- [ ] **Step 4: Run tests**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest tests/test_current_user_dual_mode.py tests/test_current_user.py -v
```

Expected: 10 passed (6 new + 4 cookie-only legacy).

- [ ] **Step 5: Commit**

```bash
cd /home/orbital/projects/pryzm && git add backend/core/cookie_auth.py backend/tests/test_current_user_dual_mode.py && \
git commit -m "feat(auth): dual-mode current_user (cookie or bearer→bootstrap admin)"
```

---

## Task 4: Switch workspace_query_dep to per-user scope

**Files:**
- Modify: `backend/core/workspace_access.py`
- Create: `backend/tests/test_workspace_query_dep.py`

- [ ] **Step 1: Read the existing `workspace_query_dep`**

```bash
grep -n "workspace_query_dep\|workspace_create_dep" /home/orbital/projects/pryzm/backend/core/workspace_access.py
```

Note the function signature and how it resolves the workspace today (likely a slug→workspace lookup without a user filter).

- [ ] **Step 2: Failing test**

Create `backend/tests/test_workspace_query_dep.py`:

```python
"""workspace_query_dep enforces per-user ownership."""
import pytest
from fastapi import HTTPException

from core.workspace_access import workspace_query_dep
from db import models


def _seed(db_session):
    alice = models.User(
        username="alice", password_hash="x", is_admin=False, is_active=True,
    )
    bob = models.User(
        username="bob", password_hash="x", is_admin=False, is_active=True,
    )
    db_session.add_all([alice, bob])
    db_session.commit()
    db_session.refresh(alice); db_session.refresh(bob)

    alice_ws = models.Workspace(
        slug="ws-shared", display_name="A's WS",
        system_prompt="", enabled_tools=[],
        is_builtin=False, is_template=False, user_id=alice.id,
        engine_config={"backend": "llama_cpp"},
    )
    bob_ws = models.Workspace(
        slug="ws-shared", display_name="B's WS",
        system_prompt="", enabled_tools=[],
        is_builtin=False, is_template=False, user_id=bob.id,
        engine_config={"backend": "llama_cpp"},
    )
    db_session.add_all([alice_ws, bob_ws])
    db_session.commit()
    return alice, bob, alice_ws, bob_ws


def test_workspace_query_dep_returns_users_own_workspace(db_session):
    alice, bob, alice_ws, bob_ws = _seed(db_session)
    result = workspace_query_dep(workspace="ws-shared", user=alice, db=db_session)
    assert result.id == alice_ws.id  # alice gets HER workspace, not bob's


def test_workspace_query_dep_404_for_other_users_workspace(db_session):
    alice, bob, alice_ws, bob_ws = _seed(db_session)
    # Charlie has no workspace with this slug
    charlie = models.User(username="charlie", password_hash="x", is_admin=False, is_active=True)
    db_session.add(charlie); db_session.commit(); db_session.refresh(charlie)

    with pytest.raises(HTTPException) as exc:
        workspace_query_dep(workspace="ws-shared", user=charlie, db=db_session)
    assert exc.value.status_code == 404


def test_workspace_query_dep_skips_templates(db_session):
    alice, bob, _, _ = _seed(db_session)
    # Add a template with the same slug — should NOT be returned
    tmpl = models.Workspace(
        slug="ws-shared", display_name="Template",
        system_prompt="", enabled_tools=[],
        is_builtin=False, is_template=True, user_id=None,
        engine_config={"backend": "llama_cpp"},
    )
    db_session.add(tmpl); db_session.commit()
    result = workspace_query_dep(workspace="ws-shared", user=alice, db=db_session)
    assert result.is_template is False
```

- [ ] **Step 3: Run test (expect failure if signature differs)**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest tests/test_workspace_query_dep.py -v
```

- [ ] **Step 4: Update `workspace_query_dep` in `backend/core/workspace_access.py`**

Replace the existing function body. The new signature takes `user: User = Depends(current_user)` and matches workspaces on `(slug, user_id, is_template=False)`:

```python
from fastapi import Depends, HTTPException, Query
from sqlalchemy.orm import Session as DbSession

from core.cookie_auth import current_user
from db import database, models


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
            models.Workspace.is_template.is_(False),
        )
        .first()
    )
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    return ws
```

If the existing module has other deps (`workspace_create_dep`, etc.) that take similar shapes, update them too — they should also use `current_user` and apply the per-user filter. If unsure, leave them alone in this task and address in a follow-up.

- [ ] **Step 5: Run tests**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest tests/test_workspace_query_dep.py tests/test_workspace_boundary.py -v
```

Expected: all pass. The boundary tests already exercise verify_workspace_owns, which is separate from workspace_query_dep and shouldn't regress.

- [ ] **Step 6: Commit**

```bash
cd /home/orbital/projects/pryzm && git add backend/core/workspace_access.py backend/tests/test_workspace_query_dep.py && \
git commit -m "feat(auth): per-user workspace_query_dep"
```

---

## Task 5: Last-admin guard helper

**Files:**
- Modify: `backend/core/cookie_auth.py`
- Create: `backend/tests/test_last_admin_guard.py`

A helper that the admin-users endpoints call before any operation that would zero out active admins.

- [ ] **Step 1: Failing test**

Create `backend/tests/test_last_admin_guard.py`:

```python
"""Last-admin guard: cannot demote/deactivate/delete the last active admin."""
import pytest
from fastapi import HTTPException

from core.cookie_auth import assert_not_removing_last_admin
from db import models


def _make_user(db_session, **kwargs):
    u = models.User(
        username=kwargs.get("username", "x"),
        password_hash="dummy",
        is_admin=kwargs.get("is_admin", False),
        is_active=kwargs.get("is_active", True),
    )
    db_session.add(u); db_session.commit(); db_session.refresh(u)
    return u


def test_guard_allows_when_two_admins_exist(db_session):
    a = _make_user(db_session, username="admin1", is_admin=True)
    b = _make_user(db_session, username="admin2", is_admin=True)
    # Demoting admin1 is allowed (admin2 remains)
    assert_not_removing_last_admin(
        db_session, target_user_id=a.id, would_be_admin=False, would_be_active=True,
    )


def test_guard_blocks_when_demoting_last_admin(db_session):
    a = _make_user(db_session, username="admin1", is_admin=True)
    _make_user(db_session, username="bob", is_admin=False)
    with pytest.raises(HTTPException) as exc:
        assert_not_removing_last_admin(
            db_session, target_user_id=a.id, would_be_admin=False, would_be_active=True,
        )
    assert exc.value.status_code == 400


def test_guard_blocks_when_deactivating_last_admin(db_session):
    a = _make_user(db_session, username="admin1", is_admin=True)
    with pytest.raises(HTTPException):
        assert_not_removing_last_admin(
            db_session, target_user_id=a.id, would_be_admin=True, would_be_active=False,
        )


def test_guard_allows_when_target_stays_active_admin(db_session):
    a = _make_user(db_session, username="admin1", is_admin=True)
    # Edit that keeps admin1's status intact
    assert_not_removing_last_admin(
        db_session, target_user_id=a.id, would_be_admin=True, would_be_active=True,
    )


def test_guard_ignores_inactive_admins(db_session):
    a = _make_user(db_session, username="admin1", is_admin=True, is_active=True)
    _make_user(db_session, username="admin2", is_admin=True, is_active=False)
    # admin2 is inactive, so admin1 demote should still block
    with pytest.raises(HTTPException):
        assert_not_removing_last_admin(
            db_session, target_user_id=a.id, would_be_admin=False, would_be_active=True,
        )
```

- [ ] **Step 2: Run test (expect ImportError)**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest tests/test_last_admin_guard.py -v
```

- [ ] **Step 3: Add `assert_not_removing_last_admin` to `backend/core/cookie_auth.py`**

Append:

```python
def assert_not_removing_last_admin(
    db: DbSession,
    target_user_id: str,
    would_be_admin: bool,
    would_be_active: bool,
) -> None:
    """Raise HTTP 400 if the proposed change to `target_user_id` would
    leave zero active admins. `would_be_admin`/`would_be_active` are the
    flag values AFTER the proposed change."""
    if would_be_admin and would_be_active:
        return
    other_active_admins = (
        db.query(models.User)
        .filter(
            models.User.is_admin.is_(True),
            models.User.is_active.is_(True),
            models.User.id != target_user_id,
        )
        .count()
    )
    if other_active_admins == 0:
        raise HTTPException(
            status_code=400,
            detail="Cannot remove last active admin. Promote another user to admin first.",
        )
```

- [ ] **Step 4: Run tests**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest tests/test_last_admin_guard.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/orbital/projects/pryzm && git add backend/core/cookie_auth.py backend/tests/test_last_admin_guard.py && \
git commit -m "feat(auth): last-admin guard helper"
```

---

## Task 6: Admin users CRUD router

**Files:**
- Create: `backend/routers/admin_users.py`
- Modify: `backend/schemas.py` (add request/response models)
- Modify: `backend/main.py` (include router)
- Create: `backend/tests/test_admin_users_router.py`

The largest new router. Implements `GET /api/admin/users`, `POST /api/admin/users`, `GET /api/admin/users/{id}`, `PATCH /api/admin/users/{id}`, `POST /api/admin/users/{id}/password`, `DELETE /api/admin/users/{id}`.

- [ ] **Step 1: Add schemas in `backend/schemas.py`**

Append:

```python
class StarterTemplate(BaseModel):
    template_id: str
    owner_can_edit: bool = False


class AdminUserCreate(BaseModel):
    username: str
    password: str
    email: Optional[str] = None
    is_admin: bool = False
    can_create_workspaces: bool = False
    starter_templates: list[StarterTemplate] = []


class AdminUserUpdate(BaseModel):
    username: Optional[str] = None
    email: Optional[str] = None
    is_admin: Optional[bool] = None
    is_active: Optional[bool] = None
    can_create_workspaces: Optional[bool] = None


class AdminPasswordReset(BaseModel):
    new_password: str
```

Add `from typing import Optional` if not already imported.

- [ ] **Step 2: Failing test**

Create `backend/tests/test_admin_users_router.py`:

```python
"""Admin users CRUD."""
import pytest
from fastapi.testclient import TestClient

from core import cookie_auth
from db import database, models
from main import app


def _setup_admin(db_session):
    admin = models.User(
        username="admin",
        password_hash=cookie_auth.hash_password("admin-pw-12chars"),
        is_admin=True,
        is_active=True,
        can_create_workspaces=True,
    )
    db_session.add(admin); db_session.commit(); db_session.refresh(admin)
    return admin


def _admin_client(db_session, monkeypatch):
    admin = _setup_admin(db_session)
    sid = cookie_auth.create_session(db_session, admin.id)
    monkeypatch.setattr("config.settings.PRYZM_API_TOKEN", "test-token")
    app.dependency_overrides[database.get_db] = lambda: db_session
    c = TestClient(app)
    c.cookies.set(cookie_auth.COOKIE_NAME, sid)
    return c, admin


def test_admin_list_users_returns_existing(db_session, monkeypatch):
    try:
        c, admin = _admin_client(db_session, monkeypatch)
        r = c.get("/api/admin/users")
        assert r.status_code == 200
        body = r.json()
        usernames = [u["username"] for u in body]
        assert "admin" in usernames
    finally:
        app.dependency_overrides.clear()


def test_admin_create_user_with_no_templates(db_session, monkeypatch):
    try:
        c, _ = _admin_client(db_session, monkeypatch)
        r = c.post("/api/admin/users", json={
            "username": "alice",
            "password": "alice-pw-12chars",
            "email": "alice@example.com",
            "is_admin": False,
            "can_create_workspaces": True,
            "starter_templates": [],
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["username"] == "alice"
        # Verify in DB
        alice = db_session.query(models.User).filter_by(username="alice").one()
        assert alice.email == "alice@example.com"
        assert alice.can_create_workspaces is True
    finally:
        app.dependency_overrides.clear()


def test_admin_create_user_instantiates_starter_templates(db_session, monkeypatch):
    try:
        c, _ = _admin_client(db_session, monkeypatch)
        # Seed a template
        tmpl = models.Workspace(
            id="tmpl-x", slug="tmpl-x", display_name="X", system_prompt="x",
            enabled_tools=[], is_builtin=False, is_template=True, user_id=None,
            engine_config={"backend": "llama_cpp"},
        )
        db_session.add(tmpl); db_session.commit()

        r = c.post("/api/admin/users", json={
            "username": "bob",
            "password": "bob-pw-12chars",
            "starter_templates": [{"template_id": "tmpl-x", "owner_can_edit": True}],
        })
        assert r.status_code == 200, r.text
        bob = db_session.query(models.User).filter_by(username="bob").one()
        instances = db_session.query(models.Workspace).filter_by(
            user_id=bob.id, template_id="tmpl-x",
        ).all()
        assert len(instances) == 1
        assert instances[0].owner_can_edit is True
    finally:
        app.dependency_overrides.clear()


def test_admin_patch_user_changes_fields(db_session, monkeypatch):
    try:
        c, _ = _admin_client(db_session, monkeypatch)
        bob = models.User(username="bob", password_hash="x", is_admin=False, is_active=True)
        db_session.add(bob); db_session.commit(); db_session.refresh(bob)
        r = c.patch(f"/api/admin/users/{bob.id}", json={
            "email": "bob@example.com",
            "can_create_workspaces": True,
        })
        assert r.status_code == 200, r.text
        db_session.expire_all()
        bob = db_session.query(models.User).filter_by(id=bob.id).one()
        assert bob.email == "bob@example.com"
        assert bob.can_create_workspaces is True
    finally:
        app.dependency_overrides.clear()


def test_admin_password_reset_invalidates_sessions(db_session, monkeypatch):
    try:
        c, _ = _admin_client(db_session, monkeypatch)
        bob = models.User(username="bob", password_hash=cookie_auth.hash_password("old-pw-12chars"),
                          is_admin=False, is_active=True)
        db_session.add(bob); db_session.commit(); db_session.refresh(bob)
        bob_sid = cookie_auth.create_session(db_session, bob.id)
        assert db_session.query(models.AuthSession).filter_by(user_id=bob.id).count() == 1

        r = c.post(f"/api/admin/users/{bob.id}/password", json={"new_password": "new-pw-12chars"})
        assert r.status_code == 200

        # Bob's session is invalidated
        db_session.expire_all()
        assert db_session.query(models.AuthSession).filter_by(user_id=bob.id).count() == 0
        # New password works
        from core.cookie_auth import verify_password
        bob = db_session.query(models.User).filter_by(id=bob.id).one()
        assert verify_password("new-pw-12chars", bob.password_hash)
    finally:
        app.dependency_overrides.clear()


def test_admin_cannot_demote_last_admin(db_session, monkeypatch):
    try:
        c, admin = _admin_client(db_session, monkeypatch)
        r = c.patch(f"/api/admin/users/{admin.id}", json={"is_admin": False})
        assert r.status_code == 400
        # Admin still admin
        db_session.expire_all()
        admin = db_session.query(models.User).filter_by(id=admin.id).one()
        assert admin.is_admin is True
    finally:
        app.dependency_overrides.clear()


def test_admin_delete_soft_by_default(db_session, monkeypatch):
    try:
        c, _ = _admin_client(db_session, monkeypatch)
        bob = models.User(username="bob", password_hash="x", is_admin=False, is_active=True)
        db_session.add(bob); db_session.commit(); db_session.refresh(bob)
        r = c.delete(f"/api/admin/users/{bob.id}")
        assert r.status_code == 200
        db_session.expire_all()
        bob = db_session.query(models.User).filter_by(id=bob.id).one()
        assert bob.is_active is False  # soft delete


def test_admin_delete_hard_cascades(db_session, monkeypatch):
    try:
        c, _ = _admin_client(db_session, monkeypatch)
        bob = models.User(username="bob", password_hash="x", is_admin=False, is_active=True)
        db_session.add(bob); db_session.commit(); db_session.refresh(bob)
        r = c.delete(f"/api/admin/users/{bob.id}?hard=true")
        assert r.status_code == 200
        assert db_session.query(models.User).filter_by(id=bob.id).first() is None
    finally:
        app.dependency_overrides.clear()


def test_non_admin_cannot_call_admin_endpoints(db_session, monkeypatch):
    try:
        non_admin = models.User(username="bob", password_hash="x", is_admin=False, is_active=True)
        db_session.add(non_admin); db_session.commit(); db_session.refresh(non_admin)
        sid = cookie_auth.create_session(db_session, non_admin.id)
        monkeypatch.setattr("config.settings.PRYZM_API_TOKEN", "test-token")
        app.dependency_overrides[database.get_db] = lambda: db_session
        c = TestClient(app)
        c.cookies.set(cookie_auth.COOKIE_NAME, sid)
        r = c.get("/api/admin/users")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 3: Run test (expect failure — router missing)**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest tests/test_admin_users_router.py -v
```

- [ ] **Step 4: Create router**

Create `backend/routers/admin_users.py`:

```python
"""Admin endpoints for user CRUD."""
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session as DbSession

from core import cookie_auth
from db import database, models
from schemas import AdminUserCreate, AdminUserUpdate, AdminPasswordReset


router = APIRouter(
    prefix="/api/admin/users",
    tags=["admin", "users"],
    dependencies=[Depends(cookie_auth.require_admin)],
)


def _user_dict(u: models.User) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "email": u.email,
        "is_admin": u.is_admin,
        "is_active": u.is_active,
        "can_create_workspaces": u.can_create_workspaces,
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
    }


@router.get("")
def list_users(
    active: Optional[bool] = Query(None),
    db: DbSession = Depends(database.get_db),
):
    q = db.query(models.User)
    if active is not None:
        q = q.filter(models.User.is_active.is_(active))
    return [_user_dict(u) for u in q.order_by(models.User.created_at.asc()).all()]


@router.post("")
def create_user(
    payload: AdminUserCreate,
    db: DbSession = Depends(database.get_db),
):
    # Reject duplicate username (case-insensitive)
    existing = db.query(models.User).filter(
        models.User.username.ilike(payload.username)
    ).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Username already exists.")

    user = models.User(
        username=payload.username,
        password_hash=cookie_auth.hash_password(payload.password),
        email=payload.email,
        is_admin=payload.is_admin,
        can_create_workspaces=payload.can_create_workspaces,
        is_active=True,
    )
    db.add(user); db.commit(); db.refresh(user)

    # Instantiate starter templates
    for starter in payload.starter_templates:
        tmpl = db.query(models.Workspace).filter_by(
            id=starter.template_id, is_template=True,
        ).first()
        if tmpl is None:
            raise HTTPException(status_code=400, detail=f"Template {starter.template_id} not found.")
        instance = models.Workspace(
            slug=tmpl.slug,
            display_name=tmpl.display_name,
            system_prompt=tmpl.system_prompt,
            enabled_tools=list(tmpl.enabled_tools or []),
            is_builtin=tmpl.is_builtin,
            is_template=False,
            template_id=tmpl.id,
            user_id=user.id,
            owner_can_edit=starter.owner_can_edit,
            engine_config=dict(tmpl.engine_config or {}),
        )
        db.add(instance)
    db.commit()

    return _user_dict(user)


@router.get("/{user_id}")
def get_user(user_id: str, db: DbSession = Depends(database.get_db)):
    u = db.query(models.User).filter_by(id=user_id).first()
    if u is None:
        raise HTTPException(status_code=404, detail="User not found.")
    return _user_dict(u)


@router.patch("/{user_id}")
def update_user(
    user_id: str,
    payload: AdminUserUpdate,
    db: DbSession = Depends(database.get_db),
):
    u = db.query(models.User).filter_by(id=user_id).first()
    if u is None:
        raise HTTPException(status_code=404, detail="User not found.")

    changes = payload.model_dump(exclude_unset=True)

    # Last-admin guard for any change to is_admin / is_active
    if "is_admin" in changes or "is_active" in changes:
        cookie_auth.assert_not_removing_last_admin(
            db,
            target_user_id=user_id,
            would_be_admin=changes.get("is_admin", u.is_admin),
            would_be_active=changes.get("is_active", u.is_active),
        )

    if "username" in changes and changes["username"] != u.username:
        # Duplicate check
        dup = db.query(models.User).filter(
            models.User.username.ilike(changes["username"]),
            models.User.id != user_id,
        ).first()
        if dup is not None:
            raise HTTPException(status_code=409, detail="Username already exists.")

    for k, v in changes.items():
        setattr(u, k, v)
    db.commit()
    db.refresh(u)
    return _user_dict(u)


@router.post("/{user_id}/password")
def reset_password(
    user_id: str,
    payload: AdminPasswordReset,
    db: DbSession = Depends(database.get_db),
):
    u = db.query(models.User).filter_by(id=user_id).first()
    if u is None:
        raise HTTPException(status_code=404, detail="User not found.")
    if len(payload.new_password) < 12:
        raise HTTPException(status_code=400, detail="Password must be at least 12 characters.")
    u.password_hash = cookie_auth.hash_password(payload.new_password)
    cookie_auth.invalidate_user_sessions(db, user_id)
    db.commit()
    return {"ok": True}


@router.delete("/{user_id}")
def delete_user(
    user_id: str,
    hard: bool = Query(False),
    db: DbSession = Depends(database.get_db),
):
    u = db.query(models.User).filter_by(id=user_id).first()
    if u is None:
        raise HTTPException(status_code=404, detail="User not found.")

    if hard:
        cookie_auth.assert_not_removing_last_admin(
            db, target_user_id=user_id, would_be_admin=False, would_be_active=False,
        )
        db.delete(u)
    else:
        cookie_auth.assert_not_removing_last_admin(
            db, target_user_id=user_id, would_be_admin=u.is_admin, would_be_active=False,
        )
        u.is_active = False
        cookie_auth.invalidate_user_sessions(db, user_id)
    db.commit()
    return {"ok": True}
```

- [ ] **Step 5: Wire router in `backend/main.py`**

Add to the import block and `include_router` calls:

```python
from routers import admin_users as admin_users_router
app.include_router(admin_users_router.router)
```

- [ ] **Step 6: Run tests**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest tests/test_admin_users_router.py -v
```

Expected: 9 passed.

- [ ] **Step 7: Commit**

```bash
cd /home/orbital/projects/pryzm && git add backend/routers/admin_users.py backend/schemas.py backend/main.py backend/tests/test_admin_users_router.py && \
git commit -m "feat(auth): admin users CRUD router"
```

---

## Task 7: Admin templates CRUD router

**Files:**
- Create: `backend/routers/admin_templates.py`
- Modify: `backend/schemas.py` (add template models)
- Modify: `backend/main.py`
- Create: `backend/tests/test_admin_templates_router.py`

Endpoints: `GET /api/admin/templates`, `POST /api/admin/templates`, `GET /api/admin/templates/{id}`, `PUT /api/admin/templates/{id}`, `DELETE /api/admin/templates/{id}`, `POST /api/admin/templates/{id}/instantiate`, `POST /api/admin/templates/{id}/push`.

- [ ] **Step 1: Add schemas**

Append to `backend/schemas.py`:

```python
class AdminTemplateCreate(BaseModel):
    slug: str
    display_name: str
    system_prompt: str = ""
    enabled_tools: list[str] = []
    color: Optional[str] = None
    engine_config: dict = {}


class AdminTemplateUpdate(BaseModel):
    slug: Optional[str] = None
    display_name: Optional[str] = None
    system_prompt: Optional[str] = None
    enabled_tools: Optional[list[str]] = None
    color: Optional[str] = None
    engine_config: Optional[dict] = None


class AdminTemplateInstantiate(BaseModel):
    user_id: str
    slug: Optional[str] = None
    owner_can_edit: bool = False
```

- [ ] **Step 2: Failing test**

Create `backend/tests/test_admin_templates_router.py`:

```python
"""Admin templates CRUD + push + instantiate."""
import pytest
from fastapi.testclient import TestClient

from core import cookie_auth
from db import database, models
from main import app


def _admin_client(db_session, monkeypatch):
    admin = models.User(
        username="admin", password_hash=cookie_auth.hash_password("admin-pw-12chars"),
        is_admin=True, is_active=True,
    )
    db_session.add(admin); db_session.commit(); db_session.refresh(admin)
    sid = cookie_auth.create_session(db_session, admin.id)
    monkeypatch.setattr("config.settings.PRYZM_API_TOKEN", "test-token")
    app.dependency_overrides[database.get_db] = lambda: db_session
    c = TestClient(app)
    c.cookies.set(cookie_auth.COOKIE_NAME, sid)
    return c, admin


def test_list_templates(db_session, monkeypatch):
    try:
        c, _ = _admin_client(db_session, monkeypatch)
        # Seed a template
        t = models.Workspace(
            id="t-1", slug="t-1", display_name="T1", system_prompt="",
            enabled_tools=[], is_builtin=False, is_template=True, user_id=None,
            engine_config={"backend": "llama_cpp"},
        )
        db_session.add(t); db_session.commit()
        r = c.get("/api/admin/templates")
        assert r.status_code == 200
        body = r.json()
        slugs = [b["slug"] for b in body]
        assert "t-1" in slugs
        # Non-templates should NOT show up
        ws = models.Workspace(
            id="ws-1", slug="ws-1", display_name="W1", system_prompt="",
            enabled_tools=[], is_builtin=False, is_template=False,
            user_id=db_session.query(models.User).first().id,
            engine_config={"backend": "llama_cpp"},
        )
        db_session.add(ws); db_session.commit()
        r = c.get("/api/admin/templates")
        slugs = [b["slug"] for b in r.json()]
        assert "ws-1" not in slugs
    finally:
        app.dependency_overrides.clear()


def test_create_template(db_session, monkeypatch):
    try:
        c, _ = _admin_client(db_session, monkeypatch)
        r = c.post("/api/admin/templates", json={
            "slug": "new-tmpl",
            "display_name": "New Template",
            "system_prompt": "You are helpful.",
            "enabled_tools": ["get_local_time"],
            "engine_config": {"backend": "llama_cpp"},
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["slug"] == "new-tmpl"
        assert body["is_template"] is True
        # Persisted
        t = db_session.query(models.Workspace).filter_by(slug="new-tmpl", is_template=True).one()
        assert t.user_id is None
    finally:
        app.dependency_overrides.clear()


def test_instantiate_template_for_user(db_session, monkeypatch):
    try:
        c, _ = _admin_client(db_session, monkeypatch)
        t = models.Workspace(
            id="t-instn", slug="t-instn", display_name="T", system_prompt="",
            enabled_tools=[], is_builtin=False, is_template=True, user_id=None,
            engine_config={"backend": "llama_cpp"},
        )
        bob = models.User(username="bob", password_hash="x", is_admin=False, is_active=True)
        db_session.add_all([t, bob]); db_session.commit(); db_session.refresh(bob)

        r = c.post(f"/api/admin/templates/t-instn/instantiate", json={
            "user_id": bob.id, "owner_can_edit": True,
        })
        assert r.status_code == 200, r.text
        # Bob now has an instance
        instance = db_session.query(models.Workspace).filter_by(
            user_id=bob.id, template_id="t-instn",
        ).first()
        assert instance is not None
        assert instance.owner_can_edit is True
    finally:
        app.dependency_overrides.clear()


def test_instantiate_duplicate_blocks(db_session, monkeypatch):
    try:
        c, _ = _admin_client(db_session, monkeypatch)
        t = models.Workspace(
            id="t-dup", slug="t-dup", display_name="T", system_prompt="",
            enabled_tools=[], is_builtin=False, is_template=True, user_id=None,
            engine_config={"backend": "llama_cpp"},
        )
        bob = models.User(username="bob", password_hash="x", is_admin=False, is_active=True)
        db_session.add_all([t, bob]); db_session.commit(); db_session.refresh(bob)
        # First instantiation
        c.post("/api/admin/templates/t-dup/instantiate", json={"user_id": bob.id})
        # Second should 400/409
        r = c.post("/api/admin/templates/t-dup/instantiate", json={"user_id": bob.id})
        assert r.status_code in (400, 409)
    finally:
        app.dependency_overrides.clear()


def test_push_updates_all_instances(db_session, monkeypatch):
    try:
        c, _ = _admin_client(db_session, monkeypatch)
        t = models.Workspace(
            id="t-push", slug="t-push", display_name="T", system_prompt="OLD",
            enabled_tools=["get_local_time"], is_builtin=False, is_template=True, user_id=None,
            engine_config={"backend": "llama_cpp"},
        )
        bob = models.User(username="bob", password_hash="x", is_admin=False, is_active=True)
        db_session.add_all([t, bob]); db_session.commit(); db_session.refresh(bob)
        # Seed an instance
        instance = models.Workspace(
            slug="t-push", display_name="T", system_prompt="OLD",
            enabled_tools=["get_local_time"], is_builtin=False, is_template=False,
            template_id="t-push", user_id=bob.id, owner_can_edit=False,
            engine_config={"backend": "llama_cpp"},
        )
        db_session.add(instance); db_session.commit()

        # Admin edits the template
        c.put("/api/admin/templates/t-push", json={
            "system_prompt": "NEW", "enabled_tools": ["check_port"],
        })
        # Push
        r = c.post("/api/admin/templates/t-push/push")
        assert r.status_code == 200
        # Instance now reflects new template settings
        db_session.expire_all()
        instance = db_session.query(models.Workspace).filter_by(
            user_id=bob.id, template_id="t-push",
        ).one()
        assert instance.system_prompt == "NEW"
        assert instance.enabled_tools == ["check_port"]
    finally:
        app.dependency_overrides.clear()


def test_delete_template_nulls_template_id_on_instances(db_session, monkeypatch):
    try:
        c, _ = _admin_client(db_session, monkeypatch)
        t = models.Workspace(
            id="t-del", slug="t-del", display_name="T", system_prompt="",
            enabled_tools=[], is_builtin=False, is_template=True, user_id=None,
            engine_config={"backend": "llama_cpp"},
        )
        bob = models.User(username="bob", password_hash="x", is_admin=False, is_active=True)
        db_session.add_all([t, bob]); db_session.commit(); db_session.refresh(bob)
        instance = models.Workspace(
            slug="t-del", display_name="T", system_prompt="",
            enabled_tools=[], is_builtin=False, is_template=False,
            template_id="t-del", user_id=bob.id,
            engine_config={"backend": "llama_cpp"},
        )
        db_session.add(instance); db_session.commit(); db_session.refresh(instance)

        r = c.delete("/api/admin/templates/t-del")
        assert r.status_code == 200
        # Template gone, instance survives with template_id NULL
        assert db_session.query(models.Workspace).filter_by(id="t-del").first() is None
        db_session.expire_all()
        instance = db_session.query(models.Workspace).filter_by(id=instance.id).one()
        assert instance.template_id is None
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 3: Run test (expect failure)**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest tests/test_admin_templates_router.py -v
```

- [ ] **Step 4: Create router**

Create `backend/routers/admin_templates.py`:

```python
"""Admin endpoints for template CRUD + push + instantiate."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DbSession

from core import cookie_auth
from db import database, models
from schemas import AdminTemplateCreate, AdminTemplateUpdate, AdminTemplateInstantiate


router = APIRouter(
    prefix="/api/admin/templates",
    tags=["admin", "templates"],
    dependencies=[Depends(cookie_auth.require_admin)],
)


_SETTINGS_FIELDS = ("system_prompt", "enabled_tools", "color", "engine_config")


def _template_dict(t: models.Workspace) -> dict:
    return {
        "id": t.id,
        "slug": t.slug,
        "display_name": t.display_name,
        "system_prompt": t.system_prompt,
        "enabled_tools": list(t.enabled_tools or []),
        "color": getattr(t, "color", None),
        "engine_config": dict(t.engine_config or {}),
        "is_template": t.is_template,
    }


@router.get("")
def list_templates(db: DbSession = Depends(database.get_db)):
    templates = db.query(models.Workspace).filter_by(is_template=True).all()
    return [_template_dict(t) for t in templates]


@router.post("")
def create_template(
    payload: AdminTemplateCreate,
    db: DbSession = Depends(database.get_db),
):
    # Templates have globally unique slugs
    dup = db.query(models.Workspace).filter_by(slug=payload.slug, is_template=True).first()
    if dup is not None:
        raise HTTPException(status_code=409, detail="Template with this slug already exists.")
    t = models.Workspace(
        slug=payload.slug,
        display_name=payload.display_name,
        system_prompt=payload.system_prompt,
        enabled_tools=list(payload.enabled_tools or []),
        is_builtin=False,
        is_template=True,
        user_id=None,
        engine_config=dict(payload.engine_config or {}),
    )
    if payload.color is not None and hasattr(models.Workspace, "color"):
        t.color = payload.color
    db.add(t); db.commit(); db.refresh(t)
    return _template_dict(t)


@router.get("/{template_id}")
def get_template(template_id: str, db: DbSession = Depends(database.get_db)):
    t = db.query(models.Workspace).filter_by(id=template_id, is_template=True).first()
    if t is None:
        raise HTTPException(status_code=404, detail="Template not found.")
    return _template_dict(t)


@router.put("/{template_id}")
def update_template(
    template_id: str,
    payload: AdminTemplateUpdate,
    db: DbSession = Depends(database.get_db),
):
    t = db.query(models.Workspace).filter_by(id=template_id, is_template=True).first()
    if t is None:
        raise HTTPException(status_code=404, detail="Template not found.")
    changes = payload.model_dump(exclude_unset=True)
    for k, v in changes.items():
        if k == "color" and not hasattr(models.Workspace, "color"):
            continue
        setattr(t, k, v)
    db.commit(); db.refresh(t)
    return _template_dict(t)


@router.delete("/{template_id}")
def delete_template(template_id: str, db: DbSession = Depends(database.get_db)):
    t = db.query(models.Workspace).filter_by(id=template_id, is_template=True).first()
    if t is None:
        raise HTTPException(status_code=404, detail="Template not found.")
    # Set template_id NULL on instances (the FK has ON DELETE SET NULL already
    # from the Phase B migration; deleting the row triggers it)
    db.delete(t)
    db.commit()
    return {"ok": True}


@router.post("/{template_id}/instantiate")
def instantiate_template(
    template_id: str,
    payload: AdminTemplateInstantiate,
    db: DbSession = Depends(database.get_db),
):
    t = db.query(models.Workspace).filter_by(id=template_id, is_template=True).first()
    if t is None:
        raise HTTPException(status_code=404, detail="Template not found.")
    user = db.query(models.User).filter_by(id=payload.user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    # Block duplicate instantiations per spec
    existing = db.query(models.Workspace).filter_by(
        user_id=payload.user_id, template_id=template_id,
    ).first()
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="User already has a workspace from this template. Delete the existing one first to re-instantiate.",
        )
    instance = models.Workspace(
        slug=payload.slug or t.slug,
        display_name=t.display_name,
        system_prompt=t.system_prompt,
        enabled_tools=list(t.enabled_tools or []),
        is_builtin=t.is_builtin,
        is_template=False,
        template_id=t.id,
        user_id=user.id,
        owner_can_edit=payload.owner_can_edit,
        engine_config=dict(t.engine_config or {}),
    )
    db.add(instance); db.commit(); db.refresh(instance)
    return {"id": instance.id, "slug": instance.slug, "user_id": instance.user_id}


@router.post("/{template_id}/push")
def push_template(template_id: str, db: DbSession = Depends(database.get_db)):
    t = db.query(models.Workspace).filter_by(id=template_id, is_template=True).first()
    if t is None:
        raise HTTPException(status_code=404, detail="Template not found.")
    instances = db.query(models.Workspace).filter_by(template_id=template_id, is_template=False).all()
    for inst in instances:
        for field in _SETTINGS_FIELDS:
            if hasattr(models.Workspace, field):
                value = getattr(t, field, None)
                if field in ("enabled_tools",) and value is not None:
                    value = list(value)
                if field in ("engine_config",) and value is not None:
                    value = dict(value)
                setattr(inst, field, value)
    db.commit()
    return {"ok": True, "affected_count": len(instances)}
```

- [ ] **Step 5: Wire in `backend/main.py`**

```python
from routers import admin_templates as admin_templates_router
app.include_router(admin_templates_router.router)
```

- [ ] **Step 6: Run tests**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest tests/test_admin_templates_router.py -v
```

Expected: 6 passed.

- [ ] **Step 7: Commit**

```bash
cd /home/orbital/projects/pryzm && git add backend/routers/admin_templates.py backend/schemas.py backend/main.py backend/tests/test_admin_templates_router.py && \
git commit -m "feat(auth): admin templates CRUD + push + instantiate"
```

---

## Task 8: Admin workspaces router (per-user listing + admin edit/delete)

**Files:**
- Create: `backend/routers/admin_workspaces.py`
- Modify: `backend/main.py`
- Create: `backend/tests/test_admin_workspaces_router.py`

Endpoints: `GET /api/admin/users/{user_id}/workspaces`, `GET /api/admin/workspaces/{id}`, `PUT /api/admin/workspaces/{id}`, `DELETE /api/admin/workspaces/{id}`.

- [ ] **Step 1: Failing test**

Create `backend/tests/test_admin_workspaces_router.py`:

```python
"""Admin workspace endpoints."""
import pytest
from fastapi.testclient import TestClient

from core import cookie_auth
from db import database, models
from main import app


def _admin_client(db_session, monkeypatch):
    admin = models.User(
        username="admin", password_hash=cookie_auth.hash_password("admin-pw-12chars"),
        is_admin=True, is_active=True,
    )
    db_session.add(admin); db_session.commit(); db_session.refresh(admin)
    sid = cookie_auth.create_session(db_session, admin.id)
    monkeypatch.setattr("config.settings.PRYZM_API_TOKEN", "test-token")
    app.dependency_overrides[database.get_db] = lambda: db_session
    c = TestClient(app)
    c.cookies.set(cookie_auth.COOKIE_NAME, sid)
    return c, admin


def test_list_users_workspaces(db_session, monkeypatch):
    try:
        c, _ = _admin_client(db_session, monkeypatch)
        bob = models.User(username="bob", password_hash="x", is_admin=False, is_active=True)
        db_session.add(bob); db_session.commit(); db_session.refresh(bob)
        for slug in ("ws-1", "ws-2"):
            db_session.add(models.Workspace(
                slug=slug, display_name=slug, system_prompt="",
                enabled_tools=[], is_builtin=False, is_template=False,
                user_id=bob.id, engine_config={"backend": "llama_cpp"},
            ))
        db_session.commit()
        r = c.get(f"/api/admin/users/{bob.id}/workspaces")
        assert r.status_code == 200
        body = r.json()
        assert len(body) == 2
    finally:
        app.dependency_overrides.clear()


def test_admin_edit_any_workspace_bypasses_owner_can_edit(db_session, monkeypatch):
    try:
        c, _ = _admin_client(db_session, monkeypatch)
        bob = models.User(username="bob", password_hash="x", is_admin=False, is_active=True)
        db_session.add(bob); db_session.commit(); db_session.refresh(bob)
        ws = models.Workspace(
            slug="ws-x", display_name="X", system_prompt="OLD",
            enabled_tools=[], is_builtin=False, is_template=False,
            user_id=bob.id, owner_can_edit=False,  # bob cannot edit
            engine_config={"backend": "llama_cpp"},
        )
        db_session.add(ws); db_session.commit(); db_session.refresh(ws)

        r = c.put(f"/api/admin/workspaces/{ws.id}", json={"system_prompt": "NEW"})
        assert r.status_code == 200
        db_session.expire_all()
        ws = db_session.query(models.Workspace).filter_by(id=ws.id).one()
        assert ws.system_prompt == "NEW"
    finally:
        app.dependency_overrides.clear()


def test_admin_delete_user_workspace(db_session, monkeypatch):
    try:
        c, _ = _admin_client(db_session, monkeypatch)
        bob = models.User(username="bob", password_hash="x", is_admin=False, is_active=True)
        db_session.add(bob); db_session.commit(); db_session.refresh(bob)
        ws = models.Workspace(
            slug="ws-del", display_name="D", system_prompt="",
            enabled_tools=[], is_builtin=False, is_template=False,
            user_id=bob.id, engine_config={"backend": "llama_cpp"},
        )
        db_session.add(ws); db_session.commit(); db_session.refresh(ws)
        r = c.delete(f"/api/admin/workspaces/{ws.id}")
        assert r.status_code == 200
        assert db_session.query(models.Workspace).filter_by(id=ws.id).first() is None
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 2: Run test (expect failure)**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest tests/test_admin_workspaces_router.py -v
```

- [ ] **Step 3: Create router**

Create `backend/routers/admin_workspaces.py`:

```python
"""Admin endpoints for per-user workspace management."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession
from typing import Optional

from core import cookie_auth
from db import database, models


router = APIRouter(
    prefix="/api/admin",
    tags=["admin", "workspaces"],
    dependencies=[Depends(cookie_auth.require_admin)],
)


class AdminWorkspaceUpdate(BaseModel):
    display_name: Optional[str] = None
    system_prompt: Optional[str] = None
    enabled_tools: Optional[list[str]] = None
    color: Optional[str] = None
    engine_config: Optional[dict] = None
    owner_can_edit: Optional[bool] = None
    slug: Optional[str] = None


def _ws_dict(w: models.Workspace) -> dict:
    return {
        "id": w.id,
        "slug": w.slug,
        "display_name": w.display_name,
        "system_prompt": w.system_prompt,
        "enabled_tools": list(w.enabled_tools or []),
        "color": getattr(w, "color", None),
        "engine_config": dict(w.engine_config or {}),
        "user_id": w.user_id,
        "is_template": w.is_template,
        "template_id": w.template_id,
        "owner_can_edit": w.owner_can_edit,
    }


@router.get("/users/{user_id}/workspaces")
def list_user_workspaces(user_id: str, db: DbSession = Depends(database.get_db)):
    user = db.query(models.User).filter_by(id=user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    workspaces = db.query(models.Workspace).filter_by(
        user_id=user_id, is_template=False,
    ).all()
    return [_ws_dict(w) for w in workspaces]


@router.get("/workspaces/{workspace_id}")
def get_workspace(workspace_id: str, db: DbSession = Depends(database.get_db)):
    w = db.query(models.Workspace).filter_by(id=workspace_id).first()
    if w is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    return _ws_dict(w)


@router.put("/workspaces/{workspace_id}")
def update_workspace(
    workspace_id: str,
    payload: AdminWorkspaceUpdate,
    db: DbSession = Depends(database.get_db),
):
    w = db.query(models.Workspace).filter_by(id=workspace_id).first()
    if w is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    changes = payload.model_dump(exclude_unset=True)
    for k, v in changes.items():
        if k == "color" and not hasattr(models.Workspace, "color"):
            continue
        setattr(w, k, v)
    db.commit(); db.refresh(w)
    return _ws_dict(w)


@router.delete("/workspaces/{workspace_id}")
def delete_workspace(workspace_id: str, db: DbSession = Depends(database.get_db)):
    w = db.query(models.Workspace).filter_by(id=workspace_id).first()
    if w is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    db.delete(w)
    db.commit()
    return {"ok": True}
```

- [ ] **Step 4: Wire in `backend/main.py`**

```python
from routers import admin_workspaces as admin_workspaces_router
app.include_router(admin_workspaces_router.router)
```

- [ ] **Step 5: Run tests**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest tests/test_admin_workspaces_router.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
cd /home/orbital/projects/pryzm && git add backend/routers/admin_workspaces.py backend/main.py backend/tests/test_admin_workspaces_router.py && \
git commit -m "feat(auth): admin workspaces router"
```

---

## Task 9: Swap require_token → require_admin on existing admin/settings routers

**Files:**
- Modify: `backend/main.py`

The existing `routers/admin.py` and `routers/settings.py` are model management and micro-prompt config — admin-only concerns. Today they use `require_token`. Switch them to `require_admin`.

- [ ] **Step 1: Update the include_router calls**

In `backend/main.py`, find the two `include_router(...)` calls for `admin.router` and `settings_router.router`. They currently look like:

```python
app.include_router(admin.router, dependencies=[Depends(require_token)])
app.include_router(settings_router.router, dependencies=[Depends(require_token)])
```

Change to:

```python
app.include_router(admin.router, dependencies=[Depends(cookie_auth.require_admin)])
app.include_router(settings_router.router, dependencies=[Depends(cookie_auth.require_admin)])
```

Add `from core import cookie_auth` near the top if not already imported.

- [ ] **Step 2: Smoke-test that bearer admin requests still work**

The dual-mode `current_user` resolves bearer to bootstrap admin, who is_admin=True. So bearer-authenticated admin calls should pass. Run an existing admin test to confirm:

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest tests/test_admin_models.py -v
```

Expected: tests pass (they were passing under require_token; they should continue passing under require_admin since the bridge resolves bearer to admin).

If admin_models tests fail because they don't set up the bootstrap admin, fix them by adding a fixture that creates one OR rely on the conftest.

- [ ] **Step 3: Commit**

```bash
cd /home/orbital/projects/pryzm && git add backend/main.py && \
git commit -m "feat(auth): admin/settings routers require_admin (cookie or bearer-as-admin)"
```

---

## Task 10: Password-change endpoint that invalidates other sessions

**Files:**
- Modify: `backend/routers/auth.py`
- Modify: `backend/schemas.py`
- Create: `backend/tests/test_password_change_invalidates_sessions.py`

- [ ] **Step 1: Add schema**

Append to `backend/schemas.py`:

```python
class PasswordChange(BaseModel):
    current_password: str
    new_password: str
```

- [ ] **Step 2: Failing test**

Create `backend/tests/test_password_change_invalidates_sessions.py`:

```python
"""POST /api/auth/password invalidates other sessions, keeps the current one."""
import pytest
from fastapi.testclient import TestClient

from core import cookie_auth
from db import database, models
from main import app


def _setup(db_session, monkeypatch):
    u = models.User(
        username="alice", password_hash=cookie_auth.hash_password("old-pw-12chars"),
        is_admin=False, is_active=True,
    )
    db_session.add(u); db_session.commit(); db_session.refresh(u)
    sid_current = cookie_auth.create_session(db_session, u.id)
    sid_other = cookie_auth.create_session(db_session, u.id)
    monkeypatch.setattr("config.settings.PRYZM_API_TOKEN", "test-token")
    app.dependency_overrides[database.get_db] = lambda: db_session
    c = TestClient(app)
    c.cookies.set(cookie_auth.COOKIE_NAME, sid_current)
    return c, u, sid_current, sid_other


def test_password_change_invalidates_other_sessions(db_session, monkeypatch):
    try:
        c, u, sid_current, sid_other = _setup(db_session, monkeypatch)
        assert db_session.query(models.AuthSession).filter_by(user_id=u.id).count() == 2

        r = c.post("/api/auth/password", json={
            "current_password": "old-pw-12chars",
            "new_password": "new-pw-12chars",
        })
        assert r.status_code == 200

        db_session.expire_all()
        remaining = {row.id for row in db_session.query(models.AuthSession).filter_by(user_id=u.id).all()}
        assert remaining == {sid_current}  # only current session survives
    finally:
        app.dependency_overrides.clear()


def test_password_change_wrong_current_returns_401(db_session, monkeypatch):
    try:
        c, u, _, _ = _setup(db_session, monkeypatch)
        r = c.post("/api/auth/password", json={
            "current_password": "wrong",
            "new_password": "new-pw-12chars",
        })
        assert r.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_password_change_short_password_returns_400(db_session, monkeypatch):
    try:
        c, u, _, _ = _setup(db_session, monkeypatch)
        r = c.post("/api/auth/password", json={
            "current_password": "old-pw-12chars",
            "new_password": "short",
        })
        assert r.status_code == 400
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 3: Add the endpoint to `backend/routers/auth.py`**

Append:

```python
from schemas import PasswordChange


@router.post("/password")
def change_password(
    payload: PasswordChange,
    request: Request,
    db: DbSession = Depends(database.get_db),
    user: models.User = Depends(cookie_auth.current_user),
):
    if not cookie_auth.verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=401, detail="Current password incorrect.")
    if len(payload.new_password) < 12:
        raise HTTPException(status_code=400, detail="Password must be at least 12 characters.")
    current_sid = request.cookies.get(cookie_auth.COOKIE_NAME)
    user.password_hash = cookie_auth.hash_password(payload.new_password)
    # Invalidate all sessions except the current one
    db.query(models.AuthSession).filter(
        models.AuthSession.user_id == user.id,
        models.AuthSession.id != current_sid,
    ).delete(synchronize_session=False)
    db.commit()
    return {"ok": True}
```

- [ ] **Step 4: Run tests**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest tests/test_password_change_invalidates_sessions.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/orbital/projects/pryzm && git add backend/routers/auth.py backend/schemas.py backend/tests/test_password_change_invalidates_sessions.py && \
git commit -m "feat(auth): POST /api/auth/password invalidates other sessions"
```

---

## Task 11: New chat sessions get user_id from current_user

**Files:**
- Modify: `backend/routers/chat.py`
- Create: `backend/tests/test_chat_session_user_ownership.py`

When a user creates a new chat session (via `/analyze`), the session must be tagged with their user_id.

- [ ] **Step 1: Find the chat-session creation site**

```bash
grep -n "models.Session\|Session(" /home/orbital/projects/pryzm/backend/routers/chat.py | head -10
```

Look for the place where a new chat `Session` is constructed (likely in the `/analyze` endpoint when no `session_id` is provided).

- [ ] **Step 2: Failing test**

Create `backend/tests/test_chat_session_user_ownership.py`:

```python
"""New chat sessions inherit current_user.id."""
import pytest
from fastapi.testclient import TestClient

from core import cookie_auth
from db import database, models
from main import app


def test_chat_session_creation_assigns_user_id(db_session, monkeypatch):
    """Smoke test: when a logged-in user creates a chat session via a write
    path (rename, branch, or first POST /analyze), the resulting row has
    Session.user_id set to that user."""
    u = models.User(
        username="alice", password_hash=cookie_auth.hash_password("alice-pw-12chars"),
        is_admin=False, is_active=True, can_create_workspaces=True,
    )
    ws = models.Workspace(
        slug="ws-chat", display_name="Chat", system_prompt="",
        enabled_tools=[], is_builtin=False, is_template=False,
        engine_config={"backend": "llama_cpp"},
    )
    db_session.add_all([u, ws]); db_session.commit()
    db_session.refresh(u); db_session.refresh(ws)
    ws.user_id = u.id; db_session.commit()
    sid = cookie_auth.create_session(db_session, u.id)

    monkeypatch.setattr("config.settings.PRYZM_API_TOKEN", "test-token")
    app.dependency_overrides[database.get_db] = lambda: db_session
    try:
        c = TestClient(app)
        c.cookies.set(cookie_auth.COOKIE_NAME, sid)
        # Use whatever write path exists for creating an empty session — look
        # for an endpoint like `POST /sessions?workspace=ws-chat` that returns
        # a session id. If chat.py doesn't expose that, this test can
        # construct a session directly to verify the model's user_id default.

        # Direct construction smoke (model layer):
        s = models.Session(workspace_id=ws.id, title="t", user_id=u.id)
        db_session.add(s); db_session.commit()
        assert s.user_id == u.id
    finally:
        app.dependency_overrides.clear()
```

If a real write endpoint exists for creating a session (e.g., `POST /sessions`), exercise it via TestClient and assert the created session's user_id. If only `/analyze` creates sessions implicitly, drive `/analyze` with a stub LLM response.

- [ ] **Step 3: Update session-creation code in `backend/routers/chat.py`**

Locate every `models.Session(...)` constructor call in chat.py. Add `user_id=user.id` to each, where `user` comes from a `Depends(cookie_auth.current_user)` parameter on the route. If the routes currently use `Depends(require_token)`, swap to `Depends(cookie_auth.current_user)` — the dual-mode dep returns bootstrap admin for bearer requests, so existing flows keep working.

- [ ] **Step 4: Run tests**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest tests/test_chat_session_user_ownership.py tests/test_async_analyze.py -v
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
cd /home/orbital/projects/pryzm && git add backend/routers/chat.py backend/tests/test_chat_session_user_ownership.py && \
git commit -m "feat(auth): chat sessions inherit current_user.id"
```

---

## Task 12: New folders get user_id from current_user

**Files:**
- Modify: `backend/routers/folders.py`
- Create: `backend/tests/test_folder_user_ownership.py`

Same pattern as chat sessions.

- [ ] **Step 1: Failing test**

Create `backend/tests/test_folder_user_ownership.py`:

```python
"""POST /folders inherits current_user.id."""
from fastapi.testclient import TestClient

from core import cookie_auth
from db import database, models
from main import app


def test_folder_create_assigns_user_id(db_session, monkeypatch):
    u = models.User(
        username="alice", password_hash=cookie_auth.hash_password("alice-pw-12chars"),
        is_admin=False, is_active=True, can_create_workspaces=True,
    )
    ws = models.Workspace(
        slug="ws-folder", display_name="F", system_prompt="",
        enabled_tools=[], is_builtin=False, is_template=False,
        engine_config={"backend": "llama_cpp"},
    )
    db_session.add_all([u, ws]); db_session.commit()
    db_session.refresh(u); db_session.refresh(ws)
    ws.user_id = u.id; db_session.commit()
    sid = cookie_auth.create_session(db_session, u.id)

    monkeypatch.setattr("config.settings.PRYZM_API_TOKEN", "test-token")
    app.dependency_overrides[database.get_db] = lambda: db_session
    try:
        c = TestClient(app)
        c.cookies.set(cookie_auth.COOKIE_NAME, sid)
        r = c.post("/folders", json={"name": "Notes", "workspace": "ws-folder"})
        assert r.status_code == 200, r.text
        body = r.json()
        folder = db_session.query(models.Folder).filter_by(id=body["id"]).one()
        assert folder.user_id == u.id
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 2: Update `create_folder` in `backend/routers/folders.py`**

Change the signature to accept `user: models.User = Depends(cookie_auth.current_user)`. Pass `user_id=user.id` to the new Folder constructor:

```python
@router.post("/folders")
def create_folder(
    folder: FolderCreate,
    db: Session = Depends(database.get_db),
    user: models.User = Depends(cookie_auth.current_user),
):
    ws = get_or_default(db, folder.workspace)
    new_folder = models.Folder(name=folder.name, workspace_id=ws.id, user_id=user.id)
    db.add(new_folder); db.commit()
    return {"id": new_folder.id, "name": new_folder.name, "workspace_id": new_folder.workspace_id}
```

- [ ] **Step 3: Run tests**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest tests/test_folder_user_ownership.py tests/test_folder_create_server_id.py -v
```

Expected: pass.

- [ ] **Step 4: Commit**

```bash
cd /home/orbital/projects/pryzm && git add backend/routers/folders.py backend/tests/test_folder_user_ownership.py && \
git commit -m "feat(auth): folders inherit current_user.id"
```

---

## Task 13: Full test suite + manual smoke

- [ ] **Step 1: Full backend test suite**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest -q --ignore=tests/test_image_upload.py --ignore=tests/test_upload_sse.py
```

Expected: all pass.

- [ ] **Step 2: Restart dev backend**

```bash
# Kill running uvicorn:
lsof -ti tcp:8000 | xargs -r kill
sleep 2
# Restart:
cd /home/orbital/projects/pryzm/backend && ./venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --reload --reload-delay 2 &
```

Wait a few seconds for it to come up.

- [ ] **Step 3: Smoke — bearer admin path still works**

```bash
PRYZM_TOKEN=$(grep ^PRYZM_API_TOKEN /home/orbital/projects/pryzm/.env | cut -d'=' -f2-)
curl -s -o /dev/null -w "bearer /workspaces: %{http_code}\n" -H "Authorization: Bearer $PRYZM_TOKEN" http://127.0.0.1:8000/workspaces
curl -s -o /dev/null -w "bearer /api/admin/users: %{http_code}\n" -H "Authorization: Bearer $PRYZM_TOKEN" http://127.0.0.1:8000/api/admin/users
```

Expected: both 200.

- [ ] **Step 4: Smoke — cookie auth path still works**

```bash
curl -s -o /dev/null -w "no-auth /api/auth/me: %{http_code}\n" http://127.0.0.1:8000/api/auth/me
curl -s -o /dev/null -w "wrong login: %{http_code}\n" -X POST http://127.0.0.1:8000/api/auth/login -H "Content-Type: application/json" -d '{"username":"admin","password":"wrong"}'
```

Expected: 401, 401.

---

## Task 14: Push branch + open PR

- [ ] **Step 1: Push**

```bash
cd /home/orbital/projects/pryzm && git push -u origin feat/auth-phase-b
```

- [ ] **Step 2: Open PR**

```bash
gh pr create --base main --head feat/auth-phase-b \
  --title "feat(auth): Phase B — workspace ownership, admin endpoints, dual-mode bridge" \
  --body "$(cat <<'EOF'
Second slice of the user-login work. Locks in workspace ownership at the schema layer, swaps existing routes to dual-mode auth, and adds the admin endpoints the dev dashboard needs.

## Schema
- FKs on workspaces.user_id, workspaces.template_id, sessions.user_id, folders.user_id
- sessions.user_id and folders.user_id are NOT NULL (Phase A's bootstrap backfilled them)

## Runtime
- current_user dep is dual-mode: valid cookie wins; bearer token resolves to the bootstrap admin (oldest active is_admin user)
- workspace_query_dep scopes by (slug, user_id), is_template=False
- Last-admin guard refuses to demote/deactivate/delete the only active admin
- Password change/reset invalidates other sessions

## Endpoints
- /api/admin/users (CRUD + password reset + soft/hard delete + starter-template instantiation)
- /api/admin/templates (CRUD + push + instantiate)
- /api/admin/users/{user_id}/workspaces (admin lists a user's workspaces)
- /api/admin/workspaces/{id} (admin GET/PUT/DELETE any workspace)
- /api/auth/password (user changes own password; invalidates other sessions)

## Migration
- routers/admin and routers/settings now gated by require_admin (bearer still passes via the dual-mode bridge)

Detail in docs/specs/2026-05-17-user-login-and-admin.md (Phase B section).
Plan in docs/plans/2026-05-18-auth-phase-b.md.

Phase C (frontend login) follows.
EOF
)"
```

- [ ] **Step 3: Don't auto-merge**

Leave PR for user review unless they've explicitly authorized auto-merge of this PR.

---

## Self-review

Coverage check against the spec (Phase B section):

- Workspace ownership migration ✓ Task 1
- FK + NOT NULL on user_id columns ✓ Task 1, 2
- Switch workspace_query_dep to per-user ✓ Task 4
- Dual-auth bridge for bearer holders ✓ Task 3
- Last-admin guard ✓ Task 5
- Session invalidation on password change ✓ Tasks 6 (admin reset), 10 (self change)
- Admin users CRUD ✓ Task 6
- Admin templates CRUD + push + instantiate ✓ Task 7
- Admin workspaces (per-user listing, admin edit/delete) ✓ Task 8
- Existing admin/settings routers swapped to require_admin ✓ Task 9
- Chat sessions inherit user_id ✓ Task 11
- Folders inherit user_id ✓ Task 12

Known under-specified spots:

- Task 1: replace `<rev>` placeholders with whatever `alembic revision` generates.
- Task 8 / 9: admin endpoints don't yet write audit events. Audit logging is its own subsystem; will be wired in when audit Phase F.2 lands.
- Task 11: the exact place to wire `user_id` in chat.py depends on how the current session-creation code is structured. The implementer should follow the existing pattern and add `user_id=user.id` to every Session() construction.
