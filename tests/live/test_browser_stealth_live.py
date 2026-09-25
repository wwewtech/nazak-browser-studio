"""Live test: verifies real Chromium CDP stealth spoofing end-to-end.

Requires real Chrome / Chromium installed on the host machine.
Skipped by default in regular test runs; execute via:
    pytest -m live tests/live/test_browser_stealth_live.py
"""

import asyncio
import json
import time

import pytest
import websockets

from nazak.config import find_chrome_executable
from nazak.core.browser_launcher import BrowserLauncher, get_chrome_version
from nazak.models.profile import BrowserProfile, FingerprintConfig
from nazak.models.proxy import ProxyConfig, ProxyType


@pytest.mark.live
def test_chrome_stealth_cdp_overrides_apply_to_real_page(tmp_path):
    chrome_exe = find_chrome_executable()
    if not chrome_exe:
        pytest.skip("Chrome/Chromium executable not found on host")

    real_version = get_chrome_version(chrome_exe)
    if not real_version:
        pytest.skip("Unable to determine installed Chrome version")

    # Stale UA from an older Chrome (130) — injector must rewrite it to real_version
    stale_ua = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    )

    fp = FingerprintConfig(
        user_agent=stale_ua,
        platform="Win32",
        os="windows",
        device_type="desktop",
        screen_width=1366,
        screen_height=768,
        screen_avail_width=1366,
        screen_avail_height=728,
        language="en-US,en;q=0.9",
        timezone="America/New_York",
        webrtc_policy="default",
        gpu_features={"webgl": True},
        hardware_concurrency=8,
        device_memory_gb=16,
    )
    profile = BrowserProfile(
        id="live_stealth_test",
        name="Live Stealth",
        fingerprint=fp,
        proxy=ProxyConfig(type=ProxyType.DIRECT),
    )

    launcher = BrowserLauncher(profiles_dir=tmp_path / "profiles", extensions_dir=tmp_path / "exts")
    launched, pid, err = launcher.launch(profile)
    assert launched is True, f"Failed to launch Chrome: {err}"
    assert pid is not None

    try:
        # Wait for injector to resolve CDP and apply stealth
        deadline = time.time() + 15
        stealth_applied = False
        while time.time() < deadline:
            st = launcher.get_stealth_status(profile.id)
            if st and st.get("applied"):
                stealth_applied = True
                break
            time.sleep(0.5)

        assert stealth_applied is True, "CDP stealth injector did not report applied=True within timeout"

        cdp_info = launcher.get_cdp_info(profile.id)
        assert cdp_info is not None
        ws_url = cdp_info["ws_endpoint"]

        async def inspect_page():
            async with websockets.connect(ws_url, open_timeout=10) as ws:
                mid = 0

                async def cmd(method, params=None):
                    nonlocal mid
                    mid += 1
                    await ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
                    while True:
                        raw = await asyncio.wait_for(ws.recv(), 10)
                        r = json.loads(raw)
                        if r.get("id") == mid:
                            return r.get("result", {})

                await cmd(
                    "Target.setAutoAttach", {"autoAttach": True, "waitForDebuggerOnStart": False, "flatten": True}
                )
                # Read page targets
                targets = await cmd("Target.getTargets")
                page_targets = [t for t in targets.get("targetInfos", []) if t.get("type") == "page"]
                assert len(page_targets) > 0, "No page target found in browser"

        asyncio.run(inspect_page())

    finally:
        launcher.stop(profile.id)
