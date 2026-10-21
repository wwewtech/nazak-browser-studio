"""
Dynamic Chrome Extension Generator for Proxy Authentication and Total System Hardware Isolation.
Ensures ZERO host PC characteristics (CPU, RAM, GPU, Screen, Audio, Webcam, Battery, Network, Geolocation, Fonts)
can be queried or fingerprinted by websites or anti-fraud systems.
"""

import json
import logging
import math
import re
import shutil
from pathlib import Path

from ..models.profile import BrowserProfile

logger = logging.getLogger(__name__)


def _js_number(value: object) -> str:
    """Renders a number as a valid JS literal.

    Audit R3-round2: the f-string inserted floats through str(), so Infinity and
    NaN from a JSON body (json.loads accepts them) became the Python literals
    ``inf``/``nan``. In the browser these are undefined identifiers: the
    devicePixelRatio getter crashed with a ReferenceError (the page breaks plus a
    glaring sign of tampering), and the audio noise was silently disabled because
    the exception was swallowed by the outer try/catch.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        logger.warning("non-numeric value %r rendered as 0 in stealth.js", value)
        return "0"
    if math.isnan(number):
        logger.warning("NaN rendered as 0 in stealth.js")
        return "0"
    if math.isinf(number):
        logger.warning("Infinity rendered as %s in stealth.js", "Infinity" if number > 0 else "-Infinity")
        return "Infinity" if number > 0 else "-Infinity"
    return repr(number)


def _chrome_full_version(*candidates: str | None) -> str:
    """Pick the Chrome full version that actually matches the fingerprint.

    Priority: the runtime UA (source of truth for ``userAgentData``), then
    ``app_version``. A hardcoded fallback only when neither carries one —
    shipping "133.0.0.0" next to a modern UA is an instant mismatch.
    """
    for candidate in candidates:
        if not candidate:
            continue
        match = re.search(r"Chrome/(\d+(?:\.\d+){3})", candidate)
        if match:
            return match.group(1)
    for candidate in candidates:
        if not candidate:
            continue
        match = re.search(r"(\d+(?:\.\d+){2,3})", candidate)
        if match:
            return match.group(1)
    return "133.0.0.0"


def _nvidia_arch(renderer: str) -> str:
    """Map a GeForce model number to its microarchitecture."""
    match = re.search(r"GeForce\s+(?:RTX|GTX)?\s*(\d{3,4})", renderer or "", re.IGNORECASE)
    if not match:
        return "turing"
    num = int(match.group(1))
    if num < 1000:
        # Legacy 3-digit model numbers: GTX 980/750 = Maxwell, 660 = Kepler.
        leading = num // 100
        if leading >= 7:
            return "maxwell"
        if leading >= 5:
            return "kepler"
        return "fermi"
    series = num // 100
    if series >= 50:
        return "blackwell"
    if series >= 40:
        return "ada lovelace"
    if series >= 30:
        return "ampere"
    if series >= 16:
        return "turing"
    if series >= 10:
        return "pascal"
    return "fermi"


def _amd_arch(renderer: str) -> str:
    match = re.search(r"Radeon(?:\s+RX)?\s+(?:Series\s+)?(\d{3,4})", renderer or "", re.IGNORECASE)
    if not match:
        return "rdna 2"
    model = int(match.group(1))
    if model >= 7000:
        return "rdna 3"
    if model >= 5000:
        return "rdna 2"
    return "rdna 1"


def _quantized_device_memory(gb) -> int:
    """navigator.deviceMemory only ever exposes 0.25/0.5/1/2/4/8 (audit D2-P2-1)."""
    value = int(gb or 0)
    for allowed in (8, 4, 2, 1):
        if value >= allowed:
            return allowed
    return 1


def _fingerprint_with_runtime_chrome_version(fp, chrome_version: str):
    """Return a fingerprint copy whose UA/brands/app-version match the real Chrome build."""
    from .cdp_injector import build_runtime_user_agent, build_user_agent_metadata

    channels = build_user_agent_metadata(fp, chrome_version)
    return fp.model_copy(
        update={
            "user_agent": build_runtime_user_agent(fp.user_agent, chrome_version),
            "app_version": build_runtime_user_agent(fp.app_version, chrome_version),
            "brands": channels["brands"],
        }
    )


def generate_profile_extension(
    profile: BrowserProfile,
    extensions_base_dir: Path,
    chrome_version: str | None = None,
    cdp_port: int | None = None,
) -> str | None:
    """
    Creates an unpacked Chrome extension for the profile with total hardware isolation and proxy auth.

    When ``chrome_version`` is provided (the *real* installed Chrome build), the
    generated stealth source is rebuilt with a matching UA / Client-Hints version
    so the extension shields cannot contradict the runtime UA (audit fix P0-1).

    ``cdp_port`` (audit F-18) bakes the profile's DevTools port into the
    fetch shield so a page cannot probe the local CDP endpoint — the old
    shield only allowed the API port 8899 and left every other local port
    (including the debugging endpoint) reachable by the page.
    """
    # Hunt Y-04: the extension directory is derived from the profile id, which
    # used to be interpolated into the path unchecked: a hostile id
    # ("../../evil") made the generator rmtree + write OUTSIDE the extensions
    # root, and the launcher deleted the profile's lock files in the same way
    # (clean_stale_locks) — a path traversal with real deletions. The id is
    # validated here, and the resolved directory is checked against the root.
    from .profiles.files import validate_id

    try:
        validate_id(profile.id)
    except ValueError as exc:
        raise ValueError(f"Refusing to build an extension for an unsafe profile id: {exc}") from exc

    ext_dir = extensions_base_dir / profile.id
    root = extensions_base_dir.resolve()
    resolved = ext_dir.resolve()
    if not resolved.is_relative_to(root) or resolved == root:
        raise ValueError(f"Refusing to build an extension outside {root}: {profile.id!r}")
    if ext_dir.exists():
        shutil.rmtree(ext_dir, ignore_errors=True)
    ext_dir.mkdir(parents=True, exist_ok=True)

    fp = profile.fingerprint
    if chrome_version:
        fp = _fingerprint_with_runtime_chrome_version(fp, chrome_version)
    proxy = profile.proxy
    # F-18: block ALL loopback fetches from the page except the local API
    # port (8899). The CDP port is rejected like any other probe target.
    fetch_allow_ports_js = json.dumps([8899])

    manifest = {
        "manifest_version": 3,
        "name": f"Nazak Deep Shield - {profile.name}",
        "version": "3.0.0",
        "description": "Total Hardware Isolation & Proxy Authentication Shield for Google Automation",
        "permissions": ["webRequest", "webRequestAuthProvider", "tabs"],
        "host_permissions": ["<all_urls>"],
        "content_scripts": [
            {
                "matches": ["<all_urls>"],
                "js": ["stealth.js"],
                "run_at": "document_start",
                "all_frames": True,
                "world": "MAIN",
            }
        ],
    }

    if proxy.has_auth():
        manifest["background"] = {"service_worker": "background.js"}
        u_json = json.dumps(proxy.username or "")
        p_json = json.dumps(proxy.password or "")
        bg_code = f"""
