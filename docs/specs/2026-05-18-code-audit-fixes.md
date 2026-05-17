# Code audit fixes — May 2026

Twelve fixes from the May audit, grouped into four commits on one
branch. R2 (the `stream_chat` refactor) and S1 (bearer token in URL)
are out of scope and tracked separately below.

## Scope

In: correctness bugs, mobile UX, ingest reliability, streaming
control, cache headers, workspace integrity.

Out:

- **S1** — bearer token in `<img>` and `EventSource` URLs. Phase E of
  the user-login spec removes the `?token=` plumbing once cookies are
  the only auth, which solves this without needing interim work.
- **R2** — `stream_chat` is 335 lines and recursively re-enters
  itself on escalation, double-firing `files_referenced` events. Own
  branch (`refactor/stream-chat-split`), own PR after this one
  merges. Full split into `_prepare_messages` and `_run_loop`.

## Branch and commits

Branch: `chore/code-audit-2026-05`

| # | Commit | Items |
|---|---|---|
| 1 | `fix(audit): correctness quick wins` | B1, B3, B6, B8, B10 |
| 2 | `fix(audit): streaming, ingest, sidebar fixes` | B2, B9, B4, B5, R1 |
| 3 | `fix(audit): cache control on document raw` | S2 |
| 4 | `fix(audit): workspace folder fk + scope check` | B7 |

Each commit is independently revertable. No Co-Authored-By trailer.

---

## Commit 1 — correctness quick wins

### B1 — Tool-result messages carry `tool_call_id` in the live loop

`backend/core/ai_engine.py:455-459`

The live agentic loop appends tool-result messages without
`tool_call_id`. The DB-rebuild path in `routers/chat.py:62-67`
already includes it. llama.cpp tolerates the missing field today, but
the two paths shouldn't drift.

Change: copy `tool_call["id"]` into a `tool_call_id` field on the
appended tool message.

### B3 — `overview_mode` retrieval orders chunks deterministically

`backend/services/knowledge.py:444-449`

The `overview_mode` path (fires when a file is attached with no text
prompt) returns chunks with no `ORDER BY`. The common
attach-and-ask flow uses the `restrict_to_filenames` path, which is
already ordered, so this is a niche fallback. Cheap to fix anyway.

Change: add `.order_by(models.DocumentChunk.id)` before `.limit(top_k)`.

### B6 — `branchSession` callback includes `workspace` in deps

`frontend/src/hooks/useMessageActions.ts:88`

`useCallback` dep array omits `workspace`. The closure uses it in
the URL, so a workspace switch leaves the callback targeting the old
slug. Sibling callbacks in the same file already include it.

Change: add `workspace` to the dep array.

### B8 — Message action toolbar reachable on touch devices

`frontend/src/components/MessageActions.tsx:41`

Toolbar uses `opacity-0 group-hover:opacity-100` plus
`pointer-events-none group-hover:pointer-events-auto`. Touch devices
don't fire `:hover`, so the actions are invisible and untappable on
mobile.

Change: add `[@media(hover:none)]:opacity-100
[@media(hover:none)]:pointer-events-auto` so the toolbar is always
visible on touch.

### B10 — `condense.py` advisory lock acquisition inside the try block

`backend/services/condense.py:43-58`

The lock-acquisition `db.execute(...)` calls sit before the `try:`.
If either raises, the `finally` that releases the lock never runs and
a half-acquired session-level lock can be returned to the pool still
held. That session's condensation is silently jammed until restart.

Change: move both `db.execute` calls inside the `try:`. Gate the
unlock on `acquired` being truthy.

---

## Commit 2 — streaming, ingest, sidebar fixes

### B2 — GC sweep deletes image files from disk

`backend/services/tasks.py:13-17`

The garbage-collection sweep uses
`.delete(synchronize_session=False)`, which bypasses SQLAlchemy's
`after_delete` hook at `db/models.py:157`. The hook is responsible
for `os.remove(target.storage_path)`. Rows go, files stay.

Change: switch to ORM-style iteration:

```python
docs = db.query(models.Document).filter(...).all()
for doc in docs:
    db.delete(doc)
db.commit()
```

Hourly GC volume is small enough that per-row overhead is fine.

### B9 — Ingest failure rolls back partial chunks

`backend/services/ingest_pipeline.py:73-81` and `_finalize_error`

When embedding raises mid-loop, `_finalize_error` commits the error
status — and that commit also flushes the chunks already `db.add()`'d.
The document ends up marked `status=error` while still carrying half
its embeddings; re-upload duplicates them.

Change: in `_finalize_error`, `db.rollback()` first. Then re-fetch
the document row, set status and error, commit.

### B4 — `stopInference` no longer aborts unrelated streams

`frontend/src/hooks/useInference.ts:315-317`

The fallback `for` loop aborts every controller whose key starts with
`optimistic-` if direct and migrated-id lookups both miss. Two
concurrent streams die together when one's stop button is clicked
with a stale id.

