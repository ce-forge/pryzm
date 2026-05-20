# Post-launch hardening

Outputs of the May 21 multi-agent review, grouped into six phases that
ship independently. Each phase is one branch and one PR.

## Scope

In:

- Security gaps (cookie flag, IDOR, must-change enforcement, workspace
  RBAC, CSRF defence-in-depth, bootstrap lockout, audit-payload spoof,
  filename sanitisation, proxy normalisation, tool allowlist coverage,
  template-instantiate strictness)
- Data layer fixes (cross-user slug check, color length mismatch,
  missing FK indices, partition coverage gap, folder leak)
- Backend refactor (ai_engine split, chat router split, audit-shape
  inversion, llama-swap config + status extraction, knowledge mode
  split, dead-code removal)
- Frontend refactor (inference hook split, session-context split,
  context value memoisation, large admin-page split, hook extraction
  for download stream / session list / folder list, shared admin
  modules)
- Doc sweep (spec drift on auth, audit-logging payloads, web-search,
  templates; CLAUDE.md "Alerts" rename; one ghost event-type)

Out:

- Password minimum length — intentionally relaxed during QA; bump back
  to 12 before production, not now
- Login rate limit → Redis — single-worker deployment only; revisit
  when multi-worker
- Audit-event `resource_id` index — no consumer endpoint today
- Workspace `created_at` nullable tightening — cosmetic
- `pryzm_session` cookie being bearer-equivalent — already an accepted
  risk in `docs/internal/2026-05-19-known-security-risks.md`

## Branches and PRs

| Phase | Branch | Risk | Sub-batches |
|---|---|---|---|
| 1 | `fix/security-high` | HIGH | one commit per fix (~7 commits) |
| 2 | `fix/security-medium` | MEDIUM | one commit per fix (~5 commits) |
| 3 | `fix/data-layer` | MEDIUM | one commit per fix (~6 commits) |
| 4 | `refactor/backend-cleanup` | LOW (test-protected) | one commit per refactor (~12 commits) |
| 5 | `refactor/frontend-cleanup` | LOW (Playwright-protected) | one commit per refactor (~14 commits) |
| 6 | `docs/post-launch-sweep` | TRIVIAL | one commit |

Phases 1–3 are surgical and can ship back-to-back. Phase 4 is large
and lives behind the 466-test pytest suite. Phase 5 is verified
through the Playwright smoke harness with the `qatest`/`test`
non-admin account plus the admin login.

Each commit body stays small. PR descriptions are six-line release
notes — no internal narration.

---

## Phase 1 — Security HIGH

### S1 — `/analyze` session lookup not scoped to caller
`backend/routers/chat.py:357-358`

`Session.id` lookup with no workspace or user filter. An
authenticated user passing `?workspace=<own-slug>` and
`session_id=<foreign-id>` can read and write the foreign session.

Change: filter by `Session.workspace_id == workspace.id`. 404 on
miss. Add a regression test (sibling shape to
`test_workspace_boundary.py`).

### S2 — `must_change_password` is enforced only in the UI
`backend/core/cookie_auth.py:89-99`

`current_user` does not consult the flag. A scripted client bypasses
the forced-change screen.

Change: in `current_user`, after the active-user check, raise 403 for
every path except `/api/auth/password`, `/api/auth/logout`, and
`/api/auth/me` when `user.must_change_password` is true. Implement by
allowing the dependency to inspect `request.url.path`. Regression
test: scripted client hits `/workspaces` while
`must_change_password=true` and gets 403.

### S3 — `can_create_workspaces` is never enforced
`backend/routers/workspaces.py:70-152`

Flag is decorative.

Change: at the top of `create_workspace`, raise 403 when
`not user.is_admin and not user.can_create_workspaces`. Add the
matching test.

### S4 — `clone_from` leaks any workspace's prompt + tools
`backend/routers/workspaces.py:106-114`

`get_by_slug` is unscoped. Source's `system_prompt` and
`enabled_tools` are copied verbatim into the new workspace and read
back to the caller.

Change: pass `user_id=user.id` to `get_by_slug`; remove the
acknowledging NOTE. If the caller still wants to seed from an
admin-published template, they should go through the workspace
template flow that already exists. Test: user A clones user B's
workspace by slug, expects 404.

### S5 — Session cookie hardcoded `secure=False`
`backend/routers/auth.py:88`

The TODO comment promises an env hook that doesn't exist.

