import httpx
from db import models
from sqlalchemy import or_
from sqlalchemy.orm import Session
from langchain_text_splitters import RecursiveCharacterTextSplitter
from config import settings
from utils.formatters import format_rag_context
from core import llm_server


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

    # Store raw chunk text only; filename is re-attached at retrieval time.
    # (Previously the filename was injected into chunk content + embedded,
    # which polluted the vector space with "Source Document: ..." boilerplate.)
    for chunk_text in chunks:
        vector = await get_embedding(client, chunk_text)
        db.add(models.DocumentChunk(
            document_id=document.id,
            workspace_id=document.workspace_id,
            content=chunk_text,
            embedding=vector,
        ))

    db.commit()
    return len(chunks)

def _strip_query_prefix(query: str) -> str:
    """Lowercase the query and strip the common interrogative prefixes that
    hurt the ILIKE substring fallback. Single source of truth — both the
    auto-RAG path and the search_knowledge_base tool use this."""
    return (
        query.lower()
        .replace("what is the ", "")
        .replace("who is ", "")
        .replace("what is ", "")
        .strip()
    )


def _query_chunks_by_vector(
    db: Session,
    query_vector: list[float],
    query: str,
    workspace_id: str,
    session_id: str = None,
    threshold: float = 0.65,
    top_k: int = 3,
):
    """Pure-DB chunk search given a pre-computed embedding vector.

    Separated from the embedding step so the sync tool path (tools/retrieval.py)
    can supply its own vector without entering async context.
    """
    distance = models.DocumentChunk.embedding.cosine_distance(query_vector)
    scope_filter = or_(
        models.Document.session_id == session_id,
        models.Document.is_global == True,
    )

    results = (
        db.query(models.DocumentChunk)
        .join(models.Document)
        .filter(
            models.Document.workspace_id == workspace_id,
            scope_filter,
            distance < threshold,
        )
        .order_by(distance)
        .limit(top_k)
        .all()
    )
    if results:
        return results

    clean_query = _strip_query_prefix(query)
    return (
        db.query(models.DocumentChunk)
        .join(models.Document)
        .filter(
            models.Document.workspace_id == workspace_id,
            scope_filter,
            models.DocumentChunk.content.ilike(f"%{clean_query}%"),
        )
        .limit(top_k)
        .all()
    )


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
    delegates to _query_chunks_by_vector for the DB work.

    The two callers pass different thresholds on purpose:
    - Auto-RAG uses a permissive 0.65 because it runs hands-off; we'd
      rather show the model a loosely-relevant chunk than skip RAG.
    - The explicit tool uses a stricter 0.45 because the LLM chose to
      look something up; precision over recall.

    Returns the list of matching DocumentChunk rows (possibly empty).
    """
    query_vector = await get_embedding(client, query)
    if not query_vector:
        return []
    return _query_chunks_by_vector(db, query_vector, query, workspace_id, session_id, threshold, top_k)


def search_chunks_sync(
    db: Session,
    query: str,
    workspace_id: str,
    session_id: str = None,
    threshold: float = 0.65,
    top_k: int = 3,
):
    """Sync chunk-search for use from tool functions (which are called
    synchronously by ai_engine). Embeds via a direct HTTP POST to the LLM
    server's /v1/embeddings endpoint and delegates to _query_chunks_by_vector
    for the DB work."""
    import requests
    url = f"{settings.LLM_SERVER_URL.strip().rstrip('/')}/v1/embeddings"
    try:
        resp = requests.post(
            url,
            json={"model": llm_server.DEFAULT_EMBED_MODEL, "input": query},
            timeout=30,
        )
        resp.raise_for_status()
        query_vector = resp.json()["data"][0]["embedding"]
    except Exception:
        query_vector = []
    if not query_vector:
        return []
    return _query_chunks_by_vector(db, query_vector, query, workspace_id, session_id, threshold, top_k)


def _label_chunk(chunk) -> str:
    """Re-attach the source filename at retrieval time. Stored chunk.content
    is now the raw text only; the model still benefits from knowing which
    document each excerpt came from."""
    filename = chunk.document.filename if chunk.document else "unknown"
    return f"[from {filename}]\n{chunk.content}"


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
    """Vector-search for relevant chunks.

    Three retrieval modes, most-specific first:

    1. **restrict_to_filenames** — when the user attached one or more files
       in this turn, retrieval is pinned to documents whose filename matches
       one of those entries (within the current session or workspace
       globals). Avoids returning chunks from unrelated docs when the
       intent is clearly "tell me about THIS file."
    2. **overview_mode** — no user text alongside the attachment; surface
       up to top_k chunks of the most recently uploaded document in the
       session.
    3. **default** — workspace-wide semantic search bounded by cosine
       distance, with an ILIKE substring fallback. Used when the user is
       asking a free-form question with no attachment.
    """
    if restrict_to_filenames:
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
        if scoped_docs:
            chunks = (
                db.query(models.DocumentChunk)
                .filter(models.DocumentChunk.document_id.in_([d.id for d in scoped_docs]))
                .limit(max(top_k * 4, 8))
                .all()
            )
            if chunks:
                unique_sources = list({c.document.filename for c in chunks})
                context_blocks = [_label_chunk(c) for c in chunks]
                formatted_context = format_rag_context(context_blocks)
                return {
                    "context": formatted_context,
                    "sources": unique_sources,
                }
        # File was renamed / deleted between turns: fall through to the
        # broader retrieval paths so the chat doesn't dead-end.

    if overview_mode and session_id:
        # Most recent document for this session, sampled up to top_k chunks.
        recent_doc = (
            db.query(models.Document)
            .filter(models.Document.session_id == session_id)
            .order_by(models.Document.created_at.desc())
            .first()
        )
        if recent_doc:
            chunks = (
                db.query(models.DocumentChunk)
                .filter(models.DocumentChunk.document_id == recent_doc.id)
                .limit(top_k)
                .all()
            )
            if chunks:
                context_blocks = [_label_chunk(c) for c in chunks]
                formatted_context = "\n\n=== FILE EXCERPTS ===\n"
                formatted_context += "\n\n---\n\n".join(context_blocks)
                return {
                    "context": formatted_context,
                    "sources": [recent_doc.filename],
                }

    results = await search_chunks(client, db, query, workspace_id=workspace_id, session_id=session_id, threshold=0.65, top_k=top_k)
    if not results:
        return None

    unique_sources = list({chunk.document.filename for chunk in results})
    context_blocks = [_label_chunk(chunk) for chunk in results]
    formatted_context = format_rag_context(context_blocks)
    return {
        "context": formatted_context,
        "sources": unique_sources,
    }