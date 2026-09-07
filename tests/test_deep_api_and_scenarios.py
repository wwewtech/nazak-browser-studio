"""
Deep API, Dolphin parity, Netscape cookies parsing, scenarios, and synchronizer test suite.
Contains 25 comprehensive tests verifying H3, H8, H9, H10, and advanced edge cases.
"""

from unittest.mock import MagicMock, patch

from starlette.testclient import TestClient

from nazak.api.server import SCENARIO_ALIASES, app as fastapi_app
from nazak.core.cookie_manager import cookies_to_netscape, parse_any_cookies, parse_netscape_cookies
from nazak.core.spintax import format_video_metadata, parse_spintax
from nazak.core.synchronizer import SynchronizerManager


# ---------------------------------------------------------------------------
# 1-6: Netscape cookie parsing and edge cases (H3)
# ---------------------------------------------------------------------------
def test_netscape_parser_handles_empty_lines_and_comments():
    raw = """
    # Netscape HTTP Cookie File
    # http://curl.haxx.se/rfc/cookie_spec.html

    .google.com\tTRUE\t/\tTRUE\t1893456000\tSID\tsecret123

    # Another comment line
    """
    cookies = parse_netscape_cookies(raw)
    assert len(cookies) == 1
    assert cookies[0]["name"] == "SID"
    assert cookies[0]["value"] == "secret123"


def test_netscape_parser_handles_httponly_prefix():
    raw = "#HttpOnly_login.live.com\tFALSE\t/\tTRUE\t1893456000\tMSPRequ\tval456\n"
    cookies = parse_netscape_cookies(raw)
    assert len(cookies) == 1
    assert cookies[0]["domain"] == "login.live.com"
    assert cookies[0]["httpOnly"] is True
    assert cookies[0]["secure"] is True


def test_netscape_parser_handles_regular_host_cookie():
    raw = "mysite.com\tFALSE\t/\tFALSE\t1893456000\tsession\tval789\n"
    cookies = parse_netscape_cookies(raw)
    assert len(cookies) == 1
    assert cookies[0]["domain"] == "mysite.com"
    assert cookies[0]["includeSubdomains"] is False
    assert cookies[0]["httpOnly"] is False
    assert cookies[0]["secure"] is False


def test_netscape_parser_handles_subdomain_flag_true():
    raw = "example.com\tTRUE\t/app\tFALSE\t1893456000\tpref\tdark_mode\n"
    cookies = parse_netscape_cookies(raw)
    assert len(cookies) == 1
    assert cookies[0]["includeSubdomains"] is True
    assert cookies[0]["path"] == "/app"


def test_netscape_parser_handles_secure_flag():
    raw_sec = "site.com\tFALSE\t/\tTRUE\t1893456000\tc1\tv1\n"
    raw_insec = "site.com\tFALSE\t/\tFALSE\t1893456000\tc2\tv2\n"
    assert parse_netscape_cookies(raw_sec)[0]["secure"] is True
    assert parse_netscape_cookies(raw_insec)[0]["secure"] is False


def test_netscape_parser_handles_expiry_timestamp():
    raw = "site.com\tFALSE\t/\tFALSE\t1750000000\tc\tv\n"
    cookies = parse_netscape_cookies(raw)
    assert cookies[0]["expires"] == 1750000000


# ---------------------------------------------------------------------------
# 7-10: Cookie roundtrip, JSON parsing, auto-detection
# ---------------------------------------------------------------------------
def test_netscape_parser_handles_session_cookie_zero_expiry():
    raw = "site.com\tFALSE\t/\tFALSE\t0\tsession_id\tabc\n"
    cookies = parse_netscape_cookies(raw)
    assert len(cookies) == 1
    assert cookies[0]["expires"] in [0, None]


