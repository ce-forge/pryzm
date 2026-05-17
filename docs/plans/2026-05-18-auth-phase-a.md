# Auth Phase A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Apply Karpathy discipline at every step: simplicity, surgical changes, verifiable goals — do exactly what the task says, no more, no less.

**Goal:** Add per-user auth infrastructure (cookie-based login, user/session tables, bootstrap admin) without changing how existing bearer-token-authenticated endpoints behave. Backend ends Phase A in dual-mode: existing routes continue accepting bearer; new `/api/auth/*` routes use cookies.

**Architecture:** New SQLAlchemy models (`User`, `AuthSession`) and new tables; columns added to existing `workspaces`, `sessions`, `folders` tables. New `core/cookie_auth.py` module isolates password hashing, session helpers, and the `current_user` dependency from the existing bearer-token code. New `routers/auth.py` exposes `/login`, `/logout`, `/me`. Lifespan handler creates the bootstrap admin on first boot from env vars. No existing endpoints change.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic, argon2-cffi for password hashing, Postgres for session storage, in-memory dict for login rate limiting.

**Reference spec:** `docs/specs/2026-05-17-user-login-and-admin.md` (Phase A section).

---

## File map

| File | Action | Purpose |
|---|---|---|
| `backend/requirements.txt` | Modify | Add argon2-cffi |
| `backend/alembic/versions/<rev>_auth_phase_a_schema.py` | Create | Tables + columns |
| `backend/alembic/versions/<rev>_builtins_to_templates.py` | Create | Mark `it_copilot`, `personal` as templates |
| `backend/alembic/versions/<rev>_folder_id_server_default.py` | Create | UUIDv7 default on folders.id |
| `backend/db/models.py` | Modify | Add `User`, `AuthSession`; add columns to `Workspace`, `Session`, `Folder` |
| `backend/core/cookie_auth.py` | Create | Password hashing, session helpers, current_user dep, rate limiter |
| `backend/routers/auth.py` | Create | `/api/auth/login`, `/logout`, `/me` |
| `backend/main.py` | Modify | Include auth router, add bootstrap admin to lifespan |
| `backend/schemas.py` | Modify | Drop `id` from `FolderCreate` |
| `backend/routers/folders.py` | Modify | Server-generate folder id |
| `backend/config.py` | Modify | Add `PRYZM_BOOTSTRAP_ADMIN_USERNAME`, `PRYZM_BOOTSTRAP_ADMIN_PASSWORD` |
| `backend/tests/test_password_hashing.py` | Create | Hash + verify |
| `backend/tests/test_auth_session.py` | Create | Session lifecycle helpers |
| `backend/tests/test_current_user.py` | Create | Dependency resolution |
| `backend/tests/test_login_rate_limit.py` | Create | Lockout logic |
| `backend/tests/test_auth_router.py` | Create | Login/logout/me end-to-end |
| `backend/tests/test_bootstrap_admin.py` | Create | First-boot creation |
| `backend/tests/test_migration_auth_phase_a.py` | Create | Schema migration smoke |
| `backend/tests/test_migration_builtins_to_templates.py` | Create | Data migration |
| `backend/tests/test_migration_folder_id_server_default.py` | Create | Folder default |
| `backend/tests/test_folder_create_server_id.py` | Create | API no longer requires client id |

---

## Task 0: Create the feature branch

**Files:** none yet.

- [ ] **Step 1: Verify clean working tree on main**

```bash
cd /home/orbital/projects/pryzm && git status --short && git branch --show-current
```

Expected: branch `main`, working tree clean except for unrelated WIP (`frontend/src/components/AssistantMessage.tsx`). If anything else is modified, stop and consult the user.

- [ ] **Step 2: Stash WIP if present**

```bash
cd /home/orbital/projects/pryzm && git stash push frontend/src/components/AssistantMessage.tsx -m "pre-phase-a: WIP AssistantMessage" 2>/dev/null || true
```

Acceptable if the file isn't modified (the command no-ops).

- [ ] **Step 3: Create and switch to the feature branch**

```bash
cd /home/orbital/projects/pryzm && git checkout -b feat/auth-phase-a main
```

Expected: `Switched to a new branch 'feat/auth-phase-a'`.

- [ ] **Step 4: Verify branch state**

```bash
cd /home/orbital/projects/pryzm && git status --short && git branch --show-current
```

Expected: `On branch feat/auth-phase-a`, working tree clean.

---

## Task 1: Add argon2-cffi to requirements

**Files:**
- Modify: `backend/requirements.txt`

- [ ] **Step 1: Append argon2-cffi to requirements**

Add a line `argon2-cffi==23.1.0` to `backend/requirements.txt`. Pin the version. If there's a section for security/auth libs, group it there; otherwise append at the end.

- [ ] **Step 2: Install into the venv**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pip install -r requirements.txt
```

Expected: argon2-cffi installs successfully.

- [ ] **Step 3: Verify import works**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/python -c "from argon2 import PasswordHasher; print(PasswordHasher().hash('test')[:20])"
```

Expected: prints an argon2 hash prefix like `$argon2id$v=19$m=...`.

- [ ] **Step 4: Commit**

```bash
cd /home/orbital/projects/pryzm && git add backend/requirements.txt && \
git commit -m "feat(auth): add argon2-cffi for password hashing"
```

---

## Task 2: Schema migration — Phase A auth tables and columns

**Files:**
- Create: `backend/alembic/versions/<rev>_auth_phase_a_schema.py`

This migration creates the `users` and `auth_sessions` tables, and adds new columns to `workspaces`, `sessions`, `folders`, and `users` itself. No FK constraints on `user_id` columns yet (Phase B adds those after backfill).

