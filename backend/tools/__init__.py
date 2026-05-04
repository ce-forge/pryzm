from .network import execute_ping, check_port

AVAILABLE_TOOLS = {
    "execute_ping": execute_ping,
    "check_port": check_port
}

TOOL_DEFINITIONS =[
    {
        "type": "function",
        "function": {
            "name": "execute_ping",
            "description": "Ping an IP address or hostname to check network connectivity and latency.",
            "parameters": {
                "type": "object",
                "properties": {
                    "hostname": {
                        "type": "string", 
                        "description": "The hostname or IP. If the user provides a partial web name like 'google', assume and append '.com'."
                    }
                },
                "required": ["hostname"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_port",
            "description": "Check if a specific TCP port is open on a target host.",
            "parameters": {
                "type": "object",
                "properties": {
                    "hostname": {"type": "string", "description": "The hostname or IP"},
                    "port": {"type": "integer", "description": "The port number to check (e.g. 80, 443, 3389)"}
                },
                "required": ["hostname", "port"]
            }
        }
    }
]