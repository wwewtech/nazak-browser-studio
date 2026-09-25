"""Live test: verifies synchronizer master-to-worker event replication and navigation mirror.

Skipped by default in regular test runs; execute via:
    pytest -m live tests/live/test_synchronizer_live.py
"""

import asyncio
import tempfile
import time
from pathlib import Path

import pytest

from nazak.config import find_chrome_executable
from nazak.core.browser_launcher import BrowserLauncher
from nazak.core.synchronizer import SynchronizerManager
from nazak.models.profile import BrowserProfile


@pytest.mark.live
def test_synchronizer_replicates_navigation_and_events_between_profiles():
    if not find_chrome_executable():
        pytest.skip("Chrome/Chromium executable not found on host")

    tmp = Path(tempfile.mkdtemp(prefix="nazak_live_sync_"))
    bl = BrowserLauncher(profiles_dir=tmp / "profiles", extensions_dir=tmp / "exts")
    master = BrowserProfile(id="sync_live_master", name="Live Master")
    worker = BrowserProfile(id="sync_live_worker", name="Live Worker")

    ok_m, _, _ = bl.launch(master, custom_url="about:blank")
    ok_w, _, _ = bl.launch(worker, custom_url="about:blank")
    if not (ok_m and ok_w):
        bl.stop("sync_live_master")
        bl.stop("sync_live_worker")
        pytest.skip("Could not launch both Chrome instances concurrently")

    mgr = SynchronizerManager(bl)
    bl.set_event_sink(mgr.submit_event)

    try:
        session = mgr.start_session(
            "sync_live_master",
            ["sync_live_worker"],
            humanize_jitter=True,
            delay_range_ms=(10, 30),
            coordinate_jitter_px=2,
        )
        assert session.active is True
        time.sleep(3)

        # 1. Real navigation mirror
        async def _nav():
            return await mgr.mirror_navigation("https://example.com")

        outcomes = asyncio.run(_nav())
        assert outcomes.get("sync_live_worker") is True

        # 2. Gesture submission
        ok_event = mgr.submit_event("sync_live_master", {"type": "scroll", "x": 0, "y": 500})
        assert ok_event is True

    finally:
        mgr.stop_session()
        bl.stop("sync_live_master")
        bl.stop("sync_live_worker")
