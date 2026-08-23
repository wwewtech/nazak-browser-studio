import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from nazak.api.server import app

client = TestClient(app)

def test_get_autopost_status_api():
    resp = client.get("/api/autopost/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "is_running" in data
    assert "ffmpeg_available" in data
    assert "jobs" in data

def test_preview_spintax_api():
    resp = client.post("/api/autopost/preview-spintax", json={
        "profile_ids": ["prof_01", "prof_02"],
        "title_template": "{Top|Best} VPN",
        "description_template": "Link: {tg}",
        "tg_channel": "@tg_bot"
    })
    assert resp.status_code == 200
    samples = resp.json()["samples"]
    assert len(samples) == 2
    assert "@tg_bot" in samples[0]["description"]

def test_cancel_autopost_api():
    resp = client.post("/api/autopost/cancel")
    assert resp.status_code == 200
    assert resp.json()["success"] is True

def test_batch_uniquify_endpoint(tmp_path):
    dummy_video = tmp_path / "dummy.mp4"
    dummy_video.write_bytes(b"DUMMY_MP4_PAYLOAD" + b"\x00" * 500)
    
    resp = client.post("/api/autopost/uniquify", json={
        "source_video_path": str(dummy_video.resolve()),
        "profile_ids": ["prof_01", "prof_02"]
    })
    assert resp.status_code == 200
    assert resp.json()["count"] == 2
