import subprocess
import platform
import socket
import requests
import time

def execute_ping(hostname: str) -> str:
    """Pings a host and returns the raw terminal result."""
    param = '-n' if platform.system().lower() == 'windows' else '-c'
    command =['ping', param, '3', hostname]
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

def check_website_status(url: str) -> str:
    """Checks if a website is online and returns the HTTP status code."""
    if not url.startswith("http"):
        url = "https://" + url
    try:
        start_time = time.time()
        response = requests.get(url, timeout=5)
        elapsed = round((time.time() - start_time) * 1000)
        return f"Website {url} is UP. Status code: {response.status_code}. Response time: {elapsed}ms."
    except requests.exceptions.RequestException as e:
        return f"Website {url} is DOWN or unreachable. Error: {str(e)}"

def dns_lookup(domain: str) -> str:
    """Resolves a domain name to its IP address."""
    try:
        ip_address = socket.gethostbyname(domain)
        return f"DNS Lookup successful: The IP address for {domain} is {ip_address}"
    except socket.gaierror as e:
        return f"DNS Lookup failed for {domain}: {str(e)}"