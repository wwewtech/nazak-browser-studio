"""
Unit tests for the CDP stealth injector pure helpers (audit fix P0-1).
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from nazak.core.cdp_injector import (
    InjectorHandle,
    build_runtime_user_agent,
    build_user_agent_metadata,
    load_stealth_source,
    pick_auth_challenge_response,
)


def test_build_runtime_user_agent_replaces_stale_version():
    stale = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
    out = build_runtime_user_agent(stale, "153.0.8010.53")
    assert "Chrome/153.0.8010.53" in out
    assert "Chrome/133" not in out
    assert out.startswith("Mozilla/5.0")


def test_build_runtime_user_agent_handles_missing_version_and_non_chrome():
    assert build_runtime_user_agent("UA", "") == "UA"
    firefox = "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0"
    assert build_runtime_user_agent(firefox, "153.0.0.0") == firefox


def test_build_user_agent_metadata_windows_consistency():
    fp = SimpleNamespace(
        platform="Win32",
        platform_version="15.0.0",
        architecture="x86",
        bitness="64",
        model="",
        mobile=False,
    )
    md = build_user_agent_metadata(fp, "153.0.8010.53")
    assert md["platform"] == "Windows"
    assert md["platformVersion"] == "15.0.0"
    assert md["uaFullVersion"] == "153.0.8010.53"
    majors = {b["version"] for b in md["brands"]}
    assert "153" in majors
    full = {b["version"] for b in md["fullVersionList"]}
    assert "153.0.8010.53" in full
    # brands and fullVersionList must agree on brand names
    assert {b["brand"] for b in md["brands"]} == {b["brand"] for b in md["fullVersionList"]}


def test_build_user_agent_metadata_platform_mapping():
    mac = build_user_agent_metadata(SimpleNamespace(platform="MacIntel"), "150.0.0.0")
    assert mac["platform"] == "macOS"
    linux = build_user_agent_metadata(SimpleNamespace(platform="Linux x86_64"), "150.0.0.0")
    assert linux["platform"] == "Linux"


def test_pick_auth_challenge_response_proxy_with_credentials():
    resp = pick_auth_challenge_response("Proxy", "user", "pass")
    assert resp == {"response": "ProvideCredentials", "username": "user", "password": "pass"}


def test_pick_auth_challenge_response_cancels_without_credentials_or_for_server():
    assert pick_auth_challenge_response("Proxy", None, None)["response"] == "CancelAuth"
    assert pick_auth_challenge_response("Proxy", "user", "")["response"] == "CancelAuth"
    assert pick_auth_challenge_response("Server", "user", "pass")["response"] == "CancelAuth"
    assert pick_auth_challenge_response(None, "user", "pass")["response"] == "CancelAuth"


def test_load_stealth_source_missing_path_returns_empty():
    assert load_stealth_source(None) == ""
    assert load_stealth_source("Z:\\does\\not\\exist\\ext") == ""


def test_injector_handle_initial_status():
    h = InjectorHandle(ws_endpoint="ws://127.0.0.1:1/devtools/browser/x")
    st = h.status()
    assert st["applied"] is False
    assert st["sessions"] == 0
    assert st["auth_challenges"] == 0
    assert h.alive is False
    # stop() on a never-started handle must be a no-op
    h.stop(timeout=0.1)


def test_apply_session_enables_auth_challenges_and_overrides():
    """Regression: Fetch.enable without handleAuthRequests never emits
    Fetch.authRequired, so proxy 407 answers stayed dead even though
    _on_auth_required was implemented (live-verified on Chrome 153)."""
    import asyncio

    from nazak.core.cdp_injector import InjectorOptions, StealthInjector

    opts = InjectorOptions(
        ws_endpoint="ws://127.0.0.1:1/devtools/browser/x",
        user_agent="UA",
        user_agent_metadata={},
        timezone="America/New_York",
        accept_language="en-US",
    )
    inj = StealthInjector(opts)
    calls: list[tuple[str, dict]] = []

    async def fake_command(method, params, session_id=None):
        calls.append((method, params or {}))
        return {}

    inj._command = fake_command  # type: ignore[method-assign]
    asyncio.run(inj._apply_session("SID"))

    fetch_calls = [p for m, p in calls if m == "Fetch.enable"]
    assert fetch_calls, "Fetch.enable must be issued for every session"
    assert fetch_calls[0].get("handleAuthRequests") is True

    tz_calls = [p for m, p in calls if m == "Emulation.setTimezoneOverride"]
    assert tz_calls and tz_calls[0]["timezoneId"] == "America/New_York"

    ua_calls = [p for m, p in calls if m == "Emulation.setUserAgentOverride"]
    assert ua_calls and ua_calls[0]["userAgent"] == "UA"

    assert inj.applied is True
    assert inj.sessions_applied == 1


# ---------------------------------------------------------------------------
# Real-version patching (audit fix A2b: UA 133 vs Client-Hints 153 mismatch)
# ---------------------------------------------------------------------------


def test_generate_extension_with_runtime_chrome_version(tmp_path):
    from nazak.core.extension_generator import generate_profile_extension
    from nazak.models.profile import BrowserProfile

    prof = BrowserProfile(id="ver_ext", name="Ver Ext")
    ext_dir = Path(generate_profile_extension(prof, tmp_path, chrome_version="155.0.7000.10"))
    stealth = (ext_dir / "stealth.js").read_text(encoding="utf-8")

    assert '"version": "155"' in stealth  # Client-Hints brands in stealth.js
    assert '"155.0.7000.10"' in stealth  # uaFullVersion / fullVersionList
    assert '"version": "133"' not in stealth  # stale brand version must be gone


def test_generate_extension_default_keeps_profile_version(tmp_path):
    from nazak.core.extension_generator import generate_profile_extension
    from nazak.models.profile import BrowserProfile

    prof = BrowserProfile(id="ver_ext_default", name="Ver Default")
    ext_dir = Path(generate_profile_extension(prof, tmp_path))
    stealth = (ext_dir / "stealth.js").read_text(encoding="utf-8")
    assert '"version": "133"' in stealth  # unchanged when version unknown


def test_build_chrome_args_uses_runtime_version(monkeypatch, tmp_path):
    from nazak.core import browser_launcher as bl_mod
    from nazak.models.profile import BrowserProfile

    monkeypatch.setattr(bl_mod, "get_chrome_version", lambda exe: "155.0.7000.10")
    bl = bl_mod.BrowserLauncher(profiles_dir=tmp_path / "p", extensions_dir=tmp_path / "e")
    prof = BrowserProfile(id="ua_arg", name="UA Arg")
    args, ext_path = bl.build_chrome_args(prof, "C:\\fake\\chrome.exe")

    ua_arg = next(a for a in args if a.startswith("--user-agent="))
    assert "Chrome/155.0.7000.10" in ua_arg
    assert "Chrome/133" not in ua_arg
    stealth = (Path(ext_path) / "stealth.js").read_text(encoding="utf-8")
    assert '"version": "155"' in stealth


def test_get_chrome_version_detects_real_binary():
    from nazak.config import find_chrome_executable
    from nazak.core.browser_launcher import get_chrome_version

    exe = find_chrome_executable()
    if not exe:
        pytest.skip("Chrome/Chromium not installed on this machine")
    version = get_chrome_version(exe)
    if version is None:
        pytest.skip("Version could not be read from the binary on this platform")
    assert version.count(".") == 3
    parts = version.split(".")
    assert all(p.isdigit() for p in parts)
    assert int(parts[0]) >= 100  # modern Chrome major
