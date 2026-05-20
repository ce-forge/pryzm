"""get_public_ip respects the NETWORK_TOOLS_ALLOW_PUBLIC_IP flag.

The tool emits outbound HTTP to api.ipify.org. Sibling tools in
tools/network.py all go through validate_target which blocks RFC1918 +
loopback + link-local. get_public_ip historically bypassed that and
leaked egress traffic even when the operator disabled network tools.
"""
from tools import network


def test_get_public_ip_disabled_returns_message(monkeypatch):
    monkeypatch.setattr("config.settings.NETWORK_TOOLS_ALLOW_PUBLIC_IP", False)
    out = network.get_public_ip()
    assert "disabled" in out.lower()
    assert "NETWORK_TOOLS_ALLOW_PUBLIC_IP" in out


def test_get_public_ip_enabled_attempts_request(monkeypatch):
    """When the flag is on the tool reaches the requests call. We don't
    actually hit ipify in tests — patch requests.get to confirm the path."""
    monkeypatch.setattr("config.settings.NETWORK_TOOLS_ALLOW_PUBLIC_IP", True)

    calls = []

    class _FakeResponse:
        text = "203.0.113.7"

    def _fake_get(url, **kwargs):
        calls.append(url)
        return _FakeResponse()

    monkeypatch.setattr("tools.network.requests.get", _fake_get)
    out = network.get_public_ip()
    assert "203.0.113.7" in out
    assert calls == ["https://api.ipify.org"]
