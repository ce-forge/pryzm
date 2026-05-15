# Async Ingestion (SSE-based) — Design Spec

- **Date**: 2026-05-15
- **Status**: Draft, pending review.
- **Branch context**: spec authored on `main` at `d5765d9`.
- **Predecessor**: future-features Item 4 ("Async execution + WebSockets") + the deferred "Uploads take ages" thread.

## Problem

Today, `POST /upload` does the full pipeline synchronously: stream bytes in → save to disk → VLM captioning (2-5 s on a warm E4B, 10-30 s on a cold swap) → embed chunks → return 200 with the document_id. The response only arrives after every step finishes. The upload pill spins for that whole window; the send button stays disabled; the user waits.

This blocks the user from typing and sending while captioning is still running, which is wasteful — bytes are on the server within a second, but the user can't dispatch a message for several more seconds. Multi-image uploads compound the wait (sequential queue, no overlap with prompt composition).

## Goal

Decouple the HTTP-request lifetime from the ingestion-pipeline lifetime. The user gets fast feedback after bytes-uploaded; status updates for the rest of the pipeline arrive via a server-pushed event stream; the prompt can be sent the instant all attached documents are ready, not when all HTTP responses complete.

**Success criterion (user-verifiable):** Upload a 2 MB JPG on the live stack. Within ~500 ms the pill flips from "uploading" to "processing"; user can type and the send button correctly indicates "waiting on processing". Within ~3 s the pill flips to "ready"; send becomes enabled. The total wall-clock from upload-click to send-able is unchanged, but typing-overlap reclaims the captioning latency for the user.

## Non-goals

- **WebSockets.** SSE is sufficient — server-push of status events is one-way (server → client). WebSocket's bidirectionality would be wasted here; we can add it later if a real use case (multi-tab sync, server-driven cancellations) emerges.
- **A worker queue (Celery / RQ / ARQ).** Captioning is bounded (~5 s, 30 s worst case). `asyncio.create_task` inside the FastAPI process handles this for a single-user dev setup. When this becomes multi-tenant, revisit with a real worker.
- **Resumable uploads.** Chunked uploads + resume-on-disconnect are a separate feature. Today's `/upload` is single-shot; this spec keeps that shape.
- **Per-stage progress detail.** Intermediate events (`captioning` → `embedding`) are not surfaced to the user — the pill just shows "processing" until terminal `ready` or `error`. The internal stages exist as code paths but not as UX surface.
- **Multi-upload parallelism on the backend.** The frontend queue is sequential today; async ingestion alone doesn't change that. Parallel uploads is a separate optimization that fits cleanly on top of this work.

## Architecture

```
                       Client (frontend)                          Server (FastAPI)
                       ─────────────────                          ─────────────────

  user picks file → POST /upload (bytes only)                   /upload handler:
       ⇡                                                          1. save_image → storage_path
  pill: "uploading"                                               2. INSERT Document(status='processing')
                       ◄── 202 {doc_id, status:'processing'}      3. asyncio.create_task(ingest_doc(doc_id))
                                                                  4. return 202 IMMEDIATELY (~200 ms)
  pill: "processing"
       ⇡
  open SSE → GET /uploads/{doc_id}/events                       /uploads/{doc_id}/events handler:
                                                                  1. read current status from DB
                                                                  2. if 'ready' / 'error' → emit terminal
                                                                  3. else → subscribe to broker channel
                                                                            for this doc_id; emit each event

                                                                ingest_doc(doc_id) background task:
                                                                  • caption via image_describe / pdf_extract
                                                                  • chunk + embed
                                                                  • UPDATE Document SET status='ready'
                                                                  • broker.publish(doc_id, {status:'ready'})
                                                                  • on exception: status='error'

                       ◄── data: {status:'ready'}\n\n              (or 'error' with optional message)

  pill: "ready" (thumbnail, green border)
  send-gate: enabled (if no other pills in-flight)
       ⇡
  user sends prompt
```

The pieces that need to exist:

- A **status column** on `documents` so the SSE handler can answer "what's the current state?" without hitting the broker.
- A **status broker** for in-process pub/sub. Wraps an `asyncio.Event` (or `asyncio.Queue`) keyed by `document_id`. Producer is `ingest_doc`; consumer is the SSE handler. In-process is enough for the single-uvicorn-worker dev setup; the broker interface is small enough to swap in Redis pub/sub later.
- An **`ingest_doc` background task** that does what the synchronous `/upload` does today minus the final return.
- An **SSE endpoint** that mirrors the `/analyze` NDJSON pattern (which we already use successfully).
- A **frontend SSE consumer** in `useUploader` that opens an EventSource per upload and flips the pill's status when terminal events arrive.

