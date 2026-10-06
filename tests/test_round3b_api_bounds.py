"""Round-3b regression tests: границы входов API, безопасный 422, security-заголовки (R3b-03…R3b-11)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError
from starlette.testclient import TestClient

from nazak.api import server
from nazak.core import profile_manager as pm_mod, proxy_checker as pc
from nazak.models.profile import (
    BatterySpoofConfig,
    FingerprintConfig,
    GeolocationSpoofConfig,
)

LOCAL_HOST = {"host": "127.0.0.1"}


@pytest.fixture()
def client():
    return TestClient(server.app)


def test_r3b_mass_generate_count_is_bounded(client):
    assert client.post("/api/profiles/mass-generate", json={"count": 100_000}, headers=LOCAL_HOST).status_code == 422
    assert client.post("/api/profiles/mass-generate", json={"count": 0}, headers=LOCAL_HOST).status_code == 422
    assert client.post("/api/profiles/mass-generate", json={"count": -5}, headers=LOCAL_HOST).status_code == 422


def test_r3b_autopost_delay_is_bounded(client):
    body = {"profile_ids": ["prof_x"], "delay_seconds": 10**9}
    assert client.post("/api/autopost/launch", json=body, headers=LOCAL_HOST).status_code == 422
    body["delay_seconds"] = -1
    assert client.post("/api/autopost/launch", json=body, headers=LOCAL_HOST).status_code == 422
    body["delay_seconds"] = 10
    assert client.post("/api/autopost/launch", json=body, headers=LOCAL_HOST).status_code != 422


def test_r3b_synchronizer_delays_and_columns_are_bounded(client):
    body = {
        "master_profile_id": "m",
        "worker_profile_ids": ["w"],
        "min_delay_ms": -5000,
        "max_delay_ms": 10**9,
    }
    assert client.post("/api/synchronizer/start", json=body, headers=LOCAL_HOST).status_code == 422
    assert client.post("/api/synchronizer/tile-windows", json={"cols": 0}, headers=LOCAL_HOST).status_code == 422
    assert client.post("/api/synchronizer/tile-windows", json={"cols": 999}, headers=LOCAL_HOST).status_code == 422


def test_r3b_profile_id_lists_and_texts_are_bounded(client):
    too_many = {"profile_ids": [f"p{i}" for i in range(501)]}
    assert client.post("/api/profiles/batch-launch", json=too_many, headers=LOCAL_HOST).status_code == 422
    # Пустой список остаётся no-op с 200 (контракт не меняем: добавлена только
    # верхняя граница как защита от заваливания сервера).
    empty = client.post("/api/profiles/batch-launch", json={"profile_ids": []}, headers=LOCAL_HOST)
    assert empty.status_code == 200
    assert empty.json().get("results") in ({}, None)
    huge_note = {"cookies_data": "x" * 5_000_001}
    assert client.post("/api/profiles/prof_x/cookies/import", json=huge_note, headers=LOCAL_HOST).status_code == 422
    bad_format = {"profile_ids": ["p"], "format": "exe"}
    assert client.post("/api/cookies/bulk-export", json=bad_format, headers=LOCAL_HOST).status_code == 422


def test_r3b_fingerprint_rejects_non_finite_numbers():
    for model, field in (
        (FingerprintConfig, "device_pixel_ratio"),
        (FingerprintConfig, "audio_noise_seed"),
        (BatterySpoofConfig, "level"),
        (GeolocationSpoofConfig, "latitude"),
    ):
        for bad in (float("inf"), float("-inf"), float("nan")):
            with pytest.raises(ValidationError):
                model.model_validate({field: bad})
    # нормальные значения по-прежнему принимаются
    assert FingerprintConfig.model_validate({"device_pixel_ratio": 2.5}).device_pixel_ratio == 2.5


def test_r3b_synchronizer_navigate_rejects_non_http_urls_at_boundary(client):
    for bad in ("file:///etc/passwd", "javascript:alert(1)", "data:text/html,x"):
        resp = client.post("/api/synchronizer/navigate", json={"url": bad}, headers=LOCAL_HOST)
        assert resp.status_code == 422, bad
    ok = client.post("/api/synchronizer/navigate", json={"url": "https://example.com"}, headers=LOCAL_HOST)
    assert ok.status_code != 422


def test_r3b_non_finite_body_yields_clean_422_not_500(client):
    """json.loads принимает Infinity/NaN: ответ 422 обязан быть сериализуемым."""
    raw = '{"id":"x","name":"X","fingerprint":{"device_pixel_ratio":Infinity}}'
    resp = client.post("/api/profiles", content=raw, headers={**LOCAL_HOST, "content-type": "application/json"})
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail and detail[0]["type"] == "finite_number"
    assert detail[0]["input"] == "inf"
    json.dumps(resp.json())  # тело сериализуемо (раньше падало с 500)

    nan_body = '{"id":"y","name":"Y","fingerprint":{"audio_noise_seed":NaN}}'
    resp_nan = client.post(
        "/api/profiles", content=nan_body, headers={**LOCAL_HOST, "content-type": "application/json"}
    )
    assert resp_nan.status_code == 422


def test_r3b_validation_error_does_not_echo_huge_input(client):
    raw = '{"cookies_data":"' + "x" * 5_000_001 + '"}'
    resp = client.post(
        "/api/profiles/p/cookies/import", content=raw, headers={**LOCAL_HOST, "content-type": "application/json"}
    )
    assert resp.status_code == 422
    assert len(json.dumps(resp.json())) < 2000


def test_r3b_mass_generate_service_clamps_count(tmp_path):
    pm = pm_mod.ProfileManager(tmp_path / "profiles.json", tmp_path / "profiles")
    created = pm.mass_generate_profiles(count=10_000)
    assert len(created) == pm_mod.MAX_MASS_GENERATE_COUNT


def test_r3b_geo_response_from_hostile_proxy_is_sanitized():
    assert pc._safe_text("x" * 10_000, 128) == "x" * 128
    assert pc._safe_text(None, 8) is None
    assert pc._safe_text("a\x00b\nc", 32) == "abc"
    assert pc._safe_timezone("Europe/Berlin") == "Europe/Berlin"
    assert pc._safe_timezone("UTC") == "UTC"
    assert pc._safe_timezone("../../etc/passwd") is None
    assert pc._safe_timezone("x" * 200) is None
    assert pc._safe_timezone("<img src=x onerror=alert(1)>") is None
    assert pc._finite_or_none(float("inf"), -90, 90) is None
    assert pc._finite_or_none(float("nan"), -90, 90) is None
    assert pc._finite_or_none("52.5", -90, 90) == 52.5
    assert pc._finite_or_none(1000, -90, 90) is None


def test_r3b_security_headers_on_dashboard_and_api(client):
    for path in ("/", "/api/system/info"):
        resp = client.get(path, headers=LOCAL_HOST)
        assert resp.headers["X-Content-Type-Options"] == "nosniff"
        assert resp.headers["Referrer-Policy"] == "no-referrer"
        assert resp.headers["X-Frame-Options"] == "DENY"
        assert "frame-ancestors 'none'" in resp.headers["Content-Security-Policy"]
        assert "object-src 'none'" in resp.headers["Content-Security-Policy"]
    assert client.get("/api/system/info", headers=LOCAL_HOST).headers["Cache-Control"] == "no-store"


def test_r3b_security_headers_on_rejections(client):
    resp = client.get("/api/system/info", headers={"host": "evil.example.com"})
    assert resp.status_code == 403
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert "frame-ancestors 'none'" in resp.headers["Content-Security-Policy"]