Change: read `PRYZM_COOKIE_SECURE` from env (default true). Backend
log warns once at startup if it's false. Update `.env.example`. The
cookie helper lives in `routers/auth.py` today; if a second site
needs it, lift to a `core/cookies.py`.

### S6 — No `Origin` allowlist on state-changing endpoints
`backend/main.py:167-175`

The 2026-05-17 user-login spec calls for an Origin check as defence
in depth alongside `SameSite=Lax`. Code has none.

Change: add a starlette `BaseHTTPMiddleware` that, on
POST/PUT/PATCH/DELETE, checks the `Origin` header against an
allowlist derived from `PRYZM_ALLOWED_ORIGINS` (comma-separated env
var, defaults to the same value already used for CORS). Reject 403 on
mismatch; allow absent Origin (curl / native apps) — these are not
the CSRF threat model. Test: POST with foreign Origin returns 403,
POST with allowed Origin passes.

### S7 — Bootstrap admin silently defaults to `admin`/`admin`
`backend/core/bootstrap.py:24-35`

Combined with S2 already being broken, a fresh internet-exposed
install is takeover-by-default until the operator logs in.

Change: when `PRYZM_BOOTSTRAP_ADMIN_PASSWORD` is unset, generate a
random 24-char password using `secrets.token_urlsafe(18)`, print it
once at startup (single-line WARN), and persist nothing on disk.
Refuse to start if the listener is on `0.0.0.0` AND the env var is
unset AND no admin row exists — leave it to the operator to pick.
Test: env unset + admin exists → random password + must_change=true;
env unset + non-loopback bind + no admin → start aborts.

---

## Phase 2 — Security MEDIUM

### M1 — Audit payload reflects spoofed workspace/session
`backend/routers/bug_reports.py:74-89, 113-119`

The `current_workspace_id` / `current_session_id` claimed in the
payload are silently nulled on the row but logged verbatim. An admin
reading the audit feed sees a foreign id and concludes the user was
in that workspace.

Change: log the validated (possibly-null) values, not the claimed
ones. If preserving the claim is useful, log it under a separate
`claimed_workspace_id` field so the spoof is visible.

### M2 — `Content-Disposition` built with unsanitised filename
`backend/routers/documents.py:262`

RFC 6266 violation; MIME-confusion risk on adversarial filenames.

Change: emit per RFC 5987 — `filename="<ascii-safe>"; filename*=UTF-8''<percent-encoded>`. Strip control characters from the
fallback ASCII name. Test: upload a doc named `weird";name.pdf` and
assert the response header parses.

### M3 — `admin_engine` proxy doesn't normalise the catch-all path
`backend/routers/admin_engine.py:140-141`

`..` segments resolve against `LLM_SERVER_URL`. Bounded today, but
the proxy is admin-cookie-only and an admin shouldn't be able to
slip out of the configured upstream via a path trick.

Change: reject any `path` containing a `..` path segment with 400
before constructing `target_url`. Test: GET with `../foo` returns 400.

### M4 — `get_public_ip` bypasses the network-tool allowlist
`backend/tools/network.py:200-206`

Every other tool in this module goes through `validate_target`.
`get_public_ip` calls `api.ipify.org` directly, leaking egress traffic
the operator may have wanted to keep quiet.

Change: respect the same `NETWORK_TOOLS_ALLOW_PUBLIC_IP` env flag
(default false). When false, the tool returns
`"Public IP lookup disabled by NETWORK_TOOLS_ALLOW_PUBLIC_IP=false."`.
Test: env unset → disabled message returned.

### M6 — Template instantiate silently filters disallowed tools
`backend/services/template_apply.py:138-197`,
`backend/tests/test_allowed_tools.py:444-470`

The 2026-05-19 per-user-allowed-tools spec separates strict sites
(instantiate) from filter sites (push, reset). The unified `/apply`
endpoint filters everywhere. The test class even documents this.

Change: in `apply_template`, when `action == "create"`, run
`enforce_allowed_tools` instead of `filter_allowed_tools` for the
target user. Update or invert the documenting test. Adopt + update
keep filter behaviour.