## Schema

```sql
ALTER TABLE documents
ADD COLUMN status VARCHAR(16) NOT NULL DEFAULT 'ready';

ALTER TABLE documents
ADD COLUMN error_message TEXT;
```

`status` values: `'processing'`, `'ready'`, `'error'`. NOT NULL, default `'ready'` so existing rows are correctly marked as done. `error_message` is nullable and populated only when status flips to `'error'`.

No other schema changes. `storage_path` from M2 stays as-is. Chunks still cascade.

## Components

### `backend/services/ingest_broker.py` — new

In-process pub/sub. ~40 lines.

```python
class IngestBroker:
    def __init__(self) -> None:
        self._waiters: dict[str, list[asyncio.Queue]] = {}

    def subscribe(self, doc_id: str) -> asyncio.Queue[dict]:
        q: asyncio.Queue = asyncio.Queue()
        self._waiters.setdefault(doc_id, []).append(q)
        return q

    def unsubscribe(self, doc_id: str, q: asyncio.Queue) -> None:
        lst = self._waiters.get(doc_id) or []
        if q in lst:
            lst.remove(q)
        if not lst:
            self._waiters.pop(doc_id, None)

    async def publish(self, doc_id: str, event: dict) -> None:
        for q in list(self._waiters.get(doc_id, [])):
            await q.put(event)
```

A module-level singleton (`_broker = IngestBroker()`) is held in `app.state` at startup. Lifecycle-bound to the uvicorn worker. The same module exposes `add_task(coro) -> asyncio.Task` which wraps `asyncio.create_task` and holds the Task in a module-level set until it completes — preventing the GC-mid-run hazard called out in Risks.

When swapped to Redis pub/sub later: same interface, different backend. The seam is small enough that nothing downstream has to change.

### `backend/services/ingest_pipeline.py` — new

The ingestion logic extracted from `/upload`'s synchronous path. ~80 lines.

```python
async def ingest_doc(doc_id: str, content: bytes, mime: str, ...) -> None:
    """Caption → chunk → embed → flip Document.status. Called from
    /upload's background task. Catches all exceptions, persists to
    Document.error_message, never re-raises (the task lives outside
    the request lifecycle — exceptions would only show up as
    'Task exception was never retrieved' warnings)."""
    db = SessionLocal()
    try:
        # ... existing caption + chunk + embed logic, just operates
        # on an existing Document row instead of inserting one.
        broker.publish(doc_id, {"status": "ready"})
    except Exception as exc:
        # Update doc with error state + publish to subscribers.
        db.query(Document).filter_by(id=doc_id).update(
            {"status": "error", "error_message": str(exc)}
        )
        db.commit()
        broker.publish(doc_id, {"status": "error", "detail": str(exc)})
    finally:
        db.close()
```

### `backend/routers/chat.py::upload_document` — modified

```python
@router.post("/upload", status_code=202)
async def upload_document(...):
    # Existing: read bytes, validate MIME, save image to disk.
    storage_path = image_storage.save_image(content, mime=content_type)

    # Insert Document FIRST, with status='processing' and empty content.
    # The ingest_doc task fills in chunks asynchronously.
    new_doc = Document(
        filename=file.filename,
        workspace_id=ws.id,
        session_id=active_session_id,
        storage_path=storage_path,
        status="processing",
    )
    db.add(new_doc); db.commit(); db.refresh(new_doc)

    # Spawn the pipeline. asyncio.create_task fires it on the current
    # event loop, but the returned Task must be held somewhere — bare
    # tasks can be garbage-collected mid-run if nothing references them.
    # The broker module owns a module-level `set[asyncio.Task]` and
    # adds/discards tasks via a small helper so the lifecycle is
    # explicit. add_task takes care of registration and cleanup.
    ingest_broker.add_task(ingest_pipeline.ingest_doc(
        doc_id=new_doc.id, content=content, mime=content_type,
        workspace_id=ws.id, session_id=active_session_id,
    ))

    return {
        "message": f"Upload accepted: {file.filename}",
        "details": {
            "document_id": new_doc.id,
            "status": "processing",
        },
        "session_id": active_session_id,
    }
```

The bytes are still in the function's `content` local; pass that to `ingest_doc`. No re-read from disk needed. Memory cost is bounded by `UPLOAD_MAX_BYTES` (10 MB).

