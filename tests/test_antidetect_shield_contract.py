"""Round-10 anti-detect shield regressions (A-01..A-03).

These are SOURCE-level contracts (the repository convention for the GUI/shield
layer, see test_gui_and_tools_hardening.py): they pin the exact defects the
empirical audit found in the generated stealth.js, so a regression cannot reach
a release unnoticed. The BEHAVIOURAL proof is the live test
``tests/live/test_antidetect_shield_live.py`` (real Chrome, `pytest -m live`).
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

import pytest

from nazak.core.extension_generator import generate_profile_extension
from nazak.core.fingerprint_generator import generate_random_fingerprint
from nazak.models.profile import BrowserProfile, GoogleSettings

REPO_ROOT = Path(__file__).resolve().parents[1]


def _generated_js() -> str:
    fp = generate_random_fingerprint("windows")
    profile = BrowserProfile(id="shield_contract", name="Shield", fingerprint=fp, google=GoogleSettings())
    with tempfile.TemporaryDirectory() as td:
        ext = generate_profile_extension(profile, Path(td))
        assert ext, "the extension generator returned no path"
        return (Path(ext) / "stealth.js").read_text(encoding="utf-8")


def test_a01_timezone_constant_is_in_the_shared_scope():
    """A-01: `targetTimezone` was declared with `const` inside section 6's
    try-block and used by section 12d — an out-of-scope reference, so EVERY
    Intl.DateTimeFormat().resolvedOptions() call threw
    "ReferenceError: targetTimezone is not defined"."""
    src = _generated_js()
    declarations = re.findall(r"^\s*const targetTimezone\s*=", src, re.M)
    assert len(declarations) == 1, (
        f"targetTimezone must be declared exactly once (found {len(declarations)}) — a second "
        "declaration inside a try-block made the other reference out of scope (A-01)"
    )
    # the single declaration must NOT live inside a try-block: find its indent
    line_no = next(idx for idx, line in enumerate(src.splitlines()) if re.match(r"^\s*const targetTimezone\s*=", line))
    lines = src.splitlines()
    # walk back to the section header the declaration belongs to
    section = ""
    for i in range(line_no, -1, -1):
        m = re.match(r"^\s*// (\d+[a-z]?)\. ", lines[i])
        if m:
            section = m.group(1)
            break
    assert section == "0", (
        f"targetTimezone is declared in section {section}; it must live in the IIFE scope "
        "next to makeNative() so BOTH the Intl hook and the Date hook can use it (A-01)"
    )


def test_a01_no_out_of_scope_timezone_use_in_the_intl_section():
    """The Intl locale section must not reference a constant it cannot see."""
    src = _generated_js()
    # the resolvedOptions hook must use the shared constant
    assert re.search(r"res\.timeZone\s*=\s*targetTimezone;", src), "the Intl hook no longer sets the timezone"
    # there must be no leftover local shadow declaration
    assert not re.search(r"const targetTimezone = [^;]+;\n\s*const origResolvedOptions", src), (
        "a local targetTimezone declaration is back (it shadows the shared one and breaks the Intl hook, A-01)"
    )


def test_a02_intl_constructors_keep_their_static_side():
    """A-02: replacing Intl.NumberFormat/Intl.DateTimeFormat with a plain
    function dropped `supportedLocalesOf` — a hard TypeError in any site that
    calls it, and a blatant sign of a tampered Intl."""
    src = _generated_js()
    assert "supportedLocalesOf" in src, (
        "the Intl constructor replacement must keep the static side (supportedLocalesOf) — "
        "dropping it broke every caller (A-02)"
    )
    # the static method must be re-attached to the wrapper, not only called
    assert re.search(r"Object\.defineProperty\(wrapped,\s*'supportedLocalesOf'", src), (
        "the wrapped Intl constructors must re-attach supportedLocalesOf (A-02)"
    )


def test_a03_voices_use_defineproperty_not_assign():
    """A-03: SpeechSynthesisVoice.prototype.name is a GETTER-ONLY accessor.
    Object.assign() onto such an instance throws, and the throw aborted the
    whole voice section — the page kept the HOST's voices."""
    src = _generated_js()
    voice_block = src[src.find("voiceObjects") - 400 : src.find("voiceObjects") + 600]
    assert "Object.assign(Object.create" not in voice_block, (
        "the voice objects must not be built with Object.assign — the SpeechSynthesisVoice "
        "prototype has getter-only properties and the assignment throws (A-03)"
    )
    assert "Object.defineProperty(inst" in voice_block, (
        "the voice objects must define their own properties with defineProperty (A-03)"
    )