- [ ] **Step 1: Generate the revision**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/alembic revision -m "auth_phase_a_schema"
```

Note the new revision id and file path. Check current head with `./venv/bin/alembic current` if needed.

- [ ] **Step 2: Fill in the migration body**

Replace the generated upgrade/downgrade with:

```python
"""auth_phase_a_schema

Creates users + auth_sessions tables. Adds user_id (nullable, no FK yet),
is_template, template_id, owner_can_edit columns to workspaces. Adds
user_id (nullable) to sessions and folders. Adds can_create_workspaces
to a separate users column already created above.

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
    op.create_table(
        "users",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("can_create_workspaces", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_users_username_lower",
        "users",
        [sa.text("lower(username)")],
        unique=True,
    )

    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])

    # workspaces: user_id (nullable for templates), is_template, template_id, owner_can_edit
    op.add_column("workspaces", sa.Column("user_id", sa.String(), nullable=True))
    op.add_column("workspaces", sa.Column("is_template", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("workspaces", sa.Column("template_id", sa.String(), nullable=True))
    op.add_column("workspaces", sa.Column("owner_can_edit", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.create_index("ix_workspaces_user_id", "workspaces", ["user_id"])
    op.create_index("ix_workspaces_template_id", "workspaces", ["template_id"])

    # sessions: user_id (nullable for Phase A; Phase B makes NOT NULL + FK)
    op.add_column("sessions", sa.Column("user_id", sa.String(), nullable=True))
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])

    # folders: user_id (nullable for Phase A; Phase B makes NOT NULL + FK)
    op.add_column("folders", sa.Column("user_id", sa.String(), nullable=True))
    op.create_index("ix_folders_user_id", "folders", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_folders_user_id", "folders")
    op.drop_column("folders", "user_id")
    op.drop_index("ix_sessions_user_id", "sessions")
    op.drop_column("sessions", "user_id")
    op.drop_index("ix_workspaces_template_id", "workspaces")
    op.drop_index("ix_workspaces_user_id", "workspaces")
    op.drop_column("workspaces", "owner_can_edit")
    op.drop_column("workspaces", "template_id")
    op.drop_column("workspaces", "is_template")
    op.drop_column("workspaces", "user_id")
    op.drop_index("ix_auth_sessions_user_id", "auth_sessions")
    op.drop_index("ix_auth_sessions_expires_at", "auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_index("ix_users_username_lower", "users")
    op.drop_table("users")
```

Leave the auto-generated `revision`, `down_revision`, `branch_labels`, `depends_on` values intact.

- [ ] **Step 3: Write the migration test**

Create `backend/tests/test_migration_auth_phase_a.py`:

```python
"""Phase A schema migration: tables + columns + indexes."""
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import NullPool

from tests.conftest import _test_database_url


def test_auth_phase_a_schema_upgrades_and_downgrades(db_at_revision, alembic_cfg):
    from alembic import command

    # Upgrade to the migration just before ours
    engine = db_at_revision("<previous-head-revision-id>")
    inspector = inspect(engine)
    assert "users" not in inspector.get_table_names()
    engine.dispose()

    # Upgrade through our migration
    command.upgrade(alembic_cfg, "head")
    engine = create_engine(_test_database_url(), poolclass=NullPool)
    inspector = inspect(engine)

    assert "users" in inspector.get_table_names()
    assert "auth_sessions" in inspector.get_table_names()

    user_cols = {c["name"] for c in inspector.get_columns("users")}
    assert {"id", "username", "password_hash", "email", "is_admin",
            "is_active", "can_create_workspaces", "created_at", "last_login_at"} <= user_cols

    auth_session_cols = {c["name"] for c in inspector.get_columns("auth_sessions")}
    assert {"id", "user_id", "created_at", "expires_at", "last_seen_at"} <= auth_session_cols

    workspace_cols = {c["name"] for c in inspector.get_columns("workspaces")}
    assert {"user_id", "is_template", "template_id", "owner_can_edit"} <= workspace_cols

    session_cols = {c["name"] for c in inspector.get_columns("sessions")}
    assert "user_id" in session_cols

    folder_cols = {c["name"] for c in inspector.get_columns("folders")}
    assert "user_id" in folder_cols
    engine.dispose()

    # Downgrade
    command.downgrade(alembic_cfg, "-1")
    engine = create_engine(_test_database_url(), poolclass=NullPool)
    inspector = inspect(engine)
    assert "users" not in inspector.get_table_names()
    assert "auth_sessions" not in inspector.get_table_names()
    workspace_cols = {c["name"] for c in inspector.get_columns("workspaces")}
    assert "user_id" not in workspace_cols
    engine.dispose()
```

Replace `<previous-head-revision-id>` with the actual previous head (run `./venv/bin/alembic history | head -3` after generating the revision to see it).

- [ ] **Step 4: Run the migration test**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest tests/test_migration_auth_phase_a.py -v
```

Expected: PASS.

- [ ] **Step 5: Apply the migration to the dev DB**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/alembic upgrade head
```

Expected: migration runs cleanly.

- [ ] **Step 6: Commit**

```bash
cd /home/orbital/projects/pryzm && git add backend/alembic/versions/ backend/tests/test_migration_auth_phase_a.py && \
git commit -m "feat(auth): add Phase A schema migration"
```

---

## Task 3: Data migration — builtin workspaces become templates

**Files:**
- Create: `backend/alembic/versions/<rev>_builtins_to_templates.py`
- Create: `backend/tests/test_migration_builtins_to_templates.py`

- [ ] **Step 1: Generate revision**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/alembic revision -m "builtins_to_templates"
```

- [ ] **Step 2: Fill in migration body**

```python
"""builtins_to_templates

Marks the two builtin workspaces (it_copilot, personal) as templates.
After this migration they have user_id NULL and is_template TRUE; admin
can instantiate them per-user during user creation.
"""
from alembic import op


revision = "<auto>"
down_revision = "<auto>"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE workspaces
           SET is_template = TRUE,
               user_id = NULL
         WHERE slug IN ('it_copilot', 'personal')
           AND is_builtin = TRUE;
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE workspaces
           SET is_template = FALSE
         WHERE slug IN ('it_copilot', 'personal')
           AND is_builtin = TRUE;
    """)
```

- [ ] **Step 3: Migration test**

Create `backend/tests/test_migration_builtins_to_templates.py`:

```python
"""Builtins-to-templates: it_copilot + personal become templates."""
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from tests.conftest import _test_database_url


def test_builtins_marked_as_templates(db_at_revision, alembic_cfg):
    from alembic import command

    # Upgrade to the schema migration; builtins exist via baseline seed,
    # is_template defaults FALSE
    engine = db_at_revision("<auth-phase-a-schema-revision-id>")
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT slug, is_template FROM workspaces WHERE slug IN ('it_copilot', 'personal')"
        )).fetchall()
    assert all(row.is_template is False for row in result)
    engine.dispose()

    # Upgrade through this migration
    command.upgrade(alembic_cfg, "head")
    engine = create_engine(_test_database_url(), poolclass=NullPool)
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT slug, is_template, user_id FROM workspaces WHERE slug IN ('it_copilot', 'personal')"
        )).fetchall()
    assert all(row.is_template is True for row in result)
    assert all(row.user_id is None for row in result)
    engine.dispose()
```

Replace `<auth-phase-a-schema-revision-id>` with the actual revision id of the migration from Task 2.

- [ ] **Step 4: Run test**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest tests/test_migration_builtins_to_templates.py -v
```

Expected: PASS.

- [ ] **Step 5: Apply to dev DB**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/alembic upgrade head
```

- [ ] **Step 6: Commit**

```bash
cd /home/orbital/projects/pryzm && git add backend/alembic/versions/ backend/tests/test_migration_builtins_to_templates.py && \
git commit -m "feat(auth): mark builtin workspaces as templates"
```

---

## Task 4: Folder.id server-side default migration

**Files:**
- Create: `backend/alembic/versions/<rev>_folder_id_server_default.py`
- Create: `backend/tests/test_migration_folder_id_server_default.py`

Folder.id was client-supplied before. Add a server-side UUIDv7 default. Existing rows keep their ids.

- [ ] **Step 1: Generate revision**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/alembic revision -m "folder_id_server_default"
```

- [ ] **Step 2: Migration body**

```python
"""folder_id_server_default

folders.id was client-supplied. Add a server-side default that generates
a UUIDv7 string. Existing rows keep their current id values; the default
only applies to inserts that don't specify id.
"""
from alembic import op
import sqlalchemy as sa


revision = "<auto>"
down_revision = "<auto>"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The Python-side default lives on the SQLAlchemy model (Folder.id =
    # Column(String, default=generate_uuid, ...)). At the DB level we add a
    # NOT NULL constraint if it isn't already one. The Python default is
    # what actually generates the id at insert time.
    # If folders.id was already NOT NULL (it's a PK), this is a no-op
    # other than the comment.
    op.alter_column("folders", "id", nullable=False)


def downgrade() -> None:
    # No-op; column was already NOT NULL as a PK.
    pass
```

- [ ] **Step 3: Migration test**

Create `backend/tests/test_migration_folder_id_server_default.py`:

