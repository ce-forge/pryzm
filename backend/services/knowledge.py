import httpx
from db import models
from sqlalchemy import or_, func as sa_func
from sqlalchemy.orm import Session
import uuid_utils
from langchain_text_splitters import RecursiveCharacterTextSplitter
from config import settings
from utils.formatters import format_rag_context
from core import llm_server


# Reciprocal Rank Fusion constant. 60 is the canonical default from the
# Cormack/Clarke/Buettcher 2009 paper that introduced RRF for combining
# heterogeneous ranked lists. No reason to tune it for our scale.
_RRF_K = 60


async def get_embedding(client: httpx.AsyncClient, text: str) -> list[float]:
    return await llm_server.embed(client, text=text, model=llm_server.DEFAULT_EMBED_MODEL)


async def ingest_document(
    client: httpx.AsyncClient,
    db: Session,
    filename: str,
    content: str,
    workspace_id: str,
    session_id: str = None,
    is_global: bool = False,
    storage_path: str | None = None,
):
    """Create a Document row and chunk+embed its content in one shot.

    Synchronous-path entrypoint preserved for callers that want the
    pre-async-ingestion behavior (insert-and-fill). The async pipeline
    (PR 3) goes through `add_chunks_to_document` instead so the
    Document row can be created upfront in `processing` state.
    """
    new_doc = models.Document(
        filename=filename,
        workspace_id=workspace_id,
        session_id=session_id,
        is_global=is_global,
        storage_path=storage_path,
    )
    db.add(new_doc)
    db.commit()
    db.refresh(new_doc)

    chunks_created = await add_chunks_to_document(client, db, new_doc, content)
    return {"status": "success", "chunks_created": chunks_created, "document_id": new_doc.id}