Note: M5 (password minimum length) is intentionally left at 4 during
QA. See [project memory](#) for the production flip.

---

## Phase 3 — Data layer

### D1 — `slugify_unique` checks across all users
`backend/services/workspaces.py:90-97`

DB allows per-user slug collisions (`uq_workspaces_user_slug` is
partial). Global check both produces `-2` suffixes for no reason and
discloses other users' chosen slugs through suffixing.

Change: add `user_id == user.id` to the existence query. Test: user A
and user B both create a workspace named "Personal" → both get slug
`personal`, no `-2`.

### D2 — `Workspace.color` length mismatch model ↔ DB ↔ template
`backend/db/models.py:47` (workspaces: `String(32)`),
`backend/db/models.py:30` (templates: unbounded).

Admin creates a template with `color` longer than 32, instantiating
copies → `value too long for type character varying(32)` at INSERT.

Change: introduce `WORKSPACE_COLORS: tuple[str, ...]` in
`backend/utils/constants.py` (or similar), declare both columns as
`String(32)`, mirror the validation in the schema layer, and add a
DB CHECK constraint `color = ANY(WORKSPACE_COLORS)` via a new
migration. Test: insert a long color through the admin template path
fails at the schema layer with 422, not at INSERT.

### D3 — Missing indices on `SET NULL` FK columns
`backend/db/models.py:182` (`bug_reports.resolved_by`),
`backend/alembic/versions/9221fabaf142_audit_events_schema.py`
(`audit_events.session_id`)

Hard-deleting an admin or a session full-scans these tables.

Change: new migration adds two partial indices —
`CREATE INDEX CONCURRENTLY ix_bug_reports_resolved_by ON bug_reports(resolved_by) WHERE resolved_by IS NOT NULL;`
and the equivalent on `audit_events`. Migration uses
`autocommit_block()`. No test (index existence is implicit
infrastructure).

### D4 — Partition scheduler covers next month but not current
`backend/services/audit_partitions.py:32-50`

A backend that's offline across two month boundaries misses a
partition; first INSERT throws.

Change: in the scheduler tick, ensure CURRENT month then NEXT month
(both with `IF NOT EXISTS`). Test: with `freeze_time` jumping the
clock forward two months, scheduler creates the missing partition.

### D5 — `GET /folders` returns raw ORM rows including `user_id`
`backend/routers/folders.py:24-29`

The field is the current user's own id today, so no live leak — but
the response shape is uncontrolled and starts leaking the moment
folder ownership ever decouples from workspace ownership.

Change: define `FolderResponse(BaseModel)` with `{id, name,
workspace_id, position}`. Switch the route to
`response_model=list[FolderResponse]`.

### D6 — `audit_partitions` regex too loose when parsing back
`backend/services/audit_partitions.py:88`

The prune path reads partition names from `pg_inherits` and passes
them straight to `DROP TABLE`. Today every name comes from internal
datetime math, but the parser tolerates anything starting with
`audit_events_y`.

Change: validate `name` against
`^audit_events_y\d{4}m\d{2}$` before interpolating into the DROP.
Skip names that don't match.

---

## Phase 4 — Backend refactor

### B1 — Split `core/ai_engine.stream_chat`
Current: one 520-line generator owning 8 concerns. Split:

- `_prepare_system_message(workspace, mode, history)` → message list
- `_resolve_route(prompt, history, attachments)` → `(model, tier, reason)`
- `_run_auto_rag(...)` → chunks + audit payload (no streaming)
- `_run_agent_loop(messages, route, tool_set, ...)` → async generator
  of typed events
- `stream_chat` becomes a 60-line orchestrator

Test: existing pytest suite covers the full loop; add no new tests,
rely on the regression bar.

### B2 — Extract `services/chat_pipeline.py`
Pull these out of `routers/chat.py`:

- `resolve_or_create_session(db, user, workspace, prompt, session_id)`
- `claim_attachments(db, workspace, session, attachment_ids)`
- `persist_user_message(db, session, prompt, log)`
- `persist_assistant_message(db, session, status, full_response,
  tool_calls, reasoning, route_meta, log)`

The two near-identical assistant-persist blocks collapse to one
function used by both completion branches. Router shrinks to ~400.

### B3 — Move single-shot LLM utilities to services
- `condense_chat_memory` → `services/condense.py` (sibling already
  there).
- `generate_title` → `services/title.py` (new).
- `_audit_chat_event` → fold into `core/audit.log_event_in_new_session`.
- `_match_session_filename_mentions` → `services/knowledge.py`,
  accepting a `db` from the caller.

### B4 — Invert tool audit shape
Tools today return strings; per-tool audit data is exfiltrated via a
`_LAST_STATS` module-level dict in `tools/web.py`.

Change: `@tool` decorator gains an optional `audit_event_type` and
the wrapped function may return `(content_str, audit_payload_dict)`.
Engine emits exactly one `CHAT_TOOL_INVOKED` (or the override) per
call, with the payload merged. Tool modules become self-contained.

### B5 — Extract `services/llama_swap_config.py`
From `routers/admin.py`, lift:

- `_read_yaml`, `_write_yaml`
- `_parse_model_row`, `_build_cmd_block`
- `_HF_RE`, `_HFF_RE`, `_NGL_RE`, `_CTX_RE`, `_QUANT_FROM_FILE_RE`
- `_reload_llama_swap` (its three call sites swallow
  `CalledProcessError` — fold the catch in)

Router becomes thin. `core/llm_router.reload_router_from_yaml`
imports from the new module.

### B6 — Extract `services/llama_swap_status.py`
The 100-line `model_status` SSE generator with three concurrent
producers becomes `async def stream_status(model_id) -> AsyncIterator[str]`.
Router endpoint is 5 lines.

### B7 — Split `knowledge.retrieve_relevant_chunks`
Three modes, one 100-line function. Split into:

- `_retrieve_pinned_filenames(...)`
- `_retrieve_session_overview(...)`
- `_retrieve_workspace_wide(...)`

Public entry point dispatches by mode argument. Drop the "fall
through" comment when the cases are actually exclusive.

### B8 — Delete dead code + dedupe sync embed
- `knowledge.ingest_document` has only test callers → delete; update
  the two tests to use `add_chunks_to_document`.
- `knowledge.search_chunks_sync` re-implements `embed()` with raw
  `requests.post` → either run `asyncio.run(llm_server.embed(...))`
  or extract a sync embed helper in `core/llm_server.py`.

### B9 — Move `WEB_SEARCH_DIRECTIVE` to data
`backend/tools/web.py:90-125` carries a 30-line LLM-facing prompt
inline. Move to `backend/data/tool_directives.default.json`; load via
`prompt_manager.get_tool_directive("web_search")`.

### B10 — Tool registration via workspace.enabled_tools
`tools/web.py:145` and `tools/retrieval.py:33` hardcode
`workspaces=["it_copilot", "personal"]`. Drop the per-tool
`workspaces=` parameter entirely; rely on the existing
`Workspace.enabled_tools` JSON column as the only gate.

### B11 — Drop `workspace="it_copilot"` default from upload
`backend/routers/documents.py:50`. Make required.

### B12 — Replace `print()` with logger
`backend/routers/chat.py:588, 663`. Two-line fix.

---

## Phase 5 — Frontend refactor

### F1 — Pure SSE event helpers
Extract from `hooks/useInference.ts`:

- `parseSseLine(parsed) → StreamEvent | null` — pure, unit-testable
- `applyStreamEvent(state, event) → state` — pure reducer

`sendMessage` becomes orchestrator only.

### F2 — Single live-key write in the stream loop
`useInference.ts` mirrors every chunk write to two keys
(`[optimisticId]` + `[realDbId]`). Introduce
`const liveKey = realDbId ?? optimisticId` and write once per chunk.
Migrate the bucket once when the real id arrives, in
`migrateBucket(optimisticId, realDbId)`.

### F3 — `clearStreamingForSession(sid)` helper
Replace the five identical delete-both-keys blocks in `finally` with
one helper. Or fold the five streaming maps into one
`Record<string, StreamingState>` and reduce the cleanup to one
`delete`.

### F4 — Split `SessionContext`
Current value is a 16-field object rebuilt on every chunk →
re-renders every consumer. Split into:

- `SessionMetaContext` — workspace, currentSession, sessionTitle,
  navigateToSession, etc. — stable across streams
- `SessionMessagesContext` — `messages`, `streamingX`,
  `appendMessage`, etc. — high-frequency churn

Consumers pick the context that matches their access pattern.

### F5 — Drop dead context exposure
`getMessages` and `activeCacheKey` are exposed from
`SessionContext` but have zero consumers. Remove from the context
type and the value.

### F6 — Memoise pass-through providers
`InferenceContext`, `UploaderContext`, `TestSuiteContext` are trivial
hook wrappers that return a fresh object every render. Wrap the
returned hook value in `useMemo` so reference identity holds when
the hook output is unchanged.

### F7 — Extract `BugDetailModal`
`app/admin/bug-reports/page.tsx` shrinks from 501 → ~280 by moving
the modal to `components/admin/bugReports/BugDetailModal.tsx`. The
admin page becomes list + filter only.

### F8 — Shared admin modules
- `STATUS_COLORS`, `<StatusBadge />` → `components/admin/StatusBadge.tsx`
- `AdminBugReport`, `AdminUserRow`, `AdminWorkspaceRow` → `types/admin.ts`

### F9 — Shared `payloadSummary`
Identical function in `app/admin/users/[user_id]/page.tsx:398-405`
and `app/admin/audit/page.tsx:337-345`. Promote to
`utils/auditPayload.ts`.

### F10 — `useModelDownloadStream`
The 7-state SSE download loop inside
`components/admin/system/SettingsModels.tsx` is a second copy of
`useInference.ts`'s NDJSON shape. Extract
`hooks/useModelDownloadStream(id)` returning
`{ log, status, err, progress, cancel }`.

### F11 — Split `WorkspaceSettings`
Discriminated-union prop type hides two unrelated components.
Split into `WorkspaceCreateModal` + `WorkspaceEditModal`, sharing a
`WorkspaceFieldsForm` sub-component. Drop the empty-success-handler
abuse of `withRollback` — write a normal try/catch in the new
components.

### F12 — `useSessionList` + `useFolderList`
`SessionDirectory.tsx` owns sessions list, folders list, drag-drop,
inline create + rename, delete confirms, and localStorage. Extract
the two list hooks; component becomes render + drag-drop wiring.

### F13 — Collapse `AppProviders`
Wraps a single child today. Either inline `AuthProvider` directly in
`layout.tsx`, or hold `AppProviders` open with comments documenting
where future global providers go. Pick one.

### F14 — `ChatInput` consumes contexts directly
Drop the 8 prop-drilled context dispatchers in favour of
`useUploaderContext()`, `useTestSuiteContext()`, etc. inside
`ChatInput`. `ActiveSession` no longer plumbs the context shape into
props.

---

## Phase 6 — Docs sweep

Lean edits — one commit.

- `docs/specs/2026-05-17-user-login-and-admin.md` — document the
  closed self-change path, the `must_change_password` flow, and the
  random-password bootstrap. Mark the `is_template` paragraph
  superseded by `2026-05-18-workspace-template-split.md`.
- `docs/specs/2026-05-20-web-search-v2.md` — describe Playwright
  fetcher, default 3, frontend-owned sources pill (model directive
  bans the footer).
- `docs/specs/2026-05-19-per-user-allowed-tools.md` — reflect Phase
  2 M6: instantiate strict, push/adopt filter.
- `docs/specs/2026-05-18-audit-logging.md` — refresh `chat.*` payload
  shapes (chat_audit_payload, web_search payload).
- `CLAUDE.md` — rename "Bug reports" admin tab to "Alerts" in the
  admin dashboard section.
- `backend/core/audit.py` — either emit `AUTH_SESSION_EXPIRED` from
  `get_session_user` when an expiry is detected, or delete the
  unused EventType constant. Pick: delete, since the cookie auth
  module doesn't have a clean place to emit and silent expiry is the
  current behaviour.

---

## Test strategy

- Phase 1, 2, 3: each fix lands with a new test or an extended
  existing test. Existing pytest suite (~466 tests) gates merge.
- Phase 4: rely on pytest suite for regression. Where extraction
  changes a public surface (e.g. `condense_chat_memory` location),
  update the test imports too.
- Phase 5: Playwright smoke suite under `tests/smoke/` gates merge.
  Add a smoke test for the `must_change_password` redirect (Phase 1
  S2 frontend follow-through) and one for the
  `WorkspaceCreate`/`WorkspaceEdit` split (Phase 5 F11). Use the
  `qatest`/`test` account for non-admin paths and `admin`/<known> for
  admin paths.
- Phase 6: docs only, no tests.

---

## Rollout order and stop conditions

Execute phases in order. Between each, commit, push, open the PR,
wait for CI, merge if green. Stop and check in with the user if:

- Any test the user didn't ask to delete starts failing
- A schema change has more than 50 affected rows on existing data
- A refactor cascades beyond the file map in the corresponding plan
  section (the plan's file map is the contract)

The "auto-merge authorized at phase boundaries" memory applies here.
