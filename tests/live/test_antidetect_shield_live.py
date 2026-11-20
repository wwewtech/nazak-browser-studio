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
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from nazak.core.browser_launcher import BrowserLauncher, find_chrome_executable
from nazak.core.fingerprint_generator import generate_random_fingerprint
from nazak.models.profile import BrowserProfile, GoogleSettings

pytest.importorskip("playwright")

PROBE = r"""() => {
  const out = {};
  const t = (n, fn) => { try { out[n] = 'OK ' + String(fn()); } catch (e) { out[n] = 'THROWS ' + e.name + ': ' + e.message; } };
  const nativeFunctionShape = (fn) => {
    let constructible = true;
    try { new fn(); } catch (e) { constructible = false; }
    return 'keys=' + Object.getOwnPropertyNames(fn).join(',') +
      ' name=' + fn.name + ' length=' + fn.length +
      ' constructible=' + constructible + ' native=' + /\{\s*\[native code\]\s*\}/.test(String(fn));
  };
  t('intl_dtf_tz', () => Intl.DateTimeFormat().resolvedOptions().timeZone);
  t('intl_dtf_locale', () => Intl.DateTimeFormat().resolvedOptions().locale);
  t('intl_nf_static', () => Intl.NumberFormat.supportedLocalesOf(['en-US']).join(','));
  t('intl_dtf_static', () => Intl.DateTimeFormat.supportedLocalesOf(['en-US']).join(','));
  t('intl_nf_format', () => new Intl.NumberFormat('en-US').format(1234.5));
  t('intl_nf_constructor_shape', () => nativeFunctionShape(Intl.NumberFormat));
  t('intl_dtf_constructor_shape', () => nativeFunctionShape(Intl.DateTimeFormat));
  t('intl_nf_static_shape', () => nativeFunctionShape(Intl.NumberFormat.supportedLocalesOf));
  t('intl_dtf_static_shape', () => nativeFunctionShape(Intl.DateTimeFormat.supportedLocalesOf));
  t('intl_nf_own', () => Object.getOwnPropertyNames(Intl.NumberFormat).join(','));
  t('intl_nf_without_new', () => Intl.NumberFormat('en-US').format(1234.5));
  t('intl_relative', () => new Intl.RelativeTimeFormat('en-US', {numeric:'auto'}).format(-1, 'day'));
  t('toLocaleString', () => (1234.5).toLocaleString());
  t('tz_offset', () => new Date().getTimezoneOffset());
  t('canvas_hash_1', () => { const c=document.createElement('canvas'); c.width=300;c.height=80; const x=c.getContext('2d'); x.textBaseline='top'; x.font='14px Arial'; x.fillStyle='#f60'; x.fillRect(125,1,62,20); x.fillStyle='#069'; x.font='11pt Arial'; x.fillText('probe',2,15); return c.toDataURL(); });
  t('canvas_hash_2', () => { const c=document.createElement('canvas'); c.width=300;c.height=80; const x=c.getContext('2d'); x.textBaseline='top'; x.font='14px Arial'; x.fillStyle='#f60'; x.fillRect(125,1,62,20); x.fillStyle='#069'; x.font='11pt Arial'; x.fillText('probe',2,15); return c.toDataURL(); });
  t('measure_1', () => { const c=document.createElement('canvas').getContext('2d'); c.font='16px Arial'; return c.measureText('probe').width; });
  t('measure_2', () => { const c=document.createElement('canvas').getContext('2d'); c.font='16px Arial'; return c.measureText('probe').width; });
  t('measure_3', () => { const c=document.createElement('canvas').getContext('2d'); c.font='16px Arial'; return c.measureText('probe').width; });
  // A-22: a main canvas and an OffscreenCanvas with the SAME content must
  // produce the SAME pixels (a plain Chrome: 0 differing bytes).
  t('canvas_offscreen_match', () => {
    const draw = (ctx) => { ctx.textBaseline='top'; ctx.font='14px Arial'; ctx.fillStyle='#f60'; ctx.fillRect(125,1,62,20); ctx.fillStyle='#069'; ctx.font='11pt Arial'; ctx.fillText('probe',2,15); };
    const oc = new OffscreenCanvas(300, 80); draw(oc.getContext('2d'));
    const c = document.createElement('canvas'); c.width=300; c.height=80; draw(c.getContext('2d'));
    const a = oc.getContext('2d').getImageData(0,0,300,80).data;
    const b = c.getContext('2d').getImageData(0,0,300,80).data;
    let diff = 0;
    for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) diff++;
    return 'diff=' + diff;
  });
  t('audio_render', async () => { const ctx=new OfflineAudioContext(1,44100,44100); const o=ctx.createOscillator(); o.connect(ctx.destination); o.start(); const b=await ctx.startRendering(); return 'len=' + b.length + ' ch=' + b.numberOfChannels; });
  t('audio_channelData', async () => { const ctx=new OfflineAudioContext(1,44100,44100); const o=ctx.createOscillator(); o.connect(ctx.destination); o.start(); const b=await ctx.startRendering(); const d=b.getChannelData(0); return 'len=' + d.length; });
  t('audio_sample_getter_shape', () => nativeFunctionShape(Object.getOwnPropertyDescriptor(BaseAudioContext.prototype, 'sampleRate').get));
  t('audio_channels_getter_shape', () => nativeFunctionShape(Object.getOwnPropertyDescriptor(AudioBuffer.prototype, 'numberOfChannels').get));
  // A-34: the native pattern — the FIRST read returns [] and the voices
  // arrive asynchronously through the voiceschanged event (the MDN recipe a
  // page follows). The probe therefore attaches the listener first.
  const __voicesArrived = new Promise((resolve) => {
    speechSynthesis.addEventListener('voiceschanged', () => resolve(speechSynthesis.getVoices()), {once: true});
  });
  t('voices_first', () => speechSynthesis.getVoices().length);
  t('voices_event_fired', () => 'pending');
  const __voiceData = (async () => {
    const timer = new Promise((r) => setTimeout(() => r(null), 3000));
    const v = await Promise.race([__voicesArrived, timer]);
    return v;
  })();
  // A-28: the voice objects must have the native shape (no own properties)
  t('voice_shape', () => {
    const v = __voiceData.then ? null : null;
    return 'deferred';
  });
  t('plugins', () => navigator.plugins.length);
  t('mimeTypes', () => navigator.mimeTypes.length);
  t('plugins_shape', () => 'proto=' + Object.getPrototypeOf(navigator.plugins).constructor.name +
    ' own=' + (Object.getOwnPropertyNames(navigator.plugins).join(',') || '(none)') +
    ' item=' + nativeFunctionShape(navigator.plugins.item) +
    ' namedItem=' + nativeFunctionShape(navigator.plugins.namedItem) +
    ' refresh=' + nativeFunctionShape(navigator.plugins.refresh));
  t('plugin0_shape', () => 'proto=' + Object.getPrototypeOf(navigator.plugins[0]).constructor.name +
    ' own=' + (Object.getOwnPropertyNames(navigator.plugins[0]).join(',') || '(none)') +
    ' item=' + nativeFunctionShape(navigator.plugins[0].item));
  t('mimetypes_shape', () => 'proto=' + Object.getPrototypeOf(navigator.mimeTypes).constructor.name +
    ' own=' + (Object.getOwnPropertyNames(navigator.mimeTypes).join(',') || '(none)') +
    ' item=' + nativeFunctionShape(navigator.mimeTypes.item));
  t('mimetype0_shape', () => 'proto=' + Object.getPrototypeOf(navigator.mimeTypes[0]).constructor.name +
    ' own=' + (Object.getOwnPropertyNames(navigator.mimeTypes[0]).join(',') || '(none)'));
  t('plugins_prototype_methods', () => Object.getOwnPropertyNames(PluginArray.prototype).join(','));
  t('plugin_prototype_accessors', () => Object.getOwnPropertyNames(Plugin.prototype).join(','));
  t('mimetype_prototype_accessors', () => Object.getOwnPropertyNames(MimeType.prototype).join(','));
  t('plugins_intermediate_layer', () => Object.getPrototypeOf(navigator.plugins) !== PluginArray.prototype &&
    Object.getPrototypeOf(Object.getPrototypeOf(navigator.plugins)) === PluginArray.prototype);
  t('plugin_identity_consistency', () => navigator.plugins.item(0) === navigator.plugins[0] &&
    navigator.plugins.namedItem('PDF Viewer') === navigator.plugins[0] &&
    navigator.plugins[0].item(1) === navigator.plugins[0]['text/pdf'] &&
    navigator.mimeTypes.item(0) === navigator.mimeTypes['application/pdf'] &&
    navigator.mimeTypes.length === 2 && navigator.mimeTypes[0] !== navigator.mimeTypes[1]);
  t('webdriver', () => navigator.webdriver);
  // A-13: the WORKER scope must be shielded too. The probe below is async
  // (a worker answers through a message event), so it is collected with a
  // separate promise and merged at the end.
  const __workerProbe = (src) => new Promise((resolve) => {
    const w = new Worker(URL.createObjectURL(new Blob([src], {type:'text/javascript'})));
    const tm = setTimeout(() => { try { w.terminate(); } catch (e) {} resolve('TIMEOUT'); }, 4000);
    w.onmessage = (e) => { clearTimeout(tm); try { w.terminate(); } catch (x) {} resolve(String(e.data)); };
    w.onerror = () => { clearTimeout(tm); resolve('ERR'); };
  });
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
  t('webgl_vendor', () => { const c=document.createElement('canvas'); const g=c.getContext('webgl'); if (!g) return 'no-ctx';
      g.getExtension('WEBGL_debug_renderer_info'); return g.getParameter(37445); });
  t('webgl_renderer', () => { const c=document.createElement('canvas'); const g=c.getContext('webgl'); if (!g) return 'no-ctx';
      g.getExtension('WEBGL_debug_renderer_info'); return g.getParameter(37446); });
  // A-17: the aliased ranges are PAIRS and come back as Float32Array
  t('webgl_aliased', () => {
    const c = document.createElement('canvas').getContext('webgl');
    if (!c) return 'no-ctx';
    const p = c.getParameter(33901), l = c.getParameter(33902);
    return 'point=' + (p && p.constructor ? p.constructor.name : typeof p) +
           ' line=' + (l && l.constructor ? l.constructor.name : typeof l) +
           ' lineValues=' + (l ? Array.from(l).join('/') : 'n/a');
  });
  // A-18: the Client Hints platform is the OS NAME, and the uaData object is
  // a real UAData instance.
  t('ch_platform', () => navigator.userAgentData ? navigator.userAgentData.platform : 'none');
  t('ch_proto', () => navigator.userAgentData ? Object.getOwnPropertyNames(Object.getPrototypeOf(navigator.userAgentData)).join(',') : 'none');
  // A-54: a real NavigatorUAData instance has no own properties. Values and
  // methods are Web IDL accessors/functions on its prototype chain.
  t('ch_own_props', () => Object.getOwnPropertyNames(navigator.userAgentData).join(',') || '(none)');
  t('ch_layer_descriptors', () => {
    const layer = Object.getPrototypeOf(navigator.userAgentData);
    return ['brands', 'mobile', 'platform', 'getHighEntropyValues', 'toJSON'].map((name) => {
      const descriptor = Object.getOwnPropertyDescriptor(layer, name);
      return name + '=' + (descriptor ? (descriptor.get ? 'getter' : typeof descriptor.value) : 'missing');
    }).join(',');
  });
  t('ch_native_proto_chain', () => {
    let current = navigator.userAgentData;
    while (current) {
      if (current === NavigatorUAData.prototype) return true;
      current = Object.getPrototypeOf(current);
    }
    return false;
  });
  // A-46: a hand-written function only LOOKS native through String(fn).  It
  // still has an own prototype and can be constructed; native Web API methods
  // have neither property.  Proxy-over-native keeps the original shape.
  t('ch_high_entropy_shape', () => nativeFunctionShape(navigator.userAgentData.getHighEntropyValues));
  t('ch_tojson_shape', () => nativeFunctionShape(navigator.userAgentData.toJSON));
  t('performance_now_shape', () => nativeFunctionShape(performance.now));
  t('performance_now_owner', () => Object.prototype.hasOwnProperty.call(performance, 'now') +
    '/' + (Performance.prototype.now === performance.now));
  t('performance_now_monotonic', () => {
    let monotonic = true;
    let previous = performance.now();
    for (let i = 0; i < 1000; i++) {
      const current = performance.now();
      if (current < previous) monotonic = false;
      previous = current;
    }
    return monotonic;
  });
  t('ch_tojson_bad_receiver', () => {
    try {
      navigator.userAgentData.toJSON.call({});
      return 'NO ERROR';
    } catch (error) {
      return error.name + ': ' + error.message;
    }
  });
  // A-24: the UNMASKED_* parameters answer null until the extension is
  // requested (the native semantics), on BOTH the WebGL1 and WebGL2 context.
  t('webgl_unmasked_before', () => {
    const c1 = document.createElement('canvas'); const g1 = c1.getContext('webgl');
    const c2 = document.createElement('canvas'); const g2 = c2.getContext('webgl2');
    if (!g1 || !g2) return 'no-ctx';
    return 'webgl1=' + String(g1.getParameter(37445)) + ' webgl2=' + String(g2.getParameter(37445));
  });
  t('webgl_unmasked_after', () => {
    const c1 = document.createElement('canvas'); const g1 = c1.getContext('webgl');
    const c2 = document.createElement('canvas'); const g2 = c2.getContext('webgl2');
    if (!g1 || !g2) return 'no-ctx';
    g1.getExtension('WEBGL_debug_renderer_info');
    g2.getExtension('WEBGL_debug_renderer_info');
    return 'webgl1=' + String(g1.getParameter(37445)) + ' webgl2=' + String(g2.getParameter(37445));
  });
  t('webgl_ext_shape', () => {
    const c1 = document.createElement('canvas'); const g1 = c1.getContext('webgl');
    const ext = g1.getExtension('WEBGL_debug_renderer_info');
    return ext ? ('getParameter=' + typeof ext.getParameter) : 'no-ext';
  });
  // A-14/A-15: the shield must leave NO trace of its own on the globals.
  // A-44: stack hooks must not leak global state or change V8's custom
  // prepareStackTrace result type.  The frame list is compared with a plain
  // Chrome control in the audit; here it must be a CallSite[] without traps.
  t('stack_limit_initial', () => Error.stackTraceLimit);
  t('stack_limit_getter_delta', () => {
    const before = Error.stackTraceLimit;
    void navigator.hardwareConcurrency;
    return Error.stackTraceLimit - before;
  });
  t('stack_limit_error_delta', () => {
    const before = Error.stackTraceLimit;
    try { Function.prototype.toString.call(null); } catch (e) {}
    return Error.stackTraceLimit - before;
  });
  t('custom_stack_shape', () => {
    const previous = Error.prepareStackTrace;
    Error.prepareStackTrace = (error, frames) => frames;
    try {
      Function.prototype.toString.call(null);
    } catch (e) {
      return 'array=' + Array.isArray(e.stack) + ' traps=' +
        e.stack.filter((f) => /newHandler|Object\.apply/.test(String(f))).length;
    } finally {
      Error.prepareStackTrace = previous;
    }
  });
  t('nav_own_props', () => Object.getOwnPropertyNames(navigator).join(',') || '(none)');
  t('win_dunder_own', () => Object.getOwnPropertyNames(window).filter(n => /^__/.test(n)).join(',') || '(none)');
  t('win_dunder_keys', () => Object.keys(window).filter(n => /^__/.test(n)).join(',') || '(none)');
  t('md_own_props', () => navigator.mediaDevices ? (Object.getOwnPropertyNames(navigator.mediaDevices).join(',') || '(none)') : 'no-mediaDevices');
  t('speech_own_props', () => window.speechSynthesis ? (Object.getOwnPropertyNames(window.speechSynthesis).join(',') || '(none)') : 'no-speechSynthesis');
  // A-27: the @font-face aliases must not be visible in the FontFaceSet
  t('fontset', () => {
    const faces = [];
    try { document.fonts.forEach((f) => faces.push(f.family)); } catch (e) { faces.push('ERR'); }
    return 'size=' + document.fonts.size + ' faces=' + (faces.join(',') || '(none)');
  });
  // A-51: filtering must preserve the native FontFaceSet methods, not only
  // hide aliases. Plain replacements were constructible and all iterators
  // were misleadingly named "iterator".
  t('fontset_own_methods', () => Object.getOwnPropertyNames(document.fonts).join(',') || '(none)');
  t('fontset_forEach_shape', () => nativeFunctionShape(document.fonts.forEach));
  t('fontset_entries_shape', () => nativeFunctionShape(document.fonts.entries));
  t('fontset_values_shape', () => nativeFunctionShape(document.fonts.values));
  t('fontset_keys_shape', () => nativeFunctionShape(document.fonts.keys));
  t('fontset_size_getter_shape', () => nativeFunctionShape(
    Object.getOwnPropertyDescriptor(Object.getPrototypeOf(document.fonts), 'size').get
  ));
  t('fontset_iterator_shapes', () => ['entries', 'values', 'keys'].map((name) => {
    const iterator = document.fonts[name]();
    return name + ':' + Object.prototype.toString.call(iterator) +
      ' next=' + nativeFunctionShape(iterator.next) +
      ' stableNext=' + (iterator.next === iterator.next) +
      ' iterableSelf=' + (iterator[Symbol.iterator]() === iterator) +
      ' proto=' + Object.getPrototypeOf(iterator).constructor.name;
  }).join(' | '));
  t('fontset_symbol_iterator_identity', () => {
    const symbolMethod = Object.getPrototypeOf(document.fonts)[Symbol.iterator];
    return 'same=' + (symbolMethod === document.fonts.values) +
      ' shape=' + nativeFunctionShape(symbolMethod);
  });
  t('fontset_iterator_for_of', () => {
    let count = 0;
    for (const face of document.fonts) count++;
    return count;
  });
  t('fontset_iterator_receiver', () => {
    const iterator = document.fonts.values();
    try {
      iterator.next.call({});
      return 'NO ERROR';
    } catch (error) {
      return error.name + ': ' + error.message;
    }
  });
  t('fontset_iterator_consistency', () => {
    const values = Array.from(document.fonts.values());
    const keys = Array.from(document.fonts.keys());
    const entries = Array.from(document.fonts.entries());
    let callbacks = 0;
    document.fonts.forEach(() => callbacks++);
    return 'size=' + document.fonts.size + ' values=' + values.length +
      ' keys=' + keys.length + ' entries=' + entries.length + ' callbacks=' + callbacks +
      ' entryPairs=' + entries.every((entry, index) => entry[0] === entry[1] && entry[0] === values[index]) +
      ' faces=' + values.map((face) => face.family).join(',');
  });
  return Promise.all([
    __workerProbe('self.postMessage(String(navigator.hardwareConcurrency));'),
    __workerProbe('self.postMessage(String(navigator.deviceMemory));'),
    __workerProbe('self.postMessage(String(new Date().getTimezoneOffset()));'),
    // A-26: the spoofed objects must have the native shape — the right
    // prototype and NO own properties (the values live on the prototype).
    (typeof navigator.getBattery === 'function'
      ? navigator.getBattery().then((b) => 'proto=' + Object.getPrototypeOf(b).constructor.name +
          ' own=' + (Object.getOwnPropertyNames(b).join(',') || '(none)') +
          ' getter=' + nativeFunctionShape(Object.getOwnPropertyDescriptor(Object.getPrototypeOf(b), 'level').get))
      : Promise.resolve('no-battery-api')),
    (navigator.mediaDevices && navigator.mediaDevices.enumerateDevices
      ? navigator.mediaDevices.enumerateDevices().then((d) => (!d.length ? 'no-devices' :
          'proto=' + Object.getPrototypeOf(d[0]).constructor.name +
          ' own=' + (Object.getOwnPropertyNames(d[0]).join(',') || '(none)')))
      : Promise.resolve('no-mediaDevices')),
    (navigator.gpu && navigator.gpu.requestAdapter
      ? navigator.gpu.requestAdapter().then((a) => (!a || !a.info ? 'no-adapter' :
          'proto=' + Object.getPrototypeOf(a.info).constructor.name +
          ' own=' + (Object.getOwnPropertyNames(a.info).join(',') || '(none)') +
          ' getter=' + nativeFunctionShape(Object.getOwnPropertyDescriptor(Object.getPrototypeOf(a.info), 'vendor').get) +
          ' infoGetter=' + nativeFunctionShape(Object.getOwnPropertyDescriptor(a, 'info').get)))
      : Promise.resolve('no-gpu')),
    navigator.userAgentData.getHighEntropyValues([]).then(
      (values) => 'keys=' + Object.keys(values).join(',') + ' json=' + JSON.stringify(values).slice(0, 200),
      (error) => 'ERR ' + error.name + ': ' + error.message
    ),
    navigator.userAgentData.getHighEntropyValues(['architecture']).then(
      (values) => 'keys=' + Object.keys(values).join(',') + ' arch=' + (values.architecture || '-'),
      (error) => 'ERR ' + error.name + ': ' + error.message
    ),
    navigator.userAgentData.getHighEntropyValues.call({}, ['platformVersion']).then(
      () => 'NO ERROR',
      (error) => error.name + ': ' + error.message
    )
  ]).then(async (vals) => {
    out.worker_cores = 'OK ' + vals[0];
    out.worker_dm = 'OK ' + vals[1];
    out.worker_tz = 'OK ' + vals[2];
    out.battery_shape = 'OK ' + vals[3];
    out.mediadev_shape = 'OK ' + vals[4];
    out.gpuinfo_shape = 'OK ' + vals[5];
    out.ch_empty_hints = 'OK ' + vals[6];
    out.ch_arch_hint = 'OK ' + vals[7];
    out.ch_bad_receiver = 'OK ' + vals[8];
    // A-34: the voices arrive through the event (the native pattern)
    const voices = await __voiceData;
    if (voices && voices.length) {
      out.voices = 'OK ' + voices.length;
      out.voice0 = 'OK ' + voices[0].name;
      out.voices_event_fired = 'OK true';
      out.voice_shape = 'OK proto=' + Object.getPrototypeOf(voices[0]).constructor.name +
        ' own=' + (Object.getOwnPropertyNames(voices[0]).join(',') || '(none)') +
        ' getter=' + nativeFunctionShape(Object.getOwnPropertyDescriptor(Object.getPrototypeOf(voices[0]), 'name').get);
    } else {
      out.voices = 'OK 0';
      out.voice0 = 'OK none';
      out.voices_event_fired = 'OK false';
      out.voice_shape = 'OK no-voices-yet';
    }
    return out;
  });
}"""


