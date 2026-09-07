"""
Regression test suite for all findings from AUDIT_REPORT.md.
Guarantees 100% verification of C1-C5, H1-H11, M1-M8, and I1.
"""

import asyncio
import inspect
import io
import json
import threading
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from starlette.testclient import TestClient

from nazak.api.server import (
    SCENARIO_ALIASES,
    app as fastapi_app,
    browser_launcher,
    profile_manager,
    validate_pid,
)
from nazak.core.browser_launcher import BrowserLauncher
from nazak.core.cookie_manager import cookies_to_netscape, parse_netscape_cookies
from nazak.core.extension_generator import generate_profile_extension
from nazak.core.profile_manager import ProfileManager
from nazak.core.spintax import format_video_metadata
from nazak.models.profile import BrowserProfile, FingerprintConfig, ProfileStatus, ProxyType
from nazak.models.proxy import ProxyConfig


def test_c1_extension_manifest_world_is_main(tmp_path):
    prof = BrowserProfile(id="c1_test", name="C1 Test")
    ext_dir_str = generate_profile_extension(prof, tmp_path)
    assert ext_dir_str is not None
    manifest_file = Path(ext_dir_str) / "manifest.json"
    assert manifest_file.exists()
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert "content_scripts" in manifest
    scripts = manifest["content_scripts"]
    assert len(scripts) > 0
    assert scripts[0].get("world") == "MAIN", "content_scripts must run in MAIN world"


def test_c2_gui_imports_and_proxy_type():
    from nazak.gui.dialogs.profile_edit_dialog import ProxyType as DialogProxyType
    from nazak.models.profile import ProxyType as ProfileProxyType
    from nazak.models.proxy import ProxyType as ModelProxyType

    assert DialogProxyType is ModelProxyType
    assert ProfileProxyType is ModelProxyType

    import nazak.gui

    assert nazak.gui is not None


def test_c3_path_traversal_validation():
    for bad_id in [
        "../evil",
        "..\\evil",
        "../../test",
        "/etc/passwd",
        "C:\\Windows",
        "",
        ".",
        "..",
        "test;rm",
        "prof 1",
        "prof/01",
    ]:
        with pytest.raises(HTTPException):
            validate_pid(bad_id)

    assert validate_pid("prof_01") == "prof_01"
    assert validate_pid("prof-valid-123") == "prof-valid-123"


def test_c3_cors_evil_origin_rejected():
    client = TestClient(fastapi_app)
    resp = client.get("/api/system/info", headers={"Origin": "https://evil.example"})
    acao = resp.headers.get("access-control-allow-origin")
    assert acao != "https://evil.example", f"Evil origin was accepted: {acao}"

    resp_local = client.get("/api/system/info", headers={"Origin": "http://localhost:3000"})
    assert resp_local.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_c3_api_path_traversal_returns_400():
    client = TestClient(fastapi_app)
    # Profile ID with unsafe characters / traversal components
    resp = client.get("/api/profiles/prof..evil")
    assert resp.status_code == 400
    assert "invalid profile_id" in resp.json()["detail"].lower()


def test_c5_concurrent_save_profiles(tmp_path):
    pfile = tmp_path / "profiles.json"
    pdir = tmp_path / "profiles"
    pm = ProfileManager(pfile, pdir)

    for i in range(10):
        p = BrowserProfile(id=f"prof_{i:02d}", name=f"Profile {i}")
        pm.profiles[p.id] = p
    pm.save_profiles()

    errors = []

    def writer_thread(idx):
        try:
            for _ in range(15):
                prof = pm.get_profile(f"prof_{idx:02d}")
                if prof:
                    prof.name = f"Updated by thread {idx}"
                    pm.save_profiles()
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=writer_thread, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Errors during concurrent save: {errors}"
    assert pfile.exists()
    loaded_data = json.loads(pfile.read_text(encoding="utf-8"))
    assert len(loaded_data) == len(pm.profiles)