```python
"""folder.id server-side default migration."""
from sqlalchemy import inspect, create_engine
from sqlalchemy.pool import NullPool

from tests.conftest import _test_database_url


def test_folder_id_remains_not_null_after_migration(alembic_cfg):
    from alembic import command
    command.upgrade(alembic_cfg, "head")

    engine = create_engine(_test_database_url(), poolclass=NullPool)
    inspector = inspect(engine)
    id_col = next(c for c in inspector.get_columns("folders") if c["name"] == "id")
    assert id_col["nullable"] is False
    engine.dispose()
```

- [ ] **Step 4: Run test**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest tests/test_migration_folder_id_server_default.py -v
```

Expected: PASS.

- [ ] **Step 5: Apply to dev DB**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/alembic upgrade head
```

- [ ] **Step 6: Commit**

```bash
cd /home/orbital/projects/pryzm && git add backend/alembic/versions/ backend/tests/test_migration_folder_id_server_default.py && \
git commit -m "feat(auth): server-side default for folder.id"
```

---

## Task 5: User SQLAlchemy model

**Files:**
- Modify: `backend/db/models.py`

- [ ] **Step 1: Add the User class to `backend/db/models.py`**

Locate the existing models (Workspace, Session, etc.). Add the new model in a logical position (near other top-level entities, before the relationship definitions if any). Insert:

```python
class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=generate_uuid, index=True)
    username = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    email = Column(String, nullable=True)
    is_admin = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)
    can_create_workspaces = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_login_at = Column(DateTime(timezone=True), nullable=True)
```

Add `Boolean`, `DateTime`, `func` imports at the top of the file if not already present.

- [ ] **Step 2: Smoke-test the model import**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/python -c "from db.models import User; print(User.__tablename__, [c.name for c in User.__table__.columns])"
```

Expected: prints `users` and the column list.

- [ ] **Step 3: Commit**

```bash
cd /home/orbital/projects/pryzm && git add backend/db/models.py && \
git commit -m "feat(auth): add User model"
```

---

## Task 6: AuthSession SQLAlchemy model

**Files:**
- Modify: `backend/db/models.py`

- [ ] **Step 1: Add the AuthSession class**

After the User class, add:

```python
class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id = Column(String, primary_key=True)  # caller supplies the random token
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    last_seen_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
```

- [ ] **Step 2: Smoke-test the model import**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/python -c "from db.models import AuthSession; print(AuthSession.__tablename__, [c.name for c in AuthSession.__table__.columns])"
```

- [ ] **Step 3: Commit**

```bash
cd /home/orbital/projects/pryzm && git add backend/db/models.py && \
git commit -m "feat(auth): add AuthSession model"
```

---

## Task 7: Add new columns to Workspace, Session, Folder models

**Files:**
- Modify: `backend/db/models.py`

The migrations added columns to existing tables. Mirror them on the ORM models.

- [ ] **Step 1: Update Workspace model**

In the `Workspace` class, add (next to existing columns):

```python
    user_id = Column(String, nullable=True, index=True)
    is_template = Column(Boolean, nullable=False, default=False)
    template_id = Column(String, nullable=True, index=True)
    owner_can_edit = Column(Boolean, nullable=False, default=False)
```

No `ForeignKey` references yet — Phase B adds those.

- [ ] **Step 2: Update Session model**

In the `Session` class (the chat-session model, not auth):

```python
    user_id = Column(String, nullable=True, index=True)
```

- [ ] **Step 3: Update Folder model**

In the `Folder` class:

```python
    user_id = Column(String, nullable=True, index=True)
```

- [ ] **Step 4: Smoke-test all models import**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/python -c "from db.models import User, AuthSession, Workspace, Session, Folder; print('ok')"
```

Expected: prints `ok`.

- [ ] **Step 5: Run any existing model-touching tests as a smoke check**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest tests/test_workspace_boundary.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
cd /home/orbital/projects/pryzm && git add backend/db/models.py && \
git commit -m "feat(auth): add user_id and template columns to existing models"
```

---

## Task 8: Password hashing module

**Files:**
- Create: `backend/core/cookie_auth.py`
- Create: `backend/tests/test_password_hashing.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_password_hashing.py`:

```python
"""Password hashing via argon2id."""
import pytest

from core.cookie_auth import hash_password, verify_password


def test_hash_password_returns_argon2id_string():
    h = hash_password("hunter2")
    assert h.startswith("$argon2id$")


def test_verify_password_accepts_correct_password():
    h = hash_password("hunter2")
    assert verify_password("hunter2", h) is True


def test_verify_password_rejects_wrong_password():
    h = hash_password("hunter2")
    assert verify_password("hunter3", h) is False


def test_verify_password_handles_invalid_hash():
    # Malformed hash strings shouldn't raise — return False.
    assert verify_password("anything", "not-a-real-hash") is False


def test_hash_password_produces_unique_salts():
    a = hash_password("hunter2")
    b = hash_password("hunter2")
    assert a != b  # different salts -> different hash strings
```

- [ ] **Step 2: Run the test (expect import failure)**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest tests/test_password_hashing.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'core.cookie_auth'`.

- [ ] **Step 3: Implement the module**

Create `backend/core/cookie_auth.py`:

```python
"""Cookie-based session authentication.

Separate from core/auth.py (bearer-token) so the eventual Phase E removal
is a clean file delete + import-replace rather than function-level surgery.

This module currently covers:
- Password hashing/verification (argon2id)
- Auth session helpers (create, lookup, invalidate)
- The current_user FastAPI dependency
- Login rate limiter (in-memory)
"""
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError, VerificationError


_ph = PasswordHasher()


def hash_password(plaintext: str) -> str:
    return _ph.hash(plaintext)


def verify_password(plaintext: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, plaintext)
    except (VerifyMismatchError, InvalidHashError, VerificationError):
        return False
```

- [ ] **Step 4: Run test**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest tests/test_password_hashing.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/orbital/projects/pryzm && git add backend/core/cookie_auth.py backend/tests/test_password_hashing.py && \
git commit -m "feat(auth): password hashing module (argon2id)"
```

---

## Task 9: Auth session helpers

**Files:**
- Modify: `backend/core/cookie_auth.py`
- Create: `backend/tests/test_auth_session.py`

Adds `create_session`, `get_session`, `invalidate_session`, `invalidate_user_sessions`, plus session lifetime constants.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_auth_session.py`:

```python
"""AuthSession lifecycle helpers."""
import secrets
from datetime import datetime, timedelta, timezone

import pytest

from core import cookie_auth
from db import models


def _make_user(db_session, username="alice"):
    u = models.User(
        username=username,
        password_hash="dummy",
        is_admin=False,
        is_active=True,
    )
    db_session.add(u)
    db_session.commit()
    return u


def test_create_session_inserts_row_and_returns_id(db_session):
    u = _make_user(db_session)
    sid = cookie_auth.create_session(db_session, u.id)
    assert isinstance(sid, str) and len(sid) > 20  # base64url, ~43 chars
    row = db_session.query(models.AuthSession).filter_by(id=sid).one()
    assert row.user_id == u.id
    assert row.expires_at > datetime.now(timezone.utc)


def test_get_session_returns_user_when_valid(db_session):
    u = _make_user(db_session)
    sid = cookie_auth.create_session(db_session, u.id)
    user = cookie_auth.get_session_user(db_session, sid)
    assert user is not None
    assert user.id == u.id


def test_get_session_returns_none_for_unknown_sid(db_session):
    assert cookie_auth.get_session_user(db_session, "nonexistent") is None


def test_get_session_returns_none_for_expired(db_session):
    u = _make_user(db_session)
    sid = cookie_auth.create_session(db_session, u.id)
    # Force-expire
    row = db_session.query(models.AuthSession).filter_by(id=sid).one()
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()
    assert cookie_auth.get_session_user(db_session, sid) is None