def test_cookies_to_netscape_roundtrip_fidelity():
    original = [
        {
            "domain": "example.org",
            "includeSubdomains": True,
            "path": "/",
            "secure": True,
            "expires": 1893456000,
            "name": "tok",
            "value": "xyz",
            "httpOnly": True,
        },
        {
            "domain": "sub.test.com",
            "includeSubdomains": False,
            "path": "/api",
            "secure": False,
            "expires": 1893456000,
            "name": "user",
            "value": "john",
            "httpOnly": False,
        },
    ]
    netscape_text = cookies_to_netscape(original)
    parsed = parse_netscape_cookies(netscape_text)
    assert len(parsed) == 2
    assert parsed[0]["name"] == "tok"
    assert parsed[0]["httpOnly"] is True
    assert parsed[0]["includeSubdomains"] is True
    assert parsed[1]["name"] == "user"
    assert parsed[1]["httpOnly"] is False
    assert parsed[1]["includeSubdomains"] is False


def test_cookie_manager_parse_json_cookie_format():
    json_cookies = (
        '[{"name": "test_c", "value": "val123", "domain": ".test.com", "path": "/", "httpOnly": true, "secure": true}]'
    )
    parsed = parse_any_cookies(json_cookies)
    assert len(parsed) == 1
    assert parsed[0]["name"] == "test_c"
    assert parsed[0]["value"] == "val123"
    assert parsed[0]["httpOnly"] is True


def test_cookie_manager_parse_any_cookies_auto_detect():
    json_str = '[{"name": "j", "value": "1", "domain": "a.com"}]'
    netscape_str = "a.com\tTRUE\t/\tFALSE\t1893456000\tn\t2\n"

    parsed_j = parse_any_cookies(json_str)
    parsed_n = parse_any_cookies(netscape_str)

    assert len(parsed_j) == 1 and parsed_j[0]["name"] == "j"
    assert len(parsed_n) == 1 and parsed_n[0]["name"] == "n"


# ---------------------------------------------------------------------------
# 11-15: Scenario aliases resolution and validation (H9)
# ---------------------------------------------------------------------------
def test_api_scenario_aliases_resolution_ecom():
    assert SCENARIO_ALIASES.get("ecommerce_trust_booster") == "scen_ecom_trust"


def test_api_scenario_aliases_resolution_youtube():
    assert SCENARIO_ALIASES.get("youtube_shorts_warmup") == "scen_youtube_viewer"


def test_api_scenario_aliases_resolution_crypto():
    assert SCENARIO_ALIASES.get("crypto_web3_farming") == "scen_crypto_web3"


def test_api_scenario_aliases_resolution_finance():
    assert SCENARIO_ALIASES.get("finance_high_cpc_banking") == "scen_finance_banking"


def test_api_run_scenario_missing_params_returns_400():
    client = TestClient(fastapi_app)
    # Neither scenario_id nor scenario_data provided
    resp = client.post("/api/scenarios/run", json={"profile_ids": []})
    assert resp.status_code == 400
    assert "Either scenario_id or scenario_data" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# 16-20: Warmup, Dolphin parity, and CDP endpoints (H10)
# ---------------------------------------------------------------------------
def test_api_run_scenario_invalid_id_returns_400():
    client = TestClient(fastapi_app)
    resp = client.post("/api/scenarios/run", json={"scenario_id": "ghost_id_xyz", "profile_ids": []})
    assert resp.status_code == 400
    assert "Unknown scenario_id" in resp.json()["detail"]


def test_api_warmup_plan_valid_niche():
    client = TestClient(fastapi_app)
    resp = client.post("/api/profiles/prof_01/warmup/plan", json={"niche": "ecommerce", "steps_count": 4})
    assert resp.status_code == 200
    data = resp.json()
    assert "search_queries" in data
    assert len(data["search_queries"]) >= 1


def test_api_dolphin_start_returns_ws_endpoint_and_wsEndpoint():
    client = TestClient(fastapi_app)
    mock_p = MagicMock()
    mock_p.id = "prof_01"
    with (
        patch("nazak.api.server.profile_manager.get_profile", return_value=mock_p),
        patch("nazak.api.server.profile_manager.update_profile"),
        patch("nazak.api.server.browser_launcher.launch_with_cdp") as mock_launch,
    ):
        mock_launch.return_value = (True, 1234, 9222, "ws://127.0.0.1:9222/devtools/browser", None)
        resp = client.get("/v1.0/browser_profiles/prof_01/start")
        assert resp.status_code == 200
        automation = resp.json().get("automation", {})
        assert "port" in automation
        assert "wsEndpoint" in automation
        assert automation["wsEndpoint"] == "ws://127.0.0.1:9222/devtools/browser"


