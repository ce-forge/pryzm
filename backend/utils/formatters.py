def format_tool_execution(func_name: str, args: dict) -> str:
    """Formats the markdown output when the AI triggers a tool.

    Three shapes by arg count:
      * 0 args  →  Tool: `tool_name`
      * 1 arg   →  Tool: `tool_name` → `"value"`           (key dropped; obvious from context)
      * 2+ args →  Tool: `tool_name` → `k="v"`, `k2=v2`    (keys kept for disambiguation)

    Both the tool name AND each arg are wrapped in backticks so the
    user sees discrete code-pill chunks separated by an arrow — much
    easier to scan than a single long Python-callable string. The pills
    are independent inline elements, so a long arg wraps as its own
    unit instead of pushing the whole line off-screen.

    Auto-injected ids (workspace_id / session_id) are filtered upstream
    in ai_engine.py."""
    if not args:
        return f"\n\n> **Tool:** `{func_name}`\n\n"

    def _fmt_value(v) -> str:
        if isinstance(v, str):
            return f'"{v}"'
        # Render arrays without Python's [] brackets so the display reads
        # `"rocket", "water"` rather than `['rocket', 'water']` — cleaner
        # inline and lets each item wrap independently if the line is long.
        if isinstance(v, (list, tuple)):
            return ", ".join(_fmt_value(x) for x in v)
        return str(v)

    if len(args) == 1:
        v = next(iter(args.values()))
        return f"\n\n> **Tool:** `{func_name}` → `{_fmt_value(v)}`\n\n"

    parts = [f"`{k}={_fmt_value(v)}`" for k, v in args.items()]
    return f"\n\n> **Tool:** `{func_name}` → {', '.join(parts)}\n\n"

def format_file_analyzed(sources: list) -> str:
    """Formats the markdown output when RAG successfully reads a file.

    Earlier versions (PR #30) embedded each image as a base64 data URL
    inline so the assistant turn rendered a tiny thumbnail next to the
    filename. That added 3-7 MB of base64 PER MESSAGE for full-size
    phone-camera photos, which got persisted to the assistant message
    and froze the UI when re-opening the chat. The upload pill already
    shows the user the image at the moment of attachment, so the chat
    transcript doesn't need to re-embed it. If a real thumbnail in
    chat is wanted later it should go through a sized server endpoint,
    not an inline data URL.
    """
    sources_str = ", ".join(sources)
    return f"\n> **File Analyzed:** `{sources_str}`\n\n"

def format_knowledge_reference(sources: list) -> str:
    """Formats the markdown output when the AI references the knowledge base."""
    sources_str = ", ".join(sources)
    return f"\n> **Knowledge Base Reference:** `{sources_str}`\n\n"

def format_error(error_msg: str, context: str = "System Error") -> str:
    """Formats standard errors (RAG failures, Engine failures, etc)."""
    return f"\n> **{context}:** `{error_msg}`\n\n"

def format_rag_context(context_blocks: list) -> str:
    """Formats the context blocks retrieved automatically from the vector DB."""
    formatted = "\n\n=== RETRIEVED KNOWLEDGE BASE CONTEXT ===\n"
    formatted += "The following information was retrieved from the local documentation. Use it to inform your answer if relevant:\n\n"
    formatted += "\n\n---\n\n".join(context_blocks)
    formatted += "\n========================================\n"
    return formatted

def format_tool_results(sources: list, context_blocks: list) -> str:
    """Formats the explicit results returned by the search_knowledge_base tool."""
    sources_str = ", ".join(sources)
    formatted = f"=== RETRIEVED RESULTS FROM: {sources_str} ===\n"
    formatted += "\n---\n".join(context_blocks)
    return formatted

def format_code_block(result: str) -> str:
    """Formats raw terminal/bash output into a markdown code block."""
    return f"```text\n{result}\n```\n\n"