def test_invalidate_session_removes_row(db_session):
    u = _make_user(db_session)
    sid = cookie_auth.create_session(db_session, u.id)
    cookie_auth.invalidate_session(db_session, sid)
    assert db_session.query(models.AuthSession).filter_by(id=sid).first() is None


def test_invalidate_user_sessions_removes_all_for_user(db_session):
    u = _make_user(db_session)
    sid_1 = cookie_auth.create_session(db_session, u.id)
    sid_2 = cookie_auth.create_session(db_session, u.id)
    cookie_auth.invalidate_user_sessions(db_session, u.id)
    assert db_session.query(models.AuthSession).filter_by(user_id=u.id).count() == 0


def test_get_session_updates_last_seen_at(db_session):
    u = _make_user(db_session)
    sid = cookie_auth.create_session(db_session, u.id)
    first_seen = db_session.query(models.AuthSession).filter_by(id=sid).one().last_seen_at
    # Re-fetch
    cookie_auth.get_session_user(db_session, sid)
    db_session.expire_all()
    second_seen = db_session.query(models.AuthSession).filter_by(id=sid).one().last_seen_at
    assert second_seen >= first_seen
```

- [ ] **Step 2: Run test (expect failure)**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest tests/test_auth_session.py -v
```

Expected: FAIL — function names missing.

- [ ] **Step 3: Add to `backend/core/cookie_auth.py`**

Append below the password helpers:

```python
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session as DbSession

from db import models


# Session lifetime defaults (resolved decisions: 7-day idle, 30-day hard cap)
SESSION_IDLE_TIMEOUT = timedelta(days=7)
SESSION_HARD_CAP = timedelta(days=30)


def create_session(db: DbSession, user_id: str) -> str:
    sid = secrets.token_urlsafe(32)  # ~43 chars, 256 bits
    now = datetime.now(timezone.utc)
    row = models.AuthSession(
        id=sid,
        user_id=user_id,
        created_at=now,
        last_seen_at=now,
        expires_at=now + SESSION_HARD_CAP,
    )
    db.add(row)
    db.commit()
    return sid


def get_session_user(db: DbSession, sid: str) -> models.User | None:
    """Resolve a session id to a User, sliding the idle window. Returns
    None if the session doesn't exist, is past its hard cap, or has been
    idle past the idle timeout."""
    if not sid:
        return None
    row = db.query(models.AuthSession).filter_by(id=sid).first()
    if row is None:
        return None
    now = datetime.now(timezone.utc)
    if row.expires_at <= now:
        return None
    if row.last_seen_at + SESSION_IDLE_TIMEOUT <= now:
        return None
    row.last_seen_at = now
    db.commit()
    user = db.query(models.User).filter_by(id=row.user_id).first()
    if user is None or not user.is_active:
        return None
    return user


def invalidate_session(db: DbSession, sid: str) -> None:
    db.query(models.AuthSession).filter_by(id=sid).delete()
    db.commit()


def invalidate_user_sessions(db: DbSession, user_id: str) -> None:
    db.query(models.AuthSession).filter_by(user_id=user_id).delete()
    db.commit()
```

- [ ] **Step 4: Run tests**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest tests/test_auth_session.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/orbital/projects/pryzm && git add backend/core/cookie_auth.py backend/tests/test_auth_session.py && \
git commit -m "feat(auth): session lifecycle helpers"
```

---

## Task 10: current_user FastAPI dependency

**Files:**
- Modify: `backend/core/cookie_auth.py`
- Create: `backend/tests/test_current_user.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_current_user.py`:

```python
"""current_user dependency: cookie → User resolution."""
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


def test_current_user_returns_user_for_valid_cookie(db_session):
    u = _make_user(db_session)
    sid = create_session(db_session, u.id)
    result = current_user(pryzm_session=sid, db=db_session)
    assert result.id == u.id


def test_current_user_raises_401_for_missing_cookie(db_session):
    with pytest.raises(HTTPException) as exc:
        current_user(pryzm_session=None, db=db_session)
    assert exc.value.status_code == 401


def test_current_user_raises_401_for_invalid_cookie(db_session):
    with pytest.raises(HTTPException) as exc:
        current_user(pryzm_session="not-a-real-sid", db=db_session)
    assert exc.value.status_code == 401


def test_current_user_raises_401_for_deactivated_user(db_session):
    u = _make_user(db_session, is_active=False)
    sid = create_session(db_session, u.id)
    with pytest.raises(HTTPException) as exc:
        current_user(pryzm_session=sid, db=db_session)
    assert exc.value.status_code == 401
```

- [ ] **Step 2: Run test (expect failure)**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest tests/test_current_user.py -v
```

Expected: FAIL.

- [ ] **Step 3: Add `current_user` to `backend/core/cookie_auth.py`**

Append:

```python
from typing import Annotated, Optional

from fastapi import Cookie, Depends, HTTPException, status

from db import database


COOKIE_NAME = "pryzm_session"


def current_user(
    pryzm_session: Annotated[Optional[str], Cookie()] = None,
    db: DbSession = Depends(database.get_db),
) -> models.User:
    user = get_session_user(db, pryzm_session) if pryzm_session else None
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
        )
    return user


def require_admin(user: models.User = Depends(current_user)) -> models.User:
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin only.",
        )
    return user
```

- [ ] **Step 4: Run tests**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest tests/test_current_user.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/orbital/projects/pryzm && git add backend/core/cookie_auth.py backend/tests/test_current_user.py && \
git commit -m "feat(auth): current_user and require_admin dependencies"
```

---

## Task 11: Login rate limiter

**Files:**
- Modify: `backend/core/cookie_auth.py`
- Create: `backend/tests/test_login_rate_limit.py`

In-memory per-username failed-attempts counter with a sliding window. 10 failures within 15 minutes → 15-minute lockout. Admin can clear via a future endpoint (not in Phase A; the in-memory state resets on backend restart for v1).

- [ ] **Step 1: Failing test**

Create `backend/tests/test_login_rate_limit.py`:

```python
"""Login rate limiting: lockout after N failures in a window."""
import time

import pytest

from core.cookie_auth import (
    LoginRateLimiter,
    RATE_LIMIT_FAILURES,
    RATE_LIMIT_WINDOW_SECONDS,
    LOCKOUT_SECONDS,
)


def test_rate_limiter_allows_attempts_below_threshold():
    rl = LoginRateLimiter()
    for _ in range(RATE_LIMIT_FAILURES - 1):
        rl.record_failure("alice")
    assert rl.is_locked("alice") is False


def test_rate_limiter_locks_after_threshold():
    rl = LoginRateLimiter()
    for _ in range(RATE_LIMIT_FAILURES):
        rl.record_failure("alice")
    assert rl.is_locked("alice") is True


def test_rate_limiter_unlocks_after_lockout_window(monkeypatch):
    rl = LoginRateLimiter()
    # Fake time progression
    fake_now = [1000.0]
    monkeypatch.setattr("time.monotonic", lambda: fake_now[0])
    for _ in range(RATE_LIMIT_FAILURES):
        rl.record_failure("alice")
    assert rl.is_locked("alice") is True
    fake_now[0] += LOCKOUT_SECONDS + 1
    assert rl.is_locked("alice") is False


