# Audit logging

## Status

Design ready for implementation. Depends on the auth foundation (`docs/specs/2026-05-17-user-login-and-admin.md`) shipping Phase A so the `users` table exists to reference.

## Why

Today Pryzm keeps no structured record of who did what. Application logs (uvicorn stdout) capture HTTP traffic but not user-level actions in a queryable form. When something goes sideways — a tool call fails, a workspace gets unexpectedly mutated, a login attempt succeeds from a weird IP — there's no way to reconstruct what happened.

The auth foundation introduces real `user_id`s; this spec adds the structured event store that anchors observability, forensics, support, and accountability across the application.

## Goals

- One queryable surface (`audit_events` table) capturing every meaningful user and admin action.
- Append-only at the DB level (Postgres trigger).
- Hard-delete-safe — user/workspace/chat removal doesn't erase audit history.
- Bounded growth via time-based partitioning + a retention sweeper.
- Performance: inline sync writes, single index keyed to the dashboard's typical query patterns.
- Per-tool extensibility — adding a new tool doesn't require schema changes; the payload is JSONB.

## Non-goals (v1)

- Tamper-evidence beyond append-only (hash chaining, signed records, external immutable mirror).
- Real-time streaming to external SIEM. Export is possible later via simple SELECT — the table is portable.
- Full chat content capture. Previews only; the full text lives in the `messages` table.
- Per-event encryption at rest.
- Application/HTTP logs (FastAPI/uvicorn stdout). These stay accessible via `docker logs`.

## Data model

### `audit_events`

| column | type | notes |
|---|---|---|
| `id` | UUIDv7 PK | natural insertion order |
| `user_id` | UUID FK users, ON DELETE SET NULL, nullable | actor; NULL after hard delete or for system-generated events |
| `user_display_name_at_event` | text, nullable | snapshot of the user's username at event write time; survives hard delete |
| `event_type` | text, indexed | e.g., `chat.message_sent`, `admin.user_created` |
| `workspace_id` | UUID FK workspaces, ON DELETE SET NULL, nullable | scope for workspace-bound events |
| `session_id` | UUID FK sessions, ON DELETE SET NULL, nullable | scope for chat-bound events |
| `resource_type` | text, nullable | e.g., `user`, `workspace`, `document`, `bug_report` |
| `resource_id` | UUID, nullable | the resource the event acted on |
| `payload` | JSONB | event-specific data, shape documented per event_type |
| `source_ip` | text, nullable | from request, captured especially for auth events |
| `user_agent` | text, nullable | from request |
| `created_at` | timestamptz | partition key + most-used filter |

Indexes:
- `(user_id, created_at DESC)` — the dashboard's primary query pattern ("show me Alice's events, newest first")
- `(event_type, created_at DESC)` — for filtering by event class
- `(workspace_id, created_at DESC)` — for per-workspace timelines

### Partitioning

Monthly partitions on `created_at`:

```sql
CREATE TABLE audit_events (...)
PARTITION BY RANGE (created_at);

CREATE TABLE audit_events_y2026m05 PARTITION OF audit_events
  FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');
```

A scheduled task creates the next month's partition a few days before month-end. The retention sweeper drops partitions older than `PRYZM_AUDIT_RETENTION_DAYS` (default 90). Partition drops are DDL — they bypass the append-only trigger by design (that's the only legitimate removal path).

### Append-only trigger