Change: delete the fallback loop. If both lookups miss, the stream is
gone.

### B5 — Hook-level + UI-level guards block double-send

`frontend/src/hooks/useInference.ts:50` and
`frontend/src/components/ChatInput.tsx:100-114`

`sendMessage` reuses the optimistic session id on a rapid second
send, overwriting the first call's abort controller. The first
stream becomes uncancellable; the first's `finally` deletes the
second's controller entry.

The UI side replaces Send with Stop during streaming, so mouse
double-click is already blocked. But `guardedKeyDown` only checks
`uploadsInProgress`, so Enter mid-stream still triggers the bug.

Changes:

1. Hook: early return at the top of `sendMessage` when `isProcessing`
   is true. Return the existing `optimisticId` so callers don't get
   a type surprise.
2. UI: add `isProcessing` to the guard conditions in `guardedSubmit`
   and `guardedKeyDown`.

### R1 — Sidebar stays mounted across open/close

`frontend/src/components/Sidebar.tsx:19`

`if (!isOpen) return null` unmounts `SessionDirectory` on every
close. Reopening refetches `/sessions` and `/folders` and resets
scroll. On mobile where the sidebar toggles frequently, every open
hits the API twice.

Change: replace the early null return with `-translate-x-full` when
closed. The existing `transition-all duration-300` then drives the
slide. Backdrop overlay stays conditional — it's a separate element.

---

## Commit 3 — cache control on document raw

### S2 — `Cache-Control: private` on authenticated document responses

`backend/routers/documents.py:233`

The `/documents/{id}/raw` endpoint sets `Cache-Control: public,
max-age=31536000, immutable`. `public` lets any cache in the network
path (Wi-Fi proxy, ISP cache, CDN) store the response. Combined with
the bearer token in the URL, the cache key includes the token, and
anyone with proxy access can replay private images.

Cross-device behavior is unaffected: each device fetches from the
server independently and caches its own copy. `private` only changes
what intermediate caches can do.

Change: `Cache-Control: private, max-age=2592000` (30 days). Add an
`ETag` derived from the document id for revalidation. Drop
`immutable`.

---

## Commit 4 — workspace folder fk + scope check

### B7 — `folder_id` on session update is workspace-scoped and FK-constrained

`backend/routers/chat.py`, `backend/db/models.py`, new alembic
migration.

`PATCH /sessions/{id}` accepts any `folder_id` and `setattr`s it
onto the session row with no scope check. `Session.folder_id` is a
plain string, not a `ForeignKey`. A client can move a session into a
folder belonging to another workspace, creating a dangling reference.

**Handler:** when `payload.folder_id` is present and not `None`, call
`verify_workspace_owns(payload.folder_id, models.Folder, workspace.id,
db)` before applying. Returns 404 on mismatch (matches the existing `verify_workspace_owns` convention, which uses 404 to avoid leaking workspace existence).

**Schema:** add `ForeignKey("folders.id", ondelete="SET NULL")` to
`Session.folder_id`. The handler check enforces workspace scoping
(the FK can't know about workspaces); the FK handles cleanup if a
folder is deleted.

**Migration:** scrub dangling references first, then add the FK:

```sql
UPDATE sessions
   SET folder_id = NULL
 WHERE folder_id IS NOT NULL
   AND folder_id NOT IN (
       SELECT id FROM folders
        WHERE workspace_id = sessions.workspace_id
   );
```

Down-migration drops the FK; it does not restore the cross-workspace
values.

**Consumer audit:** before merging, `git grep "folder_id"` across
backend to confirm no other path writes the field without going
through the handler. Frontend drag-and-drop in `SessionDirectory.tsx`
already only offers same-workspace folders; honest clients see no
change.

**Tests:** add a cross-workspace folder PATCH case to
`backend/tests/test_workspace_boundary.py`.

---

## Verification

Per commit:

- **Commit 1:** pytest passes. Manual touch-emulation check of the
  mobile toolbar.
- **Commit 2:** pytest plus autotest runs covering ingest failure,
  rapid double-Enter, sidebar toggle on a mobile viewport.
- **Commit 3:** new test asserting the response header on the
  doc-raw route.
- **Commit 4:** the new `test_workspace_boundary.py` case;
  `test_migrations_smoke.py` covers up/down.

## Workflow

One branch, four commits, one PR.

1. Branch off `main` as `chore/code-audit-2026-05`.
2. Land each commit as a self-contained unit.
3. Open one PR titled `chore: code audit fixes (May 2026)`. Lean
   description with one line per commit and a link to this spec.
4. Don't auto-merge. Explicit approval required before merge.

## Follow-up

- **R2** — own PR after this branch merges. Full split of
  `stream_chat` into `_prepare_messages` and `_run_loop`; escalation
  re-enters only the loop.
- **S1** — handled by Phase E of the user-login work.
- Lifting `/sessions` and `/folders` fetches into `SessionContext`
  is a future improvement worth doing if another remount case
  surfaces.
