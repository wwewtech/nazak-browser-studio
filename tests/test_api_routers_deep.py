"""
Deep router-level regression tests (round 4) for the FastAPI surface.

These tests deliberately target the least-covered branches of
``nazak/api/routers/*`` and ``nazak/api/realtime.py``: bulk cookie
import/export, the synchronizer session API, proxy health/rotation, warmup
planning/launch, the profile lifecycle endpoints and the WebSocket connection
manager.

Rules honoured here: every HTTP call is monkeypatched (nothing touches the
network), every request runs through ``TestClient`` on the local
``testserver`` host allowed by ``tests/conftest.py``, and validation errors are
expected to be loud 4xx answers - never a 500.
"""

from __future__ import annotations

import asyncio
import io
import json
import threading
import urllib.error
import zipfile
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from nazak.api import realtime, server
from nazak.api.realtime import ConnectionManager
from nazak.api.server import app
from nazak.core.synchronizer import SynchronizerSession
from nazak.models.health import GoogleReachability, HealthCheckResult, HealthStatus
from nazak.models.profile import BrowserProfile, ProfileStatus
from nazak.models.proxy import ProxyConfig, ProxyType

_COOKIE_JSON = json.dumps([{"name": "SID", "value": "v1", "domain": ".example.com", "path": "/", "secure": True}])


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _create_profile(profile_id: str, **kwargs: Any) -> BrowserProfile:
    """Create a profile through POST /api/profiles and hand back the stored entity."""
    server.profile_manager.delete_profile(profile_id, delete_data=True)  # keep the test idempotent
    payload = BrowserProfile(id=profile_id, name=f"Deep {profile_id}", **kwargs).model_dump(mode="json")
    resp = TestClient(app).post("/api/profiles", json=payload)
    assert resp.status_code == 200, resp.text
    stored = server.profile_manager.get_profile(profile_id)
    assert stored is not None
    return stored


def _drop(profile_id: str) -> None:
    server.profile_manager.delete_profile(profile_id, delete_data=True)


class _FakeWebSocket:
    """Minimal WebSocket stand-in for the ConnectionManager unit tests."""

    def __init__(self, fail: bool = False, on_send: Any = None) -> None:
        self.accepted = False
        self.sent: list[str] = []
        self.fail = fail
        self._on_send = on_send

    async def accept(self) -> None:
        self.accepted = True

    async def send_text(self, payload: str) -> None:
        if self.fail:
            raise RuntimeError("dead socket")
        self.sent.append(payload)
        if self._on_send is not None:
            self._on_send(payload)


# ---------------------------------------------------------------------------
# Cookies router
# ---------------------------------------------------------------------------
def test_bulk_import_validates_payload_and_reports_unknown_profiles(client: TestClient):
    empty = client.post("/api/cookies/bulk-import", json={"cookies_data": ""})
    assert empty.status_code == 400
    assert "No valid cookies" in empty.json()["detail"]
    assert "results" not in empty.json()

    garbage = client.post("/api/cookies/bulk-import", json={"cookies_data": "not a cookie file\njust some text"})
    assert garbage.status_code == 400
    assert "No valid cookies" in garbage.json()["detail"]

    unknown = client.post(
        "/api/cookies/bulk-import",
        json={
            "cookies_data": json.dumps(
                {"deep_ghost_profile": [{"name": "SID", "value": "x", "domain": ".example.com"}]}
            ),
            "auto_create_missing": False,
        },
    )
    assert unknown.status_code == 200
    body = unknown.json()
    assert body["success"] is True
    results = body["results"]
    # The per-profile failure must be reported in the payload, not swallowed.
    assert results["failed"] == 1
    assert results["created"] == 0
    assert results["matched"] == 0
    assert results["profile_ids"] == []


def test_bulk_import_netscape_autocreates_profile_and_persists_cookies(client: TestClient):
    netscape = "# Netscape HTTP Cookie File\n.example.com\tTRUE\t/\tFALSE\t1893456000\tSID\tsecret\n"
    resp = client.post("/api/cookies/bulk-import", json={"cookies_data": netscape})
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert results["created"] == 1
    assert len(results["profile_ids"]) == 1
    created_id = results["profile_ids"][0]
    try:
        stored = server.profile_manager.load_profile_cookies(created_id)
        assert [c["name"] for c in stored] == ["SID"]
        assert stored[0]["value"] == "secret"
        assert server.profile_manager.get_profile(created_id) is not None
    finally:
        _drop(created_id)