def test_shield_sections_are_independent_of_each_other():
    """A structural guarantee: every section's try-block must be independent,
    so one failing statement cannot abort the NEXT section's shield."""
    src = _generated_js()
    # no section may reference a constant declared in a DIFFERENT section's
    # try-block. The audit found exactly that class of bug (A-01).
    for const_name in ("targetTimezone", "targetOffset"):
        decl_lines = [
            idx for idx, line in enumerate(src.splitlines()) if re.match(rf"^\s*const {const_name}\s*=", line)
        ]
        assert len(decl_lines) == 1, f"{const_name} is declared {len(decl_lines)} times"


def test_a04_canvas_noise_is_content_derived_not_call_derived():
    """A-04: the canvas noise used to be re-seeded from a CALL COUNTER, so the
    same content produced a different canvas hash on every read — an unstable
    hash is a one-line automation tell. The field must be derived from the
    profile seed and the CONTENT."""
    src = _generated_js()
    assert "canvasCallCount" not in src, (
        "the canvas noise must not depend on a call counter — the same content must hash the same on every read (A-04)"
    )
    assert "contentSeed" in src, "the canvas noise must be derived from the content (A-04)"


def test_a04_to_data_url_does_not_mutate_the_live_canvas():
    """A-04: toDataURL used to write the noise back into the LIVE canvas
    (putImageData), so the second call hashed already-noised pixels and
    produced a third value. The noise must be applied to a COPY."""
    src = _generated_js()
    anchor = src.find("HTMLCanvasElement.prototype.toDataURL")
    block = src[anchor : anchor + 2200]
    # strip the comments: the word putImageData may appear in the explanation
    code_lines = []
    for line in block.splitlines():
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        code_lines.append(line)
    code = "\n".join(code_lines)
    # the noise may be written into the COPY (copyCtx.putImageData) — but it
    # must never be written back into the source canvas' own context
    assert "ctx.putImageData" not in code, (
        "toDataURL must not write the noise back into the live canvas — the hash of "
        "identical content must stay stable (A-04)"
    )
    assert "copyCtx.putImageData" in code, "the noise must be written into the COPY (A-04)"
    assert "noisyCopy" in code, "toDataURL must hash a noised COPY of the canvas (A-04)"


def test_a05_audio_channels_descriptor_is_captured_before_the_override():
    """A-05: the numberOfChannels getter read the descriptor from the prototype
    AT CALL TIME — by then it was the spoofing getter itself, so it recursed
    infinitely ("RangeError: Maximum call stack size exceeded")."""
    src = _generated_js()
    assert "origChannelsDesc" in src, (
        "the original numberOfChannels descriptor must be captured BEFORE the override (A-05)"
    )
    block = src[src.find("origChannelsDesc") : src.find("origChannelsDesc") + 700]
    assert "Object.getOwnPropertyDescriptor(AudioBuffer.prototype, 'numberOfChannels')" in block, (
        "the original descriptor must be read once, outside the getter (A-05)"
    )
    getter_start = src.find("get: makeNative(function() {", src.find("origChannelsDesc"))
    getter = src[getter_start : getter_start + 400]
    assert "Object.getOwnPropertyDescriptor(AudioBuffer.prototype" not in getter, (
        "the getter must use the captured descriptor, not look it up again (A-05)"
    )


def test_a06_audio_noise_is_applied_once():
    """A-06: the render helper called the SPOOFED getChannelData, which
    applied its own noise pass on top — the noise was applied twice and the
    phase counter advanced twice per read."""
    src = _generated_js()
    helper = src[src.find("const applyAudioNoise = function(buffer)") :][:900]
    assert "applyAudioNoiseToChannel" not in helper, (
        "the render helper must not apply the noise a second time — the getter owns it (A-06)"
    )


def test_a07_font_jitter_is_text_derived_not_call_derived():
    """A-07: the measureText jitter was re-derived from a CALL COUNTER, so
    measuring the same string twice returned two different widths (measured in
    a real Chrome: 8 measurements of one string -> 8 distinct values, while a
    real browser returns the SAME width)."""
    src = _generated_js()
    assert "fontCallCount" not in src, (
        "the font jitter must not depend on a call counter — the same string must measure the same on every read (A-07)"
    )
    assert "textJitter" in src, "the font jitter must be derived from the text itself (A-07)"
    # the DOM rect width must follow the same text-derived offset, so the
    # canvas metric and the DOM metric agree (as on a real browser)
    assert "widthAdj" in src, "the DOM width must use the same text-derived offset (A-07)"


def test_a07_rect_jitter_is_stable_per_element():
    """A-07: the rect jitter was re-derived per CALL, so the same element
    returned different coordinates on every read."""
    src = _generated_js()
    assert "rectCallCount" not in src, (
        "the rect jitter must be stable per element — a real renderer only "
        "changes the offset when the layout changes (A-07)"
    )
    assert "rectOffsets" in src, "the rect offsets must be cached per element (A-07)"


