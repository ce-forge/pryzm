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
def search_knowledge_base(query: str, workspace_id: str, session_id: str = None) -> str:
    """Searches the internal documentation and knowledge base for a specific query."""
    db = SessionLocal()
    try:
        # Stricter threshold than the auto-RAG path: the LLM picked this tool
        # deliberately, so we want precision over recall.
        results = search_chunks_sync(db, query, workspace_id=workspace_id, session_id=session_id, threshold=0.45, top_k=3)
        if not results:
            return "No relevant documentation found in the knowledge base."

        context_blocks = [_label_chunk(chunk) for chunk in results]
        unique_sources = list({chunk.document.filename for chunk in results})
        return format_tool_results(unique_sources, context_blocks)
    except Exception as e:
        return f"Knowledge base search failed with error: {str(e)}"
    finally:
        db.close()