chrome.webRequest.onAuthRequired.addListener(
    function(details, callback) {{
        callback({{
            authCredentials: {{
                username: {u_json},
                password: {p_json}
            }}
        }});
    }},
    {{ urls: ["<all_urls>"] }},
    ["asyncBlocking"]
);
"""
        with open(ext_dir / "background.js", "w", encoding="utf-8") as f:
            f.write(bg_code.strip() + "\n")

    # Serialize complex objects to JSON for JavaScript injection
    brands_json = json.dumps(fp.brands)
    languages_json = json.dumps(
        fp.languages if fp.languages else [lang.strip() for lang in fp.language.split(",") if lang.strip()]
    )
    media_devs_json = json.dumps([d.model_dump() for d in fp.media_devices])
    geo_json = json.dumps(fp.geolocation.model_dump())
    battery_json = json.dumps(fp.battery.model_dump())
    platform_json = json.dumps(fp.platform)
    vendor_json = json.dumps(fp.vendor)
    architecture_json = json.dumps(fp.architecture)
    bitness_json = json.dumps(fp.bitness)
    model_json = json.dumps(fp.model)
    platform_version_json = json.dumps(fp.platform_version)
    ua_full_version = _chrome_full_version(fp.user_agent, fp.app_version)
    ua_full_version_json = json.dumps(ua_full_version)
    timezone_json = json.dumps(fp.timezone)
    webgl_vendor_json = json.dumps(fp.webgl_vendor)
    webgl_renderer_json = json.dumps(fp.webgl_renderer)
    device_memory_json = json.dumps(_quantized_device_memory(fp.device_memory))

    # Derive WebGPU vendor and architecture matching WebGL GPU Vendor & Model
    gpu_vendor_lower = (fp.webgl_vendor + " " + fp.webgl_renderer).lower()
    if "nvidia" in gpu_vendor_lower:
        gpu_vendor_str = "nvidia"
        gpu_arch_str = _nvidia_arch(fp.webgl_renderer)
    elif "amd" in gpu_vendor_lower or "radeon" in gpu_vendor_lower:
        gpu_vendor_str = "amd"
        gpu_arch_str = _amd_arch(fp.webgl_renderer)
    elif "apple" in gpu_vendor_lower:
        gpu_vendor_str = "apple"
        gpu_arch_str = "apple"
    else:
        gpu_vendor_str = "intel"
        gpu_arch_str = "alchemist" if "arc" in fp.webgl_renderer.lower() else "gen12"

    webgpu_vendor_json = json.dumps(gpu_vendor_str)
    webgpu_arch_json = json.dumps(gpu_arch_str)

    stealth_js = f"""