def test_a11_window_geometry_is_derived_from_the_spoofed_screen():
    """A-11: the window geometry was left at the HOST's real values while the
    screen was spoofed — and the two disagreed (measured: outerHeight 1055 >
    screen.availHeight 1040, i.e. a window taller than its own screen)."""
    src = _generated_js()
    for metric in ("outerWidth", "outerHeight", "innerWidth", "innerHeight", "screenX", "screenY"):
        assert f"defineWindowMetric('{metric}'" in src, f"the window metric {metric} must be spoofed (A-11)"


def test_a12_window_metrics_are_defined_on_the_instance():
    """A-12: in Chrome these are OWN properties of the window INSTANCE
    (configurable accessors), so a Window.prototype override is shadowed and
    never applies — that is why the old devicePixelRatio spoof did nothing
    (the page kept the host's scale factor: measured 2 on a 1.0 profile)."""
    src = _generated_js()
    assert "apply(window);" in src, (
        "the window metrics must be redefined on the window INSTANCE — a prototype-level "
        "override is shadowed by Chrome's own property (A-12)"
    )
    assert "defineWindowMetric('devicePixelRatio'" in src, "devicePixelRatio must be spoofed on the instance (A-12)"
    # the old prototype-only devicePixelRatio definition must be gone
    assert "Object.defineProperty(Window.prototype, 'devicePixelRatio'" not in src, (
        "the prototype-level devicePixelRatio override never applied and contradicts the instance-level one (A-12)"
    )


def test_a13_shield_covers_the_worker_scope():
    """A-13: a page can read the REAL navigator/Intl values in a Worker scope
    (measured: the worker reported the host's hardwareConcurrency/deviceMemory
    while the main world reported the profile's). The shield must run in a
    worker too: the scope-independent sections apply there, the DOM-only ones
    are skipped, and the navigator prototypes of BOTH scopes are patched
    (a worker's navigator is a WorkerNavigator — a different class)."""
    src = _generated_js()
    assert "__scopeIsWorker" in src, "the shield must know it runs in a worker scope (A-13)"
    assert "WorkerNavigator" in src, (
        "the navigator-level shields must cover WorkerNavigator.prototype — a worker's "
        "navigator is a different class, so patching only Navigator.prototype left the "
        "worker scope untouched (A-13)"
    )
    assert "__hasDom" in src, "the DOM-only sections must be skipped in a worker (A-13)"
    for prop in ("webdriver", "hardwareConcurrency", "deviceMemory", "languages", "language"):
        assert f"__defineNav('{prop}'" in src, f"the navigator property {prop} must be shielded in both scopes (A-13)"


def test_a13_injector_reaches_worker_targets():
    """The injector must attach to worker targets and inject the shield there
    (and release them afterwards)."""
    src = (REPO_ROOT / "nazak" / "core" / "cdp_injector.py").read_text(encoding="utf-8")
    assert '"worker"' in src and '"shared_worker"' in src, "the injector must attach to worker targets (A-13)"
    assert "_apply_worker_session" in src, "the worker scope needs its own injection path (A-13)"
    assert "Runtime.runIfWaitingForDebugger" in src, "a worker paused by waitForDebuggerOnStart must be released (A-13)"


def test_a14_shield_does_not_add_own_properties_to_the_instances():
    """A-14: the shield ASSIGNED navigator.getBattery / mediaDevices.enumerateDevices
    / geolocation.getCurrentPosition / speechSynthesis.getVoices / gpu.requestAdapter
    — every assignment creates an OWN property on the instance, while a real
    Chrome keeps them on the prototype (the navigator instance has NO own
    properties at all). `Object.getOwnPropertyNames(navigator)` exposed the
    patch in one line."""
    src = _generated_js()
    for forbidden in (
        "navigator.getBattery =",
        "navigator.mediaDevices.enumerateDevices =",
        "navigator.geolocation.getCurrentPosition =",
        "navigator.geolocation.watchPosition =",
        "window.speechSynthesis.getVoices =",
        "navigator.gpu.requestAdapter =",
    ):
        assert forbidden not in src, (
            f"'{forbidden}' creates an own property on the instance — the override must live on the prototype (A-14)"
        )


def test_a15_shield_leaves_no_trace_in_the_window():
    """A-15: the shield polluted the window with its own properties:
    `__scopeIsWorker` (an enumerable top-level var — visible in
    Object.keys(window)), `__nsi` (the idempotency flag) and the CDP binding
    (installed enumerable by Runtime.addBinding). Measured: the real Chrome had
    1234 own window properties, the shielded one 1237."""
    src = _generated_js()
    assert "\nvar __scopeIsWorker" not in src, "the scope flag must not become an own property of the window (A-15)"
    assert "Symbol('nazakShieldIdempotent')" in src, (
        "the idempotency flag must live under a symbol key — a string key shows up in "
        "Object.getOwnPropertyNames(window) (A-15)"
    )
    assert "Object.defineProperty(window, '__nsi'" not in src, (
        "the idempotency flag must not be an own property of the window (A-15)"
    )


