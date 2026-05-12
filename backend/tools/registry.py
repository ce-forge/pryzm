AVAILABLE_TOOLS = {}
TOOL_DEFINITIONS = []

# Per-tool workspace allowlist. Maps tool name -> list of workspace names
# (e.g. "it_copilot", "personal") in which the tool is exposed to the LLM.
# Populated by the @tool decorator. The eventual UI-driven workspace tool
# config (see project_workspace_roadmap memory) will overlay this default.
TOOL_WORKSPACES: dict[str, list[str]] = {}


def tool(properties, required=None, workspaces=None):
    """A decorator that turns a Python function into an LLM-callable tool.

    workspaces: list of workspace names in which the tool is exposed. Defaults
    to ["it_copilot"] to preserve historical behavior — every existing tool was
    only available in the IT Copilot workspace. Pass a longer list to opt a
    tool into additional workspaces (e.g. rename_chat_session is allowed in
    "personal" too because users like that affordance everywhere).
    """
    if required is None:
        required = []
    if workspaces is None:
        workspaces = ["it_copilot"]

    def decorator(func):
        AVAILABLE_TOOLS[func.__name__] = func
        TOOL_WORKSPACES[func.__name__] = list(workspaces)

        TOOL_DEFINITIONS.append({
            "type": "function",
            "function": {
                "name": func.__name__,
                "description": func.__doc__.strip() if func.__doc__ else "No description.",
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        })
        return func
    return decorator


