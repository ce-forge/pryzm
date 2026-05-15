import ipaddress
import subprocess
import platform
import socket
import requests
import ssl
import re
from datetime import datetime, timezone
from config import settings
from .registry import tool


MODULE_DIRECTIVE = (
    "Network tools require a valid TLD (e.g. \"reddit.com\") or an explicit "
    "IPv4/IPv6 address. If the user names a known web brand without a TLD "
    "(e.g. \"youtube\"), append \".com\" before calling."
)

# Single safe-char regex for both shell-arg use and resolver input. Allows
# dotted hostnames, IPv4 literals, IPv6 literals (digits + colons), and
# Unicode-free ASCII labels. Anything with shell metacharacters is rejected.
_HOSTNAME_SHAPE = re.compile(r'^[a-zA-Z0-9.\-:]{1,253}$')


def is_safe_hostname(hostname: str) -> bool:
    """Cheap pre-flight check: reject anything that doesn't look like a
    hostname or IP literal. Does NOT do DNS or range-checking — see
    `validate_target` for the full check."""
    return bool(hostname) and bool(_HOSTNAME_SHAPE.match(hostname))


def validate_target(host: str) -> tuple[bool, str]:
    """Resolve `host` and verify every address it points to is publicly
    routable. Returns (ok, resolved_ip_or_reason).

    When settings.NETWORK_TOOLS_ALLOW_PRIVATE is True, validation reduces to
    the shape check — the operator has opted in to LAN diagnostics.

    Otherwise, ANY resolved address landing in a private/loopback/link-local/
    multicast/reserved/CGNAT/unspecified range fails the check. We refuse on
    *any* such hit (not just the first) to defeat DNS-rebinding tricks where
    a hostname returns both a public and a private address.
    """
    if not is_safe_hostname(host):
        return False, "hostname contains invalid characters"

    if settings.NETWORK_TOOLS_ALLOW_PRIVATE:
        return True, host

    # Tolerate bare brand names ("youtube") by retrying with ".com" appended
    # if the input has no dot and initial resolution fails. The TLD is the
    # only thing missing in the common case — adding it once is cheap and
    # avoids forcing every caller (LLM included) to remember the suffix.
    candidates = [host] if "." in host else [host, f"{host}.com"]
    last_err: Exception | None = None
    info = None
    for candidate in candidates:
        try:
            info = socket.getaddrinfo(candidate, None, type=socket.SOCK_STREAM)
            host = candidate
            break
        except socket.gaierror as exc:
            last_err = exc
    if info is None:
        return False, f"DNS resolution failed: {last_err}"

    resolved = sorted({entry[4][0] for entry in info})
    for ip_str in resolved:
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return False, f"resolved an invalid address: {ip_str}"
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False, (
                f"refused: {host} resolves to {ip_str}, which is in a restricted "
                f"range. Set NETWORK_TOOLS_ALLOW_PRIVATE=True to allow local-network diagnostics."
            )

    # Return the first resolved IP so callers can connect by IP and dodge
    # DNS rebinding at connect time.
    return True, resolved[0]

@tool(
    properties={"hostname": {"type": "string", "description": "The hostname or IP. Append '.com' if it's a known web brand."}},
    required=["hostname"],
    system_prompt_directive="If given a hostname (not a bare IP), run `dns_lookup` first, then call `execute_ping` with the resolved IP.",
)
def execute_ping(hostname: str) -> str:
    """Ping an IP address or hostname to check network connectivity and latency."""
    ok, detail = validate_target(hostname)
    if not ok:
        return f"Ping refused: {detail}"

    param = '-n' if platform.system().lower() == 'windows' else '-c'
    # Pass the resolved IP to the ping binary, not the raw hostname, so the
    # tool actually pings the address we validated.
    command = ['ping', param, '3', detail]
    try:
        output = subprocess.check_output(command, stderr=subprocess.STDOUT, universal_newlines=True, timeout=10)
        return f"Ping successful (target {hostname} -> {detail}):\n{output}"
    except subprocess.TimeoutExpired:
        return "Ping failed: The request timed out after 10 seconds."
    except subprocess.CalledProcessError as e:
        return f"Ping failed:\n{e.output}"

@tool(
    properties={
        "hostname": {"type": "string", "description": "The hostname or IP"},
        "port": {"type": "integer", "description": "The port number to check (e.g. 80, 443, 3389)"}
    },
    required=["hostname", "port"],
    system_prompt_directive="If given a hostname (not a bare IP), run `dns_lookup` first, then call `check_port` with the resolved IP.",
)
def check_port(hostname: str, port: int) -> str:
    """Check if a specific TCP port is open on a target host."""
    ok, detail = validate_target(hostname)
    if not ok:
        return f"Port check refused: {detail}"
    try:
        # Connect by resolved IP (not hostname) to prevent DNS-rebinding.
        with socket.create_connection((detail, int(port)), timeout=3):
            return f"Port {port} on {hostname} ({detail}) is OPEN and accepting connections."
    except Exception as e:
        return f"Port {port} on {hostname} ({detail}) is CLOSED or unreachable. Details: {str(e)}"

@tool(
    properties={"domain": {"type": "string", "description": "The domain name to resolve. Append '.com' if the user gave a bare web-brand name (e.g. \"youtube\" → \"youtube.com\")."}},
    required=["domain"]
)
def dns_lookup(domain: str) -> str:
    """Perform a DNS lookup to find the IPv4 address of a domain name."""
    ok, detail = validate_target(domain)
    if not ok:
        return f"DNS lookup refused: {detail}"
    return f"DNS Lookup successful: The IP address for {domain} is {detail}"

@tool(
    properties={"hostname": {"type": "string", "description": "The target domain or IP."}},
    required=["hostname"]
)
def traceroute(hostname: str) -> str:
    """Trace the network path (hops) to a destination server."""
    ok, detail = validate_target(hostname)
    if not ok:
        return f"Traceroute refused: {detail}"

    is_windows = platform.system().lower() == 'windows'
    # traceroute/tracert handles hostnames fine; we already validated the
    # resolved address above. Pass the IP to be deterministic about hops.
    command = ['tracert', '-h', '15', detail] if is_windows else ['traceroute', '-m', '15', detail]

    try:
        output = subprocess.check_output(command, stderr=subprocess.STDOUT, universal_newlines=True, timeout=20)
        return f"Traceroute complete (target {hostname} -> {detail}):\n{output}"
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
    ok, detail = validate_target(hostname)
    if not ok:
        return f"SSL inspection refused: {detail}"

    try:
        context = ssl.create_default_context()
        # Connect by IP, but keep the original hostname for SNI / cert
        # validation so the right certificate is returned.
        with socket.create_connection((detail, 443), timeout=5) as sock:
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