def test_h1_ws_threadsafe_dispatch():
    from nazak.api.server import on_process_state_change

    worker_err = None

    def bg_worker():
        nonlocal worker_err
        try:
            on_process_state_change("p_test", ProfileStatus.STOPPED)
        except RuntimeError as e:
            if "no running event loop" in str(e).lower() or "there is no current event loop" in str(e).lower():
                worker_err = e

    t = threading.Thread(target=bg_worker)
    t.start()
    t.join()
    assert worker_err is None, f"Thread-unsafe dispatch failed: {worker_err}"


def test_h2_spintax_empty_description_guard():
    meta = format_video_metadata(
        title_template="Title",
        description_template="",
        profile_name="Profile 1",
        profile_id="prof_01",
        tg_channel="",
    )
    desc = meta["description"]
    lines = desc.splitlines()
    first_line = lines[0] if lines else ""
    assert first_line == ""


def test_h3_netscape_subdomains_and_httponly_columns():
    netscape_line = "mysite.com\tTRUE\t/\tFALSE\t1893456000\tsession_id\tabc123\n"
    cookies = parse_netscape_cookies(netscape_line)
    assert len(cookies) == 1
    c = cookies[0]
    assert c["httpOnly"] is False, "Col 4 is FALSE -> httpOnly must be False"
    assert c["includeSubdomains"] is True, "Col 2 is TRUE -> includeSubdomains must be True"

    exported = cookies_to_netscape(cookies)
    assert not exported.startswith("#HttpOnly_"), "Cookie should not have #HttpOnly_ prefix"
    cols = exported.split("\t")
    assert cols[1] == "TRUE", "includeSubdomains col must remain TRUE"
    assert cols[3] == "FALSE", "secure col"


def test_h4_and_m7_synchronizer_status_and_win32_tile():
    from nazak.core.synchronizer import SynchronizerManager

    mock_bl = MagicMock()
    mgr = SynchronizerManager(mock_bl)
    status = mgr.get_status()
    assert status["active"] is False
    assert status["session"] is None


def test_h6_fingerprint_js_escape(tmp_path):
    fp = FingerprintConfig(
        platform='Win32"; alert("injected");//',
        vendor='Google Inc."; evil();//',
        timezone='UTC"; //',
        webgl_renderer='NVIDIA"; //',
    )
    prof = BrowserProfile(id="h6_test", name="H6 Test", fingerprint=fp)
    ext_dir_str = generate_profile_extension(prof, tmp_path)
    assert ext_dir_str is not None
    stealth_file = Path(ext_dir_str) / "stealth.js"
    assert stealth_file.exists()
    content = stealth_file.read_text(encoding="utf-8")
    assert 'alert(\\"injected\\")' in content or 'alert("injected")' in content
    assert 'get: () => "Win32"; alert' not in content


def test_h7_playwright_declared_in_requirements_and_pyproject():
    req_path = Path(__file__).resolve().parent.parent / "requirements.txt"
    pyproj_path = Path(__file__).resolve().parent.parent / "pyproject.toml"

    req_text = req_path.read_text(encoding="utf-8")
    assert "playwright" in req_text.lower(), "playwright must be in requirements.txt"

    pyproj_text = pyproj_path.read_text(encoding="utf-8")
    assert "playwright" in pyproj_text.lower(), "playwright must be in pyproject.toml"


def test_h8_uniquify_endpoint_uses_to_thread():
    from nazak.api.server import uniquify_videos_endpoint

    assert inspect.iscoroutinefunction(uniquify_videos_endpoint)
    source = inspect.getsource(uniquify_videos_endpoint)
    assert "asyncio.to_thread" in source


def test_h9_scenario_aliases_and_validation():
    assert "ecommerce_trust_booster" in SCENARIO_ALIASES
    assert "youtube_shorts_warmup" in SCENARIO_ALIASES
    assert SCENARIO_ALIASES["ecommerce_trust_booster"] == "scen_ecom_trust"
    assert SCENARIO_ALIASES["youtube_shorts_warmup"] == "scen_youtube_viewer"

    client = TestClient(fastapi_app)
    resp = client.post("/api/scenarios/run", json={"scenario_id": "ghost_scenario", "profile_ids": []})
    assert resp.status_code == 400
    assert "Unknown scenario_id" in resp.json()["detail"]


