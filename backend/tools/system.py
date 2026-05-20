from tools.registry import tool
from db.database import SessionLocal
from db.models import Session

@tool(
    properties={
        "new_title": {
            "type": "string",
            "description": "The new title. If the user asks you to rename the chat but doesn't provide a specific name, you MUST invent a concise, context-aware title based on the current conversation yourself."
        }
    },
    required=["new_title"],
    system_prompt_directive=(
        "If the user asks to rename the chat but doesn't supply a title, "
        "invent a concise, context-aware one rather than asking back."
    ),
)
def rename_chat_session(new_title: str, session_id: str = None) -> str:
    """Renames the current chat session to the requested title."""
    if not session_id:
        return "Tool execution failed: No active session ID provided."
    
    db = SessionLocal()
    try:
        session = db.query(Session).filter(Session.id == session_id).first()
        if session:
            session.title = new_title
            db.commit()
            return f"Success! The chat session has been renamed to '{new_title}'."
        return "Tool execution failed: Session not found."
    except Exception as e:
        return f"Tool execution failed: {str(e)}"
    finally:
        db.close()