async def add_chunks_to_document(
    client: httpx.AsyncClient,
    db: Session,
    document: models.Document,
    content: str,
) -> int:
    """Chunk + embed `content` and persist the chunks against an
    already-committed Document row. Returns the chunk count.

    Used by the async-ingestion pipeline where the Document is
    created upfront in `processing` state and chunks are added later
    by a background task.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
        separators=["\n\n", "\n", ".", " ", ""],
    )

    chunks = splitter.split_text(content)

    # Store the raw chunk text and embed it as-is. The filename lives on
    # the parent Document and is re-attached at retrieval time, so the
    # model still sees provenance per chunk without filename boilerplate
    # polluting every embedding vector.
    # UUIDv7 ids encode a millisecond timestamp in the leading 48 bits, so
    # `ORDER BY id` recovers chunk insertion order — the order the splitter
    # produced them, which IS the order they appear in the source document.
    # This unblocks the attached-file retrieval path (below) from having to
    # return a relevance-ranked top-K; for explicit attachments we want
    # completeness + correct order, not relevance.
    for chunk_text in chunks:
        vector = await get_embedding(client, chunk_text)
        db.add(models.DocumentChunk(
            id=str(uuid_utils.uuid7()),
            document_id=document.id,
            workspace_id=document.workspace_id,
            content=chunk_text,
            embedding=vector,
        ))

    db.commit()
    return len(chunks)

def _scope_filter(session_id: str | None):
    """Common WHERE clause restricting docs to the current session OR
    any workspace-global ones. Both retrieval paths apply this."""
    return or_(
        models.Document.session_id == session_id,
        models.Document.is_global == True,
    )


def _filename_filter(restrict_to_filenames: list[str] | None):
    """When non-empty, return a SQL filter restricting documents to the
    specified filenames (case-insensitive). Empty list / None returns
    None so callers can spread it conditionally into a filter list."""
    if not restrict_to_filenames:
        return None
    return sa_func.lower(models.Document.filename).in_(
        [f.lower() for f in restrict_to_filenames]
    )


def _query_chunks_by_vector(
    db: Session,
    query_vector: list[float],
    workspace_id: str,
    session_id: str = None,
    threshold: float = 0.65,
    top_k: int = 10,
    restrict_to_filenames: list[str] | None = None,
):
    """Pure vector search. Returns up to top_k chunks ordered by cosine
    distance ascending. `top_k` defaults to 10 because hybrid retrieval
    over-fetches from each side so RRF has material to merge.

    `restrict_to_filenames` narrows the search to chunks whose parent
    Document.filename matches one of the entries (case-insensitive).
    """
    distance = models.DocumentChunk.embedding.cosine_distance(query_vector)
    filters = [
        models.Document.workspace_id == workspace_id,
        _scope_filter(session_id),
        distance < threshold,
    ]
    fn_filter = _filename_filter(restrict_to_filenames)
    if fn_filter is not None:
        filters.append(fn_filter)

    return (
        db.query(models.DocumentChunk)
        .join(models.Document)
        .filter(*filters)
        .order_by(distance)
        .limit(top_k)
        .all()
    )


def _query_chunks_by_keyword(
    db: Session,
    query: str,
    workspace_id: str,
    session_id: str = None,
    top_k: int = 10,
    restrict_to_filenames: list[str] | None = None,
):
    """Keyword search via tsvector. Returns chunks ordered by ts_rank
    descending. Best at exact identifier strings (usernames, IDs,
    error codes, IPs) — exactly where vector similarity blurs.

    Uses `websearch_to_tsquery` which tolerates user-typed text
    (quotes for phrases, OR operators, etc.). Empty query → empty
    list (parser would otherwise produce a NULL tsquery).
    """
    if not query.strip():
        return []
    ts_q = sa_func.websearch_to_tsquery("simple", query)
    rank = sa_func.ts_rank(models.DocumentChunk.content_tsv, ts_q)
    filters = [
        models.Document.workspace_id == workspace_id,
        _scope_filter(session_id),
        models.DocumentChunk.content_tsv.op("@@")(ts_q),
    ]
    fn_filter = _filename_filter(restrict_to_filenames)
    if fn_filter is not None:
        filters.append(fn_filter)

    return (
        db.query(models.DocumentChunk)
        .join(models.Document)
        .filter(*filters)
        .order_by(rank.desc())
        .limit(top_k)
        .all()
    )


def _rrf_merge(
    vector_results: list,
    keyword_results: list,
    top_k: int,
) -> list:
    """Reciprocal Rank Fusion. Combines two ranked lists into one by
    summing 1/(K + rank) contributions from each list per chunk. Chunks
    appearing high in either list get high scores; chunks appearing
    in BOTH get the highest scores. Returns the top_k merged chunks
    in descending RRF score order.

    Key property: only rank order matters, not raw scores from the
    underlying searches. Lets us combine cosine distance + ts_rank
    cleanly without normalization headaches.
    """
    scores: dict[str, tuple[float, object]] = {}
    for rank, chunk in enumerate(vector_results):
        chunk_id = chunk.id
        scores[chunk_id] = (1.0 / (_RRF_K + rank), chunk)
    for rank, chunk in enumerate(keyword_results):
        chunk_id = chunk.id
        if chunk_id in scores:
            score, c = scores[chunk_id]
            scores[chunk_id] = (score + 1.0 / (_RRF_K + rank), c)
        else:
            scores[chunk_id] = (1.0 / (_RRF_K + rank), chunk)

    merged = sorted(scores.values(), key=lambda sc: sc[0], reverse=True)
    return [chunk for _score, chunk in merged[:top_k]]


def _query_chunks_hybrid(
    db: Session,
    query_vector: list[float] | None,
    query: str,
    workspace_id: str,
    session_id: str = None,
    threshold: float = 0.65,
    top_k: int = 3,
    restrict_to_filenames: list[str] | None = None,
):
    """Hybrid retrieval — vector + keyword, merged via RRF. Each side
    over-fetches (top_k * 4, capped at 12) so RRF has material to work
    with; the final top_k chunks come from the merge.

    `query_vector=None` is permitted (e.g., when embedding failed) —
    falls back to keyword-only. Empty/conversational queries that
    produce no keyword hits fall back to vector-only.
    """
    fetch_k = min(max(top_k * 4, 8), 12)
    vector_results = []
    if query_vector:
        vector_results = _query_chunks_by_vector(
            db, query_vector,
            workspace_id=workspace_id, session_id=session_id,
            threshold=threshold, top_k=fetch_k,
            restrict_to_filenames=restrict_to_filenames,
        )
    keyword_results = _query_chunks_by_keyword(
        db, query,
        workspace_id=workspace_id, session_id=session_id,
        top_k=fetch_k, restrict_to_filenames=restrict_to_filenames,
    )
    return _rrf_merge(vector_results, keyword_results, top_k)


async def search_chunks(
    client: httpx.AsyncClient,
    db: Session,
    query: str,
    workspace_id: str,
    session_id: str = None,
    threshold: float = 0.65,
    top_k: int = 3,
):
    """Async chunk-search used by the auto-RAG path. Embeds the query then
    runs the hybrid (vector + keyword) retrieval merged via RRF.

    The two callers (auto-RAG vs the explicit tool) pass different
    thresholds on purpose:
    - Auto-RAG uses a permissive 0.65 because it runs hands-off; we'd
      rather show the model a loosely-relevant chunk than skip RAG.
    - The explicit tool uses a stricter 0.45 because the LLM chose to
      look something up; precision over recall.
    """
    query_vector = await get_embedding(client, query) if query.strip() else None
    return _query_chunks_hybrid(
        db, query_vector, query,
        workspace_id=workspace_id, session_id=session_id,
        threshold=threshold, top_k=top_k,
    )


def search_chunks_sync(
    db: Session,
    query: str,
    workspace_id: str,
    session_id: str = None,
    threshold: float = 0.65,
    top_k: int = 3,
    restrict_to_filenames: list[str] | None = None,
):
    """Sync chunk-search for use from tool functions (called synchronously
    by ai_engine's tool dispatch). Embeds via a direct HTTP POST then
    runs hybrid retrieval merged via RRF.

    `restrict_to_filenames` narrows both sides to documents with matching
    filenames (case-insensitive)."""
    query_vector = None
    if query.strip():
        try:
            query_vector = llm_server.embed_sync(query, llm_server.DEFAULT_EMBED_MODEL)
        except Exception:
            query_vector = None
    return _query_chunks_hybrid(
        db, query_vector, query,
        workspace_id=workspace_id, session_id=session_id,
        threshold=threshold, top_k=top_k,
        restrict_to_filenames=restrict_to_filenames,
    )


def _label_chunk(chunk) -> str:
    """Re-attach the source filename at retrieval time. Stored chunk.content
    is now the raw text only; the model still benefits from knowing which
    document each excerpt came from."""
    filename = chunk.document.filename if chunk.document else "unknown"
    return f"[from {filename}]\n{chunk.content}"


def _stitch_chunks_dedup(chunk_texts: list[str], max_overlap: int = 250) -> str:
    """Concatenate ordered chunks, removing the overlap each consecutive pair
    shares due to RecursiveCharacterTextSplitter's chunk_overlap setting.

    RAG retrieval benefits from overlap (queries near a chunk boundary still
    surface the right neighbour), but full-file retrieval (the
    `restrict_to_filenames` path) sees the duplicated 200 chars twice and the
    model treats them as repetition — leading to speaker drift and token-
    substitution hallucinations on transcripts.

    For each adjacent pair we find the longest suffix of `prev` that matches a
    prefix of `next`, capped at `max_overlap`, and drop that prefix from `next`.
    O(N * max_overlap) total; max_overlap defaults a touch above the splitter's
    200-char setting to absorb minor cleanup.
    """
    if not chunk_texts:
        return ""
    out: list[str] = [chunk_texts[0]]
    for nxt in chunk_texts[1:]:
        prev = out[-1]
        bound = min(len(prev), len(nxt), max_overlap)
        overlap = 0
        for n in range(bound, 0, -1):
            if prev.endswith(nxt[:n]):
                overlap = n
                break
        out.append(nxt[overlap:])
    return "".join(out)


def _retrieve_pinned_filenames(
    db: Session,
    workspace_id: str,
    session_id: str | None,
    restrict_to_filenames: list[str],
) -> dict | None:
    """Pinned-filename retrieval: return ALL chunks of the matching document(s)
    in insertion order. Used when the user attached a file or referenced one
    by name in this turn.

    Returns None when no matching documents exist (caller falls through to a
    broader mode so the chat doesn't dead-end on a stale filename marker).
    """
    scoped_docs = (
        db.query(models.Document)
        .filter(
            models.Document.workspace_id == workspace_id,
            models.Document.filename.in_(restrict_to_filenames),
            or_(
                models.Document.session_id == session_id,
                models.Document.is_global == True,
            ),
        )
        .order_by(models.Document.created_at.desc())
        .all()
    )
    if not scoped_docs:
        return None

    # Explicit attachment ⇒ return ALL chunks of the scoped doc(s) in
    # insertion order. UUIDv7 ids make `ORDER BY id` equivalent to "the
    # order the splitter produced them". Relevance ranking would be the
    # wrong operation here — the user wants the whole document.
    # Context-window overflow on huge files surfaces via the upstream
    # error message (core/llm_server._raise_for_status_with_body).
    chunks = (
        db.query(models.DocumentChunk)
        .filter(models.DocumentChunk.document_id.in_([d.id for d in scoped_docs]))
        .order_by(models.DocumentChunk.id)
        .all()
    )
    if not chunks:
        return None

    unique_sources = list({c.document.filename for c in chunks})
    # Group by document, stitch each doc's chunks with overlap removed,
    # then label once per doc — avoids the chunk_overlap=200 duplication
    # the splitter intentionally bakes in.
    chunks_by_doc: dict[str, list] = {}
    for c in chunks:
        chunks_by_doc.setdefault(c.document_id, []).append(c)
    context_blocks = []
    for doc_chunks in chunks_by_doc.values():
        filename = doc_chunks[0].document.filename if doc_chunks[0].document else "unknown"
        stitched = _stitch_chunks_dedup([c.content for c in doc_chunks])
        context_blocks.append(f"[from {filename}]\n{stitched}")
    return {
        "context": format_rag_context(context_blocks),
        "sources": unique_sources,
    }


def _retrieve_session_overview(
    db: Session,
    session_id: str,
    top_k: int,
) -> dict | None:
    """Overview mode: surface up to top_k chunks of the most recently uploaded
    document in the session. Used when the user attached a file with no text
    alongside it — the intent is "tell me about this file" rather than search.
    """
    recent_doc = (
        db.query(models.Document)
        .filter(models.Document.session_id == session_id)
        .order_by(models.Document.created_at.desc())
        .first()
    )
    if not recent_doc:
        return None

    chunks = (
        db.query(models.DocumentChunk)
        .filter(models.DocumentChunk.document_id == recent_doc.id)
        .order_by(models.DocumentChunk.id)
        .limit(top_k)
        .all()
    )
    if not chunks:
        return None

    context_blocks = [f"[from {recent_doc.filename}]\n{c.content}" for c in chunks]
    formatted_context = "\n\n=== FILE EXCERPTS ===\n"
    formatted_context += "\n\n---\n\n".join(context_blocks)
    return {
        "context": formatted_context,
        "sources": [recent_doc.filename],
    }


async def _retrieve_workspace_wide(
    client: httpx.AsyncClient,
    db: Session,
    query: str,
    workspace_id: str,
    session_id: str | None,
    top_k: int,
) -> dict | None:
    """Default mode: workspace-wide hybrid (vector + keyword) retrieval bounded
    by cosine distance. Used for free-form questions with no attachment."""
    results = await search_chunks(
        client, db, query,
        workspace_id=workspace_id, session_id=session_id,
        threshold=0.65, top_k=top_k,
    )
    if not results:
        return None

    unique_sources = list({chunk.document.filename for chunk in results})
    context_blocks = [_label_chunk(chunk) for chunk in results]
    return {
        "context": format_rag_context(context_blocks),
        "sources": unique_sources,
    }


async def retrieve_relevant_chunks(
    client: httpx.AsyncClient,
    db: Session,
    query: str,
    workspace_id: str,
    session_id: str = None,
    top_k: int = 3,
    overview_mode: bool = False,
    restrict_to_filenames: list[str] | None = None,
):
    """Retrieve relevant chunks via one of three modes, most-specific first.

    Modes are tried in order; if a mode finds nothing, the next eligible mode
    runs. This fall-through is intentional — a stale filename marker (file
    renamed/deleted between turns) shouldn't dead-end the chat.

    1. **pinned filenames** — when `restrict_to_filenames` is non-empty,
       pin to docs whose filename matches.
    2. **session overview** — when `overview_mode=True`, sample the most
       recently uploaded document in the session.
    3. **workspace-wide** — hybrid semantic + keyword search, the default.
    """
    if restrict_to_filenames:
        result = _retrieve_pinned_filenames(
            db, workspace_id, session_id, restrict_to_filenames,
        )
        if result is not None:
            return result

    if overview_mode and session_id:
        result = _retrieve_session_overview(db, session_id, top_k)
        if result is not None:
            return result

    return await _retrieve_workspace_wide(
        client, db, query, workspace_id, session_id, top_k,
    )