For text uploads (.txt, .md, .pdf, etc.) the same path applies: status='processing' at insert, ingest_doc handles the rest.

### `backend/routers/chat.py::sse_doc_events` — new

```python
@router.get("/uploads/{doc_id}/events")
async def sse_doc_events(doc_id: str, db: Session = Depends(...)):
    """SSE stream of ingestion status events for one document.

    Subscribes to the in-process broker keyed by doc_id. If the doc
    is already terminal ('ready' or 'error') the stream emits that
    state once and closes — handles the race where the client opens
    the stream after the background task has already finished.
    """
    doc = db.query(Document).filter_by(id=doc_id).first()
    if not doc:
        raise HTTPException(404)

    async def generate():
        # Replay current state first so late-subscribing clients
        # don't hang waiting for an event that already fired.
        if doc.status in ("ready", "error"):
            yield f"data: {json.dumps({'status': doc.status})}\n\n"
            return

        q = broker.subscribe(doc_id)
        try:
            while True:
                event = await asyncio.wait_for(q.get(), timeout=120.0)
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("status") in ("ready", "error"):
                    return
        except asyncio.TimeoutError:
            yield f"data: {json.dumps({'status': 'timeout'})}\n\n"
        finally:
            broker.unsubscribe(doc_id, q)

    return StreamingResponse(generate(), media_type="text/event-stream")
```

Path-based auth: the existing `Depends(require_token)` chain on the chat router covers this.

### `frontend/src/hooks/useUploader.ts` — modified

The XHR upload flow now resolves with `status: "processing"` and a `document_id`. The hook then opens an `EventSource` for `/uploads/{doc_id}/events` and updates the pill on terminal events:

```ts
const res = await uploadWithProgress(...);
if (res.ok) {
  const data = JSON.parse(res.body);
  const docId = data.details.document_id;
  setUploads(prev => prev.map(u => u.id === item.id ? {
    ...u, status: "processing", document_id: docId, progress: 100,
  } : u));

  // Subscribe to status events. The EventSource closes itself on the
  // terminal event; the listener also tears down on doc-removed.
  const es = new EventSource(`${API_URL}/uploads/${docId}/events`);
  es.onmessage = (ev) => {
    const event = JSON.parse(ev.data);
    if (event.status === "ready") {
      setUploads(prev => prev.map(u => u.id === item.id ? { ...u, status: "success" } : u));
      es.close();
    } else if (event.status === "error") {
      setUploads(prev => prev.map(u => u.id === item.id ? {
        ...u, status: "error", errorMessage: event.detail || "Processing failed",
      } : u));
      es.close();
    }
  };
}
```

EventSource has a built-in auto-reconnect — fine for now. If the user's network blips, the SSE re-opens and the GET handler's "replay current state" branch handles the race cleanly.

**Auth note:** EventSource doesn't allow setting custom headers, so `Authorization: Bearer` can't ride on the request the way `apiFetch` puts it on fetch. Options:
1. Put the token in the URL as a query param (`?token=...`). Simple; matches a common SSE pattern; token leaks into server logs.
2. Issue a short-lived signed URL per upload. Cleanest but requires new endpoint plumbing.
3. Switch the SSE endpoint to cookie auth (the planned end-state for the broader Phase 2 token → cookie migration).

For v1: option 1. `core.auth.require_token` gains a fallback that reads `?token=` from the URL when the `Authorization` header is absent. The check stays `hmac.compare_digest` against `settings.PRYZM_API_TOKEN`. Other endpoints continue to use the header; only EventSource clients fall back to the URL path. The token already lives in localStorage so the threat-model expansion is bounded; the real fix is the cookie-auth migration on the broader roadmap.

### `frontend/src/components/ChatInput.tsx` — pill state machine

The `FileUpload.status` union gains `"processing"`:

```ts
status: "pending" | "uploading" | "processing" | "success" | "error";
```

Pill rendering:
- `uploading`: progress ring (existing)
- `processing`: ring stays in indeterminate-spin mode (already supported by `CircularProgress` when `value >= 100`)
- `success`: thumbnail in emerald border (existing)
- `error`: alert icon in red border (existing)

Send-gate widens:

```ts
const uploadsInProgress = uploads.some(
  (u) => u.status === "pending"
      || u.status === "uploading"
      || u.status === "processing",
);
```

No new UI components needed — `CircularProgress`'s `indeterminate` branch (PR #41) already handles the visual, and the indeterminate state was always meant to cover the "bytes sent, server still working" window. Async ingestion just makes that window actually exist.

## Migration

