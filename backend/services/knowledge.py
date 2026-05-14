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

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
        separators=["\n\n", "\n", ".", " ", ""],
    )

    chunks = splitter.split_text(content)

    # Store the raw chunk text and embed it as-is. The filename is already
    # carried on the parent Document; injecting it into every chunk's content
    # AND its embedding vector (the previous behaviour) polluted the
    # vector space — every query had to compete against "Source Document: ..."
    # boilerplate. Filename gets re-attached at retrieval time so the model
    # still sees provenance per chunk.
    for chunk_text in chunks:
        vector = await get_embedding(client, chunk_text)
        db.add(models.DocumentChunk(
            document_id=new_doc.id,
            workspace_id=workspace_id,
            content=chunk_text,
            embedding=vector,
        ))

    db.commit()
    return {"status": "success", "chunks_created": len(chunks), "document_id": new_doc.id}

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
):
    """Vector-search for relevant chunks. With overview_mode=True (and a
    session id), bypasses semantic search and returns up to top_k chunks of
    the most recently uploaded document — used when the user attached a file
    but didn't include any text query of their own."""
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
                context_blocks = [f"[from {recent_doc.filename}]\n{c.content}" for c in chunks]
                formatted_context = "\n\n=== FILE EXCERPTS ===\n"
                formatted_context += "\n\n---\n\n".join(context_blocks)
                return {
                    "context": formatted_context,
                    "sources": [recent_doc.filename],
                    "reattach_images": _collect_reattach_paths([recent_doc]),
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
        "reattach_images": _collect_reattach_paths([chunk.document for chunk in results]),
    }


def _collect_reattach_paths(documents) -> list[str]:
    """Pull `storage_path` off each Document, dedupe, and drop any path
    where the file is no longer on disk (storage could have been cleaned
    out-of-band). Order-preserving so the model sees images in retrieval
    rank order."""
    import os as _os
    seen: set[str] = set()
    out: list[str] = []
    for doc in documents:
        path = getattr(doc, "storage_path", None) if doc else None
        if not path or path in seen:
            continue
        if not _os.path.exists(path):
            continue
        seen.add(path)
        out.append(path)
    return out