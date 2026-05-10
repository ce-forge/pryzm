import subprocess
import platform
import socket
import requests
import time
import ssl
import re
from datetime import datetime, timezone
from .registry import tool

def is_safe_hostname(hostname: str) -> bool:
    """Basic validation to prevent command injection via hostname."""
    return bool(re.match(r'^[a-zA-Z0-9.-]+$', hostname))

@tool(
    properties={"hostname": {"type": "string", "description": "The hostname or IP. Append '.com' if it's a known web brand."}},
    required=["hostname"]
)
def execute_ping(hostname: str) -> str:
    """Ping an IP address or hostname to check network connectivity and latency."""
    
    if not is_safe_hostname(hostname):
        return "Error: Invalid hostname provided."

    param = '-n' if platform.system().lower() == 'windows' else '-c'
    command = ['ping', param, '3', hostname]
    try:
        output = subprocess.check_output(command, stderr=subprocess.STDOUT, universal_newlines=True, timeout=10)
        return f"Ping successful:\n{output}"
    except subprocess.TimeoutExpired:
        return "Ping failed: The request timed out after 10 seconds."
    except subprocess.CalledProcessError as e:
        return f"Ping failed:\n{e.output}"

@tool(
    properties={
        "hostname": {"type": "string", "description": "The hostname or IP"},
        "port": {"type": "integer", "description": "The port number to check (e.g. 80, 443, 3389)"}
    },
    required=["hostname", "port"]
)
def check_port(hostname: str, port: int) -> str:
    """Check if a specific TCP port is open on a target host."""
    try:
        with socket.create_connection((hostname, int(port)), timeout=3):
            return f"Port {port} on {hostname} is OPEN and accepting connections."
    except Exception as e:
        return f"Port {port} on {hostname} is CLOSED or unreachable. Details: {str(e)}"

@tool(
    properties={"domain": {"type": "string", "description": "The domain name to resolve."}},
    required=["domain"]
)
def dns_lookup(domain: str) -> str:
    """Perform a DNS lookup to find the IPv4 address of a domain name."""
    try:
        ip_address = socket.gethostbyname(domain)
        return f"DNS Lookup successful: The IP address for {domain} is {ip_address}"
    except socket.gaierror as e:
        return f"DNS Lookup failed for {domain}: {str(e)}"

@tool(
    properties={"hostname": {"type": "string", "description": "The target domain or IP."}},
    required=["hostname"]
)
def traceroute(hostname: str) -> str:
    """Trace the network path (hops) to a destination server."""
    is_windows = platform.system().lower() == 'windows'
    command = ['tracert', '-h', '15', hostname] if is_windows else ['traceroute', '-m', '15', hostname]
    
    if not is_safe_hostname(hostname):
        return "Error: Invalid hostname provided."

    try:
        output = subprocess.check_output(command, stderr=subprocess.STDOUT, universal_newlines=True, timeout=20)
        return f"Traceroute complete:\n{output}"
    except subprocess.TimeoutExpired:
        return "Traceroute failed: Timed out after 20 seconds."
    except Exception as e:
        return f"Traceroute failed. (Note: traceroute may not be installed on this host). Details: {str(e)}"

@tool(
    properties={"hostname": {"type": "string", "description": "The domain name to check (e.g., google.com)"}},
    required=["hostname"]
)
def ssl_inspect(hostname: str) -> str:
    """Inspects a domain's SSL/TLS certificate to see if it is valid and when it expires."""
    try:
        context = ssl.create_default_context()
        with socket.create_connection((hostname, 443), timeout=5) as sock:
            with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                cert = ssock.getpeercert()
                
                expire_str = cert.get('notAfter')
                expire_date = datetime.strptime(expire_str, "%b %d %H:%M:%S %Y %Z")
                
                expire_date = expire_date.replace(tzinfo=timezone.utc)
                now_utc = datetime.now(timezone.utc)
                
                days_left = (expire_date - now_utc).days
                
                return (f"SSL Certificate for {hostname} is VALID.\n"
                        f"Expires on: {expire_date.strftime('%Y-%m-%d')} ({days_left} days remaining).\n"
                        f"Issued to: {cert.get('subject')[0][0][1]}\n"
                        f"Issuer: {cert.get('issuer')[1][0][1]}")
    except Exception as e:
        return f"SSL inspection failed for {hostname}. Details: {str(e)}"

@tool(properties={}, required=[])
def get_public_ip() -> str:
    """Fetches the external Public IP Address of the network you are currently running on."""
    try:
        ip = requests.get('https://api.ipify.org', timeout=5).text
        return f"Your current Public IP Address is: {ip}"
    except Exception as e:
        return f"Failed to retrieve public IP. Details: {str(e)}"