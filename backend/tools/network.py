import subprocess
import platform
import socket

def execute_ping(hostname: str) -> str:
    """Pings a host and returns the raw terminal result."""
    param = '-n' if platform.system().lower() == 'windows' else '-c'
    command = ['ping', param, '3', hostname]
    try:
        output = subprocess.check_output(command, stderr=subprocess.STDOUT, universal_newlines=True, timeout=10)
        return f"Ping successful:\n{output}"
    except subprocess.TimeoutExpired:
        return f"Ping failed: The request timed out after 10 seconds. The host is likely offline or blocking ICMP."
    except subprocess.CalledProcessError as e:
        return f"Ping failed:\n{e.output}"

def check_port(hostname: str, port: int) -> str:
    """Checks if a specific TCP port is open."""
    try:
        with socket.create_connection((hostname, int(port)), timeout=3):
            return f"Port {port} on {hostname} is OPEN and accepting connections."
    except Exception as e:
        return f"Port {port} on {hostname} is CLOSED or unreachable. Details: {str(e)}"