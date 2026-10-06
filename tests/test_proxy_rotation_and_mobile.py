"""
Unit Tests for Mobile Proxy IP Rotation URLs.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import nazak.api.server
from nazak.api.server import app, profile_manager
from nazak.models.profile import BrowserProfile
from nazak.models.proxy import ProxyConfig, ProxyType

client = TestClient(app)


def test_proxy_parse_with_rotation_url():
    # 1. Pipe format
    p1 = ProxyConfig.parse("1.2.3.4:8080:usr:pwd|https://change-ip.provider.com/reset?key=123")
    assert p1.host == "1.2.3.4"
    assert p1.port == 8080
    assert p1.username == "usr"
    assert p1.password == "pwd"
    assert p1.rotation_url == "https://change-ip.provider.com/reset?key=123"

    # 2. Hash format
    p2 = ProxyConfig.parse("socks5://usr:pwd@5.6.7.8:1080#http://rotate.me/ip")
    assert p2.host == "5.6.7.8"
    assert p2.rotation_url == "http://rotate.me/ip"

    # 3. 5-part colon format
    p3 = ProxyConfig.parse("9.9.9.9:8080:u:p:https://api.mobileproxy.ru/change")
    assert p3.host == "9.9.9.9"
    assert p3.rotation_url == "https://api.mobileproxy.ru/change"


def test_rotate_proxy_endpoint():
    proxy = ProxyConfig.parse("1.2.3.4:8080:u:p:https://rotate.provider.com/new-ip")
    prof = BrowserProfile(name="Mobile Proxy Profile", proxy=proxy)
    created = profile_manager.create_profile(prof)

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = b'{"status": "IP_CHANGED", "new_ip": "100.20.30.40"}'
    mock_resp.__enter__.return_value = mock_resp

    # Audit R3: запрос идёт через opener, запинненный к проверенному IP.
    with (
        patch("nazak.api.server._resolve_host_ips", return_value=["93.184.216.34"]),
        patch("nazak.api.server._build_pinned_opener") as build_opener,
    ):
        build_opener.return_value.open.return_value = mock_resp
        res = client.post(f"/api/profiles/{created.id}/rotate-proxy")
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert "IP_CHANGED" in data["response"]
        assert build_opener.call_args.args[0] == "93.184.216.34"
        opener = build_opener.return_value.open
        assert opener.call_args.args[0].full_url == "https://rotate.provider.com/new-ip"


@pytest.mark.parametrize(
    "rotation_url",
    [
        "file:///C:/Windows/win.ini",
        "http://127.0.0.1:8899/steal",
        "http://localhost/secret",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://192.168.1.1/admin",
    ],
)
def test_rotate_proxy_endpoint_refuses_local_and_file_targets(rotation_url):
    """Audit D2-P1-2: the rotation URL used to be fetched as-is (SSRF / local file read)."""
    proxy = ProxyConfig(type="http", host="1.2.3.4", port=8080, rotation_url=rotation_url)
    prof = BrowserProfile(name="Rotate Guard", proxy=proxy)
    created = profile_manager.create_profile(prof)

    with patch("nazak.api.server._build_pinned_opener") as build_opener:
        res = client.post(f"/api/profiles/{created.id}/rotate-proxy")
        assert res.status_code == 400
        build_opener.assert_not_called()


def test_rotate_proxy_endpoint_refuses_unresolvable_hosts():
    proxy = ProxyConfig(type="http", host="1.2.3.4", port=8080, rotation_url="https://no-such-host.invalid/ip")
    prof = BrowserProfile(name="Rotate DNS", proxy=proxy)
    created = profile_manager.create_profile(prof)

    with patch("nazak.api.server._resolve_host_ips", return_value=[]):
        res = client.post(f"/api/profiles/{created.id}/rotate-proxy")
        assert res.status_code == 400
        # never echo DNS details back to the caller
        assert "no-such-host" not in res.text
