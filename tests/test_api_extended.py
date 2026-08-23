import pytest
from fastapi.testclient import TestClient
from nazak.api.server import app

client = TestClient(app)

def test_randomize_fingerprint_api():
    resp = client.post("/api/profiles/randomize-fingerprint?os_type=windows")
    assert resp.status_code == 200
    data = resp.json()
    assert "user_agent" in data
    assert "hardware_concurrency" in data
    assert data["platform"] == "Win32"

def test_bulk_import_api():
    proxy_lines = "1.1.1.1:8080\n2.2.2.2:8080:user:pass"
    resp = client.post("/api/profiles/bulk-import", json={
        "proxy_lines": proxy_lines,
        "group": "Test Group",
        "target_page": "google_login"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["created_count"] == 2

def test_warmup_plan_api():
    resp = client.post("/api/profiles/prof_01/warmup/plan", json={
        "niche": "tech",
        "steps_count": 3
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["steps_count"] == 3
    assert len(data["search_queries"]) == 3

def test_cookies_import_api():
    cookies_data = '[{"name": "test_sid", "value": "val123", "domain": "google.com"}]'
    resp = client.post("/api/profiles/prof_01/cookies/import", json={
        "cookies_data": cookies_data
    })
    assert resp.status_code == 200
    assert resp.json()["parsed_cookies_count"] == 1

def test_batch_stop_api():
    resp = client.post("/api/profiles/batch-stop", json={"profile_ids": ["prof_01", "prof_02"]})
    assert resp.status_code == 200
    assert resp.json()["stopped_count"] == 2
