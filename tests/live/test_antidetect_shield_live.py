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
  t('canvas_hash_1', () => { const c=document.createElement('canvas'); c.width=300;c.height=80; const x=c.getContext('2d'); x.textBaseline='top'; x.font='14px Arial'; x.fillStyle='#f60'; x.fillRect(125,1,62,20); x.fillStyle='#069'; x.font='11pt Arial'; x.fillText('probe',2,15); return c.toDataURL(); });
  t('canvas_hash_2', () => { const c=document.createElement('canvas'); c.width=300;c.height=80; const x=c.getContext('2d'); x.textBaseline='top'; x.font='14px Arial'; x.fillStyle='#f60'; x.fillRect(125,1,62,20); x.fillStyle='#069'; x.font='11pt Arial'; x.fillText('probe',2,15); return c.toDataURL(); });
  t('measure_1', () => { const c=document.createElement('canvas').getContext('2d'); c.font='16px Arial'; return c.measureText('probe').width; });
  t('measure_2', () => { const c=document.createElement('canvas').getContext('2d'); c.font='16px Arial'; return c.measureText('probe').width; });
  t('measure_3', () => { const c=document.createElement('canvas').getContext('2d'); c.font='16px Arial'; return c.measureText('probe').width; });
  t('audio_render', async () => { const ctx=new OfflineAudioContext(1,44100,44100); const o=ctx.createOscillator(); o.connect(ctx.destination); o.start(); const b=await ctx.startRendering(); return 'len=' + b.length + ' ch=' + b.numberOfChannels; });
  t('audio_channelData', async () => { const ctx=new OfflineAudioContext(1,44100,44100); const o=ctx.createOscillator(); o.connect(ctx.destination); o.start(); const b=await ctx.startRendering(); const d=b.getChannelData(0); return 'len=' + d.length; });
  t('voices', () => speechSynthesis.getVoices().length);
  t('voice0', () => { const v = speechSynthesis.getVoices()[0]; return v ? v.name : 'none'; });
  t('plugins', () => navigator.plugins.length);
  t('mimeTypes', () => navigator.mimeTypes.length);
  t('webdriver', () => navigator.webdriver);
  t('cores', () => navigator.hardwareConcurrency);
  t('screen', () => screen.width + 'x' + screen.height);
  t('geometry', () => {
    const s = { w: screen.availWidth, h: screen.availHeight, l: screen.availLeft, t: screen.availTop };
    const w = { x: window.screenX, y: window.screenY, ow: window.outerWidth, oh: window.outerHeight,
                iw: window.innerWidth, ih: window.innerHeight, dpr: window.devicePixelRatio };
    const bad = [];
    if (w.ow > s.w) bad.push('outerWidth>availWidth');
    if (w.oh > s.h) bad.push('outerHeight>availHeight');
    if (w.iw > w.ow) bad.push('innerWidth>outerWidth');
    if (w.x + w.ow > s.w + s.l) bad.push('off-right');
    if (w.y + w.oh > s.h + s.t) bad.push('off-bottom');
    if (w.dpr <= 0) bad.push('dpr<=0');
    return 'bad=' + (bad.join(',') || 'none') + ' dpr=' + w.dpr +
           ' outer=' + w.ow + 'x' + w.oh + ' avail=' + s.w + 'x' + s.h;
  });
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
        # A-11/A-12: the window geometry must fit inside the spoofed screen and
        # the device pixel ratio must be the profile's (the host's own
        # properties are own instance accessors — a prototype-level override
        # is shadowed and never applies).
        assert "bad=none" in res["geometry"], f"incoherent window geometry: {res['geometry']}"
        dpr_reported = res["geometry"].split("dpr=")[1].split(" ")[0]
        assert float(dpr_reported) == float(fp.device_pixel_ratio), res["geometry"]
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

        # A-04: the same content must hash the SAME on every read (an unstable
        # canvas hash is a one-line automation tell).
        assert res["canvas_hash_1"] == res["canvas_hash_2"], (
            "the canvas hash is not stable for identical content (A-04)"
        )

        # A-05: the audio path must not recurse (it used to raise
        # "RangeError: Maximum call stack size exceeded").
        assert res["audio_render"].startswith("OK"), res["audio_render"]
        assert res["audio_channelData"].startswith("OK"), res["audio_channelData"]

        # A-07: the same string must measure the SAME width on every read (a
        # real browser returns one value; a per-call jitter is a tell).
        assert res["measure_1"] == res["measure_2"] == res["measure_3"], (
            f"the font metric is not stable for identical text (A-07): "
            f"{res['measure_1']} / {res['measure_2']} / {res['measure_3']}"
        )
    finally:
        launcher.stop(profile.id)