def test_rate_limiter_record_success_clears_failures():
    rl = LoginRateLimiter()
    for _ in range(RATE_LIMIT_FAILURES - 1):
        rl.record_failure("alice")
    rl.record_success("alice")
    # Failures cleared, lockout shouldn't trigger on next failure
    rl.record_failure("alice")
    assert rl.is_locked("alice") is False


def test_rate_limiter_is_per_username():
    rl = LoginRateLimiter()
    for _ in range(RATE_LIMIT_FAILURES):
        rl.record_failure("alice")
    assert rl.is_locked("alice") is True
    assert rl.is_locked("bob") is False
```

- [ ] **Step 2: Run test (expect failure)**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest tests/test_login_rate_limit.py -v
```

- [ ] **Step 3: Add rate limiter to `backend/core/cookie_auth.py`**

Append:

```python
import time
from collections import defaultdict


RATE_LIMIT_FAILURES = 10
RATE_LIMIT_WINDOW_SECONDS = 15 * 60  # 15 minutes
LOCKOUT_SECONDS = 15 * 60            # 15-minute lockout


class LoginRateLimiter:
    """In-memory failed-login tracker per username.

    State resets on backend restart (acceptable for v1; a determined
    attacker can survive a restart but is unlikely to coordinate with
    one). Stored in process memory only; for multi-worker deployments,
    move to Redis later.
    """

    def __init__(self) -> None:
        self._failures: dict[str, list[float]] = defaultdict(list)
        self._locked_until: dict[str, float] = {}

    def _normalize(self, username: str) -> str:
        return username.lower()

    def is_locked(self, username: str) -> bool:
        key = self._normalize(username)
        until = self._locked_until.get(key)
        if until is None:
            return False
        if time.monotonic() < until:
            return True
        # Lockout expired; clear it
        del self._locked_until[key]
        self._failures.pop(key, None)
        return False

    def record_failure(self, username: str) -> None:
        key = self._normalize(username)
        now = time.monotonic()
        cutoff = now - RATE_LIMIT_WINDOW_SECONDS
        recent = [ts for ts in self._failures[key] if ts > cutoff]
        recent.append(now)
        self._failures[key] = recent
        if len(recent) >= RATE_LIMIT_FAILURES:
            self._locked_until[key] = now + LOCKOUT_SECONDS

    def record_success(self, username: str) -> None:
        key = self._normalize(username)
        self._failures.pop(key, None)
        self._locked_until.pop(key, None)


# Module-level singleton used by the auth router
login_rate_limiter = LoginRateLimiter()
```

- [ ] **Step 4: Run tests**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest tests/test_login_rate_limit.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/orbital/projects/pryzm && git add backend/core/cookie_auth.py backend/tests/test_login_rate_limit.py && \
git commit -m "feat(auth): per-username login rate limiter"
```

---

## Task 12: Auth router — POST /api/auth/login

**Files:**
- Create: `backend/routers/auth.py`
- Modify: `backend/schemas.py` (add LoginRequest)
- Create: `backend/tests/test_auth_router.py`

- [ ] **Step 1: Add LoginRequest schema**

In `backend/schemas.py`, append:

```python
class LoginRequest(BaseModel):
    username: str
    password: str
```

- [ ] **Step 2: Failing test for login endpoint**

Create `backend/tests/test_auth_router.py`:

```python
"""Auth router: /api/auth/login."""
import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from core import cookie_auth
from db import database, models
from main import app


def _setup_user(db_session, username="alice", password="hunter2hunter2", is_active=True):
    u = models.User(
        username=username,
        password_hash=cookie_auth.hash_password(password),
        is_admin=False,
        is_active=is_active,
    )
    db_session.add(u)
    db_session.commit()
    return u


def _client(db_session, monkeypatch):
    monkeypatch.setattr("config.settings.PRYZM_API_TOKEN", "test-token")
    app.dependency_overrides[database.get_db] = lambda: db_session
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    cookie_auth.login_rate_limiter = cookie_auth.LoginRateLimiter()
    yield


def test_login_success_sets_cookie_and_returns_user(db_session, monkeypatch):
    u = _setup_user(db_session)
    try:
        c = _client(db_session, monkeypatch)
        r = c.post("/api/auth/login", json={"username": "alice", "password": "hunter2hunter2"})
        assert r.status_code == 200
        body = r.json()
        assert body["username"] == "alice"
        assert body["id"] == u.id
        assert body["is_admin"] is False
        assert cookie_auth.COOKIE_NAME in r.cookies
    finally:
        app.dependency_overrides.clear()


def test_login_wrong_password_returns_401(db_session, monkeypatch):
    _setup_user(db_session)
    try:
        c = _client(db_session, monkeypatch)
        r = c.post("/api/auth/login", json={"username": "alice", "password": "wrong"})
        assert r.status_code == 401
        assert cookie_auth.COOKIE_NAME not in r.cookies
    finally:
        app.dependency_overrides.clear()


def test_login_unknown_username_returns_401(db_session, monkeypatch):
    try:
        c = _client(db_session, monkeypatch)
        r = c.post("/api/auth/login", json={"username": "nobody", "password": "wrong"})
        assert r.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_login_deactivated_user_returns_401(db_session, monkeypatch):
    _setup_user(db_session, is_active=False)
    try:
        c = _client(db_session, monkeypatch)
        r = c.post("/api/auth/login", json={"username": "alice", "password": "hunter2hunter2"})
        assert r.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_login_case_insensitive_username(db_session, monkeypatch):
    _setup_user(db_session, username="Alice")
    try:
        c = _client(db_session, monkeypatch)
        r = c.post("/api/auth/login", json={"username": "ALICE", "password": "hunter2hunter2"})
        assert r.status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_login_locks_out_after_threshold(db_session, monkeypatch):
    _setup_user(db_session)
    try:
        c = _client(db_session, monkeypatch)
        for _ in range(cookie_auth.RATE_LIMIT_FAILURES):
            c.post("/api/auth/login", json={"username": "alice", "password": "wrong"})
        # Even correct password should now be rejected with 429 or 401
        r = c.post("/api/auth/login", json={"username": "alice", "password": "hunter2hunter2"})
        assert r.status_code in (401, 429)
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 3: Run test (expect failure)**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest tests/test_auth_router.py -v
```

Expected: FAIL — router doesn't exist.

- [ ] **Step 4: Create the router**

Create `backend/routers/auth.py`:

```python
"""Cookie-based authentication: /api/auth/{login,logout,me}."""
import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session as DbSession

from core import cookie_auth
from db import database, models
from schemas import LoginRequest


router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
async def login(
    payload: LoginRequest,
    response: Response,
    db: DbSession = Depends(database.get_db),
):
    username = payload.username.strip()
    if cookie_auth.login_rate_limiter.is_locked(username):
        # Slow attackers down even for locked accounts
        await asyncio.sleep(0.25)
        raise HTTPException(status_code=401, detail="Invalid credentials.")

    user = (
        db.query(models.User)
        .filter(models.User.username.ilike(username))
        .filter(models.User.is_active.is_(True))
        .first()
    )
    if user is None or not cookie_auth.verify_password(payload.password, user.password_hash):
        cookie_auth.login_rate_limiter.record_failure(username)
        await asyncio.sleep(0.25)
        raise HTTPException(status_code=401, detail="Invalid credentials.")

    cookie_auth.login_rate_limiter.record_success(username)
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()

    sid = cookie_auth.create_session(db, user.id)
    response.set_cookie(
        cookie_auth.COOKIE_NAME,
        sid,
        max_age=int(cookie_auth.SESSION_IDLE_TIMEOUT.total_seconds()),
        httponly=True,
        secure=False,  # set True behind TLS in production via env/config
        samesite="lax",
        path="/",
    )
    return {
        "id": user.id,
        "username": user.username,
        "is_admin": user.is_admin,
        "can_create_workspaces": user.can_create_workspaces,
    }
