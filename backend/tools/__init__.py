from .network import execute_ping, check_port, check_website_status, dns_lookup

AVAILABLE_TOOLS = {
    "execute_ping": execute_ping,
    "check_port": check_port,
    "check_website_status": check_website_status,
    "dns_lookup": dns_lookup
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
    },
    {
        "type": "function",
        "function": {
            "name": "check_website_status",
            "description": "Check if a website is online and return the HTTP status code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The website URL to check"}
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "dns_lookup",
            "description": "Perform a DNS lookup to find the IPv4 address of a domain name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string", "description": "The domain name to resolve"}
                },
                "required": ["domain"]
            }
        }
    }
]