One Alembic revision: `add_documents_status_and_error`. UP:

```python
def upgrade():
    op.add_column("documents",
        sa.Column("status", sa.String(16), nullable=False, server_default="ready"))
    op.add_column("documents",
        sa.Column("error_message", sa.Text(), nullable=True))
    op.create_check_constraint(
        "documents_status_check",
        "documents",
        "status IN ('processing', 'ready', 'error')",
    )
```

DOWN drops both columns + the constraint.

Existing rows get `status='ready'`, which is correct — they're all already ingested.

## Sequencing

Four PRs, each independently shippable:

| # | PR | Scope | Status |
|---|---|---|---|
| 1 | **Migration + Document.status field** | Alembic revision, `db/models.Document` gains the column, no behavior change. Forward-compatible: old `/upload` still works, new column defaults to 'ready'. | Shipped (#57) |
| 2 | **Backend pipeline extraction + broker** | New `services/ingest_broker.py` + `services/ingest_pipeline.py`. Refactor existing `/upload` to call `ingest_doc` synchronously (await it inside the handler) as a no-op preservation of current behavior. Tests pin the same green outcomes. | Shipped (#58) |
| 3 | **Async `/upload` + SSE endpoint** | Flip `/upload` to spawn `asyncio.create_task` and return 202. Add `GET /uploads/{doc_id}/events`. Frontend `useUploader` opens the EventSource. Pill gains `'processing'` state. | Shipped (#59) |
| 4 | **Smoke harness + spec close-out** | New Playwright probe for the 202-then-SSE-then-ready flow with a backend-side VLM stub for fast runs. Spec close-out. The URL-query auth lands as the permanent fallback for EventSource until cookie auth ships — it can't be dropped without also dropping SSE. | This PR |

PR 2 is the safety net: it changes the code path internally without changing the user-visible behavior, so PR 3's flip is a single localised change.

## Testing

- **Unit tests for the broker:** subscribe → publish → receive; unsubscribe; multi-subscriber fan-out; replay-current-state on late subscribe.
- **Unit tests for `ingest_doc`:** happy path sets status='ready'; exception path sets status='error' + error_message; broker receives the right event.
- **Integration test for the SSE endpoint:** opens the stream, kicks `ingest_doc`, receives the `ready` event, stream closes.
- **Smoke harness update:** new Playwright probe — upload a fixture, assert the pill goes `uploading` → `processing` → `success` (with the right visual transitions); send button is disabled during `processing` and enabled after `success`.
- **Migration tests:** up/down round-trip; existing rows backfill to `status='ready'`.

## Risks

- **Auth on SSE.** EventSource header limitation means the token rides in the URL. Documented, but it's a short-term wart. Real fix is the cookie auth migration that's already on the roadmap.
- **Background task lifecycle.** `asyncio.create_task` returns a task whose reference must be held — otherwise the task can be garbage-collected mid-run. The pipeline holds a strong reference via the broker and the DB session, but to be safe we'll keep a process-level set of active task references.
- **DB session lifecycle in background task.** The `/upload` handler's session is bound to the request; the background task needs its own. Use `SessionLocal()` inside `ingest_doc` and close it in a finally.
- **Race: SSE opens before Document row commit.** The 202 response is sent AFTER `db.commit()` for the Document row, so the doc_id the frontend has is guaranteed to exist when it opens SSE. No race.
- **Race: ingestion finishes before SSE subscribes.** Handled by the "replay current state first" branch in the SSE handler.
- **Memory growth.** Active in-flight tasks each hold `content` bytes (up to 10 MB each). Worst case at typical use is a handful concurrent — bounded. If multi-tenant scaling pushes this, swap to worker queue.

## Rollback

- PR 1: drop the migration (down works).
- PR 2: revert the refactor, /upload is unchanged.
- PR 3: revert the route change — flip `/upload` back to awaiting `ingest_doc` synchronously. The pill never sees `processing` state, no SSE traffic. Old behavior fully restored without DB roll-back.

## Out-of-scope follow-ups

- **WebSocket transport** for the chat-streaming endpoint too (Item 4 of future-features). Worth doing once we have a second real use case for it.
- **Worker queue** when the dev box is no longer the only host running ingestion.
- **Resumable uploads** (chunked upload + retry) for large files. The 10 MB ceiling makes this unnecessary today.
- **SSE cookie auth.** Pairs with the broader auth migration.
- **Per-stage progress events.** Internal `caption_started` / `caption_done` / `embed_started` events could be surfaced for power-user transparency; not currently a user request.
