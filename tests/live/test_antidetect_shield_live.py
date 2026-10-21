"""Live test: the generated stealth shield must apply AND must not break the
page (round 10 anti-detect audit, findings A-01..A-03).

The audit found that several shield sections were installed but THREW at
runtime:

* A-01 — ``Intl.DateTimeFormat().resolvedOptions()`` raised
  "ReferenceError: targetTimezone is not defined" (the constant was declared
  inside another section's try-block), so EVERY Intl call on the page broke;
* A-02 — ``Intl.NumberFormat.supportedLocalesOf`` was "not a function"
  (the constructor replacement dropped the static side);
* A-03 — the speechSynthesis voice pool was never installed (assigning to the
  getter-only ``SpeechSynthesisVoice.prototype.name`` threw and aborted the
  whole section), so the page kept the HOST's voices.

A broken hook is worse than no hook: the site sees a sabotaged API and a
detector sees the same. This test runs the REAL product path (the product
launches Chrome and injects the shield over CDP) and asserts that every
shielded API answers with the PROFILE's values and never throws.

Requires a real Chrome/Chromium on the host. Skipped by default:
    pytest -m live tests/live/test_antidetect_shield_live.py
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest

from nazak.core.browser_launcher import BrowserLauncher, find_chrome_executable
from nazak.core.fingerprint_generator import generate_random_fingerprint
from nazak.models.profile import BrowserProfile, GoogleSettings

pytest.importorskip("playwright")

PROBE = """() => {
  const out = {};
  const t = (n, fn) => { try { out[n] = 'OK ' + String(fn()); } catch (e) { out[n] = 'THROWS ' + e.name + ': ' + e.message; } };
  t('intl_dtf_tz', () => Intl.DateTimeFormat().resolvedOptions().timeZone);
  t('intl_dtf_locale', () => Intl.DateTimeFormat().resolvedOptions().locale);
  t('intl_nf_static', () => Intl.NumberFormat.supportedLocalesOf(['en-US']).join(','));
  t('intl_dtf_static', () => Intl.DateTimeFormat.supportedLocalesOf(['en-US']).join(','));
  t('intl_nf_format', () => new Intl.NumberFormat('en-US').format(1234.5));
  t('intl_relative', () => new Intl.RelativeTimeFormat('en-US', {numeric:'auto'}).format(-1, 'day'));
  t('toLocaleString', () => (1234.5).toLocaleString());
  t('tz_offset', () => new Date().getTimezoneOffset());
  t('voices', () => speechSynthesis.getVoices().length);
  t('voice0', () => { const v = speechSynthesis.getVoices()[0]; return v ? v.name : 'none'; });
  t('plugins', () => navigator.plugins.length);
  t('mimeTypes', () => navigator.mimeTypes.length);
  t('webdriver', () => navigator.webdriver);
  t('cores', () => navigator.hardwareConcurrency);
  t('screen', () => screen.width + 'x' + screen.height);
  t('languages', () => navigator.languages.join(','));
  t('webgl_vendor', () => { const c=document.createElement('canvas').getContext('webgl'); return c ? c.getParameter(37445) : 'no-ctx'; });
  t('webgl_renderer', () => { const c=document.createElement('canvas').getContext('webgl'); return c ? c.getParameter(37446) : 'no-ctx'; });
  return out;
}"""


@pytest.mark.live
def test_generated_shield_applies_and_never_throws(tmp_path):
    from playwright.async_api import async_playwright

    if not find_chrome_executable():
        pytest.skip("Chrome/Chromium executable not found on host")

    fp = generate_random_fingerprint("windows")
    profile = BrowserProfile(
        id="live_shield_audit",
        name="Live Shield Audit",
        fingerprint=fp,
        google=GoogleSettings(),
    )
    launcher = BrowserLauncher(profiles_dir=tmp_path / "profiles", extensions_dir=tmp_path / "exts")
    launched, pid, err = launcher.launch(profile, cdp_port=9455)
    assert launched is True, f"failed to launch Chrome: {err}"

    try:
        deadline = time.time() + 20
        applied = False
        while time.time() < deadline:
            st = launcher.get_stealth_status(profile.id)
            if st and st.get("applied"):
                applied = True
                break
            time.sleep(0.5)
        assert applied is True, "the CDP stealth injector never reported applied=True"

        cdp_info = launcher.get_cdp_info(profile.id)
        assert cdp_info is not None

        async def probe():
            async with async_playwright() as p:
                browser = await p.chromium.connect_over_cdp(cdp_info["http_endpoint"])
                ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
                page = ctx.pages[0] if ctx.pages else await ctx.new_page()
                await page.goto("data:text/html,<html><body>audit</body></html>")
                await page.wait_for_timeout(1200)
                res = await page.evaluate(PROBE)
                await browser.close()
                return res

        res = asyncio.run(probe())

        broken = {k: v for k, v in res.items() if v.startswith("THROWS")}
        assert not broken, f"shielded APIs throw at runtime (a broken hook is worse than no hook): {broken}"

        # the shield must report the PROFILE's values, not the host's
        assert res["cores"].endswith(str(fp.hardware_concurrency)), res["cores"]
        assert res["screen"].endswith(f"{fp.screen_width}x{fp.screen_height}"), res["screen"]
        assert res["tz_offset"].endswith(str(fp.timezone_offset)), res["tz_offset"]
        assert res["intl_dtf_tz"].endswith(fp.timezone), res["intl_dtf_tz"]
        assert res["languages"].endswith(",".join(fp.languages[:2])), res["languages"]
        assert res["webgl_vendor"].endswith(fp.webgl_vendor), res["webgl_vendor"]
        assert res["webgl_renderer"].endswith(fp.webgl_renderer), res["webgl_renderer"]
        assert res["webdriver"].endswith("false"), res["webdriver"]
        assert res["plugins"].endswith("5"), res["plugins"]
        assert res["mimeTypes"].endswith("2"), res["mimeTypes"]

        # A-03: the voice pool must be the PROFILE's (8..12 on Windows), not
        # the host's (21 on the audit machine) — and every voice must carry a
        # name (the getter-only prototype broke the old construction).
        voices = int(res["voices"].split()[-1])
        assert 8 <= voices <= 12, f"the host's voice pool leaked through: {voices} voices"
        assert "Microsoft" in res["voice0"] or "Google" in res["voice0"], res["voice0"]
    finally:
        launcher.stop(profile.id)
