import pytest
from fastapi.testclient import TestClient
from nazak.api.server import app

client = TestClient(app)

def test_api_system_info():
    resp = client.get("/api/system/info")
    assert resp.status_code == 200
    data = resp.json()
    assert "chrome_installed" in data
    assert "total_profiles" in data
    assert data["total_profiles"] >= 10

def test_api_list_and_get_profiles():
    resp = client.get("/api/profiles")
    assert resp.status_code == 200
    profiles = resp.json()
    assert len(profiles) >= 10

    first_id = profiles[0]["id"]
    get_resp = client.get(f"/api/profiles/{first_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == first_id

def test_api_test_proxy_endpoint():
    resp = client.post("/api/profiles/test-proxy", json={"raw_proxy": "direct"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("healthy", "degraded", "idle", "checking")
