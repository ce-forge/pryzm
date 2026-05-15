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
        },
        "filenames": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "OPTIONAL. When the user references specific files by name (e.g., "
                "'what's in screenshot.png' or 'check runbook.pdf'), pass those "
                "filenames here. Retrieval will be scoped to those documents only, "
                "so unrelated content in the workspace doesn't compete in the results. "
                "Omit when the user is asking a general question across the knowledge base."
            ),
        },
    },
    required=["queries"],
    workspaces=["it_copilot", "personal"],
)
def search_knowledge_base(
    queries=None,
    workspace_id: str = "",
    session_id: str = None,
    filenames=None,
) -> str:
    """Search the internal documentation and knowledge base.

    Two calling modes:

    1. **Query mode** — `queries=[...]` (optionally + `filenames=[...]`
       to scope). Runs vector + keyword hybrid search per query,
       returns labeled sections.
    2. **Filename-only mode** — `filenames=[...]` with no queries.
       Returns all chunks of the matching documents, no semantic
       filter. Natural shorthand for "show me this file." Used when
       the LLM was given a file reference and just wants the content
       without inventing a search term.

    Tolerates bare strings for both args (older model calls)."""
    if isinstance(queries, str):
        queries = [queries]
    if isinstance(filenames, str):
        filenames = [filenames]

    db = SessionLocal()
    try:
        # Filename-only mode: return all chunks of matching docs.
        if not queries and filenames:
            from sqlalchemy import or_, func as sa_func
            from db import models
            scoped_docs = (
                db.query(models.Document)
                .filter(
                    models.Document.workspace_id == workspace_id,
                    sa_func.lower(models.Document.filename).in_(
                        [f.lower() for f in filenames]
                    ),
                    or_(
                        models.Document.session_id == session_id,
                        models.Document.is_global == True,  # noqa: E712
                    ),
                )
                .order_by(models.Document.created_at.desc())
                .all()
            )
            if not scoped_docs:
                return f"No documents found matching: {filenames!r}"
            # Cap at 3 chunks per filename-only call. For most uploaded
            # images and short docs that's all there is; for longer
            # docs it returns the most-recent-uploaded ones (chunks
            # ordered by id which is time-ordered with UUIDv7). Keeps
            # the assistant turn's displayed tool-output compact rather
            # than dumping every chunk into the chat surface.
            chunks = (
                db.query(models.DocumentChunk)
                .filter(models.DocumentChunk.document_id.in_([d.id for d in scoped_docs]))
                .order_by(models.DocumentChunk.id)
                .limit(3)
                .all()
            )
            if not chunks:
                return f"Documents found but no chunks: {filenames!r}"
            blocks = [_label_chunk(c) for c in chunks]
            return f"Filename-only retrieval for {filenames!r}\n" + "\n".join(blocks)

        if not queries:
            return (
                "No queries provided. Pass queries=[...] for semantic/keyword "
                "search, or filenames=[...] alone to retrieve a file's contents directly."
            )

        sections = []
        for q in queries:
            # Stricter threshold than the auto-RAG path: the LLM picked this tool
            # deliberately, so we want precision over recall.
            results = search_chunks_sync(
                db, q, workspace_id=workspace_id, session_id=session_id,
                threshold=0.45, top_k=3,
                restrict_to_filenames=filenames or None,
            )
            if results:
                blocks = [_label_chunk(chunk) for chunk in results]
                sections.append(f"Query: {q!r}\n" + "\n".join(blocks))
            else:
                sections.append(f"Query: {q!r}\nNo relevant documentation found.")
        return "\n---\n".join(sections)
    except Exception as e:
        return f"Knowledge base search failed with error: {str(e)}"
    finally:
        db.close()
