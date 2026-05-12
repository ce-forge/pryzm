from sqlalchemy.orm import Session
from sqlalchemy import or_
from tools.registry import tool
from db.database import SessionLocal
from db import models
from services.knowledge import get_embedding 
from utils.formatters import format_rag_context, format_tool_results

@tool(
    properties={
        "query": {
            "type": "string",
            "description": "The search query, topic, or specific filename to look up."
        }
    },
    required=["query"],
    workspaces=["it_copilot", "personal"],
)
def search_knowledge_base(query: str, workspace: str, session_id: str = None) -> str:
    """
    Searches the internal documentation and knowledge base and passes a specific search query.
    """
    db = SessionLocal()
    try:
        query_vector = get_embedding(query)
        if not query_vector:
            return "Knowledge base search failed: Could not generate embedding."

        distance = models.DocumentChunk.embedding.cosine_distance(query_vector)
        results = (
            db.query(models.DocumentChunk)
            .join(models.Document)
            .filter(
                models.Document.workspace == workspace,
                or_(
                    models.Document.is_global == True, 
                    models.Document.session_id == session_id
                ),
                distance < 0.45 
            )
            .order_by(distance)
            .limit(3)
            .all()
        )

        if not results:
            clean_query = query.lower().replace("what is the ", "").replace("who is ", "").replace("what is ", "").strip()
            
            results = (
                db.query(models.DocumentChunk)
                .join(models.Document)
                .filter(
                    models.Document.workspace == workspace,
                    or_(
                        models.Document.is_global == True, 
                        models.Document.session_id == session_id
                    ),
                    models.DocumentChunk.content.ilike(f"%{clean_query}%")
                )
                .limit(3)
                .all()
            )

        if not results:
            return "No relevant documentation found in the knowledge base."

        context_blocks = [chunk.content for chunk in results]
        unique_sources = list(set([chunk.document.filename for chunk in results]))
        
        return format_tool_results(unique_sources, context_blocks)
        
    except Exception as e:
        return f"Knowledge base search failed with error: {str(e)}"
    finally:
        db.close()