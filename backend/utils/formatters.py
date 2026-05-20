from urllib.parse import quote


def safe_content_disposition(filename: str, disposition: str = "inline") -> str:
    """Build an RFC 5987-compliant Content-Disposition header value.

    Untrusted filenames can carry quote characters, control bytes, and
    non-ASCII glyphs that break the plain `filename="..."` form. RFC 5987
    pairs an ASCII-safe `filename=` with a percent-encoded `filename*=`
    so legacy clients see a degraded but parseable name and modern
    clients see the original.
    """
    ascii_safe = "".join(
        c for c in filename if 32 <= ord(c) < 127 and c not in '"\\'
    )
    if not ascii_safe:
        ascii_safe = "file"
    encoded = quote(filename, safe="")
    return f"{disposition}; filename=\"{ascii_safe}\"; filename*=UTF-8''{encoded}"


def format_file_analyzed(sources: list) -> str:
    """Markdown banner for a turn whose RAG context came from attached files.

    Filenames only — image bytes are not re-embedded inline; the upload
    pill is the user-visible preview.
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