```sql
CREATE FUNCTION audit_events_no_mutation() RETURNS trigger AS $$
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

Application code that attempts UPDATE or DELETE on the table fails loudly. DDL-level partition drops by the retention sweeper still work.

## Event taxonomy

The event_type strings group by domain prefix. v1 surface:

**`auth.*`** — login_success, login_failure, logout, password_changed, password_reset_by_admin

**`admin.user.*`** — created, edited, deactivated, activated, deleted (payload includes `is_hard: bool`), promoted_to_admin, demoted_from_admin

**`admin.template.*`** — created, edited, deleted, instantiated, pushed

**`admin.workspace.*`** — edited, deleted (admin acting on a user's workspace)

**`admin.system.*`** — model_added, model_removed, micro_prompt_edited

**`workspace.*`** — created, edited (user editing their own workspace; payload lists changed fields)

**`chat.*`** — session_created, session_deleted, message_sent, message_received, tool_invoked, rag_retrieved, web_search

**`document.*`** — uploaded, deleted, processing_failed

**`folder.*`** — created, edited, deleted

**`bugreport.*`** — submitted, acknowledged, resolved, dismissed, deleted (lifecycle of `bug_reports` rows, owned by the dashboard subsystem)

**`notification.*`** — broadcast_sent (admin → all users), sent (admin → specific user)

Adding a new event_type doesn't require a migration — the payload is JSONB and the type is a string. Conventions matter: keep the prefix.domain.verb shape and document the payload.

## Payload conventions

For each event_type, the expected payload keys are documented (in code, alongside the call site). Representative examples:

| event_type | payload shape |
|---|---|
| `auth.login_failure` | `{username_attempted: str, reason: 'wrong_password' \| 'account_disabled' \| 'rate_limited'}` |
| `chat.message_sent` | `{content_preview: str, token_count: int, has_attachments: bool, attachment_filenames: [str]}` |
| `chat.message_received` | `{content_preview: str, token_count: int, model: str, finished_cleanly: bool, tier: str, tools_used: [str], tools_count: int, reasoning: str?, reasoning_duration_s: float?, prompt_tokens: int, completion_tokens: int, duration_ms: int, ttft_ms: int, tokens_per_sec: float}` |
| `chat.tool_invoked` | `{tool_name: str, arg_values: dict, succeeded: bool, error_message: str?}` |
| `chat.rag_retrieved` | `{query_preview: str, num_results: int, source_filenames: [str], mode: str}` |
| `chat.web_search` | `{query_preview: str, query_refined: str, k_requested: int, k_returned_by_searxng: int, k_fetched_ok: int, k_failed: int, failure_reasons: dict, fetch_wall_clock_ms: int, extracted_bytes_total: int, synthesis_model_id: str}` |
| `workspace.edited` | `{changed_fields: [str], previous_values: dict, new_values: dict}` |
| `document.uploaded` | `{filename: str, mime: str, size_bytes: int, document_id: uuid}` |
| `admin.template_pushed` | `{template_id: uuid, affected_workspace_count: int, affected_user_count: int, had_customizations_count: int}` |
| `admin.user_deleted` | `{deleted_user_id: uuid, deleted_username: str, is_hard: bool}` |
| `bugreport.submitted` | `{bug_report_id: uuid, message_preview: str, current_workspace_id: uuid?, current_session_id: uuid?}` |

## Sensitive data policy

- **Chat content (prompts, responses):** first 200 chars stored as `content_preview`. Full text remains in `messages`; admin investigating a specific event can drill from `session_id` into the message table.
- **Tool args:** stored verbatim in v1. All current tools take innocuous arguments (hostnames, URLs, IDs). When a sensitive tool lands (e.g., one that takes a credential), add it to a per-tool denylist in `core/audit.py` — the args dict gets filtered before write.
- **Passwords:** never logged. `auth.login_failure` records the username attempted but not the password.
- **API tokens, session cookies, bearer headers:** never logged. The audit write path doesn't have access to them.
- **Request bodies:** not blanket-captured. Specific fields per event_type as documented above.

## Write path

Sync inline writes for v1. The audit insert participates in the surrounding request transaction; if the audit write fails (DB down, constraint violation, anything), the entire request rolls back. No silent swallowing of audit failures.

Centralized helper in `core/audit.py`:

```python
def log_event(
    db: Session,
    event_type: str,
    *,
    user: User | None = None,
    workspace: Workspace | None = None,
    session: Session | None = None,
    resource_type: str | None = None,
    resource_id: UUID | None = None,
    payload: dict | None = None,
    request: Request | None = None,
) -> None:
    db.add(AuditEvent(
        user_id=user.id if user else None,
        user_display_name_at_event=user.username if user else None,
        event_type=event_type,
        workspace_id=workspace.id if workspace else None,
        session_id=session.id if session else None,
        resource_type=resource_type,
        resource_id=resource_id,
        payload=payload or {},
        source_ip=request.client.host if request else None,
        user_agent=request.headers.get("user-agent") if request else None,
    ))
    # commit happens with the surrounding transaction
