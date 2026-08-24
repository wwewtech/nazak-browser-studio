"""
Unit Tests for Dolphin{anty} Local Automation API and CDP Endpoint Allocation.
"""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from nazak.api.server import app, browser_launcher, profile_manager
from nazak.models.profile import BrowserProfile, ProxyConfig
from nazak.core.browser_launcher import get_free_port, BrowserLauncher

client = TestClient(app)

def test_get_free_port():
    port1 = get_free_port()
    port2 = get_free_port()
    assert isinstance(port1, int)
    assert 1024 < port1 < 65535
    assert isinstance(port2, int)

def test_dolphin_v1_list_profiles_endpoint():
    response = client.get("/v1.0/browser_profiles")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert isinstance(data["data"], list)

def test_dolphin_v1_start_stop_mocked():
    p = BrowserProfile(name="Dolphin Auto Test Profile", proxy=ProxyConfig())
    created = profile_manager.create_profile(p)

    with patch.object(browser_launcher, "launch_with_cdp", return_value=(True, 9999, 9222, "ws://127.0.0.1:9222/devtools/browser/abc", None)):
        resp_start = client.get(f"/v1.0/browser_profiles/{created.id}/start")
        assert resp_start.status_code == 200
        data = resp_start.json()
        assert data["success"] is True
        assert data["automation"]["port"] == 9222
        assert "ws://" in data["automation"]["wsEndpoint"]

    with patch.object(browser_launcher, "stop", return_value=True):
        resp_stop = client.get(f"/v1.0/browser_profiles/{created.id}/stop")
        assert resp_stop.status_code == 200
        assert resp_stop.json()["success"] is True

def test_nazak_api_v1_start_stop_endpoints():
    p = BrowserProfile(name="Nazak CDP Test Profile", proxy=ProxyConfig())
    created = profile_manager.create_profile(p)

    with patch.object(browser_launcher, "launch_with_cdp", return_value=(True, 8888, 9333, "ws://127.0.0.1:9333/devtools/browser/xyz", None)):
        resp_start = client.post(f"/api/v1/profiles/{created.id}/start")
        assert resp_start.status_code == 200
        data = resp_start.json()
        assert data["automation"]["port"] == 9333

    with patch.object(browser_launcher, "stop", return_value=True):
        resp_stop = client.post(f"/api/v1/profiles/{created.id}/stop")
        assert resp_stop.status_code == 200
        assert resp_stop.json()["success"] is True

def test_dolphin_active_profiles_endpoint():
    resp = client.get("/v1.0/browser_profiles/active")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "active_count" in data
    assert isinstance(data["profiles"], list)
