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
from nazak.core.synchronizer import SynchronizerManager, dispose_sync_client_js, sync_client_js
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

        # 1. A real DOM gesture must travel through the real CDP binding.
        #    Repeat install must not duplicate listeners; dispose must remove
        #    them and the fixed window.__nse_c guard must never exist (A-45).
        async def _client_lifecycle():
            from playwright.async_api import async_playwright

            cdp = bl.get_cdp_info(master.id)
            async with async_playwright() as p:
                browser = await p.chromium.connect_over_cdp(cdp["http_endpoint"])
                page = browser.contexts[0].pages[0]
                binding_name = session.sync_binding_name
                await page.wait_for_function(
                    "(name) => typeof window[name] === 'function'", arg=binding_name, timeout=5000
                )
                client = sync_client_js(binding_name, session.sync_guard_key)
                dispose = dispose_sync_client_js(binding_name, session.sync_guard_key)
                injector = bl._injectors[master.id].injector
                before = injector.binding_events_accepted
                dispatch = "() => document.dispatchEvent(new MouseEvent('click', {bubbles:true}))"

                async def accepted(expected):
                    deadline = time.time() + 3
                    while time.time() < deadline:
                        await asyncio.sleep(0.05)
                        if injector.binding_events_accepted - before >= expected:
                            return injector.binding_events_accepted - before
                    return injector.binding_events_accepted - before

                await page.evaluate(client)
                await page.evaluate(dispatch)
                assert await accepted(1) == 1
                await page.evaluate(client)
                await page.evaluate(dispatch)
                assert await accepted(2) == 2
                assert await page.evaluate("() => Object.hasOwn(window,'__nse_c')") is False

                await page.evaluate(dispose)
                await page.evaluate(dispatch)
                await page.wait_for_timeout(200)
                assert injector.binding_events_accepted - before == 2
                await page.evaluate(client)
                await page.evaluate(dispatch)
                assert await accepted(3) == 3
                await page.evaluate(dispose)
                await browser.close()
                return injector.binding_events_accepted - before

        delivered = asyncio.run(_client_lifecycle())
        assert delivered == 3, f"real DOM gestures did not reach the synchronizer: {delivered}"

        # 2. Real navigation mirror and automatic client restoration in the
        # new master document (A-47).
        async def _nav():
            return await mgr.mirror_navigation("https://example.com")

        outcomes = asyncio.run(_nav())
        assert outcomes.get("sync_live_worker") is True

        async def _master_after_navigation():
            from playwright.async_api import async_playwright

            cdp = bl.get_cdp_info(master.id)
            async with async_playwright() as p:
                browser = await p.chromium.connect_over_cdp(cdp["http_endpoint"])
                page = browser.contexts[0].pages[0]
                await page.goto("https://example.com")
                await page.wait_for_timeout(1000)
                injector = bl._injectors[master.id].injector
                before = injector.binding_events_accepted
                await page.evaluate("() => document.dispatchEvent(new MouseEvent('click', {bubbles:true}))")
                deadline = time.time() + 3
                while time.time() < deadline and injector.binding_events_accepted == before:
                    await asyncio.sleep(0.05)
                delivered = injector.binding_events_accepted - before
                await browser.close()
                return delivered

        assert asyncio.run(_master_after_navigation()) == 1

    finally:
        mgr.stop_session()
        bl.stop("sync_live_master")
        bl.stop("sync_live_worker")
