"""Lock the CORS private-network regex.

This regex is in main.py's CORSMiddleware so mobile/LAN browsers can
fetch the API without each device's IP being enumerated in
CORS_ORIGINS. The boundary is exactly the RFC1918 private space plus
loopback — public-internet origins must still be added explicitly to
CORS_ORIGINS.
"""
from __future__ import annotations

import re

from config import settings


_RE = re.compile(settings.CORS_PRIVATE_NETWORK_REGEX)


def test_loopback_matches():
    assert _RE.match("http://127.0.0.1:3000")
    assert _RE.match("http://localhost:3000")
    assert _RE.match("https://127.0.0.1:3000")


def test_rfc1918_class_c_matches():
    assert _RE.match("http://192.168.0.108:3000")
    assert _RE.match("http://192.168.1.50:3000")
    assert _RE.match("https://192.168.255.255:3000")


def test_rfc1918_class_a_matches():
    assert _RE.match("http://10.0.0.5:3000")
    assert _RE.match("http://10.255.255.255:3000")


def test_rfc1918_class_b_matches():
    assert _RE.match("http://172.16.0.1:3000")
    assert _RE.match("http://172.20.30.40:3000")
    assert _RE.match("http://172.31.255.255:3000")


def test_class_b_outside_rfc1918_rejected():
    """172.32.* and 172.15.* are PUBLIC space, must not match."""
    assert not _RE.match("http://172.32.0.1:3000")
    assert not _RE.match("http://172.15.255.255:3000")


def test_public_ip_rejected():
    assert not _RE.match("http://8.8.8.8:3000")
    assert not _RE.match("http://1.1.1.1:3000")
    assert not _RE.match("https://evil.example.com:3000")


def test_origin_without_port_matches():
    """CORS origins commonly come without an explicit port (80/443 default)."""
    assert _RE.match("http://192.168.0.108")
    assert _RE.match("https://localhost")


def test_path_or_query_after_origin_rejected():
    """An origin is host[:port] only; anything trailing is not an origin."""
    assert not _RE.match("http://192.168.0.108:3000/sneaky")
    assert not _RE.match("http://localhost:3000?a=b")


def test_no_protocol_rejected():
    assert not _RE.match("192.168.0.108:3000")
    assert not _RE.match("//192.168.0.108:3000")
