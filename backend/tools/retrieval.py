from tools.registry import tool
from db.database import SessionLocal
from services.knowledge import search_chunks_sync, _label_chunk
from utils.formatters import format_tool_results


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
    """Searches the internal documentation and knowledge base for a specific query."""
    db = SessionLocal()
    try:
        # The `workspace` arg here is the slug (injected by ai_engine via
        # workspace.slug). Resolve to id for the new search_chunks signature.
        from fastapi import HTTPException
        from services.workspaces import get_by_slug
        try:
            ws = get_by_slug(db, workspace)
        except HTTPException:
            return f"Knowledge base search failed: workspace not found ({workspace})"
        # Stricter threshold than the auto-RAG path: the LLM picked this tool
        # deliberately, so we want precision over recall.
        results = search_chunks_sync(db, query, workspace_id=ws.id, session_id=session_id, threshold=0.45, top_k=3)
        if not results:
            return "No relevant documentation found in the knowledge base."

        context_blocks = [_label_chunk(chunk) for chunk in results]
        unique_sources = list({chunk.document.filename for chunk in results})
        return format_tool_results(unique_sources, context_blocks)
    except Exception as e:
        return f"Knowledge base search failed with error: {str(e)}"
    finally:
        db.close()