```

Call sites add `log_event(db, "domain.verb", user=current_user, ...)` after the business operation succeeds, before the response returns.

If profiling later shows the inline write adds measurable per-request latency, swap to an async queue (Redis Streams or in-memory) without changing call-site shape — the helper signature stays the same, only the internals change.

## Hard-delete and FK behavior

All FK references use `ON DELETE SET NULL`:
- `user_id` — after a user hard-delete, `user_display_name_at_event` keeps the event readable
- `workspace_id` — after workspace deletion, events still discoverable by `user_id` or `event_type`
- `session_id` — after chat-session deletion, same

This means audit_events never cascade-deletes from hard-delete chains. Retention is the only path that removes rows, and only at the partition level.

The auth spec already commits to this contract — Phase A doesn't add an `audit_events.user_id` FK because the table doesn't exist yet; this spec adds the FK with the correct SET NULL behavior.

## Endpoints

All read endpoints gated by `require_admin`.

- `GET /api/admin/audit` — paginated query. Query params: `user_id`, `event_type` (exact or `prefix:` match), `workspace_id`, `from`, `to`, `limit`, `cursor`. Returns events ordered by `created_at` desc. Cursor pagination (created_at + id) for stable scrolling across appended events.
- `GET /api/admin/audit/event-types` — returns the list of known event types, used by the dashboard's filter dropdown. Derived from a canonical list in `core/audit.py`.
- `GET /api/admin/audit/{event_id}` — single event detail, including the full payload (the list endpoint truncates large payloads to keep the response light).

No write endpoints. Events are emitted by app code via the `log_event` helper.

## Retention

- Default: 90 days. Configurable via `PRYZM_AUDIT_RETENTION_DAYS`.
- Implementation: a daily scheduled task computes the cutoff month and drops any partitions whose upper bound is below it.
- The audit retention task is independent of the GC sweeper that already cleans orphan documents.

## Migration order

Phase F of the broader auth+audit+dashboard work:

- **F.1** — schema migration: create `audit_events`, partitioning helpers, append-only trigger, retention task scaffolding. No application code writes events yet.
- **F.2** — wire `log_event(...)` calls into existing surfaces. Done incrementally per surface (auth, chat, tools, workspaces, documents, folders). Each PR adds events for one domain and a corresponding test.
- **F.3** — admin read endpoints. Required by the dashboard's Audit tab.

F.1 ships immediately after auth Phase B (when `users` exists). F.2 can interleave with auth Phase C. F.3 ships before the dashboard spec's Audit tab implementation.

## Testing

Each event_type wired in F.2 gets a test that:
1. Triggers the business operation (e.g., post a chat message)
2. Asserts an `audit_events` row was written
3. Verifies the row's `event_type`, `user_id`, `workspace_id`, and key payload fields

A separate test exercises the append-only trigger by attempting `UPDATE audit_events` and asserting it raises. Same for `DELETE`.

A migration smoke test exercises partition creation and the retention sweeper (insert into a future-dated partition, run sweeper, verify it's untouched; insert into a past-dated partition, run sweeper, verify it's dropped).

## Decisions

All resolved in the May 18 brainstorm:

1. **Chat content detail:** preview (first 200 chars), not full content. Full text remains in `messages`.
2. **Tool args:** stored verbatim in v1. Per-tool denylist added when the first sensitive tool ships.
3. **Retention:** 90 days default, configurable.
4. **Write path:** sync inline, participating in the request transaction.
5. **Append-only enforcement:** Postgres trigger.
6. **Bug reports separate from audit_events:** lifecycle data in `bug_reports`, lifecycle events recorded in `audit_events` (designed in the dashboard spec).
7. **Partitioning:** monthly, on `created_at`.
8. **FK behavior:** SET NULL across the board; snapshot fields preserve readability.

## What this unblocks

- Dev dashboard's Audit tab (the main consumer).
- Bug-report lifecycle visibility — every state transition is in the audit log.
- Login-failure forensics ("show me failed logins from this IP in the last week").
- Notification system audit ("admin sent a broadcast at this time").
- Future SIEM export — `audit_events` is portable, no proprietary format.
- Compliance posture for any future certification work.