def test_bulk_export_zip_archive_and_profile_export_formats(client: TestClient):
    profile_id = "deep_cookie_prof"
    _create_profile(profile_id)
    try:
        imported = client.post(f"/api/profiles/{profile_id}/cookies/import", json={"cookies_data": _COOKIE_JSON})
        assert imported.status_code == 200
        assert imported.json()["parsed_cookies_count"] == 1

        zip_resp = client.post("/api/cookies/bulk-export", json={"profile_ids": [profile_id], "format": "zip"})
        assert zip_resp.status_code == 200
        assert zip_resp.headers["content-type"] == "application/zip"
        assert "nazak_cookies.zip" in zip_resp.headers["content-disposition"]
        with zipfile.ZipFile(io.BytesIO(zip_resp.content)) as archive:
            assert archive.namelist() == [f"{profile_id}.json"]
            assert json.loads(archive.read(f"{profile_id}.json"))[0]["name"] == "SID"

        as_json = client.get(f"/api/profiles/{profile_id}/cookies/export")
        assert as_json.status_code == 200
        json_body = as_json.json()
        assert json_body["format"] == "json"
        assert json_body["cookies_count"] == 1
        assert json_body["cookies"][0]["name"] == "SID"

        as_netscape = client.get(f"/api/profiles/{profile_id}/cookies/export?format=netscape")
        assert as_netscape.status_code == 200
        netscape_body = as_netscape.json()
        assert netscape_body["format"] == "netscape"
        assert netscape_body["cookies_count"] == 1
        assert "\tSID\tv1" in netscape_body["content"]
    finally:
        _drop(profile_id)


def test_bulk_export_netscape_format_is_honoured(client: TestClient):
    profile_id = "deep_netscape_prof"
    _create_profile(profile_id)
    try:
        client.post(f"/api/profiles/{profile_id}/cookies/import", json={"cookies_data": _COOKIE_JSON})
        resp = client.post("/api/cookies/bulk-export", json={"profile_ids": [profile_id], "format": "netscape"})
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("format") == "netscape"
        assert "\tSID\tv1" in body.get("content", "")
    finally:
        _drop(profile_id)


def test_import_cookies_unknown_profile_404(client: TestClient):
    resp = client.post("/api/profiles/deep_missing_profile/cookies/import", json={"cookies_data": _COOKIE_JSON})
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Profile not found"


# ---------------------------------------------------------------------------
# Synchronizer router
# ---------------------------------------------------------------------------
def test_synchronizer_start_validates_ids_and_normalises_payload(client: TestClient):
    bad_master = client.post(
        "/api/synchronizer/start",
        json={"master_profile_id": "../evil", "worker_profile_ids": ["prof_02"]},
    )
    assert bad_master.status_code == 400
    assert bad_master.json()["detail"].startswith("Invalid master_profile_id")

    bad_worker = client.post(
        "/api/synchronizer/start",
        json={"master_profile_id": "prof_01", "worker_profile_ids": ["prof_02", "../evil"]},
    )
    assert bad_worker.status_code == 400
    assert "Invalid worker_profile_id" in bad_worker.json()["detail"]
    assert ".." in bad_worker.json()["detail"]

    def _start(**kwargs: Any) -> SynchronizerSession:
        session = SynchronizerSession(**kwargs)
        # mirror SynchronizerManager.start_session: the returned session is live
        session.active = True
        return session

    with patch.object(server.synchronizer_mgr, "start_session", side_effect=_start) as start:
        ok = client.post(
            "/api/synchronizer/start",
            json={
                "master_profile_id": "prof_01",
                "worker_profile_ids": ["prof_02", "prof_01", "prof_03"],
                "min_delay_ms": 2000,
                "max_delay_ms": 1000,
                "coordinate_jitter_px": 3,
            },
        )
    assert ok.status_code == 200
    body = ok.json()
    assert body["success"] is True
    session = body["session"]
    assert session["master_profile_id"] == "prof_01"
    # the master is never also a worker
    assert session["worker_profile_ids"] == ["prof_02", "prof_03"]
    # an inverted interval is normalised instead of killing the pump thread
    assert session["delay_range_ms"] == [1000, 2000]
    assert session["coordinate_jitter_px"] == 3
    assert session["active"] is True
    assert start.call_args.kwargs["delay_range_ms"] == (2000, 1000)