@pytest.mark.live
def test_generated_shield_applies_and_never_throws(tmp_path):
    from playwright.async_api import async_playwright

    if not find_chrome_executable():
        pytest.skip("Chrome/Chromium executable not found on host")

    fp = generate_random_fingerprint("windows")
    # Guarantee at least one local-font alias on every host so the A-51
    # FontFaceSet filtering hooks are exercised rather than silently skipped.
    fp.fonts = [*list(fp.fonts), "Nazak Audit Missing Font 51"]
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

        # UA-CH high-entropy values require a secure context.  data: URLs have
        # no userAgentData in plain Chrome, so they cannot validate this hook.
        class AuditPage(BaseHTTPRequestHandler):
            def do_GET(self):
                body = b"<html><body>audit</body></html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), AuditPage)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        audit_url = f"http://127.0.0.1:{server.server_port}/"

        async def probe():
            async with async_playwright() as p:
                browser = await p.chromium.connect_over_cdp(cdp_info["http_endpoint"])
                ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
                page = ctx.pages[0] if ctx.pages else await ctx.new_page()
                await page.goto(audit_url)
                await page.wait_for_timeout(1200)
                res = await page.evaluate(PROBE)
                await browser.close()
                return res

        try:
            res = asyncio.run(probe())
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=2)
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
        assert res["languages"].endswith(",".join(fp.languages)), res["languages"]
        assert res["webgl_vendor"].endswith(fp.webgl_vendor), res["webgl_vendor"]
        assert res["webgl_renderer"].endswith(fp.webgl_renderer), res["webgl_renderer"]
        assert res["webdriver"].endswith("false"), res["webdriver"]
        assert res["plugins"].endswith("5"), res["plugins"]
        assert res["mimeTypes"].endswith("2"), res["mimeTypes"]

        # A-34: the FIRST read must return [] (the native pattern — the
        # voices load asynchronously and the page listens for the event).
        assert res["voices_first"].endswith("0"), (
            f"the first getVoices() must be empty like a real browser (A-34): {res['voices_first']}"
        )
        # A-03: the voice pool must arrive through the event and be the
        # PROFILE's (8..12 on Windows), not the host's (21 on the audit machine).
        voices = int(res["voices"].split()[-1])
        assert 8 <= voices <= 12, f"the host's voice pool leaked through: {voices} voices"
        assert res["voices_event_fired"].endswith("true"), (
            f"the voiceschanged event must fire like a real browser (A-34): {res['voices_event_fired']}"
        )
        assert "Microsoft" in res["voice0"] or "Google" in res["voice0"], res["voice0"]
        # A-28: the voice objects must carry NO own properties (the native
        # SpeechSynthesisVoice keeps its values on the prototype).
        if res["voice_shape"] not in ("OK no-voices-yet", "OK deferred"):
            assert "proto=SpeechSynthesisVoice" in res["voice_shape"], res["voice_shape"]
            assert "own=(none)" in res["voice_shape"], res["voice_shape"]
            assert "constructible=true" not in res["voice_shape"], (
                f"the voice objects carry own properties (A-28): {res['voice_shape']}"
            )

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

        # A-22: the main canvas and the OffscreenCanvas must agree
        assert res["canvas_offscreen_match"].endswith("diff=0"), (
            f"the main and offscreen canvases render different images for the same "
            f"content (A-22): {res['canvas_offscreen_match']}"
        )

        # A-13: the WORKER scope must be shielded too — a page reads the real
        # navigator values there with a three-line probe.
        assert res["worker_cores"].endswith(str(fp.hardware_concurrency)), (
            f"the worker scope leaks the host's hardwareConcurrency (A-13): {res['worker_cores']}"
        )
        # navigator.deviceMemory only ever exposes 0.25/0.5/1/2/4/8 (the API
        # quantises it), so the shield reports the quantised profile value.
        from nazak.core.extension_generator import _quantized_device_memory

        expected_dm = _quantized_device_memory(fp.device_memory)
        assert res["worker_dm"].endswith(str(expected_dm)), (
            f"the worker scope leaks the host's deviceMemory (A-13): {res['worker_dm']} (expected {expected_dm})"
        )
        assert res["worker_tz"].endswith(str(fp.timezone_offset)), (
            f"the worker scope leaks the host's timezone offset (A-13): {res['worker_tz']}"
        )

        # A-44: the trap's deeper capture must be invisible to the page, and
        # custom stack formatting must keep its native CallSite[] type.
        assert res["stack_limit_initial"].endswith("10"), res["stack_limit_initial"]
        assert res["stack_limit_getter_delta"].endswith("0"), res["stack_limit_getter_delta"]
        assert res["stack_limit_error_delta"].endswith("0"), res["stack_limit_error_delta"]
        assert res["custom_stack_shape"].endswith("array=true traps=0"), res["custom_stack_shape"]

        # A-14/A-15: the shield must not leave own properties on the globals —
        # a real Chrome's navigator / mediaDevices / speechSynthesis instances
        # carry none, and the window carries no "__" properties of ours.
        assert res["nav_own_props"].endswith("(none)"), (
            f"the shield added own properties to the navigator instance (A-14): {res['nav_own_props']}"
        )
        assert res["md_own_props"].endswith("(none)") or res["md_own_props"].endswith("no-mediaDevices"), (
            f"the shield added own properties to navigator.mediaDevices (A-14): {res['md_own_props']}"
        )
        assert res["speech_own_props"].endswith("(none)") or res["speech_own_props"].endswith("no-speechSynthesis"), (
            f"the shield added own properties to window.speechSynthesis (A-14): {res['speech_own_props']}"
        )

        # A-26: the spoofed objects must have the native shape — the right
        # prototype class and NO own properties.
        if res["battery_shape"] != "OK no-battery-api":
            assert res["battery_shape"].startswith("OK proto=BatteryManager"), res["battery_shape"]
            assert "own=(none)" in res["battery_shape"], res["battery_shape"]
        if res["mediadev_shape"] != "OK no-mediaDevices":
            assert res["mediadev_shape"].startswith("OK proto=InputDeviceInfo"), res["mediadev_shape"]
            assert res["mediadev_shape"].endswith("own=(none)"), res["mediadev_shape"]
        if res["gpuinfo_shape"] != "OK no-gpu":
            assert res["gpuinfo_shape"].startswith("OK proto=GPUAdapterInfo"), res["gpuinfo_shape"]
            assert "own=(none)" in res["gpuinfo_shape"], res["gpuinfo_shape"]

        # A-27: the font aliases must not be visible in the FontFaceSet
        assert "size=0" in res["fontset"], f"the font aliases are visible (A-27): {res['fontset']}"
        assert "faces=(none)" in res["fontset"], f"the font aliases are visible (A-27): {res['fontset']}"
        assert res["win_dunder_own"].endswith("(none)"), (
            f"the shield left its own properties on the window (A-15): {res['win_dunder_own']}"
        )
        assert res["win_dunder_keys"].endswith("(none)"), (
            f"the shield left enumerable own properties on the window (A-15): {res['win_dunder_keys']}"
        )

        # A-17: the WebGL aliased ranges must come back as Float32Array pairs
        # (the host's shape) — a scalar there exposes the patch.
        assert "point=Float32Array" in res["webgl_aliased"], res["webgl_aliased"]
        assert "line=Float32Array" in res["webgl_aliased"], res["webgl_aliased"]

        # A-18: the Client Hints platform is the OS name, and the uaData object
        # carries the real UAData prototype members.
        expected_ch = "Windows" if "Win" in fp.platform else ("macOS" if "Mac" in fp.platform else "Linux")
        assert res["ch_platform"].endswith(expected_ch), (
            f"the Client Hints platform must be the OS name (A-18): {res['ch_platform']}"
        )
        assert "getHighEntropyValues" in res["ch_proto"], (
            f"the userAgentData object must be a real UAData instance (A-18): {res['ch_proto']}"
        )

        # A-48: the generated Plugin layer must actually install (the old
        # strict-mode assignment threw and silently exposed the host objects).
        assert res["plugins_intermediate_layer"].endswith("true"), res["plugins_intermediate_layer"]
        assert res["plugin_identity_consistency"].endswith("true"), res["plugin_identity_consistency"]
        assert res["mimetype0_shape"].endswith("own=(none)"), res["mimetype0_shape"]
        for key in ("plugins_shape", "plugin0_shape", "mimetypes_shape"):
            assert "keys=length,name,prototype" not in res[key], res[key]
            assert "constructible=true" not in res[key], res[key]

        for shape_key in ("battery_shape", "voice_shape", "gpuinfo_shape"):
            if "no-" not in res[shape_key]:
                assert "constructible=true" not in res[shape_key], res[shape_key]
                assert "keys=length,name,prototype" not in res[shape_key], res[shape_key]

        # A-49: Intl constructors are constructible (unlike Web API methods),
        # but their static supportedLocalesOf methods and audio getters are
        # not.  Bound/plain stand-ins must not expose an extra prototype.
        for shape_key, expected_name, expected_length, constructible in (
            ("intl_nf_constructor_shape", "NumberFormat", 0, "true"),
            ("intl_dtf_constructor_shape", "DateTimeFormat", 0, "true"),
        ):
            assert res[shape_key].startswith("OK keys=length,name,prototype,supportedLocalesOf "), res[shape_key]
            assert (
                f"name={expected_name} length={expected_length} constructible={constructible} native=true"
                in res[shape_key]
            ), f"non-native Intl constructor shape (A-49): {res[shape_key]}"
        for shape_key, expected_name, expected_length in (
            ("intl_nf_static_shape", "supportedLocalesOf", 1),
            ("intl_dtf_static_shape", "supportedLocalesOf", 1),
            ("audio_sample_getter_shape", "get sampleRate", 0),
            ("audio_channels_getter_shape", "get numberOfChannels", 0),
        ):
            assert res[shape_key].startswith("OK keys=length,name "), res[shape_key]
            assert f"name={expected_name} length={expected_length} constructible=false native=true" in res[shape_key], (
                f"non-native Intl/audio function shape (A-49): {res[shape_key]}"
            )

        assert res["ch_empty_hints"].startswith("OK keys= json={}"), res["ch_empty_hints"]
        assert res["ch_arch_hint"].startswith("OK keys=architecture arch="), res["ch_arch_hint"]
        assert res["ch_bad_receiver"].startswith("OK TypeError:"), res["ch_bad_receiver"]
        assert res["ch_tojson_bad_receiver"].startswith("OK TypeError:"), res["ch_tojson_bad_receiver"]
        assert res["performance_now_owner"].endswith("false/true"), res["performance_now_owner"]
        assert res["performance_now_monotonic"].endswith("true"), res["performance_now_monotonic"]
        assert res["intl_nf_own"].endswith("length,name,prototype,supportedLocalesOf"), res["intl_nf_own"]
        assert res["intl_nf_without_new"].startswith("OK"), res["intl_nf_without_new"]

        # A-53: the filtering method must return the browser's FontFaceSet
        # iterator, not an eagerly materialized Array Iterator.
        assert res["fontset_iterator_shapes"].count("[object FontFaceSet Iterator]") == 3, res[
            "fontset_iterator_shapes"
        ]
        assert "Array Iterator" not in res["fontset_iterator_shapes"], res["fontset_iterator_shapes"]
        assert res["fontset_iterator_shapes"].count("stableNext=true") == 3, res["fontset_iterator_shapes"]
        assert res["fontset_iterator_shapes"].count("iterableSelf=true") == 3, res["fontset_iterator_shapes"]
        assert res["fontset_iterator_receiver"].startswith("OK TypeError:"), res["fontset_iterator_receiver"]
        assert res["fontset_iterator_for_of"].endswith("0"), res["fontset_iterator_for_of"]
        assert res["fontset_symbol_iterator_identity"].startswith("OK same=true"), res[
            "fontset_symbol_iterator_identity"
        ]
        assert "constructible=false native=true" in res["fontset_symbol_iterator_identity"], res[
            "fontset_symbol_iterator_identity"
        ]

        # A-51: FontFaceSet filtering must not replace native methods with
        # constructible/generically-named JavaScript functions.
        for shape_key, expected_name in (
            ("fontset_forEach_shape", "forEach"),
            ("fontset_entries_shape", "entries"),
            ("fontset_values_shape", "values"),
            ("fontset_keys_shape", "keys"),
            ("fontset_size_getter_shape", "get size"),
        ):
            assert res[shape_key].startswith("OK keys=length,name "), res[shape_key]
            assert f"name={expected_name}" in res[shape_key], res[shape_key]
            assert "constructible=false native=true" in res[shape_key], res[shape_key]
        assert res["fontset_own_methods"].endswith("(none)"), res["fontset_own_methods"]
        assert "entryPairs=true" in res["fontset_iterator_consistency"], res["fontset_iterator_consistency"]
        assert "size=0 values=0 keys=0 entries=0 callbacks=0" in res["fontset_iterator_consistency"], res[
            "fontset_iterator_consistency"
        ]

        # A-54: UAData itself must not carry five synthetic own data/method
        # properties. Its native interface prototype remains in the chain.
        assert res["ch_own_props"].endswith("(none)"), res["ch_own_props"]
        assert res["ch_layer_descriptors"].endswith(
            "brands=getter,mobile=getter,platform=getter,getHighEntropyValues=function,toJSON=function"
        ), res["ch_layer_descriptors"]
        assert res["ch_native_proto_chain"].endswith("true"), res["ch_native_proto_chain"]

        # A-46: native methods have only length/name own properties and are
        # not constructible.  String(fn) alone is not enough evidence.
        for shape_key, expected_name, expected_length in (
            ("ch_high_entropy_shape", "getHighEntropyValues", 1),
            ("ch_tojson_shape", "toJSON", 0),
            ("performance_now_shape", "now", 0),
        ):
            assert res[shape_key].startswith("OK keys=length,name "), res[shape_key]
            assert f"name={expected_name} length={expected_length} constructible=false native=true" in res[shape_key], (
                f"non-native function shape (A-46): {res[shape_key]}"
            )

        # A-24: the UNMASKED_* parameters follow the native semantics — null
        # before the extension is requested, the profile's vendor after.
        assert res["webgl_unmasked_before"].endswith("webgl1=null webgl2=null"), (
            f"the UNMASKED_* parameters must be null before the extension is requested "
            f"(A-24): {res['webgl_unmasked_before']}"
        )
        assert fp.webgl_vendor in res["webgl_unmasked_after"], (
            f"the UNMASKED_VENDOR must be the profile's after the extension (A-24): {res['webgl_unmasked_after']}"
        )
        assert res["webgl_ext_shape"].endswith("getParameter=undefined"), (
            f"the extension object must keep its native shape (A-24): {res['webgl_ext_shape']}"
        )
    finally:
        launcher.stop(profile.id)
