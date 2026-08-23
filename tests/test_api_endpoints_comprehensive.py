import pytest
import json
from pathlib import Path
from fastapi.testclient import TestClient
from nazak.api.server import app

client = TestClient(app)

def test_api_system_info():
    res = client.get("/api/system/info")
    assert res.status_code == 200
    d = res.json()
    assert "status" in d
    assert "chrome_installed" in d
    assert "total_profiles" in d

def test_api_list_profiles():
    res = client.get("/api/profiles")
    assert res.status_code == 200
    profs = res.json()
    assert len(profs) >= 10

def test_api_get_profile_by_id():
    res = client.get("/api/profiles/prof_01")
    assert res.status_code == 200
    prof = res.json()
    assert prof["id"] == "prof_01"

def test_api_get_profile_not_found():
    res = client.get("/api/profiles/prof_nonexistent_999")
    assert res.status_code == 404

def test_api_create_profile_valid():
    payload = {
        "id": "api_test_prof",
        "name": "API Test Profile",
        "proxy": {"type": "direct", "raw": "direct"},
        "fingerprint": {
            "user_agent": "Mozilla/5.0",
            "screen_width": 1920,
            "screen_height": 1080
        }
    }
    res = client.post("/api/profiles", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == "api_test_prof"
    
    # Cleanup
    client.delete("/api/profiles/api_test_prof")

def test_api_update_profile():
    res = client.get("/api/profiles/prof_02")
    prof = res.json()
    prof["name"] = "02 - Modified Name"
    
    up_res = client.put("/api/profiles/prof_02", json=prof)
    assert up_res.status_code == 200
    assert up_res.json()["name"] == "02 - Modified Name"

def test_api_clone_profile():
    res = client.post("/api/profiles/prof_01/clone")
    assert res.status_code == 200
    cloned = res.json()
    assert cloned["id"] != "prof_01"
    assert "Copy" in cloned["name"]
    
    # Cleanup
    client.delete(f"/api/profiles/{cloned['id']}")

def test_api_clone_profile_not_found():
    res = client.post("/api/profiles/fake_unknown_id/clone")
    assert res.status_code == 404

def test_api_delete_profile():
    # Create temp profile to delete
    create_res = client.post("/api/profiles", json={
        "id": "to_be_deleted",
        "name": "Delete Me",
        "fingerprint": {"user_agent": "UA", "screen_width": 1920, "screen_height": 1080}
    })
    assert create_res.status_code == 200
    
    del_res = client.delete("/api/profiles/to_be_deleted")
    assert del_res.status_code == 200
    assert del_res.json()["success"] is True

def test_api_delete_profile_not_found():
    res = client.delete("/api/profiles/nonexistent_delete_id")
    assert res.status_code == 404

def test_api_randomize_fingerprint():
    res = client.post("/api/profiles/randomize-fingerprint?os_type=windows")
    assert res.status_code == 200
    fp = res.json()
    assert fp["platform"] == "Win32"
    assert isinstance(fp["timezone"], str)
    assert fp["canvas_noise_seed"] > 0

def test_api_bulk_import_proxies():
    lines = "1.2.3.4:8080:u1:p1\n5.6.7.8:9000:u2:p2"
    res = client.post("/api/profiles/bulk-import", json={
        "proxy_lines": lines,
        "group": "Imported Test Group"
    })
    assert res.status_code == 200
    data = res.json()
    assert data["created_count"] == 2

def test_api_bulk_import_empty_text():
    res = client.post("/api/profiles/bulk-import", json={"proxy_lines": ""})
    assert res.status_code == 400

def test_api_warmup_plan_ecommerce():
    res = client.post("/api/profiles/prof_01/warmup/plan", json={
        "niche": "ecommerce",
        "steps_count": 5
    })
    assert res.status_code == 200
    plan = res.json()
    assert plan["niche"] == "ecommerce"
    assert len(plan["search_queries"]) == 5

def test_api_warmup_plan_crypto():
    res = client.post("/api/profiles/prof_01/warmup/plan", json={
        "niche": "crypto",
        "steps_count": 3
    })
    assert res.status_code == 200
    plan = res.json()
    assert len(plan["search_queries"]) == 3

def test_api_import_cookies_valid_json():
    cookies_json = json.dumps([{"name": "SID", "value": "test_sid", "domain": ".google.com"}])
    res = client.post("/api/profiles/prof_01/cookies/import", json={
        "cookies_data": cookies_json
    })
    assert res.status_code == 200
    assert res.json()["parsed_cookies_count"] == 1

def test_api_import_cookies_invalid():
    res = client.post("/api/profiles/prof_01/cookies/import", json={
        "cookies_data": "not valid cookie data"
    })
    assert res.status_code == 400

def test_api_test_raw_proxy_direct():
    res = client.post("/api/profiles/test-proxy", json={"raw_proxy": "direct"})
    assert res.status_code == 200
    data = res.json()
    assert "status" in data

def test_api_autopost_status():
    res = client.get("/api/autopost/status")
    assert res.status_code == 200
    d = res.json()
    assert "is_running" in d
    assert "jobs" in d

def test_api_autopost_preview_spintax():
    res = client.post("/api/autopost/preview-spintax", json={
        "profile_ids": ["prof_01", "prof_02"],
        "title_template": "{Top|Best} VPN {year}",
        "description_template": "Download: {tg}",
        "tg_channel": "@test_channel"
    })
    assert res.status_code == 200
    samples = res.json()["samples"]
    assert len(samples) == 2
    assert "@test_channel" in samples[0]["description"]

def test_api_autopost_cancel():
    res = client.post("/api/autopost/cancel")
    assert res.status_code == 200
    assert res.json()["success"] is True

def test_api_batch_stop():
    res = client.post("/api/profiles/batch-stop", json={
        "profile_ids": ["prof_01", "prof_02"]
    })
    assert res.status_code == 200
    assert res.json()["success"] is True

def test_api_clear_profile_cache():
    res = client.post("/api/profiles/prof_01/clear-cache")
    assert res.status_code == 200
    assert res.json()["success"] is True

def test_api_index_page():
    res = client.get("/")
    assert res.status_code == 200