def test_synchronizer_start_must_reject_empty_workers_and_unknown_ids(client: TestClient):
    def _start(**kwargs: Any) -> SynchronizerSession:
        return SynchronizerSession(**kwargs)

    with patch.object(server.synchronizer_mgr, "start_session", side_effect=_start):
        empty = client.post(
            "/api/synchronizer/start",
            json={"master_profile_id": "prof_01", "worker_profile_ids": []},
        )
        unknown = client.post(
            "/api/synchronizer/start",
            json={"master_profile_id": "deep_no_such_master", "worker_profile_ids": ["deep_no_such_worker"]},
        )
    assert empty.status_code == 400
    assert unknown.status_code == 400


def test_synchronizer_tile_windows_bounds_and_passthrough(client: TestClient):
    with patch.object(server.synchronizer_mgr, "tile_active_windows", return_value=True) as tile:
        no_body = client.post("/api/synchronizer/tile-windows")
        default_body = client.post("/api/synchronizer/tile-windows", json={})
        one_col = client.post("/api/synchronizer/tile-windows", json={"cols": 1})
        max_cols = client.post("/api/synchronizer/tile-windows", json={"cols": 8})
        too_small = client.post("/api/synchronizer/tile-windows", json={"cols": 0})
        too_big = client.post("/api/synchronizer/tile-windows", json={"cols": 9})
        wrong_type = client.post("/api/synchronizer/tile-windows", json={"cols": "two"})

    assert no_body.status_code == 200 and no_body.json() == {"success": True}
    assert default_body.status_code == 200
    assert one_col.status_code == 200
    assert max_cols.status_code == 200
    assert too_small.status_code == 422
    assert too_big.status_code == 422
    assert wrong_type.status_code == 422
    assert [call.kwargs["cols"] for call in tile.call_args_list] == [None, None, 1, 8]


def test_synchronizer_stop_status_and_navigate_when_idle(client: TestClient):
    assert client.post("/api/synchronizer/stop").status_code == 200

    status_resp = client.get("/api/synchronizer/status")
    assert status_resp.status_code == 200
    assert status_resp.json() == {"active": False, "session": None}

    # stopping again is a harmless no-op, not a 500
    again = client.post("/api/synchronizer/stop")
    assert again.status_code == 200
    assert again.json()["success"] is True

    idle_nav = client.post("/api/synchronizer/navigate", json={"url": "https://example.com"})
    assert idle_nav.status_code == 200
    assert idle_nav.json() == {"success": True, "results": {}}

    dash = client.post("/api/synchronizer/navigate", json={"url": "-rf /"})
    assert dash.status_code == 422
    scheme = client.post("/api/synchronizer/navigate", json={"url": "vbscript:msgbox(1)"})
    assert scheme.status_code == 422
    empty = client.post("/api/synchronizer/navigate", json={"url": ""})
    assert empty.status_code == 422


