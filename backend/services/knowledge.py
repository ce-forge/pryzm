import requests
from db import models
from sqlalchemy import or_
from sqlalchemy.orm import Session
from langchain_text_splitters import RecursiveCharacterTextSplitter
from config import settings
from utils.formatters import format_rag_context

OLLAMA_URL = settings.OLLAMA_URL.strip().rstrip('/')
EMBED_MODEL = "nomic-embed-text"

def get_embedding(text: str) -> list[float]:
    url = f"{OLLAMA_URL}/api/embeddings"
    payload = {
        "model": EMBED_MODEL,
        "prompt": text,
    }
    response = requests.post(url, json=payload, timeout=30)
    response.raise_for_status()
    return response.json().get("embedding", [])


def ingest_document(db: Session, filename: str, content: str, workspace_id: str, session_id: str = None, is_global: bool = False):
    new_doc = models.Document(filename=filename, workspace_id=workspace_id, session_id=session_id, is_global=is_global)
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
        vector = get_embedding(chunk_text)
        db.add(models.DocumentChunk(
            document_id=new_doc.id,
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


def search_chunks(
    db: Session,
    query: str,
    workspace_id: str,
    session_id: str = None,
    threshold: float = 0.65,
    top_k: int = 3,
):
    """Shared chunk-search routine used by both the auto-RAG path
    (services/knowledge.py:retrieve_relevant_chunks) and the explicit
    `search_knowledge_base` tool (tools/retrieval.py). Embeds the query,
    runs a cosine-distance vector search filtered by workspace and the
    session/global scope, and falls back to a case-insensitive substring
    match when the vector search returns nothing.

    The two callers pass different thresholds on purpose:
    - Auto-RAG uses a permissive 0.65 because it runs hands-off; we'd
      rather show the model a loosely-relevant chunk than skip RAG.
    - The explicit tool uses a stricter 0.45 because the LLM chose to
      look something up; precision over recall.

    Returns the list of matching DocumentChunk rows (possibly empty).
    """
    query_vector = get_embedding(query)
    if not query_vector:
        return []

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


def _label_chunk(chunk) -> str:
    """Re-attach the source filename at retrieval time. Stored chunk.content
    is now the raw text only; the model still benefits from knowing which
    document each excerpt came from."""
    filename = chunk.document.filename if chunk.document else "unknown"
    return f"[from {filename}]\n{chunk.content}"


def retrieve_relevant_chunks(db: Session, query: str, workspace_id: str, session_id: str = None, top_k: int = 3):
    if query == "document overview" and session_id:
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
                return {"context": formatted_context, "sources": [recent_doc.filename]}

    results = search_chunks(db, query, workspace_id=workspace_id, session_id=session_id, threshold=0.65, top_k=top_k)
    if not results:
        return None

    unique_sources = list({chunk.document.filename for chunk in results})
    context_blocks = [_label_chunk(chunk) for chunk in results]
    formatted_context = format_rag_context(context_blocks)
    return {
        "context": formatted_context,
        "sources": unique_sources,
    }