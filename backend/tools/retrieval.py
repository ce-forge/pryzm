from tools.registry import tool
from db.database import SessionLocal
from services.knowledge import search_chunks_sync, _label_chunk
from utils.formatters import format_tool_results


@tool(
    properties={
        "queries": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "One or more distinct search terms, topics, or filenames. "
                "Pass ALL items the user asks about in a single call as an array — "
                "e.g. [\"rocket\", \"water\"] for a request like \"search for rocket and water\". "
                "Do NOT issue separate tool calls for each item; this tool batches multiple "
                "queries internally and labels the results by query."
            ),
        }
    },
    required=["queries"],
    workspaces=["it_copilot", "personal"],
)
def search_knowledge_base(queries, workspace_id: str, session_id: str = None) -> str:
    """Search the internal documentation and knowledge base.

    Accepts a list of search terms. For each, runs an independent vector
    search and returns a labeled section. Single-query callers can pass a
    one-element list — the function also tolerates a bare string for
    backward-compat with mid-stream model calls during the schema migration."""
    # Backward-compat: a model that hasn't updated may still send a string.
    if isinstance(queries, str):
        queries = [queries]
    if not queries:
        return "No queries provided."

    db = SessionLocal()
    try:
        sections = []
        all_sources = set()
        for q in queries:
            # Stricter threshold than the auto-RAG path: the LLM picked this tool
            # deliberately, so we want precision over recall.
            results = search_chunks_sync(
                db, q, workspace_id=workspace_id, session_id=session_id,
                threshold=0.45, top_k=3,
            )
            if results:
                blocks = [_label_chunk(chunk) for chunk in results]
                sections.append(f"Query: {q!r}\n" + "\n".join(blocks))
                for chunk in results:
                    all_sources.add(chunk.document.filename)
            else:
                sections.append(f"Query: {q!r}\nNo relevant documentation found.")
        return "\n---\n".join(sections)
    except Exception as e:
        return f"Knowledge base search failed with error: {str(e)}"
    finally:
        db.close()