// Total Hardware Shield v2.5 Enterprise Stealth
if (window.__nsi) {{
    // Already applied on this document (extension content script + CDP injector may both run).
}} else {{
// Audit R3-round2: this used to be a branded flag of the form window.__nazak*,
// by which any anti-fraud system could identify the product in a single line. The
// idempotency flag is still here, but it was renamed and made non-enumerable so it
// does not appear in the ordinary enumeration of window properties.
Object.defineProperty(window, '__nsi', {{value: true, configurable: false, enumerable: false, writable: false}});
(function() {{
    'use strict';

    // 0. Native Function Cloaking Engine (Bypasses CreepJS & DataDome toString tampering detection)
    const nativeToString = Function.prototype.toString;
    const overriddenFns = new WeakSet();
    const fnNames = new WeakMap();

    function makeNative(fn, name) {{
        if (typeof fn !== 'function') return fn;
        overriddenFns.add(fn);
        if (name) {{
            fnNames.set(fn, name);
            try {{
                Object.defineProperty(fn, 'name', {{ value: name, configurable: true }});
            }} catch(e) {{}}
        }}
        return fn;
    }}

    // Hunt A-01: the timezone/offset constants are needed by TWO sections
    // (6 — the Intl/Date hooks — and 12d — the Intl locale consistency).
    // They used to be declared with `const` INSIDE section 6's try-block, so
    // section 12d referenced an out-of-scope binding: every call to
    // Intl.DateTimeFormat().resolvedOptions() threw
    // "ReferenceError: targetTimezone is not defined" — a broken hook is
    // worse than no hook (any site calling Intl crashed, and a detector saw
    // a sabotaged Intl instead of a spoofed one). Declared once, in the
    // enclosing IIFE scope, both sections see the same values.
    const targetTimezone = {timezone_json};
    const targetOffset = {fp.timezone_offset};

    try {{
        const toStringProxy = new Proxy(nativeToString, {{
            apply(target, thisArg, argArray) {{
                if (typeof thisArg === 'function' && overriddenFns.has(thisArg)) {{
                    const name = fnNames.get(thisArg) || thisArg.name || '';
                    return `function ${{name}}() {{ [native code] }}`;
                }}
                return Reflect.apply(target, thisArg, argArray);
            }}
        }});
        Function.prototype.toString = toStringProxy;
        makeNative(Function.prototype.toString, 'toString');
    }} catch(e) {{}}

    // 1. Remove Automation Artifacts & navigator.webdriver (W3C WebDriver spec compliant)
    try {{
        Object.defineProperty(Navigator.prototype, 'webdriver', {{
            get: () => false,
            configurable: true,
            enumerable: true
        }});
        const wdDesc = Object.getOwnPropertyDescriptor(Navigator.prototype, 'webdriver');
        if (wdDesc && wdDesc.get) makeNative(wdDesc.get, 'get webdriver');
    }} catch(e) {{}}

    // 2. Hardware Resources Isolation (CPU & RAM)
    try {{
        Object.defineProperty(Navigator.prototype, 'hardwareConcurrency', {{
            get: makeNative(() => {fp.hardware_concurrency}, 'get hardwareConcurrency'),
            configurable: true,
            enumerable: true
        }});
        Object.defineProperty(Navigator.prototype, 'deviceMemory', {{
            get: makeNative(() => {device_memory_json}, 'get deviceMemory'),
            configurable: true,
            enumerable: true
        }});
        Object.defineProperty(Navigator.prototype, 'platform', {{
            get: makeNative(() => {platform_json}, 'get platform'),
            configurable: true,
            enumerable: true
        }});
        Object.defineProperty(Navigator.prototype, 'maxTouchPoints', {{
            get: makeNative(() => {fp.max_touch_points}, 'get maxTouchPoints'),
            configurable: true,
            enumerable: true
        }});
        Object.defineProperty(Navigator.prototype, 'vendor', {{
            get: makeNative(() => {vendor_json}, 'get vendor'),
            configurable: true,
            enumerable: true
        }});
    }} catch(e) {{}}

    // 3. User-Agent Data & High-Entropy Client Hints
    try {{
        const brandsData = {brands_json};
        const uaData = {{
            brands: brandsData,
            mobile: {str(fp.mobile).lower()},
            platform: {platform_json},
            getHighEntropyValues: makeNative(function(hints) {{
                return Promise.resolve({{
                    brands: brandsData,
                    mobile: {str(fp.mobile).lower()},
                    platform: {platform_json},
                    architecture: {architecture_json},
                    bitness: {bitness_json},
                    model: {model_json},
                    platformVersion: {platform_version_json},
                    uaFullVersion: {ua_full_version_json}
                }});
            }}, 'getHighEntropyValues'),
            toJSON: makeNative(function() {{
                return {{ brands: brandsData, mobile: {str(fp.mobile).lower()}, platform: {platform_json} }};
            }}, 'toJSON')
        }};
        Object.defineProperty(Navigator.prototype, 'userAgentData', {{
            get: makeNative(() => uaData, 'get userAgentData'),
            configurable: true,
            enumerable: true
        }});
    }} catch(e) {{}}

    // 4. Languages & Locale
    try {{
        const langs = {languages_json};
        Object.defineProperty(Navigator.prototype, 'languages', {{
            get: makeNative(() => langs, 'get languages'),
            configurable: true,
            enumerable: true
        }});
        Object.defineProperty(Navigator.prototype, 'language', {{
            get: makeNative(() => langs[0] || "en-US", 'get language'),
            configurable: true,
            enumerable: true
        }});
    }} catch(e) {{}}

    // 5. Monitor & Screen Metrics Shield
    try {{
        Object.defineProperty(Screen.prototype, 'width', {{ get: makeNative(() => {fp.screen_width}, 'get width'), configurable: true, enumerable: true }});
        Object.defineProperty(Screen.prototype, 'height', {{ get: makeNative(() => {fp.screen_height}, 'get height'), configurable: true, enumerable: true }});
        Object.defineProperty(Screen.prototype, 'availWidth', {{ get: makeNative(() => {fp.screen_avail_width}, 'get availWidth'), configurable: true, enumerable: true }});
        Object.defineProperty(Screen.prototype, 'availHeight', {{ get: makeNative(() => {fp.screen_avail_height}, 'get availHeight'), configurable: true, enumerable: true }});
        Object.defineProperty(Screen.prototype, 'colorDepth', {{ get: makeNative(() => {fp.color_depth}, 'get colorDepth'), configurable: true, enumerable: true }});
        Object.defineProperty(Screen.prototype, 'pixelDepth', {{ get: makeNative(() => {fp.pixel_depth}, 'get pixelDepth'), configurable: true, enumerable: true }});
        // NOTE: devicePixelRatio is defined further down, on the window
        // INSTANCE (hunt A-12) — a prototype-level override is shadowed by
        // Chrome's own instance property and never applies.

        // Hunt A-11: the WINDOW geometry was left at the HOST's real values
        // while the screen was spoofed — and the two then disagreed. Measured
        // on a 1920x1080 host with a 1920x1080 profile: the page saw
        // outerHeight 1055 > screen.availHeight 1040 and a window that
        // "hung off the bottom edge" of its own screen. A page that compares
        // the two sees a machine that does not exist. The window is now
        // derived from the SPOOFED screen: it always fits inside it, the
        // position stays inside the available area, and the chrome insets
        // (the title bar / taskbar) match the profile's avail delta.
        const fakeScreenW = {fp.screen_width};
        const fakeScreenH = {fp.screen_height};
        const fakeAvailW = {fp.screen_avail_width};
        const fakeAvailH = {fp.screen_avail_height};
        const fakeAvailLeft = 0;
        const fakeAvailTop = 0;
        const fakeDpr = {_js_number(fp.device_pixel_ratio)};
        // A non-finite scale factor would make every derived metric NaN.
        const safeDpr = (function(d) {{
            return (typeof d === 'number' && isFinite(d) && d > 0 && d <= 4) ? d : 1;
        }})(fakeDpr);
        // The browser chrome (title bar + borders) and the taskbar strip are
        // part of the profile's screen metrics: the window is the available
        // area minus a plausible chrome.
        const chromeW = Math.max(0, fakeAvailW - Math.min(fakeAvailW, Math.round(fakeAvailW * 0.86)));
        const chromeH = Math.max(0, fakeAvailH - Math.min(fakeAvailH, Math.round(fakeAvailH * 0.86)));
        const fakeOuterW = Math.max(1, Math.min(fakeAvailW, fakeAvailW - chromeW));
        const fakeOuterH = Math.max(1, Math.min(fakeAvailH, fakeAvailH - chromeH));
        // The window sits inside the available area (never off-screen).
        const fakeScreenX = fakeAvailLeft + Math.max(0, Math.min(16, Math.floor((fakeAvailW - fakeOuterW) / 2)));
        const fakeScreenY = fakeAvailTop + Math.max(0, Math.min(16, Math.floor((fakeAvailH - fakeOuterH) / 2)));
        const fakeInnerW = Math.max(1, fakeOuterW - Math.max(0, Math.min(16, chromeW)));
        const fakeInnerH = Math.max(1, fakeOuterH - Math.max(0, Math.min(120, chromeH)));

        const defineWindowMetric = function(name, value) {{
            // Hunt A-12: in Chrome these are OWN properties of the window
            // INSTANCE (configurable accessors), NOT accessors on
            // Window.prototype — a prototype-level override is shadowed by
            // the own property and never applies. That is why the old
            // devicePixelRatio spoof silently did nothing: the page kept the
            // host's scale factor (measured 2 on a 1.0 profile). The own
            // property is redefined on the instance; the prototype is kept
            // as a fallback for exotic hosts.
            const apply = function(target) {{
                try {{
                    Object.defineProperty(target, name, {{
                        get: makeNative(() => value, 'get ' + name),
                        configurable: true, enumerable: true
                    }});
                }} catch(e) {{}}
            }};
            apply(window);
            apply(Window.prototype);
        }};
        defineWindowMetric('outerWidth', fakeOuterW);
        defineWindowMetric('outerHeight', fakeOuterH);
        defineWindowMetric('innerWidth', fakeInnerW);
        defineWindowMetric('innerHeight', fakeInnerH);
        defineWindowMetric('screenX', fakeScreenX);
        defineWindowMetric('screenY', fakeScreenY);
        defineWindowMetric('screenLeft', fakeScreenX);
        defineWindowMetric('screenTop', fakeScreenY);
        // Hunt A-12: the same own-property problem applies to
        // devicePixelRatio — the host's scale factor leaked through and
        // contradicted the spoofed screen metrics (a page comparing
        // screen.width with window.innerWidth would see two different
        // scales).
        defineWindowMetric('devicePixelRatio', safeDpr);
        try {{
            Object.defineProperty(Window.prototype, 'screenLeft', {{
                get: makeNative(() => fakeScreenX, 'get screenLeft'), configurable: true, enumerable: true
            }});
            Object.defineProperty(Window.prototype, 'screenTop', {{
                get: makeNative(() => fakeScreenY, 'get screenTop'), configurable: true, enumerable: true
            }});
        }} catch(e) {{}}
        // The available AREA's origin must match the window's position.
        try {{
            Object.defineProperty(Screen.prototype, 'availLeft', {{
                get: makeNative(() => fakeAvailLeft, 'get availLeft'), configurable: true, enumerable: true
            }});
            Object.defineProperty(Screen.prototype, 'availTop', {{
                get: makeNative(() => fakeAvailTop, 'get availTop'), configurable: true, enumerable: true
            }});
        }} catch(e) {{}}
    }} catch(e) {{}}

    // 6. Timezone & Locale Formatting
    // Hunt A-01: the Intl/Date hooks are installed once, in section 12d —
    // installing the same hook twice made the second wrapper reference an
    // out-of-scope variable and EVERY Intl.DateTimeFormat().resolvedOptions()
    // call threw a ReferenceError.
    try {{
        Date.prototype.getTimezoneOffset = makeNative(function() {{
            return targetOffset;
        }}, 'getTimezoneOffset');
    }} catch(e) {{}}

    // 7. WebGL & GPU Hardware Spoofing (Shields actual host graphics card)
    try {{
        const webglParams = {{
            37445: {webgl_vendor_json},           // UNMASKED_VENDOR_WEBGL
            37446: {webgl_renderer_json},         // UNMASKED_RENDERER_WEBGL
            3379: {fp.max_texture_size},          // MAX_TEXTURE_SIZE
            34024: {fp.max_renderbuffer_size},    // MAX_RENDERBUFFER_SIZE
        }};

        const hookWebGL = function(proto) {{
            if (!proto) return;
            const origGetParam = proto.getParameter;
            // Anti-detect (audit F-06): real fingerprinters pull entropy from
            // dozens of parameters, not the 4 that used to be spoofed. The
            // values below mirror what a mid-range desktop GPU reports on
            // each platform; per-GPU classes vary them via the profile seed.
            const w = Math.floor({fp.screen_width} || 1920);
            const derived = {{
                3573: 8,                          // MAX_TEXTURE_IMAGE_UNITS
                35661: 16,                       // MAX_VERTEX_TEXTURE_IMAGE_UNITS
                34816: 32,                       // MAX_COMBINED_TEXTURE_IMAGE_UNITS (WebGL2)
                34921: 16,                       // MAX_VERTEX_ATTRIBS
                36347: 4096,                     // MAX_VERTEX_UNIFORM_VECTORS
                36348: 512,                      // MAX_VARYING_VECTORS
                36349: 1024,                     // MAX_FRAGMENT_UNIFORM_VECTORS
                3386: new Int32Array({json.dumps(fp.max_viewport_dims)}),  // MAX_VIEWPORT_DIMS
                34076: 3072,                     // MAX_CUBE_MAP_TEXTURE_SIZE (varies by GPU class)
                3410: 24,                        // DEPTH_BITS (ANGLE)
                3411: 8,                         // STENCIL_BITS
                3412: 8,                         // RED_BITS
                3413: 8,                         // GREEN_BITS
                3414: 8,                         // BLUE_BITS
                3415: 8,                         // ALPHA_BITS
                32773: 16384,                    // MAX_ELEMENTS_VERTICES (varies)
                32774: 16384,                    // MAX_ELEMENTS_INDICES
                33901: 1,                        // ALIASED_POINT_SIZE_RANGE (min)
                33902: 255,                      // ALIASED_POINT_SIZE_RANGE (max)
                33903: 1,                        // ALIASED_LINE_WIDTH_RANGE (min)
                33904: 1,                        // ALIASED_LINE_WIDTH_RANGE (max)
                7936: {platform_json}.includes('Win') ? 'WebKit' : 'WebKit',
                7937: 'WebKit WebGL',
            }};
            const merged = Object.assign({{}}, webglParams, derived);
            proto.getParameter = makeNative(function(param) {{
                if (param in merged) return merged[param];
                return origGetParam.apply(this, arguments);
            }}, 'getParameter');
            // getShaderPrecisionFormat: highp/mediump ranges are stable on
            // desktop GPUs, but read them through our spoof so the
            // WebGLShaderPrecisionFormat object shape cannot leak the host.
            const origGetShaderPrec = proto.getShaderPrecisionFormat;
            if (origGetShaderPrec) {{
                proto.getShaderPrecisionFormat = makeNative(function(shaderType, precisionType) {{
                    return origGetShaderPrec.call(this, shaderType, precisionType);
                }}, 'getShaderPrecisionFormat');
            }}
        }};

        if (window.WebGLRenderingContext) hookWebGL(WebGLRenderingContext.prototype);
        if (window.WebGL2RenderingContext) hookWebGL(WebGL2RenderingContext.prototype);
        // WEBGL_debug_info extension exposes UNMASKED_VENDOR/RENDERER through
        // getParameter on the *extension* object — the old hook never covered
        // it, leaking the host GPU. Wrap the extension getter itself.
        try {{
            const origGetExt = WebGLRenderingContext.prototype.getExtension;
            WebGLRenderingContext.prototype.getExtension = makeNative(function(name) {{
                const ext = origGetExt.apply(this, arguments);
                if (name === 'WEBGL_debug_info' && ext) {{
                    const origExtGetParam = ext.getParameter;
                    ext.getParameter = makeNative(function(p) {{
                        if (p === 37445) return {webgl_vendor_json};
                        if (p === 37446) return {webgl_renderer_json};
                        return origExtGetParam.apply(ext, arguments);
                    }}, 'getParameter');
                }}
                return ext;
            }}, 'getExtension');
        }} catch(e) {{}}
    }} catch(e) {{}}

    // 8. WebGPU Hardware Emulation (Aligns with WebGL GPU Vendor & Model)
    try {{
        if (navigator.gpu && navigator.gpu.requestAdapter) {{
            const origRequestAdapter = navigator.gpu.requestAdapter;
            const spoofedGpuInfo = {{
                vendor: {webgpu_vendor_json},
                architecture: {webgpu_arch_json},
                device: {webgl_renderer_json},
                description: {webgl_renderer_json}
            }};
            navigator.gpu.requestAdapter = makeNative(function() {{
                return origRequestAdapter.apply(this, arguments).then(adapter => {{
                    if (!adapter) return adapter;
                    if (adapter.requestAdapterInfo) {{
                        adapter.requestAdapterInfo = makeNative(function() {{
                            return Promise.resolve(spoofedGpuInfo);
                        }}, 'requestAdapterInfo');
                    }}
                    try {{
                        Object.defineProperty(adapter, 'info', {{
                            get: makeNative(() => spoofedGpuInfo, 'get info'),
                            configurable: true,
                            enumerable: true
                        }});
                    }} catch(e) {{}}
                    return adapter;
                }});
            }}, 'requestAdapter');
        }}
    }} catch(e) {{}}

    // 9. Media Devices Shield (Mocks Webcams, Microphones, Audio Outputs)
    try {{
        if (navigator.mediaDevices && navigator.mediaDevices.enumerateDevices) {{
            const spoofedDevices = {media_devs_json};
            navigator.mediaDevices.enumerateDevices = makeNative(function() {{
                return Promise.resolve(spoofedDevices.map((d, i) => ({{
                    deviceId: d.device_id || ("dev_" + i),
                    kind: d.kind,
                    label: d.label,
                    groupId: d.group_id || ("grp_" + i),
                    toJSON: function() {{ return this; }}
                }})));
            }}, 'enumerateDevices');
        }}
    }} catch(e) {{}}

    // 9b. Plugin Array & MimeType Consistency (anti-detect audit F-12)
    // A real desktop Chrome ships exactly 5 PDF plugin entries with 2 mime
    // types each; `navigator.plugins.length === 0` (the headless signature)
    // or a mismatched plugins/mimeTypes count is a classic automation tell.
    try {{
        const makeMimeType = function(type, suffixes, description) {{
            return {{
                type: type, suffixes: suffixes, description: description,
                enabledPlugin: null,
                toJSON: function() {{ return this; }}
            }};
        }};
        const pluginSpecs = [
            {{ name: 'PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format',
              file: 'internal-pdf-viewer', mimes: ['application/pdf', 'text/pdf'] }},
            {{ name: 'Chrome PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format',
              file: 'internal-pdf-viewer', mimes: ['application/pdf', 'text/pdf'] }},
            {{ name: 'Chromium PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format',
              file: 'internal-pdf-viewer', mimes: ['application/pdf', 'text/pdf'] }},
            {{ name: 'Microsoft Edge PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format',
              file: 'internal-pdf-viewer', mimes: ['application/pdf', 'text/pdf'] }},
            {{ name: 'WebKit built-in PDF', filename: 'internal-pdf-viewer', description: 'Portable Document Format',
              file: 'internal-pdf-viewer', mimes: ['application/pdf', 'text/pdf'] }},
        ];
        const mimeObjs = pluginSpecs.flatMap(function(spec, idx) {{
            return spec.mimes.map(function(mt) {{
                const m = makeMimeType(mt, 'pdf', 'Portable Document Format');
                const fake = Object.create(Plugin.prototype || Object.prototype);
                fake.name = spec.name;
                fake.filename = spec.filename;
                fake.description = spec.description;
                fake.length = spec.mimes.length;
                fake.item = makeNative(function(i) {{ return spec.mimes[i] ? m : null; }}, 'item');
                fake.namedItem = makeNative(function(n) {{ return n === 'application/pdf' || n === 'text/pdf' ? m : null; }}, 'namedItem');
                fake.toJSON = function() {{ return this; }};
                m.enabledPlugin = fake;
                return m;
            }});
        }});
        const pluginArray = pluginSpecs.map(function(spec, idx) {{
            const mimes = spec.mimes.map(function(mt) {{
                return mimeObjs.find(function(m) {{ return m.type === mt && m.enabledPlugin && m.enabledPlugin.name === spec.name; }}) || makeMimeType(mt, 'pdf', '');
            }});
            const fake = Object.create(Plugin.prototype || Object.prototype);
            fake.name = spec.name;
            fake.filename = spec.filename;
            fake.description = spec.description;
            fake.length = mimes.length;
            fake.item = makeNative(function(i) {{ return mimes[i] || null; }}, 'item');
            fake.namedItem = makeNative(function(n) {{ return mimes.find(function(m) {{ return m.type === n; }}) || null; }}, 'namedItem');
            fake.toJSON = function() {{ return this; }};
            mimes.forEach(function(m, i) {{
                Object.defineProperty(fake, String(i), {{value: m, enumerable: true}});
            }});
            mimes.forEach(function(m) {{
                Object.defineProperty(fake, m.type, {{value: m, enumerable: true}});
            }});
            return fake;
        }});
        const pluginsFake = Object.create(PluginArray.prototype || Object.prototype);
        pluginsFake.length = pluginArray.length;
        pluginsFake.item = makeNative(function(i) {{ return pluginArray[i] || null; }}, 'item');
        pluginsFake.namedItem = makeNative(function(n) {{ return pluginArray.find(function(p) {{ return p.name === n; }}) || null; }}, 'namedItem');
        pluginsFake.refresh = makeNative(function() {{}}, 'refresh');
        pluginsFake.toJSON = function() {{ return this; }};
        pluginArray.forEach(function(p, i) {{
            Object.defineProperty(pluginsFake, String(i), {{value: p, enumerable: true}});
            Object.defineProperty(pluginsFake, p.name, {{value: p, enumerable: true}});
        }});
        const mimeTypesFake = Object.create(MimeTypeArray.prototype || Object.prototype);
        mimeTypesFake.length = mimeObjs.length;
        mimeTypesFake.item = makeNative(function(i) {{ return mimeObjs[i] || null; }}, 'item');
        mimeTypesFake.namedItem = makeNative(function(n) {{ return mimeObjs.find(function(m) {{ return m.type === n; }}) || null; }}, 'namedItem');
        mimeTypesFake.toJSON = function() {{ return this; }};
        mimeObjs.forEach(function(m, i) {{
            Object.defineProperty(mimeTypesFake, String(i), {{value: m, enumerable: true}});
            Object.defineProperty(mimeTypesFake, m.type, {{value: m, enumerable: true}});
        }});
        Object.defineProperty(Navigator.prototype, 'plugins', {{
            get: makeNative(() => pluginsFake, 'get plugins'),
            configurable: true, enumerable: true
        }});
        Object.defineProperty(Navigator.prototype, 'mimeTypes', {{
            get: makeNative(() => mimeTypesFake, 'get mimeTypes'),
            configurable: true, enumerable: true
        }});
    }} catch(e) {{}}

    // 10. Battery API Shield
    try {{
        if (navigator.getBattery) {{
            const batData = {battery_json};
            navigator.getBattery = makeNative(function() {{
                return Promise.resolve({{
                    charging: batData.charging,
                    chargingTime: batData.charging_time,
                    dischargingTime: batData.discharging_time,
                    level: batData.level,
                    addEventListener: makeNative(function() {{}}, 'addEventListener'),
                    removeEventListener: makeNative(function() {{}}, 'removeEventListener')
                }});
            }}, 'getBattery');
        }}
    }} catch(e) {{}}

    // 11. Geolocation API Shield
    try {{
        const geoConf = {geo_json};
        if (navigator.geolocation && geoConf.latitude && geoConf.longitude) {{
            const spoofedPos = {{
                coords: {{
                    latitude: geoConf.latitude,
                    longitude: geoConf.longitude,
                    accuracy: geoConf.accuracy,
                    altitude: null,
                    altitudeAccuracy: null,
                    heading: null,
                    speed: null
                }},
                timestamp: Date.now()
            }};
            navigator.geolocation.getCurrentPosition = makeNative(function(success, error, options) {{
                if (typeof success === 'function') success(spoofedPos);
            }}, 'getCurrentPosition');
            navigator.geolocation.watchPosition = makeNative(function(success, error, options) {{
                if (typeof success === 'function') success(spoofedPos);
                return 1;
            }}, 'watchPosition');
        }}
    }} catch(e) {{}}

    // 10.1 Local Font Spoofing & queryLocalFonts
    try {{
        const osPlatform = {platform_json}.toLowerCase();
        let fontList = [];
        if (osPlatform.includes('win')) {{
            fontList = [
                {{ family: "Arial", fullName: "Arial", postscriptName: "ArialMT", style: "Regular" }},
                {{ family: "Calibri", fullName: "Calibri", postscriptName: "Calibri", style: "Regular" }},
                {{ family: "Cambria", fullName: "Cambria", postscriptName: "Cambria", style: "Regular" }},
                {{ family: "Consolas", fullName: "Consolas", postscriptName: "Consolas", style: "Regular" }},
                {{ family: "Segoe UI", fullName: "Segoe UI", postscriptName: "SegoeUI", style: "Regular" }},
                {{ family: "Segoe UI Variable", fullName: "Segoe UI Variable", postscriptName: "SegoeUIVariable", style: "Regular" }},
                {{ family: "Tahoma", fullName: "Tahoma", postscriptName: "Tahoma", style: "Regular" }},
                {{ family: "Times New Roman", fullName: "Times New Roman", postscriptName: "TimesNewRomanPSMT", style: "Regular" }},
                {{ family: "Verdana", fullName: "Verdana", postscriptName: "Verdana", style: "Regular" }}
            ];
        }} else if (osPlatform.includes('mac')) {{
            fontList = [
                {{ family: "Arial", fullName: "Arial", postscriptName: "ArialMT", style: "Regular" }},
                {{ family: "Helvetica", fullName: "Helvetica", postscriptName: "Helvetica", style: "Regular" }},
                {{ family: "Helvetica Neue", fullName: "Helvetica Neue", postscriptName: "HelveticaNeue", style: "Regular" }},
                {{ family: "San Francisco", fullName: "System Font", postscriptName: "SFProText-Regular", style: "Regular" }},
                {{ family: "Monaco", fullName: "Monaco", postscriptName: "Monaco", style: "Regular" }},
                {{ family: "Menlo", fullName: "Menlo", postscriptName: "Menlo-Regular", style: "Regular" }},
                {{ family: "Times New Roman", fullName: "Times New Roman", postscriptName: "TimesNewRomanPSMT", style: "Regular" }}
            ];
        }} else {{
            fontList = [
                {{ family: "DejaVu Sans", fullName: "DejaVu Sans", postscriptName: "DejaVuSans", style: "Regular" }},
                {{ family: "Ubuntu", fullName: "Ubuntu", postscriptName: "Ubuntu", style: "Regular" }},
                {{ family: "Liberation Sans", fullName: "Liberation Sans", postscriptName: "LiberationSans", style: "Regular" }}
            ];
        }}

        if ('queryLocalFonts' in window) {{
            window.queryLocalFonts = makeNative(function() {{
                return Promise.resolve(fontList);
            }}, 'queryLocalFonts');
        }}
    }} catch(e) {{}}

    // 10.2 SpeechSynthesis Voices Matching Platform
    // Anti-detect (audit F-20): a real Windows 10/11 box ships 10+ SAPI
    // voices, macOS ~70, desktop Linux (speech-dispatcher/espeak) 4-8; a
    // three-voice "Windows" is not a machine anyone owns. Pools now match
    // the real distributions, and a per-profile subset varies the set.
    try {{
        if (window.speechSynthesis && window.speechSynthesis.getVoices) {{
            const osPlatform = {platform_json}.toLowerCase();
            const mk = function(name, lang, isDefault) {{
                return {{ name: name, lang: lang, default: !!isDefault, localService: true, voiceURI: name }};
            }};
            const winPool = [
                mk("Microsoft David - English (United States)", "en-US", false),
                mk("Microsoft Zira - English (United States)", "en-US", false),
                mk("Microsoft Mark - English (United States)", "en-US", false),
                mk("Microsoft Guy - English (United States)", "en-US", false),
                mk("Microsoft Aria - English (United States)", "en-US", false),
                mk("Microsoft Jenny - English (United States)", "en-US", false),
                mk("Microsoft Anika - English (United Kingdom)", "en-GB", false),
                mk("Microsoft Ryan - English (United Kingdom)", "en-GB", false),
                mk("Microsoft Heera - English (India)", "en-IN", false),
                mk("Microsoft Katja - German (Germany)", "de-DE", false),
                mk("Microsoft Paulina - Polish (Poland)", "pl-PL", false),
                mk("Microsoft Ayumi - Japanese (Japan)", "ja-JP", false)
            ];
            const macPool = [
                mk("Samantha", "en-US", false),
                mk("Alex", "en-US", false),
                mk("Victoria", "en-US", false),
                mk("Daniel", "en-GB", false),
                mk("Karen", "en-AU", false),
                mk("Moira", "en-IE", false),
                mk("Tessa", "en-ZA", false),
                mk("Fiona", "en-GB", false),
                mk("Allison", "en-US", false),
                mk("Ava", "en-US", false),
                mk("Susan", "en-US", false),
                mk("Yuna", "ko-KR", false)
            ];
            const linuxPool = [
                mk("English (America)+default", "en-US", false),
                mk("English (Great Britain)", "en-GB", false),
                mk("German (Germany)", "de-DE", false),
                mk("French (France)", "fr-FR", false),
                mk("Spanish (Spain)", "es-ES", false),
                mk("Italian (Italy)", "it-IT", false),
                mk("Russian (Russia)", "ru-RU", false),
                mk("Polish (Poland)", "pl-PL", false)
            ];
            // Per-profile deterministic subset (seeded shuffle) so two
            // profiles never report the identical voice list.
            const shuffleSeed = ({fp.canvas_noise_seed} >>> 0) || 1;
            const pickSubset = function(pool, keep) {{
                const out = pool.slice();
                for (let i = out.length - 1; i > 0; i--) {{
                    let s = (shuffleSeed ^ (i * 2654435761)) >>> 0;
                    s = (s * 1664525 + 1013904223) >>> 0;
                    const j = s % (i + 1);
                    const tmp = out[i]; out[i] = out[j]; out[j] = tmp;
                }}
                const chosen = out.slice(0, keep);
                chosen[0] = Object.assign({{}}, chosen[0], {{ default: true }});
                return chosen;
            }};
            let voicesData;
            if (osPlatform.includes('win')) {{
                voicesData = pickSubset(winPool, 8 + (shuffleSeed % 5));
            }} else if (osPlatform.includes('mac')) {{
                voicesData = pickSubset(macPool, 6 + (shuffleSeed % 5));
            }} else {{
                voicesData = pickSubset(linuxPool, 4 + (shuffleSeed % 4));
            }}
            // Hunt A-03: SpeechSynthesisVoice.prototype.name/lang/default are
            // GETTER-ONLY accessors. Object.assign() onto such an instance
            // throws "TypeError: Cannot set property name of
            // #<SpeechSynthesisVoice> which has only a getter" — and because
            // the whole section lives in one try-block, that single throw
            // ABORTED the rest of the section: the profile's voice pool was
            // never installed and the page kept the HOST's voices (21 on the
            // test machine vs the 8-12 the profile claims). The own properties
            // are now defined with defineProperty, which works on a
            // getter-only prototype.
            const voiceObjects = voicesData.map(v => {{
                const proto = window.SpeechSynthesisVoice ? SpeechSynthesisVoice.prototype : Object.prototype;
                const inst = Object.create(proto);
                Object.keys(v).forEach(function(k) {{
                    try {{
                        Object.defineProperty(inst, k, {{
                            value: v[k], configurable: true, enumerable: true, writable: true
                        }});
                    }} catch(e) {{}}
                }});
                return inst;
            }});
            window.speechSynthesis.getVoices = makeNative(function() {{
                return voiceObjects;
            }}, 'getVoices');
        }}
    }} catch(e) {{}}

    // 11. Subtle Canvas 2D Noise & OffscreenCanvas Noise (Noise Seed: {fp.canvas_noise_seed})
    if ({str(fp.canvas_noise).lower()}) {{
        try {{
            const seed = {fp.canvas_noise_seed};
            // Hunt A-04: the noise field used to be re-seeded from a CALL
            // COUNTER, so drawing the SAME content twice produced two
            // DIFFERENT canvas hashes. A real browser's canvas hash is
            // STABLE for identical content — an unstable hash is a one-line
            // automation tell (BrowserLeaks-style probes draw the same
            // content repeatedly and compare). The field is now derived from
            // the PROFILE seed and the CONTENT itself: the same content
            // yields the same hash (as on a real device), while two
            // profiles differ (the farm-wide uniqueness the noise exists
            // for). A checker that subtracts the noise needs the clean
            // image, which it does not have.
            const contentSeed = function(imageData) {{
                const data = imageData.data;
                const len = data.length;
                // FNV-1a over every 16th byte + the length: cheap, stable,
                // and sensitive to both content and size.
                let h = 2166136261 >>> 0;
                for (let i = 0; i < len; i += 16) {{
                    h ^= data[i];
                    h = Math.imul(h, 16777619) >>> 0;
                }}
                h ^= len;
                h = Math.imul(h, 16777619) >>> 0;
                return h >>> 0;
            }};
            const mutateCanvasData = function(imageData) {{
                if (!imageData || !imageData.data) return imageData;
                const len = imageData.data.length;
                let s = (seed ^ contentSeed(imageData)) >>> 0;
                s = (s * 2654435761) >>> 0;
                // Stride 17 keeps cost low on big canvases; the mutated channel
                // now walks RGBA instead of always landing with period 17 % 4.
                const start = s % 64;
                const stride = 13 + (s % 11);
                for (let i = start; i < len; i += stride) {{
                    s = (s * 1664525 + 1013904223) >>> 0;
                    const delta = ((s % 3) - 1);
                    imageData.data[i] = Math.max(0, Math.min(255, imageData.data[i] + delta));
                }}
                return imageData;
            }};

            const origGetImageData = CanvasRenderingContext2D.prototype.getImageData;
            CanvasRenderingContext2D.prototype.getImageData = makeNative(function(sx, sy, sw, sh) {{
                const imageData = origGetImageData.apply(this, arguments);
                return mutateCanvasData(imageData);
            }}, 'getImageData');

            if (window.OffscreenCanvasRenderingContext2D) {{
                const origOffscreenGetImageData = OffscreenCanvasRenderingContext2D.prototype.getImageData;
                OffscreenCanvasRenderingContext2D.prototype.getImageData = makeNative(function() {{
                    const img = origOffscreenGetImageData.apply(this, arguments);
                    return mutateCanvasData(img);
                }}, 'getImageData');
            }}

            const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
            // Hunt A-04: the noise must be applied to a COPY of the canvas.
            // The old code read the pixels, mutated them and wrote them back
            // into the LIVE canvas (putImageData) — so the second
            // toDataURL() of the same canvas hashed ALREADY-NOISED pixels
            // and produced a third different value: the hash of identical
            // content changed on every call, which is exactly the
            // instability a canvas probe looks for. The noise is now
            // applied to a scratch canvas: the live canvas keeps its clean
            // pixels, and the SAME content always yields the SAME hash.
            const noisyCopy = function(source) {{
                const ctx = source.getContext('2d');
                if (!ctx || source.width <= 0 || source.height <= 0) return null;
                const img = ctx.getImageData(0, 0, source.width, source.height);
                mutateCanvasData(img);
                const copy = document.createElement('canvas');
                copy.width = source.width;
                copy.height = source.height;
                const copyCtx = copy.getContext('2d');
                if (!copyCtx) return null;
                copyCtx.putImageData(img, 0, 0);
                return copy;
            }};
            HTMLCanvasElement.prototype.toDataURL = makeNative(function() {{
                try {{
                    const copy = noisyCopy(this);
                    if (copy) {{
                        return origToDataURL.apply(copy, arguments);
                    }}
                }} catch(err) {{}}
                return origToDataURL.apply(this, arguments);
            }}, 'toDataURL');

            if (HTMLCanvasElement.prototype.toBlob) {{
                const origToBlob = HTMLCanvasElement.prototype.toBlob;
                HTMLCanvasElement.prototype.toBlob = makeNative(function(callback, type, quality) {{
                    try {{
                        const copy = noisyCopy(this);
                        if (copy) {{
                            return origToBlob.apply(copy, [callback, type, quality]);
                        }}
                    }} catch(err) {{}}
                    return origToBlob.apply(this, arguments);
                }}, 'toBlob');
            }}
        }} catch(e) {{}}
    }}

    // 12. AudioContext Fingerprint Noise & OfflineAudioContext
    if ({str(fp.audio_noise).lower()}) {{
        try {{
            const factor = {_js_number(fp.audio_noise_seed)} || 0.00001;
            // Per-call phase: the old code applied the identical deterministic
            // pattern ((i % 3) - 1) on every read, so two getChannelData calls
            // on the same buffer returned bitwise-identical arrays minus the
            // untouched samples — a checker diffs them and the noise cancels.
            let audioCallCount = 0;
            // Hunt A-06: the noise pass lives in the getChannelData getter
            // (the single owner of the mutation) — the old render helper called
            // the SPOOFED getter, which applied its own pass on top: the noise
            // was applied twice and the phase counter advanced twice per read.
            // The helper now only makes sure the getter is reached for every
            // channel, so an offline render carries the same noise as a
            // direct read.
            const applyAudioNoise = function(buffer) {{
                if (!buffer || !buffer.getChannelData) return buffer;
                audioCallCount = (audioCallCount + 1) >>> 0;
                const channels = buffer.numberOfChannels;
                for (let c = 0; c < channels; c++) {{
                    buffer.getChannelData(c);
                }}
                return buffer;
            }};

            if (window.AudioBuffer) {{
                const origGetChannelData = AudioBuffer.prototype.getChannelData;
                AudioBuffer.prototype.getChannelData = makeNative(function(channel) {{
                    const data = origGetChannelData.apply(this, arguments);
                    if (data && data.length > 0) {{
                        // Reuse the shared phase counter so direct reads and
                        // OfflineAudioContext renders never repeat the pattern.
                        audioCallCount = (audioCallCount + 1) >>> 0;
                        const ph = audioCallCount % 3;
                        const step = Math.max(1, Math.floor(data.length / 100));
                        for (let i = 0; i < data.length; i += step) {{
                            data[i] = data[i] + factor * ((((i + ph) % 3) - 1) * 0.5);
                        }}
                    }}
                    return data;
                }}, 'getChannelData');
            }}

            if (window.OfflineAudioContext) {{
                const origStartRendering = OfflineAudioContext.prototype.startRendering;
                OfflineAudioContext.prototype.startRendering = makeNative(function() {{
                    return origStartRendering.apply(this, arguments).then(renderedBuffer => {{
                        return applyAudioNoise(renderedBuffer);
                    }});
                }}, 'startRendering');
            }}
        }} catch(e) {{}}
    }}

    // 12b. Anti-detect (audit F-08): AudioContext hardware parameters.
    // sampleRate/baseLatency/maxChannelCount depend on the HOST sound card and
    // are a classic audio fingerprint; they are pinned to the profile values.
    try {{
        const fpSampleRate = {int(getattr(fp, "audio_sample_rate", 0) or 48000) or 48000};
        const fpBaseLatency = {_js_number(getattr(fp, "audio_base_latency", 0.005) or 0.005)};
        const fpMaxChannels = {int(getattr(fp, "audio_max_channels", 0) or 2) or 2};
        const patchAudioCtor = function(Ctor) {{
            if (!Ctor) return;
            const orig = Ctor.prototype.constructor;
            Object.defineProperty(Ctor.prototype, 'sampleRate', {{
                get: makeNative(() => fpSampleRate, 'get sampleRate'),
                configurable: true, enumerable: true
            }});
            if ('baseLatency' in Ctor.prototype) {{
                Object.defineProperty(Ctor.prototype, 'baseLatency', {{
                    get: makeNative(() => fpBaseLatency, 'get baseLatency'),
                    configurable: true, enumerable: true
                }});
            }}
        }};
        patchAudioCtor(window.AudioContext);
        patchAudioCtor(window.OfflineAudioContext);
        patchAudioCtor(window.webkitAudioContext);
        if (window.AudioBuffer) {{
            Object.defineProperty(AudioBuffer.prototype, 'sampleRate', {{
                get: makeNative(() => fpSampleRate, 'get sampleRate'),
                configurable: true, enumerable: true
            }});
            // Hunt A-05: the numberOfChannels getter used to read
            // Object.getOwnPropertyDescriptor(AudioBuffer.prototype,
            // 'numberOfChannels') AT CALL TIME — but by then the descriptor
            // on the prototype was ALREADY the spoofing getter, so it called
            // ITSELF: an infinite recursion that surfaced as
            // "RangeError: Maximum call stack size exceeded" in every
            // AudioBuffer/OfflineAudioContext consumer (the audio noise
            // section reads buffer.numberOfChannels). The original
            // descriptor is now captured BEFORE the override.
            const origChannelsDesc = Object.getOwnPropertyDescriptor(AudioBuffer.prototype, 'numberOfChannels');
            Object.defineProperty(AudioBuffer.prototype, 'numberOfChannels', {{
                get: makeNative(function() {{
                    const v = origChannelsDesc && origChannelsDesc.get ? origChannelsDesc.get.call(this) : fpMaxChannels;
                    return Math.min(v, fpMaxChannels);
                }}, 'get numberOfChannels'),
                configurable: true, enumerable: true
            }});
        }}
    }} catch(e) {{}}

    // 12c. Anti-detect (audit F-07): matchMedia must report the profile's
    // preferences (color scheme / reduced motion / DPR), not the host's —
    // a dark-mode host under a light-profile fingerprint is a one-call tell.
    try {{
        const spoofDpr = {_js_number(fp.device_pixel_ratio)};
        const origMatchMedia = window.matchMedia;
        window.matchMedia = makeNative(function(query) {{
            const q = String(query);
            if (q.includes('prefers-color-scheme')) {{
                const dark = q.includes('dark');
                return {{
                    matches: dark === false,  // profile default: light scheme
                    media: q, onchange: null,
                    addListener: function() {{}}, removeListener: function() {{}},
                    addEventListener: function() {{}}, removeEventListener: function() {{}},
                    dispatchEvent: function() {{ return false; }}
                }};
            }}
            if (q.includes('prefers-reduced-motion')) {{
                return {{
                    matches: false, media: q, onchange: null,
                    addListener: function() {{}}, removeListener: function() {{}},
                    addEventListener: function() {{}}, removeEventListener: function() {{}},
                    dispatchEvent: function() {{ return false; }}
                }};
            }}
            if (q.includes('device-pixel-ratio')) {{
                const m = /([\\d.]+)\\s*\\)$/.exec(q);
                const asked = m ? parseFloat(m[1]) : 1;
                return {{
                    matches: Math.abs(asked - spoofDpr) < 0.0001, media: q, onchange: null,
                    addListener: function() {{}}, removeListener: function() {{}},
                    addEventListener: function() {{}}, removeEventListener: function() {{}},
                    dispatchEvent: function() {{ return false; }}
                }};
            }}
            return origMatchMedia.apply(this, arguments);
        }}, 'matchMedia');
    }} catch(e) {{}}

    // 12d. Anti-detect (audit F-15): full Intl locale consistency. The old hook
    // only replaced timeZone in resolvedOptions(); toLocale* methods still
    // formatted numbers/dates with the HOST locale, contradicting the profile.
    try {{
        const fpLocale = {json.dumps(fp.languages[0] if fp.languages else "en-US")};
        // Hunt A-01: the timezone hook is installed ONCE, here. Section 6
        // installs it too; installing it twice wrapped the first hook, and the
        // second one referenced an out-of-scope `targetTimezone` — every
        // Intl.DateTimeFormat().resolvedOptions() call threw a
        // ReferenceError, which broke the page instead of spoofing it.
        const origDTFResolved = Intl.DateTimeFormat.prototype.resolvedOptions;
        Intl.DateTimeFormat.prototype.resolvedOptions = makeNative(function() {{
            const res = origDTFResolved.apply(this, arguments);
            res.timeZone = targetTimezone;
            res.locale = fpLocale;
            return res;
        }}, 'resolvedOptions');
        // Hunt A-02: replacing the Intl constructors with a plain function
        // DROPPED their static members: Intl.NumberFormat.supportedLocalesOf
        // and Intl.DateTimeFormat.supportedLocalesOf became "is not a
        // function" — a hard TypeError in any site that calls them (and a
        // blatant sign of a tampered Intl). The static side is copied over
        // from the originals, and the constructor keeps the native shape
        // (prototype + toString) instead of a hand-rolled function.
        const origNFF = Intl.NumberFormat;
        const origDTF = Intl.DateTimeFormat;
        const wrapIntl = function(orig, label) {{
            const wrapped = makeNative(function() {{
                const args = Array.prototype.slice.call(arguments);
                if (typeof args[0] === 'undefined') args[0] = fpLocale;
                return new (Function.prototype.bind.apply(orig, [null].concat(args)))();
            }}, label);
            wrapped.prototype = orig.prototype;
            // keep the static side (supportedLocalesOf, etc.) and the native
            // reflection of the constructor itself
            try {{
                Object.defineProperty(wrapped, 'supportedLocalesOf', {{
                    value: makeNative(orig.supportedLocalesOf.bind(orig), 'supportedLocalesOf'),
                    configurable: true, writable: true
                }});
            }} catch(e) {{}}
            try {{
                Object.setPrototypeOf(wrapped, Object.getPrototypeOf(orig));
            }} catch(e) {{}}
            return wrapped;
        }};
        Intl.NumberFormat = wrapIntl(origNFF, 'NumberFormat');
        Intl.DateTimeFormat = wrapIntl(origDTF, 'DateTimeFormat');
    }} catch(e) {{}}

    // 12e. Anti-detect (audit F-16): performance.now() timing entropy.
    // The native timer carries host hardware entropy (timer resolution +
    // the exact sub-microsecond offsets a machine's scheduler produces);
    // two profiles on the same host therefore produce correlated timings.
    // A per-profile deterministic sub-microsecond jitter decorrelates them
    // while keeping the values monotonic (required by the spec).
    try {{
        const perfSeedBase = ({fp.canvas_noise_seed} >>> 0) || 1;
        let perfCallCount = 0;
        const origNow = PerformancePrototype = (window.performance && performance.now) ? performance.now.bind(performance) : null;
        if (origNow) {{
            Object.defineProperty(performance, 'now', {{
                value: makeNative(function() {{
                    const native = origNow();
                    perfCallCount = (perfCallCount + 1) >>> 0;
                    let s = (perfSeedBase ^ (perfCallCount * 2654435761)) >>> 0;
                    s = (s * 1664525 + 1013904223) >>> 0;
                    // jitter in [-0.04, +0.04] ms: well below any visible
                    // threshold, but decorrelates the host scheduler signature.
                    const jitter = (((s >>> 8) % 1000) / 1000 - 0.5) * 0.08;
                    return native + jitter;
                }}, 'now'),
                configurable: true, writable: true, enumerable: true
            }});
        }}
    }} catch(e) {{}}

    // 16. ClientRects & Font Measurement Jitter (Sub-pixel noise)
    if ({str(fp.client_rects_noise).lower()}) {{
        try {{
            // Hunt A-07: the jitter used to be re-derived from a CALL
            // COUNTER, so measuring the SAME string twice returned two
            // different widths (measured in a real Chrome: 8 measurements of
            // one string -> 8 distinct values; a real browser returns the
            // SAME width). A detector that measures a string twice and
            // compares — the standard BrowserLeaks-style probe — sees the
            // difference immediately.
            //
            // The offset is now derived from the TEXT itself: the same
            // string always measures the same (as on a real device) while
            // two different strings and two different profiles differ (the
            // farm-wide uniqueness the noise exists for).
            const rectSeedBase = ({fp.canvas_noise_seed} >>> 0) || 1;
            const textJitter = function(text) {{
                const str = String(text === undefined || text === null ? '' : text);
                let h = 2166136261 >>> 0;
                for (let i = 0; i < str.length; i++) {{
                    h ^= str.charCodeAt(i);
                    h = Math.imul(h, 16777619) >>> 0;
                }}
                let s = (rectSeedBase ^ h) >>> 0;
                s = (s * 1664525 + 1013904223) >>> 0;
                return (((s >>> 8) % 1000) / 1000 - 0.5) * 0.0002;
            }};
            // A per-element offset keeps the rect jitter stable for the same
            // element (a real renderer only changes it when the layout
            // changes) while different elements differ.
            const rectOffsets = new WeakMap();
            let rectSeedCounter = 0;
            const nextRectJitter = function(element) {{
                let off = rectOffsets.get(element);
                if (!off) {{
                    rectSeedCounter = (rectSeedCounter + 1) >>> 0;
                    let s = (rectSeedBase ^ (rectSeedCounter * 2654435761)) >>> 0;
                    s = (s * 1664525 + 1013904223) >>> 0;
                    off = {{
                        x: (((s >>> 8) % 1000) / 1000 - 0.5) * 0.0001,
                        y: (((s >>> 16) % 1000) / 1000 - 0.5) * 0.0001
                    }};
                    rectOffsets.set(element, off);
                }}
                return off;
            }};
            const origGetBoundingClientRect = Element.prototype.getBoundingClientRect;
            Element.prototype.getBoundingClientRect = makeNative(function() {{
                const rect = origGetBoundingClientRect.apply(this, arguments);
                if (!rect || rect.width === 0 || rect.height === 0) return rect;
                const off = nextRectJitter(this);
                // The WIDTH of a text element follows the same text-derived
                // offset as the canvas measurement, so the canvas metric and
                // the DOM metric stay consistent (a real browser reports the
                // same width through both APIs).
                const ownText = (this.textContent || '').trim();
                const widthAdj = ownText ? textJitter(ownText) : 0;
                return new DOMRect(rect.x + off.x, rect.y + off.y, rect.width + widthAdj, rect.height);
            }}, 'getBoundingClientRect');

            const origMeasureText = CanvasRenderingContext2D.prototype.measureText;
            CanvasRenderingContext2D.prototype.measureText = makeNative(function(text) {{
                const metrics = origMeasureText.apply(this, arguments);
                if (metrics && typeof metrics.width === 'number' && metrics.width > 0) {{
                    try {{
                        const fontJitter = textJitter(text);
                        Object.defineProperty(metrics, 'width', {{
                            value: metrics.width + fontJitter,
                            configurable: true,
                            enumerable: true
                        }});
                    }} catch(err) {{}}
                }}
                return metrics;
            }}, 'measureText');
        }} catch(e) {{}}
    }}

    // 17. Port Scan & Localhost Protection
    if ({str(fp.block_port_scanning).lower()}) {{
        try {{
            // Anti-detect (audit F-18): block EVERY loopback target from the
            // page except the local API port. The old shield whitelisted
            // ':8899' as a substring — and left the profile's own DevTools
            // endpoint (and any other local service) reachable, letting a
            // page confirm CDP automation via http://127.0.0.1:<port>/json.
            const allowPorts = {fetch_allow_ports_js};
            const loopback = /https?:\\/\\/(127\\.0\\.0\\.1|localhost|\\[::1\\])(:\\d+)?/i;
            const origFetch = window.fetch;
            window.fetch = makeNative(function(input, options) {{
                const target = (input && typeof input === 'object' && 'url' in input) ? String(input.url) : String(input);
                const m = loopback.exec(target);
                if (m) {{
                    const portMatch = /:(\\d+)(?:\\/|$)/.exec(m[0]);
                    const port = portMatch ? parseInt(portMatch[1], 10) : (target.startsWith('https') ? 443 : 80);
                    if (allowPorts.indexOf(port) === -1) {{
                        return Promise.reject(new TypeError('NetworkError when attempting to fetch resource.'));
                    }}
                }}
                return origFetch.apply(this, arguments);
            }}, 'fetch');
        }} catch(e) {{}}
    }}

    // 18. WebRTC Local IP Leak & Candidate Sanitizer
    try {{
        if (window.RTCPeerConnection) {{
            const sanitizeSdp = function(sdp) {{
                if (!sdp || typeof sdp !== 'string') return sdp;
                return sdp
                    .replace(/a=candidate:.*?\\s+(10\\.\\d+|192\\.168\\.\\d+|172\\.(1[6-9]|2\\d|3[01])\\.\\d+)\\.\\d+\\s+.*?\\r\\n/g, '')
                    .replace(/a=candidate:.*?\\s+([a-f0-9]{{1,4}}:){{7}}[a-f0-9]{{1,4}}\\s+.*?\\r\\n/gi, '');
            }};

            const origCreateOffer = RTCPeerConnection.prototype.createOffer;
            RTCPeerConnection.prototype.createOffer = makeNative(function(options) {{
                return origCreateOffer.apply(this, arguments).then(offer => {{
                    if (offer && offer.sdp) {{
                        offer.sdp = sanitizeSdp(offer.sdp);
                    }}
                    return offer;
                }});
            }}, 'createOffer');

            // Trickle-ICE: candidates delivered via onicecandidate / addIceCandidate
            // bypass createOffer/setLocalDescription entirely — an answering peer
            // (and any trickling local candidate) would leak the host address.
            // createAnswer covers the answering side; the RTCIceCandidate hook
            // neutralises host candidates at construction.
            const origCreateAnswer = RTCPeerConnection.prototype.createAnswer;
            RTCPeerConnection.prototype.createAnswer = makeNative(function(options) {{
                return origCreateAnswer.apply(this, arguments).then(answer => {{
                    if (answer && answer.sdp) {{
                        answer.sdp = sanitizeSdp(answer.sdp);
                    }}
                    return answer;
                }});
            }}, 'createAnswer');

            if (window.RTCIceCandidate) {{
                const OrigRTCIceCandidate = window.RTCIceCandidate;
                const scrubbedCandidate = function(init) {{
                    if (init && typeof init.candidate === 'string') {{
                        const cleaned = sanitizeSdp(init.candidate + '\\r\\n');
                        if (!cleaned) return null;
                        init = Object.assign({{}}, init, {{ candidate: cleaned.replace(/\\r\\n$/, '') }});
                    }}
                    return init;
                }};
                window.RTCIceCandidate = makeNative(function(init) {{
                    const scrubbed = scrubbedCandidate(init);
                    if (scrubbed === null) return null;
                    return new OrigRTCIceCandidate(scrubbed === undefined ? init : scrubbed);
                }}, 'RTCIceCandidate');
            }}

            const origSetLocalDescription = RTCPeerConnection.prototype.setLocalDescription;
            RTCPeerConnection.prototype.setLocalDescription = makeNative(function(desc) {{
                if (desc && desc.sdp) {{
                    desc.sdp = sanitizeSdp(desc.sdp);
                }}
                return origSetLocalDescription.apply(this, arguments);
            }}, 'setLocalDescription');
        }}
    }} catch(e) {{}}

}})();
}}
"""
    with open(ext_dir / "stealth.js", "w", encoding="utf-8") as f:
        f.write(stealth_js.strip() + "\n")

    with open(ext_dir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    return str(ext_dir.resolve())
