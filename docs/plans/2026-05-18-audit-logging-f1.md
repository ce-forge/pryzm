# Audit Logging F.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax. Apply Karpathy discipline: simplicity, surgical changes, verifiable goals.

**Goal:** Lay the foundation for the audit logging subsystem per `docs/specs/2026-05-18-audit-logging.md`. Create the `audit_events` table with monthly partitions and append-only trigger, the SQLAlchemy model, the central `log_event()` helper, retention-task scaffolding, and **wire only the auth-domain events** as proof of life.

**Architecture:** Partitioned Postgres table on `created_at` (monthly), with `BEFORE UPDATE` and `BEFORE DELETE` triggers raising `audit_events is append-only`. Application code emits events via a single `core/audit.py::log_event(...)` helper that takes the request transaction's `db` session and queues the insert. Auth router (login/logout/password change) gets the first wave of call sites. Retention sweeper is implemented but not yet scheduled — it's a callable function tested in isolation; auto-scheduling happens in a follow-up.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic + Postgres native partitioning. No new dependencies.

**Reference spec:** `docs/specs/2026-05-18-audit-logging.md`.

**Out of scope (subsequent PRs):**
- F.2 — wiring `log_event` into chat / workspace / document / folder / tool / admin surfaces (one PR per domain)
- F.3 — `GET /api/admin/audit` read endpoints
- The dashboard's Audit tab (depends on F.3 + Phase D)
- Scheduled retention task (the sweeper exists but isn't wired into a cron/asyncio task yet)

---

## File map

| File | Action | Purpose |
|---|---|---|
| `backend/alembic/versions/<rev>_audit_events_schema.py` | Create | Partitioned table + trigger + first month partition |
| `backend/db/models.py` | Modify | Add `AuditEvent` ORM class |
| `backend/core/audit.py` | Create | `log_event()` helper + `event_types` canonical list + `EventType` string constants |
| `backend/services/audit_partitions.py` | Create | `ensure_next_month_partition()` and `prune_old_partitions()` callables |
| `backend/routers/auth.py` | Modify | Emit `auth.login_success`, `auth.login_failure`, `auth.logout`, `auth.password_changed` |
| `backend/config.py` | Modify | Add `AUDIT_RETENTION_DAYS: int = 90` setting |
| `backend/tests/test_audit_schema.py` | Create | Append-only trigger, partition exists, FK SET NULL behavior |
| `backend/tests/test_audit_log_event.py` | Create | Helper writes a row; payload shape; null-user case |
| `backend/tests/test_audit_partitions.py` | Create | `ensure_next_month_partition` is idempotent; `prune_old_partitions` drops old, leaves recent |
| `backend/tests/test_audit_auth_events.py` | Create | Login success/failure/logout/password-change each emit the expected event |

---

## Task 0: Branch setup

The branch `feat/audit-logging-f1` is already checked out.

- [ ] **Step 1: Commit this plan**

```bash
cd /home/orbital/projects/pryzm && git add docs/plans/2026-05-18-audit-logging-f1.md && \
git commit -m "docs(plan): audit logging F.1 plan (schema + helper + auth events)"
```

---

## Task 1: Schema migration

**Files:**
- Create: `backend/alembic/versions/<rev>_audit_events_schema.py`

### Step 1: Generate the revision

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/alembic revision -m "audit_events_schema"
```

Confirm `down_revision` resolves to the current head. Verify with `./venv/bin/alembic current` first.

### Step 2: Migration body

The migration must do (in order):

1. Create the parent partitioned table `audit_events`:

```sql
CREATE TABLE audit_events (
    id VARCHAR PRIMARY KEY,
    user_id VARCHAR,
    user_display_name_at_event TEXT,
    event_type TEXT NOT NULL,
    workspace_id VARCHAR,
    session_id VARCHAR,
    resource_type TEXT,
    resource_id VARCHAR,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_ip TEXT,
    user_agent TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_audit_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
    CONSTRAINT fk_audit_workspace FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE SET NULL,
    CONSTRAINT fk_audit_session FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE SET NULL
) PARTITION BY RANGE (created_at);
```

Use `op.execute(sa.text("..."))` for the partition syntax — `op.create_table` doesn't support `PARTITION BY`.

2. Create the indexes ON THE PARENT TABLE (Postgres propagates them to partitions automatically):

```sql
CREATE INDEX ix_audit_events_user_created ON audit_events (user_id, created_at DESC);
CREATE INDEX ix_audit_events_event_type_created ON audit_events (event_type, created_at DESC);
CREATE INDEX ix_audit_events_workspace_created ON audit_events (workspace_id, created_at DESC);
```

3. Create the append-only trigger function and triggers:

```sql
CREATE OR REPLACE FUNCTION audit_events_no_mutation() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'audit_events is append-only';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_events_no_update
  BEFORE UPDATE ON audit_events
  FOR EACH ROW EXECUTE FUNCTION audit_events_no_mutation();

CREATE TRIGGER audit_events_no_delete
  BEFORE DELETE ON audit_events
  FOR EACH ROW EXECUTE FUNCTION audit_events_no_mutation();
```

Note: triggers on a partitioned parent table apply to all current and future partitions automatically.

4. Create the first month's partition (current month, computed dynamically):

```python
from datetime import datetime, timezone
now = datetime.now(timezone.utc)
month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
# Compute next month start
if now.month == 12:
    next_month_start = month_start.replace(year=now.year + 1, month=1)
else:
    next_month_start = month_start.replace(month=now.month + 1)

partition_name = f"audit_events_y{month_start.year}m{month_start.month:02d}"
op.execute(sa.text(f"""
    CREATE TABLE {partition_name} PARTITION OF audit_events
    FOR VALUES FROM ('{month_start.isoformat()}') TO ('{next_month_start.isoformat()}');
"""))
```

### Step 3: Downgrade

```python
def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_events_no_delete ON audit_events;")
    op.execute("DROP TRIGGER IF EXISTS audit_events_no_update ON audit_events;")
    op.execute("DROP FUNCTION IF EXISTS audit_events_no_mutation();")
    # Dropping the parent drops all child partitions too.
    op.execute("DROP TABLE IF EXISTS audit_events CASCADE;")
```

### Step 4: Apply to dev DB

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/alembic upgrade head
```

Verify:

```bash
PGPASSWORD=$(grep ^DB_PASSWORD /home/orbital/projects/pryzm/.env | cut -d= -f2-) \
  psql -h 127.0.0.1 -U pryzm_admin -d pryzm_core -c "\\d+ audit_events"
PGPASSWORD=$(grep ^DB_PASSWORD /home/orbital/projects/pryzm/.env | cut -d= -f2-) \
  psql -h 127.0.0.1 -U pryzm_admin -d pryzm_core -c "SELECT inhrelid::regclass FROM pg_inherits WHERE inhparent = 'audit_events'::regclass;"
```

Expected: parent table + one partition for the current month.

### Step 5: Commit

```bash
cd /home/orbital/projects/pryzm && git add backend/alembic/versions/ && \
git commit -m "feat(audit): add audit_events table with monthly partitioning + append-only trigger"
```

---

## Task 2: SQLAlchemy model

**File:** `backend/db/models.py`

### Step 1: Add `AuditEvent`

Near the other top-level entities, after `Folder` (or wherever logical), add:

```python
class AuditEvent(Base):
    __tablename__ = "audit_events"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    user_display_name_at_event = Column(Text, nullable=True)
    event_type = Column(Text, nullable=False, index=True)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True)
    session_id = Column(String, ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True)
    resource_type = Column(Text, nullable=True)
    resource_id = Column(String, nullable=True)
    payload = Column(JSON, nullable=False, default=dict, server_default="{}")
    source_ip = Column(Text, nullable=True)
    user_agent = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
```

Use `JSON` not `JSONB` to match the convention of `WorkspaceTemplate.engine_config` (per project memory; type-consistency was approved in the workspace-template-split review).

If `Text` isn't imported at the top, add it to the existing sqlalchemy import.

### Step 2: Smoke import

```bash
cd /home/orbital/projects/pryzm/backend && \
./venv/bin/python -c "from db.models import AuditEvent; print(sorted(c.name for c in AuditEvent.__table__.columns))"
```

Expected: list of 12 columns matching the schema.

### Step 3: Commit

```bash
cd /home/orbital/projects/pryzm && git add backend/db/models.py && \
git commit -m "feat(audit): AuditEvent ORM model"
```

---

## Task 3: `log_event` helper

**File:** `backend/core/audit.py`

### Step 1: Create the helper

```python
"""Audit logging helper.

The single entry point for emitting audit events. Inserts are sync and
participate in the surrounding request transaction — if the audit write
fails, the entire request rolls back. This is deliberate; silent audit
failure is worse than a visible 500 because it creates a false sense of
observability.

Event_type strings follow `domain.verb` shape. Add new constants here
as new domains land.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import Request
from sqlalchemy.orm import Session

from db import models


class EventType:
    """Canonical event-type strings. Add new entries here, not inline."""

    # auth.*
    AUTH_LOGIN_SUCCESS = "auth.login_success"
    AUTH_LOGIN_FAILURE = "auth.login_failure"
    AUTH_LOGOUT = "auth.logout"
    AUTH_PASSWORD_CHANGED = "auth.password_changed"
    AUTH_PASSWORD_RESET_BY_ADMIN = "auth.password_reset_by_admin"
    AUTH_SESSION_EXPIRED = "auth.session_expired"

    # Subsequent F.2 PRs will add admin.*, chat.*, workspace.*, document.*,
    # folder.*, bugreport.*, notification.* constants here.


def log_event(
    db: Session,
    event_type: str,
    *,
    user: Optional[models.User] = None,
    workspace: Optional[models.Workspace] = None,
    session: Optional[models.Session] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    payload: Optional[dict[str, Any]] = None,
    source_ip: Optional[str] = None,
    user_agent: Optional[str] = None,
    request: Optional[Request] = None,
) -> models.AuditEvent:
    """Append one row to audit_events using the caller's db session.

    The row is `db.add`-ed but not committed; the surrounding request
    transaction commits it. If the request later rolls back, the audit
    row rolls back with it — which is the right semantic (we don't
    record events for failed operations).

    Pass `request` to auto-extract `source_ip` and `user_agent` from
    headers; explicit `source_ip` / `user_agent` kwargs override.
    """
    if request is not None:
        if source_ip is None:
            source_ip = request.client.host if request.client else None
        if user_agent is None:
            user_agent = request.headers.get("user-agent")

    event = models.AuditEvent(
        user_id=user.id if user else None,
        user_display_name_at_event=user.username if user else None,
        event_type=event_type,
        workspace_id=workspace.id if workspace else None,
        session_id=session.id if session else None,
        resource_type=resource_type,
        resource_id=resource_id,
        payload=payload or {},
        source_ip=source_ip,
        user_agent=user_agent,
    )
    db.add(event)
    return event
```

### Step 2: Smoke import

```bash
cd /home/orbital/projects/pryzm/backend && \
./venv/bin/python -c "from core.audit import log_event, EventType; print(EventType.AUTH_LOGIN_SUCCESS)"
```

Expected: `auth.login_success`.

### Step 3: Commit

```bash
cd /home/orbital/projects/pryzm && git add backend/core/audit.py && \
git commit -m "feat(audit): core/audit.py log_event helper + EventType constants"
```

---

## Task 4: Partition + retention scaffolding

**File:** `backend/services/audit_partitions.py`

### Step 1: Create the file

```python
"""Audit-events partition lifecycle.

`audit_events` is partitioned by month on `created_at`. We need to:
  1. Create the next month's partition before month-end (so inserts at
     midnight on the 1st have a target partition).
  2. Drop partitions older than retention.

This module provides both as callable functions. F.1 doesn't auto-
schedule them; F.2 (or operator cron) wires them up.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session


def _partition_name(year: int, month: int) -> str:
    return f"audit_events_y{year}m{month:02d}"


def _month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start, end


def ensure_next_month_partition(db: Session, now: datetime | None = None) -> str:
    """Create next month's partition if it doesn't exist.

    Idempotent: uses `CREATE TABLE IF NOT EXISTS`. Returns the
    partition name (created or pre-existing).
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if now.month == 12:
        target_year, target_month = now.year + 1, 1
    else:
        target_year, target_month = now.year, now.month + 1
    name = _partition_name(target_year, target_month)
    start, end = _month_bounds(target_year, target_month)
    db.execute(text(
        f"CREATE TABLE IF NOT EXISTS {name} PARTITION OF audit_events "
        f"FOR VALUES FROM ('{start.isoformat()}') TO ('{end.isoformat()}');"
    ))
    return name


def prune_old_partitions(
    db: Session,
    retention_days: int,
    now: datetime | None = None,
) -> list[str]:
    """Drop partitions whose upper bound is older than now - retention_days.

    Returns the list of dropped partition names.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=retention_days)

    # Discover all child partitions of audit_events
    rows = db.execute(text("""
        SELECT inhrelid::regclass::text AS name
        FROM pg_inherits
        WHERE inhparent = 'audit_events'::regclass
    """)).fetchall()

    dropped: list[str] = []
    for (raw_name,) in rows:
        # Strip schema prefix if present
        name = raw_name.split(".")[-1]
        if not name.startswith("audit_events_y"):
            continue
        # Parse y<year>m<month> from the suffix
        suffix = name[len("audit_events_y"):]
        try:
            year_str, month_str = suffix.split("m")
            year, month = int(year_str), int(month_str)
        except (ValueError, IndexError):
            continue
        _, partition_end = _month_bounds(year, month)
        if partition_end <= cutoff:
            db.execute(text(f"DROP TABLE {name};"))
            dropped.append(name)
    return dropped
```

### Step 2: Add retention setting to `backend/config.py`

In the `Settings` class:

```python
AUDIT_RETENTION_DAYS: int = 90
```

Place it near other knob settings (e.g., near `MAXIMUM_TOOL_LOOPS` or `MEMORY_CONDENSE_THRESHOLD`).

### Step 3: Smoke import

```bash
cd /home/orbital/projects/pryzm/backend && \
./venv/bin/python -c "from services.audit_partitions import ensure_next_month_partition, prune_old_partitions; print('ok')"
```

### Step 4: Commit

```bash
cd /home/orbital/projects/pryzm && git add backend/services/audit_partitions.py backend/config.py && \
git commit -m "feat(audit): partition lifecycle helpers + AUDIT_RETENTION_DAYS setting"
```

---

## Task 5: Wire auth events

**File:** `backend/routers/auth.py`

The four auth endpoints emit one event each. The exact payload shapes follow the spec.

### Step 1: Read the file first

```bash
cat /home/orbital/projects/pryzm/backend/routers/auth.py
```

Note: imports, endpoint shapes, the existing `change_password` handler.

### Step 2: Add the import

At the top:

```python
from core.audit import log_event, EventType
```

### Step 3: Wire `auth.login_success` and `auth.login_failure`

In the `login` endpoint, after successful credential verification and session creation, **before** the response return:

```python
log_event(
    db, EventType.AUTH_LOGIN_SUCCESS,
    user=user,
    request=request,
    payload={},
)
```

In the FAILURE branches (wrong password, unknown username, deactivated account, rate-limit hit), emit:

```python
log_event(
    db, EventType.AUTH_LOGIN_FAILURE,
    request=request,
    payload={
        "username_attempted": payload.username,
        "reason": "wrong_password",  # or "account_disabled" / "rate_limited" / "unknown_user"
    },
)
db.commit()  # commit the audit row before raising the 401
```

Yes — for failure, you must explicitly commit because the HTTPException raise rolls back otherwise. Pattern: insert the audit row, commit, then raise.

If the existing handler uses `db.commit()` already for the rate-limit-counter update, the audit emit can ride that same commit.

### Step 4: Wire `auth.logout`

In the `logout` endpoint:

```python
log_event(
    db, EventType.AUTH_LOGOUT,
    user=user,  # if available from cookie_auth.current_user dependency
    request=request,
    payload={},
)
```

Logout is idempotent — it returns 200 even with no cookie. Only emit the event when a real session was deleted (i.e., `user` is non-None). Skip emission for the no-cookie case.

### Step 5: Wire `auth.password_changed`

In `change_password` (POST /api/auth/password), after the password hash + session invalidation succeed, before the response return:

```python
log_event(
    db, EventType.AUTH_PASSWORD_CHANGED,
    user=user,
    request=request,
    payload={"invalidated_other_sessions": True},
)
```

### Step 6: Add `Request` to handler signatures where needed

If `request: Request` is not already a parameter on `login`, `logout`, or `change_password`, add it. Import `Request` from FastAPI at the top of the file if not already.

### Step 7: Smoke probe

Restart the backend, do a login, then check the table:

```bash
PGPASSWORD=$(grep ^DB_PASSWORD /home/orbital/projects/pryzm/.env | cut -d= -f2-) \
  psql -h 127.0.0.1 -U pryzm_admin -d pryzm_core -c \
  "SELECT id, event_type, user_display_name_at_event, source_ip, created_at FROM audit_events ORDER BY created_at DESC LIMIT 5;"
```

Expected: at least one row with `event_type = 'auth.login_success'`.

### Step 8: Commit

```bash
cd /home/orbital/projects/pryzm && git add backend/routers/auth.py && \
git commit -m "feat(audit): emit auth.login_success, login_failure, logout, password_changed events"
```

---

## Task 6: Tests

**Files to create:**
- `backend/tests/test_audit_schema.py`
- `backend/tests/test_audit_log_event.py`
- `backend/tests/test_audit_partitions.py`
- `backend/tests/test_audit_auth_events.py`

### Step 1: `test_audit_schema.py`

Tests the migration's structural guarantees:

```python
"""audit_events schema: append-only trigger, FK SET NULL, partition exists."""
import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError, InternalError

from db import models


def _seed_event(db_session):
    user = models.User(
        username="alice",
        password_hash="dummy",
        is_admin=False,
        is_active=True,
    )
    db_session.add(user); db_session.commit(); db_session.refresh(user)
    e = models.AuditEvent(
        user_id=user.id,
        user_display_name_at_event="alice",
        event_type="auth.login_success",
        payload={"k": "v"},
    )
    db_session.add(e); db_session.commit(); db_session.refresh(e)
    return user, e


def test_update_raises(db_session):
    _, e = _seed_event(db_session)
    with pytest.raises(Exception) as exc_info:
        db_session.execute(text(
            "UPDATE audit_events SET event_type = 'tampered' WHERE id = :id"
        ), {"id": e.id})
        db_session.commit()
    assert "append-only" in str(exc_info.value).lower()


def test_delete_raises(db_session):
    _, e = _seed_event(db_session)
    with pytest.raises(Exception) as exc_info:
        db_session.execute(text(
            "DELETE FROM audit_events WHERE id = :id"
        ), {"id": e.id})
        db_session.commit()
    assert "append-only" in str(exc_info.value).lower()


def test_user_fk_set_null_on_user_delete(db_session):
    user, e = _seed_event(db_session)
    # Hard-delete the user (rare in production but the audit row should survive)
    db_session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user.id})
    db_session.commit()
    refreshed = db_session.query(models.AuditEvent).filter_by(id=e.id).first()
    assert refreshed is not None
    assert refreshed.user_id is None
    # Display name snapshot survives
    assert refreshed.user_display_name_at_event == "alice"


def test_current_month_partition_exists(db_session):
    rows = db_session.execute(text("""
        SELECT inhrelid::regclass::text AS name
        FROM pg_inherits
        WHERE inhparent = 'audit_events'::regclass
    """)).fetchall()
    names = [r[0].split(".")[-1] for r in rows]
    assert any(n.startswith("audit_events_y") for n in names), names
```

### Step 2: `test_audit_log_event.py`

```python
"""log_event helper writes the expected row shape."""
from core.audit import log_event, EventType
from db import models


def test_log_event_with_user_and_payload(db_session):
    user = models.User(username="bob", password_hash="x", is_admin=False, is_active=True)
    db_session.add(user); db_session.commit(); db_session.refresh(user)

    event = log_event(
        db_session, EventType.AUTH_LOGIN_SUCCESS,
        user=user, payload={"reason": "valid"},
        source_ip="1.2.3.4", user_agent="curl/8.0",
    )
    db_session.commit()
    db_session.refresh(event)
    assert event.event_type == "auth.login_success"
    assert event.user_id == user.id
    assert event.user_display_name_at_event == "bob"
    assert event.payload == {"reason": "valid"}
    assert event.source_ip == "1.2.3.4"
    assert event.user_agent == "curl/8.0"


def test_log_event_without_user(db_session):
    event = log_event(
        db_session, EventType.AUTH_LOGIN_FAILURE,
        payload={"username_attempted": "ghost", "reason": "unknown_user"},
    )
    db_session.commit()
    db_session.refresh(event)
    assert event.user_id is None
    assert event.user_display_name_at_event is None
    assert event.payload["username_attempted"] == "ghost"
```

### Step 3: `test_audit_partitions.py`

```python
"""Partition lifecycle helpers."""
from datetime import datetime, timezone

from sqlalchemy import text

from services.audit_partitions import (
    ensure_next_month_partition,
    prune_old_partitions,
)


def test_ensure_next_month_idempotent(db_session):
    fixed = datetime(2026, 3, 15, tzinfo=timezone.utc)
    name1 = ensure_next_month_partition(db_session, now=fixed)
    db_session.commit()
    name2 = ensure_next_month_partition(db_session, now=fixed)
    db_session.commit()
    assert name1 == name2 == "audit_events_y2026m04"
    # Verify it actually exists
    rows = db_session.execute(text("""
        SELECT inhrelid::regclass::text FROM pg_inherits
        WHERE inhparent = 'audit_events'::regclass
    """)).fetchall()
    assert any(r[0].endswith("audit_events_y2026m04") for r in rows)


def test_prune_drops_old_partitions(db_session):
    # Create an old partition far in the past
    db_session.execute(text("""
        CREATE TABLE IF NOT EXISTS audit_events_y2020m01 PARTITION OF audit_events
        FOR VALUES FROM ('2020-01-01') TO ('2020-02-01');
    """))
    db_session.commit()

    dropped = prune_old_partitions(db_session, retention_days=90,
                                    now=datetime(2026, 5, 18, tzinfo=timezone.utc))
    db_session.commit()
    assert "audit_events_y2020m01" in dropped


def test_prune_keeps_recent_partitions(db_session):
    fixed_now = datetime(2026, 5, 18, tzinfo=timezone.utc)
    # The current month partition (y2026m05) was created by the migration.
    dropped = prune_old_partitions(db_session, retention_days=90, now=fixed_now)
    db_session.commit()
    assert "audit_events_y2026m05" not in dropped
```

### Step 4: `test_audit_auth_events.py`

Tests that the four auth events are actually emitted by the endpoints. Reuse the cookie-based TestClient pattern from Phase E migrations.

```python
"""Auth router emits audit events at the right call sites."""
from fastapi.testclient import TestClient

from core import cookie_auth
from db import database, models
from main import app


def _seed_admin(db_session, password="admin-pw"):
    admin = models.User(
        username="admin",
        password_hash=cookie_auth.hash_password(password),
        is_admin=True,
        is_active=True,
    )
    db_session.add(admin); db_session.commit(); db_session.refresh(admin)
    return admin


def test_login_success_emits_event(db_session, monkeypatch):
    admin = _seed_admin(db_session)
    app.dependency_overrides[database.get_db] = lambda: db_session
    try:
        c = TestClient(app)
        r = c.post("/api/auth/login", json={"username": "admin", "password": "admin-pw"})
        assert r.status_code == 200
        events = db_session.query(models.AuditEvent).filter_by(
            event_type="auth.login_success", user_id=admin.id
        ).all()
        assert len(events) == 1
    finally:
        app.dependency_overrides.clear()


def test_login_failure_emits_event(db_session, monkeypatch):
    _seed_admin(db_session)
    app.dependency_overrides[database.get_db] = lambda: db_session
    try:
        c = TestClient(app)
        r = c.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
        assert r.status_code == 401
        events = db_session.query(models.AuditEvent).filter_by(
            event_type="auth.login_failure"
        ).all()
        assert len(events) == 1
        assert events[0].payload["username_attempted"] == "admin"
        assert events[0].payload["reason"] == "wrong_password"
    finally:
        app.dependency_overrides.clear()


def test_logout_emits_event(db_session, monkeypatch):
    admin = _seed_admin(db_session)
    sid = cookie_auth.create_session(db_session, admin.id)
    app.dependency_overrides[database.get_db] = lambda: db_session
    try:
        c = TestClient(app)
        c.cookies.set(cookie_auth.COOKIE_NAME, sid)
        r = c.post("/api/auth/logout")
        assert r.status_code == 200
        events = db_session.query(models.AuditEvent).filter_by(
            event_type="auth.logout", user_id=admin.id
        ).all()
        assert len(events) == 1
    finally:
        app.dependency_overrides.clear()


def test_password_change_emits_event(db_session, monkeypatch):
    admin = _seed_admin(db_session, password="old-pw")
    sid = cookie_auth.create_session(db_session, admin.id)
    app.dependency_overrides[database.get_db] = lambda: db_session
    try:
        c = TestClient(app)
        c.cookies.set(cookie_auth.COOKIE_NAME, sid)
        r = c.post("/api/auth/password", json={
            "current_password": "old-pw",
            "new_password": "new-pw",
        })
        assert r.status_code == 200
        events = db_session.query(models.AuditEvent).filter_by(
            event_type="auth.password_changed", user_id=admin.id
        ).all()
        assert len(events) == 1
    finally:
        app.dependency_overrides.clear()
```

### Step 5: Run all the new tests

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest \
  tests/test_audit_schema.py \
  tests/test_audit_log_event.py \
  tests/test_audit_partitions.py \
  tests/test_audit_auth_events.py -v
```

All pass.

### Step 6: Run full sweep — confirm no regressions

```bash
cd /home/orbital/projects/pryzm/backend && ./venv/bin/pytest -q
```

Baseline: 359 passed. New: 359 + new audit tests.

### Step 7: Commit

```bash
cd /home/orbital/projects/pryzm && git add backend/tests/test_audit_*.py && \
git commit -m "test(audit): schema constraints, log_event helper, partitions, auth event emission"
```

---

## Task 7: Push + open PR

- [ ] **Step 1: Push**

```bash
cd /home/orbital/projects/pryzm && git push -u origin feat/audit-logging-f1
```

- [ ] **Step 2: Open PR**

```bash
gh pr create --base main --head feat/audit-logging-f1 \
  --title "feat(audit): F.1 — audit_events schema + log_event helper + auth events" \
  --body "$(cat <<'EOF'
First slice of the audit logging subsystem per docs/specs/2026-05-18-audit-logging.md. Foundation only — no event-emission call sites beyond the auth router. F.2 (chat / workspace / document / folder / tool / admin event wiring) and F.3 (admin read endpoints) come in subsequent PRs.

## Changes
- New audit_events table, monthly partitioned on created_at, with BEFORE UPDATE and BEFORE DELETE triggers raising "append-only"
- New AuditEvent ORM model + core/audit.py log_event helper + EventType constants
- services/audit_partitions.py with ensure_next_month_partition() and prune_old_partitions() callables (not scheduled yet)
- AUDIT_RETENTION_DAYS = 90 setting in config.py
- Wired the four auth events: login_success, login_failure, logout, password_changed
- Tests: schema constraints, FK SET NULL behavior, append-only enforcement, log_event shape, partition lifecycle, auth-event emission

After this lands, the spec's "F.1 ships immediately after auth Phase B" milestone is met. F.2 PRs add events to existing surfaces one domain at a time.

Spec: docs/specs/2026-05-18-audit-logging.md. Plan: docs/plans/2026-05-18-audit-logging-f1.md.
EOF
)"
```

- [ ] **Step 3: No auto-merge** — chore-but-foundational PR; operator reviews.

---

## Self-review

Spec coverage for F.1:

- [x] audit_events schema with required columns (Task 1)
- [x] Monthly partitioning on created_at (Task 1)
- [x] Append-only trigger (Task 1, test in Task 6)
- [x] FK ON DELETE SET NULL with display-name snapshot (Tasks 1+2, test in Task 6)
- [x] AuditEvent ORM (Task 2)
- [x] log_event helper with the documented signature (Task 3)
- [x] Retention sweeper + next-month creator callable (Task 4, test in Task 6)
- [x] AUDIT_RETENTION_DAYS setting (Task 4)
- [x] At least one domain wired as proof of life — auth (Task 5)

Out of scope (explicit follow-ups):
- F.2: wire chat / workspace / document / folder / tool / admin events
- F.3: GET /api/admin/audit endpoints
- Scheduled retention task (currently just callable functions, no cron yet)
- Dashboard Audit tab (Phase D dependency)