```

- [ ] **Step 5: Wire the router in `backend/main.py`**

Find the `app.include_router(...)` block (after line 150 per the codebase scan). Add:

```python
from routers import auth as auth_router
app.include_router(auth_router.router)
```

The new router does NOT get `dependencies=[Depends(require_token)]` — these endpoints handle their own auth (or no auth, in login's case).

- [ ] **Step 6: Run tests**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest tests/test_auth_router.py -v
```

Expected: 6 passed.

- [ ] **Step 7: Commit**

```bash
cd /home/orbital/projects/pryzm && git add backend/routers/auth.py backend/schemas.py backend/main.py backend/tests/test_auth_router.py && \
git commit -m "feat(auth): POST /api/auth/login with rate limiting"
```

---

## Task 13: Auth router — POST /api/auth/logout

**Files:**
- Modify: `backend/routers/auth.py`
- Modify: `backend/tests/test_auth_router.py` (append)

- [ ] **Step 1: Append failing tests**

Append to `backend/tests/test_auth_router.py`:

```python
def test_logout_clears_cookie_and_session(db_session, monkeypatch):
    _setup_user(db_session)
    try:
        c = _client(db_session, monkeypatch)
        c.post("/api/auth/login", json={"username": "alice", "password": "hunter2hunter2"})
        # session row exists
        assert db_session.query(models.AuthSession).count() == 1

        r = c.post("/api/auth/logout")
        assert r.status_code == 200
        # session row deleted
        db_session.expire_all()
        assert db_session.query(models.AuthSession).count() == 0
        # cookie cleared (max-age=0 on the response sets it to expire)
        assert r.cookies.get(cookie_auth.COOKIE_NAME) in (None, "")
    finally:
        app.dependency_overrides.clear()


def test_logout_without_cookie_returns_200_idempotent(db_session, monkeypatch):
    try:
        c = _client(db_session, monkeypatch)
        r = c.post("/api/auth/logout")
        assert r.status_code == 200
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 2: Run test (expect failure)**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest tests/test_auth_router.py::test_logout_clears_cookie_and_session -v
```

- [ ] **Step 3: Add logout endpoint**

Append to `backend/routers/auth.py`:

```python
@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    db: DbSession = Depends(database.get_db),
):
    sid = request.cookies.get(cookie_auth.COOKIE_NAME)
    if sid:
        cookie_auth.invalidate_session(db, sid)
    response.delete_cookie(cookie_auth.COOKIE_NAME, path="/")
    return {"ok": True}
```

- [ ] **Step 4: Run tests**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest tests/test_auth_router.py -v
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/orbital/projects/pryzm && git add backend/routers/auth.py backend/tests/test_auth_router.py && \
git commit -m "feat(auth): POST /api/auth/logout"
```

---

## Task 14: Auth router — GET /api/auth/me

**Files:**
- Modify: `backend/routers/auth.py`
- Modify: `backend/tests/test_auth_router.py` (append)

- [ ] **Step 1: Failing tests**

Append:

```python
def test_me_returns_user_when_authenticated(db_session, monkeypatch):
    _setup_user(db_session)
    try:
        c = _client(db_session, monkeypatch)
        c.post("/api/auth/login", json={"username": "alice", "password": "hunter2hunter2"})
        r = c.get("/api/auth/me")
        assert r.status_code == 200
        body = r.json()
        assert body["username"] == "alice"
        assert body["is_admin"] is False
    finally:
        app.dependency_overrides.clear()


def test_me_returns_401_when_no_cookie(db_session, monkeypatch):
    try:
        c = _client(db_session, monkeypatch)
        r = c.get("/api/auth/me")
        assert r.status_code == 401
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 2: Add /me endpoint**

Append to `backend/routers/auth.py`:

```python
@router.get("/me")
def me(user: models.User = Depends(cookie_auth.current_user)):
    return {
        "id": user.id,
        "username": user.username,
        "is_admin": user.is_admin,
        "can_create_workspaces": user.can_create_workspaces,
        "email": user.email,
    }
```

- [ ] **Step 3: Run tests**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest tests/test_auth_router.py -v
```

Expected: 10 passed.

- [ ] **Step 4: Commit**

```bash
cd /home/orbital/projects/pryzm && git add backend/routers/auth.py backend/tests/test_auth_router.py && \
git commit -m "feat(auth): GET /api/auth/me"
```

---

## Task 15: Folder.id server-side generation

**Files:**
- Modify: `backend/schemas.py`
- Modify: `backend/routers/folders.py`
- Modify: `backend/db/models.py` (confirm `Folder.id` uses `default=generate_uuid`)
- Create: `backend/tests/test_folder_create_server_id.py`

- [ ] **Step 1: Update FolderCreate schema**

In `backend/schemas.py`, find `class FolderCreate(BaseModel):` (around line 59-60). Remove the `id: str` field. Keep `name` and `workspace`. The class becomes:

```python
class FolderCreate(BaseModel):
    name: str
    workspace: str
```

(If the existing schema also has other fields, keep them; only remove `id`.)

- [ ] **Step 2: Update folders router**

In `backend/routers/folders.py`, the `create_folder` function currently reads `folder.id`. Replace the body to generate the id server-side using the model default. Before:

```python
@router.post("/folders")
def create_folder(folder: FolderCreate, db: Session = Depends(database.get_db)):
    ws = get_or_default(db, folder.workspace)
    if db.query(models.Folder).filter(models.Folder.id == folder.id).first():
        # duplicate handling
        ...
    new_folder = models.Folder(id=folder.id, name=folder.name, workspace_id=ws.id)
    db.add(new_folder)
    ...
```

After:

```python
@router.post("/folders")
def create_folder(folder: FolderCreate, db: Session = Depends(database.get_db)):
    ws = get_or_default(db, folder.workspace)
    new_folder = models.Folder(name=folder.name, workspace_id=ws.id)
    db.add(new_folder)
    db.commit()
    return {"id": new_folder.id, "name": new_folder.name, "workspace_id": new_folder.workspace_id}
```

Keep whatever the existing return shape was; just remove the client-id handling. Also delete the duplicate-id check (no longer possible since the server generates the id via `default=generate_uuid` on the model — collisions are astronomically unlikely).

- [ ] **Step 3: Confirm Folder model has the default**

Read `backend/db/models.py`, find the `Folder` class, verify the `id` column is:

```python
id = Column(String, primary_key=True, default=generate_uuid, index=True)
```

If it isn't, change it.

- [ ] **Step 4: Failing test**

Create `backend/tests/test_folder_create_server_id.py`:

```python
"""POST /folders generates its own id."""
from fastapi.testclient import TestClient

from core import cookie_auth
from db import database, models
from main import app