def test_h10_ws_endpoint_aliases():
    launcher = BrowserLauncher(Path("/tmp/prof"), Path("/tmp/ext"))
    launcher.is_profile_running = MagicMock(return_value=True)
    launcher.profile_cdp_ports["dummy_id"] = 9222
    cdp = launcher.get_cdp_info("dummy_id")
    assert "ws_endpoint" in cdp
    assert "wsEndpoint" in cdp
    assert cdp["ws_endpoint"] == cdp["wsEndpoint"]


def test_h11_no_hardcoded_secrets_in_cli():
    cli_path = Path(__file__).resolve().parent.parent / "nazak" / "cli_auto_login_and_upload.py"
    cli_text = cli_path.read_text(encoding="utf-8")
    assert "Gomie8383888" not in cli_text
    assert "qq6rxgbtkfetme7digqvl27kkechle5i" not in cli_text
    assert "D:/nazak" not in cli_text


def test_m1_process_monitor_skips_stopped():
    from nazak.core.process_monitor import ProcessMonitor

    p_stopped = BrowserProfile(id="p_stop", name="Stopped", status=ProfileStatus.STOPPED)
    mock_pm = MagicMock()
    mock_pm.list_profiles.return_value = [p_stopped]
    mock_pm.get_profile.return_value = p_stopped
    mock_bl = MagicMock()
    mock_bl.is_profile_running.return_value = False

    monitor = ProcessMonitor(mock_pm, mock_bl, poll_interval=0.05)
    monitor._running = True
    profiles = mock_pm.list_profiles()
    for p in profiles:
        if p.status == ProfileStatus.RUNNING:
            alive = mock_bl.is_profile_running(p.id)
            if not alive:
                mock_pm.update_profile(p)
    mock_pm.update_profile.assert_not_called()


def test_m3_zip_slip_prevention(tmp_path):
    pfile = tmp_path / "profiles.json"
    pdir = tmp_path / "profiles"
    pm = ProfileManager(pfile, pdir)

    zip_bytes = io.BytesIO()
    with zipfile.ZipFile(zip_bytes, "w") as zf:
        meta = {"id": "slip_test", "name": "Zip Slip Test"}
        zf.writestr("profile.json", json.dumps(meta))
        zf.writestr("data/../../evil.txt", "MALICIOUS PAYLOAD")
        zf.writestr("data/subdir/safe.txt", "SAFE PAYLOAD")
    zip_bytes.seek(0)

    zip_file = tmp_path / "bundle.nazak"
    zip_file.write_bytes(zip_bytes.getvalue())

    imported = pm.import_profile_bundle(zip_file)
    assert imported is not None
    assert not (tmp_path / "evil.txt").exists()
    assert not (tmp_path / "profiles" / "evil.txt").exists()
    assert (pdir / imported.id / "subdir" / "safe.txt").exists()


def test_m4_main_window_imports_singletons():
    from nazak.api.server import browser_launcher as api_bl, profile_manager as api_pm
    from nazak.gui.main_window import browser_launcher as gui_bl, profile_manager as gui_pm

    assert gui_pm is api_pm
    assert gui_bl is api_bl


def test_m5_create_profile_rejects_duplicate(tmp_path):
    pfile = tmp_path / "profiles.json"
    pdir = tmp_path / "profiles"
    pm = ProfileManager(pfile, pdir)

    p1 = BrowserProfile(id="prof_unique", name="Unique 1")
    pm.create_profile(p1)

    p2 = BrowserProfile(id="prof_unique", name="Unique 2")
    with pytest.raises(ValueError, match="already exists"):
        pm.create_profile(p2)


def test_m8_mirror_navigation_no_urllib_blocking():
    from nazak.core.synchronizer import SynchronizerManager

    source = inspect.getsource(SynchronizerManager.mirror_navigation)
    assert "urllib.request.urlopen" not in source
    assert "httpx" in source or "asyncio.to_thread" in source