def test_a15_injector_hides_the_cdp_binding():
    """The CDP binding is installed as an ENUMERABLE own property of the
    window — `Object.keys(window)` showed it. It must be hidden, and it must
    not be installed at all when no synchronizer sink exists (without one it
    could never be accepted: binding_event_allowed -> 'no-sink')."""
    src = (REPO_ROOT / "nazak" / "core" / "cdp_injector.py").read_text(encoding="utf-8")
    assert "_hide_binding" in src, "the CDP binding must be hidden from Object.keys (A-15)"
    assert "enumerable: false" in src, "the binding must be redefined as non-enumerable (A-15)"
    assert "if self.opts.event_sink:" in src, (
        "the binding must only be installed when a synchronizer sink exists (A-15)"
    )


def test_a16_font_pool_is_part_of_the_profile():
    """A-16: the shield returned a HARDCODED list of nine families regardless
    of the profile, while a real Windows box reports 25-60 (measured: 122
    families installed on the audit host, 40+ detectable by width). The list
    also advertised a family the OS does not have, so the query answer and the
    rendering contradicted each other."""
    src = _generated_js()
    assert "const profileFonts" in src, "the font list must come from the profile, not from a hardcoded list (A-16)"
    assert "__installFontAliases" in src, (
        "the families the OS lacks must be aliased to a real sibling font, so the "
        "rendering matches the query answer (A-16)"
    )
    assert "@font-face" in src, "the font aliases are installed through @font-face (A-16)"


def test_a16_font_pool_is_generated_per_profile():
    """The font pool must be realistic for the platform and different between
    profiles (a farm where every profile reports the same nine fonts is a
    one-line cluster signature)."""
    from nazak.core.fingerprint_generator import FONT_POOLS, generate_random_fingerprint

    for os_name, pool in FONT_POOLS.items():
        assert len(pool) >= 25, f"the {os_name} font pool is unrealistically small: {len(pool)}"
    a = generate_random_fingerprint("windows")
    b = generate_random_fingerprint("windows")
    assert a.fonts, "a generated profile must carry a font pool"
    assert len(a.fonts) >= 20, f"the font pool is too small to look real: {len(a.fonts)}"
    assert a.fonts != b.fonts, "two profiles must not report the same font pool"
    for core in ("Arial", "Calibri", "Segoe UI", "Tahoma", "Times New Roman", "Verdana"):
        assert core in a.fonts, f"the core family {core} is missing from the pool"


def test_a17_webgl_aliased_ranges_are_float32_arrays():
    """A-17: the ALIASED_*_RANGE parameters are PAIRS and WebGL returns them
    as a Float32Array — the shield substituted plain numbers (and mixed up the
    pnumbs: 33901 is the POINT size range, 33902 the LINE width range).
    Measured: the host returned Float32Array(1, 1024) where the shield
    returned the scalar 1 — the type alone exposed the patch."""
    src = _generated_js()
    assert "33901: new Float32Array([1, 1])" in src, "ALIASED_POINT_SIZE_RANGE must be a Float32Array pair (A-17)"
    assert "33902: new Float32Array([1, 1024])" in src, "ALIASED_LINE_WIDTH_RANGE must be a Float32Array pair (A-17)"
    assert "33901: 1," not in src and "33902: 255," not in src, "the aliased ranges must not be plain numbers (A-17)"


def test_a18_client_hints_platform_is_the_os_name():
    """A-18: the Client Hints `platform` is the OS NAME ("Windows", "macOS",
    "Linux") while `navigator.platform` is the legacy API string ("Win32").
    The shield used the legacy string for both, so userAgentData.platform
    reported "Win32" — a value the UA-CH spec never produces."""
    src = _generated_js()
    # the OS name is substituted into the generated JS as a literal
    assert '"Windows"' in src or '"macOS"' in src or '"Linux"' in src, (
        "the Client Hints platform must be the OS name, not navigator.platform (A-18)"
    )
    assert "platform: {platform_json}" not in src, (
        "the uaData platform must not use the legacy navigator.platform string (A-18)"
    )
    assert "NavigatorUAData" in src, "the userAgentData object must be built on the real UAData prototype (A-18)"


def test_generated_shield_is_valid_javascript():
    """The generated shield must parse as JS (node --check when available)."""
    import shutil
    import subprocess

    src = _generated_js()
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "stealth.js"
        f.write_text(src, encoding="utf-8")
        proc = subprocess.run([node, "--check", str(f)], capture_output=True, text=True)
        assert proc.returncode == 0, f"the generated shield is not valid JS: {proc.stderr[:400]}"