def test_folder_create_does_not_require_client_id(db_session, monkeypatch):
    # Seed a workspace
    ws = models.Workspace(
        id="ws-fid", slug="ws-fid", display_name="FID",
        system_prompt="", enabled_tools=[], is_builtin=False,
        engine_config={"backend": "llama_cpp"},
    )
    db_session.add(ws)
    db_session.commit()

    monkeypatch.setattr("config.settings.PRYZM_API_TOKEN", "test-token")
    app.dependency_overrides[database.get_db] = lambda: db_session
    try:
        c = TestClient(app)
        c.headers.update({"Authorization": "Bearer test-token"})
        r = c.post("/folders", json={"name": "Notes", "workspace": "ws-fid"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert "id" in body
        assert len(body["id"]) > 20  # uuid
        # Verify the row exists in db
        folder = db_session.query(models.Folder).filter_by(id=body["id"]).one()
        assert folder.name == "Notes"
    finally:
        app.dependency_overrides.clear()


def test_folder_create_rejects_extra_id_field(db_session, monkeypatch):
    # If the client sends id, pydantic should reject it (extra fields default-forbidden? confirm)
    # OR if pydantic ignores extra fields, the test should confirm the server-side id is used (not the client's).
    ws = models.Workspace(
        id="ws-fid2", slug="ws-fid2", display_name="FID2",
        system_prompt="", enabled_tools=[], is_builtin=False,
        engine_config={"backend": "llama_cpp"},
    )
    db_session.add(ws)
    db_session.commit()

    monkeypatch.setattr("config.settings.PRYZM_API_TOKEN", "test-token")
    app.dependency_overrides[database.get_db] = lambda: db_session
    try:
        c = TestClient(app)
        c.headers.update({"Authorization": "Bearer test-token"})
        r = c.post("/folders", json={"name": "Notes", "workspace": "ws-fid2", "id": "client-supplied-id"})
        # Either pydantic rejects (422) or the server ignores and uses its own id
        assert r.status_code in (200, 422)
        if r.status_code == 200:
            body = r.json()
            assert body["id"] != "client-supplied-id"
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 5: Run tests**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest tests/test_folder_create_server_id.py -v
```

Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
cd /home/orbital/projects/pryzm && git add backend/schemas.py backend/routers/folders.py backend/db/models.py backend/tests/test_folder_create_server_id.py && \
git commit -m "feat(auth): server-side folder id generation"
```

---

## Task 16: Bootstrap admin on lifespan startup

**Files:**
- Modify: `backend/config.py` (add env var settings)
- Modify: `backend/main.py` (extend lifespan)
- Create: `backend/tests/test_bootstrap_admin.py`

- [ ] **Step 1: Add config fields**

In `backend/config.py`, add to the `Settings` class:

```python
PRYZM_BOOTSTRAP_ADMIN_USERNAME: str = "admin"
PRYZM_BOOTSTRAP_ADMIN_PASSWORD: str | None = None
```

These map to the env vars `PRYZM_BOOTSTRAP_ADMIN_USERNAME` and `PRYZM_BOOTSTRAP_ADMIN_PASSWORD` (pydantic-settings convention).

- [ ] **Step 2: Failing test**

Create `backend/tests/test_bootstrap_admin.py`:

```python
"""Bootstrap admin creation on startup."""
import pytest

from core.bootstrap import ensure_bootstrap_admin
from db import models


def test_bootstrap_creates_admin_when_users_empty(db_session, monkeypatch):
    monkeypatch.setattr("config.settings.PRYZM_BOOTSTRAP_ADMIN_USERNAME", "admin")
    monkeypatch.setattr("config.settings.PRYZM_BOOTSTRAP_ADMIN_PASSWORD", "bootstrap-pw-123456")

    ensure_bootstrap_admin(db_session)

    admin = db_session.query(models.User).filter_by(username="admin").one()
    assert admin.is_admin is True
    assert admin.is_active is True


def test_bootstrap_noop_when_users_already_exist(db_session, monkeypatch):
    monkeypatch.setattr("config.settings.PRYZM_BOOTSTRAP_ADMIN_USERNAME", "admin")
    monkeypatch.setattr("config.settings.PRYZM_BOOTSTRAP_ADMIN_PASSWORD", "bootstrap-pw-123456")
    # Pre-existing user
    db_session.add(models.User(
        username="existing", password_hash="dummy", is_admin=False, is_active=True,
    ))
    db_session.commit()

    ensure_bootstrap_admin(db_session)

    # Bootstrap admin should NOT have been created
    assert db_session.query(models.User).filter_by(username="admin").first() is None


def test_bootstrap_raises_when_users_empty_and_no_password(db_session, monkeypatch):
    monkeypatch.setattr("config.settings.PRYZM_BOOTSTRAP_ADMIN_PASSWORD", None)

    with pytest.raises(RuntimeError, match="PRYZM_BOOTSTRAP_ADMIN_PASSWORD"):
        ensure_bootstrap_admin(db_session)


def test_bootstrap_instantiates_builtin_templates_for_admin(db_session, monkeypatch):
    monkeypatch.setattr("config.settings.PRYZM_BOOTSTRAP_ADMIN_USERNAME", "admin")
    monkeypatch.setattr("config.settings.PRYZM_BOOTSTRAP_ADMIN_PASSWORD", "bootstrap-pw-123456")

    # Seed a template (mirroring what migration 2 did)
    template = models.Workspace(
        id="tmpl-it", slug="it_copilot", display_name="IT Copilot",
        system_prompt="IT helper", enabled_tools=[],
        is_builtin=True, is_template=True, user_id=None,
        engine_config={"backend": "llama_cpp"},
    )
    db_session.add(template)
    db_session.commit()

    ensure_bootstrap_admin(db_session)

    admin = db_session.query(models.User).filter_by(username="admin").one()
    instances = db_session.query(models.Workspace).filter_by(
        user_id=admin.id, template_id="tmpl-it",
    ).all()
    assert len(instances) == 1
    assert instances[0].is_template is False
```

- [ ] **Step 3: Run test (expect failure — module doesn't exist)**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest tests/test_bootstrap_admin.py -v
```

- [ ] **Step 4: Create the bootstrap module**

Create `backend/core/bootstrap.py`:

```python
"""First-boot bootstrap logic: create admin user if users table is empty,
instantiate templates for them, backfill existing chats/folders/workspaces.
"""
from sqlalchemy.orm import Session as DbSession

from config import settings
from core import cookie_auth
from db import models


def ensure_bootstrap_admin(db: DbSession) -> models.User | None:
    """If the users table is empty, create the bootstrap admin from env
    vars and instantiate the builtin templates. Returns the admin (or
    None if a non-empty users table means bootstrap is no-op)."""
    existing = db.query(models.User).first()
    if existing is not None:
        return None

    if not settings.PRYZM_BOOTSTRAP_ADMIN_PASSWORD:
        raise RuntimeError(
            "Users table is empty and PRYZM_BOOTSTRAP_ADMIN_PASSWORD is not set. "
            "Set the env var to bootstrap the first admin, then restart."
        )

    admin = models.User(
        username=settings.PRYZM_BOOTSTRAP_ADMIN_USERNAME,
        password_hash=cookie_auth.hash_password(settings.PRYZM_BOOTSTRAP_ADMIN_PASSWORD),
        is_admin=True,
        is_active=True,
        can_create_workspaces=True,
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)

    _instantiate_templates_for(db, admin)
    _backfill_orphan_data(db, admin)

    return admin


def _instantiate_templates_for(db: DbSession, user: models.User) -> None:
    templates = db.query(models.Workspace).filter_by(is_template=True).all()
    for tmpl in templates:
        instance = models.Workspace(
            slug=tmpl.slug,
            display_name=tmpl.display_name,
            system_prompt=tmpl.system_prompt,
            enabled_tools=list(tmpl.enabled_tools or []),
            is_builtin=tmpl.is_builtin,
            is_template=False,
            template_id=tmpl.id,
            user_id=user.id,
            owner_can_edit=True,  # bootstrap admin can edit their own
            engine_config=dict(tmpl.engine_config or {}),
        )
        db.add(instance)
    db.commit()


def _backfill_orphan_data(db: DbSession, user: models.User) -> None:
    """Attach any pre-existing chats/folders/non-template workspaces
    without a user_id to the bootstrap admin."""
    db.query(models.Session).filter(models.Session.user_id.is_(None)).update(
        {"user_id": user.id}, synchronize_session=False,
    )
    db.query(models.Folder).filter(models.Folder.user_id.is_(None)).update(
        {"user_id": user.id}, synchronize_session=False,
    )
    db.query(models.Workspace).filter(
        models.Workspace.user_id.is_(None),
        models.Workspace.is_template.is_(False),
    ).update({"user_id": user.id}, synchronize_session=False)
    db.commit()
```

- [ ] **Step 5: Wire into lifespan in `backend/main.py`**

Find the `async def lifespan(app: FastAPI):` function (around line 89). Inside the startup section (before `yield`), add:

```python
    # Bootstrap admin on first boot
    from db import database
    from core.bootstrap import ensure_bootstrap_admin
    bootstrap_db = database.SessionLocal()
    try:
        ensure_bootstrap_admin(bootstrap_db)
    finally:
        bootstrap_db.close()
```

If `ensure_bootstrap_admin` raises a `RuntimeError`, the startup will fail — that's intentional (the operator gets a clear error pointing at the env var).

- [ ] **Step 6: Run tests**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest tests/test_bootstrap_admin.py -v
```

Expected: 4 passed.

- [ ] **Step 7: Commit**

```bash
cd /home/orbital/projects/pryzm && git add backend/config.py backend/core/bootstrap.py backend/main.py backend/tests/test_bootstrap_admin.py && \
git commit -m "feat(auth): bootstrap admin from env on first boot"
```

---

## Task 17: Full test suite + manual smoke

**Files:** none new.

- [ ] **Step 1: Run the entire backend test suite**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest -q --ignore=tests/test_image_upload.py --ignore=tests/test_upload_sse.py
```

The two ignored files have pre-existing failures unrelated to this work (carried over from the structural-cleanup PR). Anything else failing is a regression and must be fixed before commit.

Expected: all tests pass.

- [ ] **Step 2: Verify the dev DB is on the latest migration**

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/alembic current
```

Expected: shows the folder_id_server_default migration as head.

- [ ] **Step 3: Restart the dev backend with bootstrap env set**

```bash
# In the backend's terminal:
export PRYZM_BOOTSTRAP_ADMIN_PASSWORD="bootstrap-test-password-do-not-ship"
# Restart uvicorn (kill the existing process and start with the env var set)
```

Verify startup logs don't show any errors. The `users` table should now contain an `admin` row.

- [ ] **Step 4: Manual smoke: hit /api/auth/login**

```bash
curl -i -X POST http://127.0.0.1:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"bootstrap-test-password-do-not-ship"}'
```

Expected: 200, `Set-Cookie: pryzm_session=...` header in the response.

- [ ] **Step 5: Manual smoke: hit /api/auth/me with the cookie**

```bash
curl -i -b "pryzm_session=<sid-from-previous-response>" http://127.0.0.1:8000/api/auth/me
```

Expected: 200, JSON body with the admin user.

- [ ] **Step 6: Verify bearer auth still works for existing endpoints**

```bash
curl -i -H "Authorization: Bearer $PRYZM_API_TOKEN" http://127.0.0.1:8000/sessions?workspace=it_copilot
```

Expected: 200 — confirms dual-mode operation. Phase A doesn't break existing flows.

- [ ] **Step 7: Commit if any nits surfaced from the smoke run**

If steps 1-6 surfaced any small fixes, commit them with a descriptive message. If everything passed clean, no commit needed.

---

## Task 18: Push branch + open PR

**Files:** none.

- [ ] **Step 1: Push the branch**

```bash
cd /home/orbital/projects/pryzm && git push -u origin feat/auth-phase-a
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --base main --head feat/auth-phase-a \
  --title "feat(auth): Phase A — cookie-based login, user model, bootstrap admin" \
  --body "$(cat <<'EOF'
First slice of the user-login work. Backend is now dual-mode: existing bearer-token routes keep working unchanged; new /api/auth/login, /logout, /me routes use cookie-based sessions.

Schema
- New tables: users, auth_sessions
- New columns on workspaces (user_id, is_template, template_id, owner_can_edit), sessions (user_id), folders (user_id)
- Builtin workspaces (it_copilot, personal) marked as templates
- folder.id now server-generated

Runtime
- argon2id password hashing
- Per-username login rate limit (10 failures in 15 min → 15 min lockout)
- Bootstrap admin created from PRYZM_BOOTSTRAP_ADMIN_PASSWORD env on first boot
- Bootstrap admin gets instances of all builtin templates
- Existing chats/folders/workspaces backfilled to the bootstrap admin

Detail in docs/specs/2026-05-17-user-login-and-admin.md (Phase A section).
Plan in docs/plans/2026-05-18-auth-phase-a.md.

Phases B-E follow in their own PRs.
EOF
)"
```

- [ ] **Step 3: Don't auto-merge**

Wait for explicit user approval before merging.

- [ ] **Step 4: Restore the stashed WIP if it was stashed in Task 0**

After the PR is merged:

```bash
cd /home/orbital/projects/pryzm && git checkout main && git pull && git stash pop 2>/dev/null || true
```

---

## Self-review notes

Coverage check against the spec (Phase A section):

- `users` table ✓ Tasks 2, 5
- `auth_sessions` table ✓ Tasks 2, 6
- Workspace columns (user_id, is_template, template_id, owner_can_edit) ✓ Tasks 2, 7
- `users.can_create_workspaces` ✓ Tasks 2, 5
- `sessions.user_id`, `folders.user_id` (nullable in Phase A) ✓ Tasks 2, 7
- Builtin workspaces become templates ✓ Task 3
- folder.id server-generated ✓ Tasks 4, 15
- argon2id password hashing ✓ Tasks 1, 8
- Sessions: create / lookup / sliding / invalidate ✓ Task 9
- current_user dependency ✓ Task 10
- Login rate limit ✓ Task 11
- POST /api/auth/login ✓ Task 12
- POST /api/auth/logout ✓ Task 13
- GET /api/auth/me ✓ Task 14
- Bootstrap admin from env on first boot ✓ Task 16
- Bootstrap auto-instantiates builtin templates ✓ Task 16
- Backfill existing chats/folders/workspaces to bootstrap admin ✓ Task 16
- Bearer auth (require_token) untouched ✓ (none of the tasks modify core/auth.py or require_token-gated routes)

Known under-specified spots an executor will need to adapt:

- Task 2 / 3 / 4: replace `<previous-head-revision-id>` and `<auth-phase-a-schema-revision-id>` placeholders with the actual ids that `alembic revision` generates.
- Task 4: the migration body assumes folders.id is already PK NOT NULL. If for some reason it isn't, the alter_column statement is the right shape but might need adjustment.
- Task 15: the `create_folder` response shape may differ from what existing frontend callers expect; verify by reading the existing router and matching its response shape exactly (only the input changes; output stays).
- Task 16: the `_instantiate_templates_for` helper assumes `Workspace.enabled_tools` is a list and `engine_config` is a dict. Confirm by reading the existing Workspace model — adjust if they're different types (e.g., JSONB columns deserialized differently).

Pre-existing failures in `tests/test_image_upload.py` and `tests/test_upload_sse.py` (path-validator regression from the structural cleanup PR) are out of scope for this plan — they should be filed as a separate bug.
