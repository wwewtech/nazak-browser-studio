"""
Unit Tests for Mobile Proxy IP Rotation URLs.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from nazak.api.server import app, profile_manager
from nazak.models.profile import BrowserProfile
from nazak.models.proxy import ProxyConfig

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

    with patch("urllib.request.urlopen", return_value=mock_resp):
        res = client.post(f"/api/profiles/{created.id}/rotate-proxy")
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert "IP_CHANGED" in data["response"]
