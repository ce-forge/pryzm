def format_tool_execution(func_name: str, args: dict) -> str:
    """Formats the markdown output when the AI triggers a tool."""
    return f"\n\n> **System Action:** Executing `{func_name}` on `{args}`...\n\n"

def format_file_analyzed(sources: list) -> str:
    """Formats the markdown output when RAG successfully reads a file."""
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