def test_api_dolphin_active_profiles_endpoint():
    client = TestClient(fastapi_app)
    mock_p = MagicMock()
    mock_p.id = "prof_01"
    mock_p.name = "Test Profile"
    with (
        patch("nazak.api.server.profile_manager.list_profiles", return_value=[mock_p]),
        patch("nazak.api.server.browser_launcher.is_profile_running", return_value=True),
        patch("nazak.api.server.browser_launcher.get_cdp_info", return_value={"port": 9222, "wsEndpoint": "ws://..."}),
        patch("nazak.api.server.browser_launcher.profile_pids", {"prof_01": 1234}),
    ):
        resp = client.get("/v1.0/browser_profiles/active")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert resp.json()["active_count"] == 1
        assert len(resp.json()["profiles"]) == 1
        assert resp.json()["profiles"][0]["profile_id"] == "prof_01"


def test_api_dolphin_stop_profile_endpoint():
    client = TestClient(fastapi_app)
    mock_p = MagicMock()
    mock_p.id = "prof_01"
    with (
        patch("nazak.api.server.profile_manager.get_profile", return_value=mock_p),
        patch("nazak.api.server.profile_manager.update_profile"),
        patch("nazak.api.server.browser_launcher.stop", return_value=True),
    ):
        resp = client.get("/v1.0/browser_profiles/prof_01/stop")
        assert resp.status_code == 200
        assert resp.json()["success"] is True


# ---------------------------------------------------------------------------
# 21-25: Autopost uniquify, synchronizer, and spintax formatting
# ---------------------------------------------------------------------------
def test_api_autopost_uniquify_nonexistent_source_returns_400():
    client = TestClient(fastapi_app)
    resp = client.post(
        "/api/autopost/uniquify",
        json={"source_video_path": "non_existent_video_path_9999.mp4", "profile_ids": ["prof_01"]},
    )
    assert resp.status_code == 400
    assert "not found" in resp.json()["detail"].lower()


def test_api_autopost_uniquify_dispatches_to_thread():
    import inspect

    from nazak.api.server import uniquify_videos_endpoint

    source = inspect.getsource(uniquify_videos_endpoint)
    # Verifies synchronous ffmpeg call is offloaded to worker thread (H8)
    assert "asyncio.to_thread" in source


def test_synchronizer_mirror_navigation_httpx_timeout():
    import inspect

    from nazak.core.synchronizer import SynchronizerManager

    source = inspect.getsource(SynchronizerManager.mirror_navigation)
    assert "urllib.request.urlopen" not in source
    assert "httpx.AsyncClient" in source


def test_synchronizer_tile_active_windows_grid_math():
    mock_bl = MagicMock()
    mock_bl.profile_pids = {"p1": 101, "p2": 102, "p3": 103, "p4": 104}
    mgr = SynchronizerManager(mock_bl)
    with patch("nazak.core.synchronizer.tile_windows_win32", return_value=True) as mock_tile:
        res = mgr.tile_active_windows(cols=2)
        assert res is True
        mock_tile.assert_called_once_with([101, 102, 103, 104], cols=2)


def test_spintax_format_video_metadata_full_matrix():
    # 1. Standard spintax
    res = parse_spintax("{Apple|Banana|Cherry}")
    assert res in ["Apple", "Banana", "Cherry"]

    # 2. Nested spintax
    res_nested = parse_spintax("{A|{B|C}}")
    assert res_nested in ["A", "B", "C"]

    # 3. Full metadata format with telegram channel and unicode
    meta = format_video_metadata(
        title_template="{🔥|⚡} Топ {10|5} лайфхаков для разработчиков",
        description_template="Подпишись на канал: {tg}\n#shorts #tech",
        profile_name="Dev Profile",
        profile_id="prof_01",
        tg_channel="@tech_daily",
    )
    assert "@tech_daily" in meta["description"]
    assert any(icon in meta["title"] for icon in ["🔥", "⚡"])
    assert "#shorts" in meta["description"]