# ---------------------------------------------------------------------------
# Proxies router
# ---------------------------------------------------------------------------
def test_test_proxy_forwards_parsed_config_to_health_checker(client: TestClient):
    result = HealthCheckResult(status=HealthStatus.HEALTHY, ping_ms=42.0, ip="203.0.113.9", country="DE")
    seen: dict[str, Any] = {}

    async def fake_check(proxy: ProxyConfig, profile_dir: Any = None, **_kwargs: Any) -> HealthCheckResult:
        seen["proxy"] = proxy
        seen["profile_dir"] = profile_dir
        return result

    with patch("nazak.api.routers.proxies.check_proxy_health", new=fake_check):
        resp = client.post("/api/profiles/test-proxy", json={"raw_proxy": "socks5://user:pw@1.2.3.4:1080"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "healthy"
    assert body["ip"] == "203.0.113.9"
    proxy = seen["proxy"]
    assert proxy.type is ProxyType.SOCKS5
    assert (proxy.host, proxy.port) == ("1.2.3.4", 1080)
    assert (proxy.username, proxy.password) == ("user", "pw")
    # a standalone proxy test has no profile directory attached
    assert seen["profile_dir"] is None

    # oversized raw proxy strings are refused at the boundary, not passed on
    huge = client.post("/api/profiles/test-proxy", json={"raw_proxy": "1.2.3.4:8080" + "x" * 3000})
    assert huge.status_code == 422


def test_test_proxy_malformed_input_must_fail_loudly(client: TestClient):
    async def fake_check(proxy: ProxyConfig, profile_dir: Any = None, **_kwargs: Any) -> HealthCheckResult:
        return HealthCheckResult(status=HealthStatus.HEALTHY, ping_ms=1.0, ip="127.0.0.1")

    with patch("nazak.api.routers.proxies.check_proxy_health", new=fake_check):
        hostless = client.post("/api/profiles/test-proxy", json={"raw_proxy": "http://:8080"})
        garbage = client.post("/api/profiles/test-proxy", json={"raw_proxy": "definitely not a proxy"})
    assert hostless.status_code == 400
    assert garbage.status_code == 400


def test_check_profile_proxy_unknown_404_and_geo_persistence(client: TestClient):
    assert client.post("/api/profiles/deep_missing_profile/check").status_code == 404

    profile_id = "deep_health_prof"
    _create_profile(profile_id)
    try:
        result = HealthCheckResult(
            status=HealthStatus.HEALTHY,
            ping_ms=12.0,
            ip="203.0.113.10",
            timezone_name="Europe/Berlin",
            latitude=52.52,
            longitude=13.405,
            google=GoogleReachability(google_main=True),
        )
        with patch("nazak.api.routers.proxies.check_proxy_health", new=AsyncMock(return_value=result)):
            resp = client.post(f"/api/profiles/{profile_id}/check")
        assert resp.status_code == 200
        assert resp.json()["timezone_name"] == "Europe/Berlin"
        assert resp.json()["status"] == "healthy"

        stored = server.profile_manager.get_profile(profile_id)
        assert stored is not None
        assert stored.fingerprint.timezone == "Europe/Berlin"
        assert stored.fingerprint.geolocation.latitude == pytest.approx(52.52)
        assert stored.fingerprint.geolocation.longitude == pytest.approx(13.405)
        assert stored.last_health_check is not None
        assert stored.last_health_check.ip == "203.0.113.10"
    finally:
        _drop(profile_id)


def test_rotate_proxy_refusals_and_upstream_failures(client: TestClient):
    plain = _create_profile("deep_rotate_plain")
    plain_resp = client.post(f"/api/profiles/{plain.id}/rotate-proxy")
    assert plain_resp.status_code == 400
    assert "rotation URL" in plain_resp.json()["detail"]

    masked = _create_profile(
        "deep_rotate_masked",
        proxy=ProxyConfig(type=ProxyType.HTTP, host="1.2.3.4", port=8080, rotation_url="***"),
    )
    masked_resp = client.post(f"/api/profiles/{masked.id}/rotate-proxy")
    assert masked_resp.status_code == 400
    assert "masked" in masked_resp.json()["detail"]

    assert client.post("/api/profiles/deep_missing_profile/rotate-proxy").status_code == 404
    _drop(plain.id)
    _drop(masked.id)

    target = _create_profile(
        "deep_rotate_target",
        proxy=ProxyConfig(
            type=ProxyType.HTTP,
            host="1.2.3.4",
            port=8080,
            rotation_url="https://rotate.example.com/new-ip",
        ),
    )
    try:
        with (
            patch("nazak.api.server._resolve_host_ips", return_value=["93.184.216.34"]),
            patch("nazak.api.server._build_pinned_opener") as build_opener,
        ):
            build_opener.return_value.open.side_effect = urllib.error.URLError("connection refused")
            down = client.post(f"/api/profiles/{target.id}/rotate-proxy")
            build_opener.return_value.open.side_effect = urllib.error.HTTPError(
                "https://rotate.example.com/new-ip", 503, "unavailable", {}, None
            )
            refused = client.post(f"/api/profiles/{target.id}/rotate-proxy")
        assert down.status_code == 502
        assert down.json()["detail"] == "Proxy rotation request failed"
        assert refused.status_code == 400
        assert "unexpected HTTP status 503" in refused.json()["detail"]
    finally:
        _drop(target.id)


# ---------------------------------------------------------------------------
# Warmup / scenarios router
# ---------------------------------------------------------------------------
def test_run_scenario_alias_and_custom_data_dispatch(client: TestClient):
    with patch.object(server.scenario_executor, "run_batch_warmup") as run:
        alias_resp = client.post(
            "/api/scenarios/run",
            json={"scenario_id": "ecommerce_trust_booster", "profile_ids": []},
        )
        custom_resp = client.post(
            "/api/scenarios/run",
            json={
                "scenario_data": {
                    "id": "scen_deep_custom",
                    "name": "Deep Custom Scenario",
                    "steps": [{"action": "dwell", "params": {"min_sec": 1, "max_sec": 2}}],
                },
                "profile_ids": [],
            },
        )
        unknown_resp = client.post("/api/scenarios/run", json={"scenario_id": "ghost_scenario", "profile_ids": []})

    assert alias_resp.status_code == 200
    alias_body = alias_resp.json()
    assert alias_body["success"] is True
    # the alias resolved to the built-in scenario before dispatch
    assert "E-Commerce & Google Ads Trust Booster" in alias_body["message"]

    assert custom_resp.status_code == 200
    assert "Deep Custom Scenario" in custom_resp.json()["message"]

    assert unknown_resp.status_code == 400
    detail = unknown_resp.json()["detail"]
    assert "Unknown scenario_id 'ghost_scenario'" in detail
    assert "ecommerce_trust_booster" in detail

    assert run.call_count == 2
    dispatched = [call.kwargs["scenario"] for call in run.call_args_list]
    assert dispatched[0].id == "scen_ecom_trust"
    assert dispatched[1].id == "scen_deep_custom"
    assert len(dispatched[1].steps) == 1
    assert run.call_args_list[0].kwargs["max_concurrency"] == 3
    assert run.call_args_list[0].kwargs["profile_ids"] == []


def test_warmup_plan_is_bounded_by_niche_pool(client: TestClient):
    resp = client.post("/api/profiles/prof_01/warmup/plan", json={"niche": "crypto", "steps_count": 20})
    assert resp.status_code == 200
    body = resp.json()
    assert body["profile_id"] == "prof_01"
    assert body["niche"] == "crypto"
    # the plan can never promise more steps than the niche query pool holds
    assert body["steps_count"] == len(body["search_queries"])
    assert 1 <= body["steps_count"] <= 4
    assert len(set(body["search_queries"])) == body["steps_count"]
    assert body["estimated_duration_minutes"] == pytest.approx(body["steps_count"] * 1.5)

    assert client.post("/api/profiles/prof_01/warmup/plan", json={"steps_count": 21}).status_code == 422
    assert client.post("/api/profiles/prof_01/warmup/plan", json={"steps_count": 0}).status_code == 422
    assert client.post("/api/profiles/prof_01/warmup/plan", json={"niche": "x" * 200}).status_code == 422


def test_warmup_launch_unknown_profile_and_launcher_failure(client: TestClient):
    missing = client.post(
        "/api/profiles/deep_missing_profile/warmup/launch", json={"niche": "ecommerce", "steps_count": 3}
    )
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Profile not found"

    profile_id = "deep_warmup_prof"
    _create_profile(profile_id)
    try:
        with patch.object(server.browser_launcher, "launch", return_value=(False, None, "no chrome binary")):
            failed = client.post(
                f"/api/profiles/{profile_id}/warmup/launch", json={"niche": "ecommerce", "steps_count": 2}
            )
        assert failed.status_code == 400
        assert failed.json()["detail"] == "no chrome binary"

        with patch.object(server.browser_launcher, "launch", return_value=(True, 777, None)) as launch:
            ok = client.post(f"/api/profiles/{profile_id}/warmup/launch", json={"niche": "crypto", "steps_count": 2})
        assert ok.status_code == 200
        body = ok.json()
        assert body["success"] is True
        assert body["pid"] == 777
        assert body["plan"]["steps_count"] == 2
        assert body["start_url"].startswith("https://www.google.com/search?q=")
        assert launch.call_args.kwargs["custom_url"] == body["start_url"]

        stored = server.profile_manager.get_profile(profile_id)
        assert stored is not None
        assert stored.status is ProfileStatus.RUNNING
        assert stored.pid == 777
    finally:
        _drop(profile_id)


# ---------------------------------------------------------------------------
# Profiles router
# ---------------------------------------------------------------------------
def test_profile_lifecycle_guards_when_running(client: TestClient):
    doomed = "deep_lifecycle_prof"
    _create_profile(doomed)
    with (
        patch.object(server.browser_launcher, "is_profile_running", return_value=True),
        patch.object(server.browser_launcher, "stop") as stop,
    ):
        deleted = client.delete(f"/api/profiles/{doomed}")
    assert deleted.status_code == 200
    assert deleted.json()["success"] is True
    stop.assert_called_once_with(doomed)
    assert client.get(f"/api/profiles/{doomed}").status_code == 404

    kept = "deep_stoppable_prof"
    _create_profile(kept)
    try:
        with (
            patch.object(server.browser_launcher, "is_profile_running", side_effect=lambda pid: pid == kept),
            patch.dict(server.browser_launcher.profile_pids, {kept: 5150}),
        ):
            listing = client.get("/api/profiles")
            detail = client.get(f"/api/profiles/{kept}")
        assert listing.status_code == 200
        listed = {item["id"]: item for item in listing.json()}
        assert listed[kept]["status"] == "running"
        assert listed[kept]["pid"] == 5150
        assert detail.status_code == 200
        assert detail.json()["status"] == "running"
        assert detail.json()["pid"] == 5150

        with patch.object(server.browser_launcher, "is_profile_running", return_value=True):
            blocked = client.post(f"/api/profiles/{kept}/clear-cache")
        assert blocked.status_code == 400
        assert "Cannot clear cache" in blocked.json()["detail"]

        with patch.object(server.browser_launcher, "stop") as stop_again:
            stopped = client.post(f"/api/profiles/{kept}/stop")
        assert stopped.status_code == 200
        assert stopped.json() == {"success": True, "profile_id": kept}
        stop_again.assert_called_once_with(kept)
        stored = server.profile_manager.get_profile(kept)
        assert stored is not None
        assert stored.status is ProfileStatus.STOPPED
        assert stored.pid is None
    finally:
        _drop(kept)


def test_launch_profile_url_validation_unknown_and_failure_paths(client: TestClient):
    profile_id = "deep_launch_prof"
    _create_profile(profile_id)
    try:
        bad_url = client.post(f"/api/profiles/{profile_id}/launch", json={"custom_url": "file:///etc/passwd"})
        assert bad_url.status_code == 400
        assert "Invalid launch URL" in bad_url.json()["detail"]

        assert client.post("/api/profiles/deep_missing_profile/launch").status_code == 404

        with patch.object(server.browser_launcher, "launch", return_value=(False, None, "chrome exploded")):
            failed = client.post(f"/api/profiles/{profile_id}/launch")
        assert failed.status_code == 400
        assert failed.json()["detail"] == "chrome exploded"
        failed_state = server.profile_manager.get_profile(profile_id)
        assert failed_state is not None
        assert failed_state.status is ProfileStatus.ERROR

        with patch.object(server.browser_launcher, "launch", return_value=(True, 4242, None)) as launch:
            ok = client.post(f"/api/profiles/{profile_id}/launch", json={"custom_url": "example.com"})
        assert ok.status_code == 200
        assert ok.json() == {"success": True, "pid": 4242, "profile_id": profile_id}
        assert launch.call_args.kwargs["custom_url"] == "https://example.com"
        running = server.profile_manager.get_profile(profile_id)
        assert running is not None
        assert running.status is ProfileStatus.RUNNING
        assert running.pid == 4242
    finally:
        _drop(profile_id)


def test_clear_cache_unknown_profile_must_404(client: TestClient):
    resp = client.post("/api/profiles/deep_missing_profile/clear-cache")
    assert resp.status_code == 404
    # The message names the missing profile (more useful than a bare string).
    assert "deep_missing_profile" in resp.json()["detail"]
    assert "not found" in resp.json()["detail"]


def test_mass_generate_bounds_and_masks_proxy_secrets(client: TestClient):
    resp = client.post(
        "/api/profiles/mass-generate",
        json={"count": 2, "group": "Deep Mass", "notes": "deep mass note", "tags": ["deep"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["created_count"] == 2
    assert len(body["profiles"]) == 2
    created_ids = [item["id"] for item in body["profiles"]]
    try:
        for item in body["profiles"]:
            assert item["group"] == "Deep Mass"
            assert item["proxy"]["password"] in (None, "***")
            assert item["proxy"]["rotation_url"] in (None, "***")
    finally:
        for created_id in created_ids:
            _drop(created_id)

    assert client.post("/api/profiles/mass-generate", json={"count": 201}).status_code == 422
    assert (
        client.post("/api/profiles/mass-generate", json={"count": 1, "tags": [f"t{i}" for i in range(51)]}).status_code
        == 422
    )
    assert client.post("/api/profiles/mass-generate", json={"count": 1, "notes": "x" * 4001}).status_code == 422
    assert client.post("/api/profiles/mass-generate", json={"count": 1, "os_mix": "w" * 17}).status_code == 422


def test_bundle_export_unknown_404_and_zip_payload(client: TestClient):
    assert client.get("/api/profiles/deep_missing_profile/bundle/export").status_code == 404

    profile_id = "deep_bundle_prof"
    _create_profile(profile_id)
    try:
        client.post(f"/api/profiles/{profile_id}/cookies/import", json={"cookies_data": _COOKIE_JSON})
        resp = client.get(f"/api/profiles/{profile_id}/bundle/export")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/zip"
        assert ".nazak" in resp.headers["content-disposition"]
        assert resp.content[:2] == b"PK"
        with zipfile.ZipFile(io.BytesIO(resp.content)) as archive:
            names = archive.namelist()
            assert "profile.json" in names
            assert "cookies.json" in names
            meta = json.loads(archive.read("profile.json"))
            assert meta["id"] == profile_id
    finally:
        _drop(profile_id)


def test_bulk_import_profiles_must_bound_created_count(client: TestClient):
    fake_manager = MagicMock()
    fake_manager.list_profiles.return_value = []
    fake_manager.create_profile.side_effect = lambda profile: profile
    lines = "\n".join(f"10.0.0.{index}:8080:user:pass" for index in range(520))

    with patch("nazak.api.server.profile_manager", fake_manager):
        resp = client.post("/api/profiles/bulk-import", json={"proxy_lines": lines})

    assert fake_manager.create_profile.call_count <= 500
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Realtime hub
# ---------------------------------------------------------------------------
def test_broadcast_drops_dead_sockets_and_keeps_live_ones():
    manager = ConnectionManager()
    dead = _FakeWebSocket(fail=True)
    live = _FakeWebSocket()

    asyncio.run(manager.connect(dead))
    asyncio.run(manager.connect(live))
    assert dead.accepted and live.accepted
    assert manager.active_connections == [dead, live]

    asyncio.run(manager.broadcast("profile_status_change", {"profile_id": "p1"}))
    # the dead socket is evicted, the live one still received the payload
    assert manager.active_connections == [live]
    assert json.loads(live.sent[0]) == {
        "event": "profile_status_change",
        "data": {"profile_id": "p1"},
    }

    manager.disconnect(live)
    manager.disconnect(live)
    assert manager.active_connections == []


def test_server_loop_registry_and_process_state_broadcast():
    original_loop = realtime.get_server_loop()
    original_connections = list(realtime.ws_manager.active_connections)
    received = threading.Event()
    socket = _FakeWebSocket(on_send=lambda _payload: received.set())
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    try:
        realtime.set_server_loop(None)
        assert realtime.get_server_loop() is None
        realtime.set_server_loop(loop)
        assert realtime.get_server_loop() is loop

        asyncio.run_coroutine_threadsafe(realtime.ws_manager.connect(socket), loop).result(timeout=2)
        realtime.on_process_state_change("deep_sync_prof", ProfileStatus.RUNNING)
        assert received.wait(timeout=0.2), "profile_status_change was never broadcast through the server loop"
        assert json.loads(socket.sent[0]) == {
            "event": "profile_status_change",
            "data": {"profile_id": "deep_sync_prof", "status": "running"},
        }
    finally:
        realtime.ws_manager.disconnect(socket)
        realtime.set_server_loop(original_loop)
        for connection in original_connections:
            if connection not in realtime.ws_manager.active_connections:
                realtime.ws_manager.active_connections.append(connection)
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=2)
        loop.close()
