AVAILABLE_TOOLS = {}
TOOL_DEFINITIONS =[]

def tool(properties, required=None):
    """
    A decorator that automatically converts a Python function 
    into a compatible JSON tool for the LLM.
    """
    if required is None:
        required =[]
        
    def decorator(func):
        AVAILABLE_TOOLS[func.__name__] = func
        
        TOOL_DEFINITIONS.append({
            "type": "function",
            "function": {
                "name": func.__name__,
                "description": func.__doc__.strip() if func.__doc__ else "No description.",
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required
                }
            }
        })
        return func
    return decorator