"""
Dynamic Chrome Extension Generator for Proxy Authentication and Total System Hardware Isolation.
Ensures ZERO host PC characteristics (CPU, RAM, GPU, Screen, Audio, Webcam, Battery, Network, Geolocation, Fonts)
can be queried or fingerprinted by websites or anti-fraud systems.
"""

import json
import shutil
from pathlib import Path

from ..models.profile import BrowserProfile


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
    profile: BrowserProfile, extensions_base_dir: Path, chrome_version: str | None = None
) -> str | None:
    """
    Creates an unpacked Chrome extension for the profile with total hardware isolation and proxy auth.

    When ``chrome_version`` is provided (the *real* installed Chrome build), the
    generated stealth source is rebuilt with a matching UA / Client-Hints version
    so the extension shields cannot contradict the runtime UA (audit fix P0-1).
    """
    ext_dir = extensions_base_dir / profile.id
    if ext_dir.exists():
        shutil.rmtree(ext_dir, ignore_errors=True)
    ext_dir.mkdir(parents=True, exist_ok=True)

    fp = profile.fingerprint
    if chrome_version:
        fp = _fingerprint_with_runtime_chrome_version(fp, chrome_version)
    proxy = profile.proxy

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
    ua_full_version = fp.app_version.split("Chrome/")[1].split(" ")[0] if "Chrome/" in fp.app_version else "133.0.0.0"
    ua_full_version_json = json.dumps(ua_full_version)
    timezone_json = json.dumps(fp.timezone)
    webgl_vendor_json = json.dumps(fp.webgl_vendor)
    webgl_renderer_json = json.dumps(fp.webgl_renderer)

    # Derive WebGPU vendor and architecture matching WebGL GPU Vendor & Model
    gpu_vendor_lower = (fp.webgl_vendor + " " + fp.webgl_renderer).lower()
    if "nvidia" in gpu_vendor_lower:
        gpu_vendor_str = "nvidia"
        gpu_arch_str = (
            "ada lovelace" if "40" in fp.webgl_renderer else ("ampere" if "30" in fp.webgl_renderer else "turing")
        )
    elif "amd" in gpu_vendor_lower or "radeon" in gpu_vendor_lower:
        gpu_vendor_str = "amd"
        gpu_arch_str = "rdna 3" if "7900" in fp.webgl_renderer else "rdna 2"
    elif "apple" in gpu_vendor_lower:
        gpu_vendor_str = "apple"
        gpu_arch_str = "apple"
    else:
        gpu_vendor_str = "intel"
        gpu_arch_str = "alchemist" if "arc" in fp.webgl_renderer.lower() else "gen12"

    webgpu_vendor_json = json.dumps(gpu_vendor_str)
    webgpu_arch_json = json.dumps(gpu_arch_str)

    stealth_js = f"""
// Nazak Total Hardware Shield v2.5 Enterprise Stealth
if (window.__nazakShieldApplied) {{
    // Already applied on this document (extension content script + CDP injector may both run).
}} else {{
window.__nazakShieldApplied = true;
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
            get: makeNative(() => {fp.device_memory}, 'get deviceMemory'),
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
        Object.defineProperty(Window.prototype, 'devicePixelRatio', {{ get: makeNative(() => {fp.device_pixel_ratio}, 'get devicePixelRatio'), configurable: true, enumerable: true }});
    }} catch(e) {{}}

    // 6. Timezone & Locale Formatting
    try {{
        const targetTimezone = {timezone_json};
        const targetOffset = {fp.timezone_offset};

        const origResolvedOptions = Intl.DateTimeFormat.prototype.resolvedOptions;
        Intl.DateTimeFormat.prototype.resolvedOptions = makeNative(function() {{
            const res = origResolvedOptions.apply(this, arguments);
            res.timeZone = targetTimezone;
            return res;
        }}, 'resolvedOptions');

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
            proto.getParameter = makeNative(function(param) {{
                if (param in webglParams) return webglParams[param];
                if (param === 3386) return new Int32Array({json.dumps(fp.max_viewport_dims)});
                return origGetParam.apply(this, arguments);
            }}, 'getParameter');
        }};

        if (window.WebGLRenderingContext) hookWebGL(WebGLRenderingContext.prototype);
        if (window.WebGL2RenderingContext) hookWebGL(WebGL2RenderingContext.prototype);
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
    try {{
        if (window.speechSynthesis && window.speechSynthesis.getVoices) {{
            const osPlatform = {platform_json}.toLowerCase();
            let voicesData = [];
            if (osPlatform.includes('win')) {{
                voicesData = [
                    {{ name: "Microsoft David - English (United States)", lang: "en-US", default: true, localService: true, voiceURI: "Microsoft David - English (United States)" }},
                    {{ name: "Microsoft Zira - English (United States)", lang: "en-US", default: false, localService: true, voiceURI: "Microsoft Zira - English (United States)" }},
                    {{ name: "Microsoft Mark - English (United States)", lang: "en-US", default: false, localService: true, voiceURI: "Microsoft Mark - English (United States)" }}
                ];
            }} else if (osPlatform.includes('mac')) {{
                voicesData = [
                    {{ name: "Samantha", lang: "en-US", default: true, localService: true, voiceURI: "Samantha" }},
                    {{ name: "Alex", lang: "en-US", default: false, localService: true, voiceURI: "Alex" }},
                    {{ name: "Victoria", lang: "en-US", default: false, localService: true, voiceURI: "Victoria" }}
                ];
            }} else {{
                voicesData = [
                    {{ name: "English (America)+default", lang: "en-US", default: true, localService: true, voiceURI: "default" }}
                ];
            }}
            const voiceObjects = voicesData.map(v => Object.assign(Object.create(window.SpeechSynthesisVoice ? SpeechSynthesisVoice.prototype : Object.prototype), v));
            window.speechSynthesis.getVoices = makeNative(function() {{
                return voiceObjects;
            }}, 'getVoices');
        }}
    }} catch(e) {{}}

    // 11. Subtle Canvas 2D Noise & OffscreenCanvas Noise (Noise Seed: {fp.canvas_noise_seed})
    if ({str(fp.canvas_noise).lower()}) {{
        try {{
            const seed = {fp.canvas_noise_seed};
            const mutateCanvasData = function(imageData) {{
                if (!imageData || !imageData.data) return imageData;
                let s = seed;
                const len = imageData.data.length;
                for (let i = (s % 7); i < len; i += 17) {{
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
            HTMLCanvasElement.prototype.toDataURL = makeNative(function() {{
                try {{
                    const ctx = this.getContext('2d');
                    if (ctx && this.width > 0 && this.height > 0) {{
                        const img = ctx.getImageData(0, 0, Math.min(this.width, 16), Math.min(this.height, 16));
                        mutateCanvasData(img);
                        ctx.putImageData(img, 0, 0);
                    }}
                }} catch(err) {{}}
                return origToDataURL.apply(this, arguments);
            }}, 'toDataURL');

            if (HTMLCanvasElement.prototype.toBlob) {{
                const origToBlob = HTMLCanvasElement.prototype.toBlob;
                HTMLCanvasElement.prototype.toBlob = makeNative(function(callback, type, quality) {{
                    try {{
                        const ctx = this.getContext('2d');
                        if (ctx && this.width > 0 && this.height > 0) {{
                            const img = ctx.getImageData(0, 0, Math.min(this.width, 16), Math.min(this.height, 16));
                            mutateCanvasData(img);
                            ctx.putImageData(img, 0, 0);
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
            const factor = {fp.audio_noise_seed} || 0.00001;
            const applyAudioNoise = function(buffer) {{
                if (!buffer || !buffer.getChannelData) return buffer;
                for (let c = 0; c < buffer.numberOfChannels; c++) {{
                    const data = buffer.getChannelData(c);
                    if (data && data.length > 0) {{
                        const step = Math.max(1, Math.floor(data.length / 100));
                        for (let i = 0; i < data.length; i += step) {{
                            data[i] = data[i] + factor * (((i % 3) - 1) * 0.5);
                        }}
                    }}
                }}
                return buffer;
            }};

            if (window.AudioBuffer) {{
                const origGetChannelData = AudioBuffer.prototype.getChannelData;
                AudioBuffer.prototype.getChannelData = makeNative(function(channel) {{
                    const data = origGetChannelData.apply(this, arguments);
                    if (data && data.length > 0) {{
                        const step = Math.max(1, Math.floor(data.length / 100));
                        for (let i = 0; i < data.length; i += step) {{
                            data[i] = data[i] + factor * (((i % 3) - 1) * 0.5);
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

    // 16. ClientRects & Font Measurement Jitter (Sub-pixel noise)
    if ({str(fp.client_rects_noise).lower()}) {{
        try {{
            const seed = {fp.canvas_noise_seed};
            const jitter = ((seed % 7) - 3) * 0.00005;
            const origGetBoundingClientRect = Element.prototype.getBoundingClientRect;
            Element.prototype.getBoundingClientRect = makeNative(function() {{
                const rect = origGetBoundingClientRect.apply(this, arguments);
                if (!rect || rect.width === 0 || rect.height === 0) return rect;
                return new DOMRect(rect.x + jitter, rect.y + jitter, rect.width, rect.height);
            }}, 'getBoundingClientRect');

            const fontJitter = ((seed % 5) - 2) * 0.0001;
            const origMeasureText = CanvasRenderingContext2D.prototype.measureText;
            CanvasRenderingContext2D.prototype.measureText = makeNative(function(text) {{
                const metrics = origMeasureText.apply(this, arguments);
                if (metrics && typeof metrics.width === 'number' && metrics.width > 0) {{
                    try {{
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
            const origFetch = window.fetch;
            window.fetch = makeNative(function(url, options) {{
                if (typeof url === 'string' && (url.includes('127.0.0.1') || url.includes('localhost')) && !url.includes(':8899')) {{
                    return Promise.reject(new TypeError('NetworkError when attempting to fetch resource.'));
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
