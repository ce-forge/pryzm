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
        "prompt": text
    }
    response = requests.post(url, json=payload)
    response.raise_for_status()
    return response.json().get("embedding",[])

# Passed the new is_global flag
def ingest_document(db: Session, filename: str, content: str, workspace: str = "itCopilot", session_id: str = None, is_global: bool = False):
    new_doc = models.Document(filename=filename, workspace=workspace, session_id=session_id, is_global=is_global)
    db.add(new_doc)
    db.commit()
    db.refresh(new_doc)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
        separators=["\n\n", "\n", ".", " ", ""]
    )
    
    chunks = splitter.split_text(content)
    
    for i, chunk_text in enumerate(chunks):
        contextualized_text = f"Source Document: {filename}\nContent: {chunk_text}"
        
        vector = get_embedding(contextualized_text)
        
        doc_chunk = models.DocumentChunk(
            document_id=new_doc.id,
            content=contextualized_text,
            embedding=vector
        )
        db.add(doc_chunk)

    db.commit()
    return {"status": "success", "chunks_created": len(chunks), "document_id": new_doc.id}

def retrieve_relevant_chunks(db: Session, query: str, workspace: str, session_id: str = None, top_k: int = 3):
    if query == "document overview" and session_id:
        # Get the most recently uploaded document for this session, then return up
        # to top_k of its chunks. DocumentChunk has no ordering column, so we can't
        # guarantee the chunks are the *start* of the document — just a sample.
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
                context_blocks = [chunk.content for chunk in chunks]
                formatted_context = "\n\n=== FILE EXCERPTS ===\n"
                formatted_context += "\n\n---\n\n".join(context_blocks)
                return {"context": formatted_context, "sources": [recent_doc.filename]}
    
    query_vector = get_embedding(query)
    if not query_vector:
        return None

    distance = models.DocumentChunk.embedding.cosine_distance(query_vector)
    
    # Filter updated to check is_global instead of None
    results = (
        db.query(models.DocumentChunk)
        .join(models.Document)
        .filter(
            models.Document.workspace == workspace,
            or_(models.Document.session_id == session_id, models.Document.is_global == True),
            distance < 0.65
        )
        .order_by(distance)
        .limit(top_k)
        .all()
    )

    if not results:
        clean_query = query.lower().replace("what is the ", "").replace("who is ", "").replace("what is ", "").strip()
        
        # Filter updated to check is_global instead of None
        results = (
            db.query(models.DocumentChunk)
            .join(models.Document)
            .filter(
                models.Document.workspace == workspace,
                or_(models.Document.session_id == session_id, models.Document.is_global == True),
                models.DocumentChunk.content.ilike(f"%{clean_query}%") 
            )
            .limit(top_k)
            .all()
        )

    if not results:
        return None

    unique_sources = list(set([chunk.document.filename for chunk in results]))
    context_blocks = [chunk.content for chunk in results]
    
    formatted_context = format_rag_context(context_blocks)
    
    return {
        "context": formatted_context,
        "sources": unique_sources
    }