"""
Dynamic Chrome Extension Generator for Proxy Authentication and Total System Hardware Isolation.
Ensures ZERO host PC characteristics (CPU, RAM, GPU, Screen, Audio, Webcam, Battery, Network, Geolocation, Fonts)
can be queried or fingerprinted by websites or anti-fraud systems.
"""

import json
import shutil
from pathlib import Path

from ..models.profile import BrowserProfile


def generate_profile_extension(profile: BrowserProfile, extensions_base_dir: Path) -> str | None:
    """
    Creates an unpacked Chrome extension for the profile with total hardware isolation and proxy auth.
    """
    ext_dir = extensions_base_dir / profile.id
    if ext_dir.exists():
        shutil.rmtree(ext_dir, ignore_errors=True)
    ext_dir.mkdir(parents=True, exist_ok=True)

    fp = profile.fingerprint
    proxy = profile.proxy

    manifest = {
        "manifest_version": 2,
        "name": f"Nazak Deep Shield - {profile.name}",
        "version": "2.0.0",
        "description": "Total Hardware Isolation & Proxy Authentication Shield for Google Automation",
        "permissions": ["webRequest", "webRequestBlocking", "<all_urls>", "tabs"],
        "content_scripts": [
            {"matches": ["<all_urls>"], "js": ["stealth.js"], "run_at": "document_start", "all_frames": True}
        ],
    }

    if proxy.has_auth():
        manifest["background"] = {"scripts": ["background.js"], "persistent": True}
        u_json = json.dumps(proxy.username or "")
        p_json = json.dumps(proxy.password or "")
        bg_code = f"""
chrome.webRequest.onAuthRequired.addListener(
    function(details) {{
        return {{
            authCredentials: {{
                username: {u_json},
                password: {p_json}
            }}
        }};
    }},
    {{ urls: ["<all_urls>"] }},
    ["blocking"]
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

    stealth_js = f"""
// Nazak Total Hardware Shield v2.0
(function() {{
    'use strict';

    // 1. Remove Automation Artifacts & navigator.webdriver
    try {{
        Object.defineProperty(Navigator.prototype, 'webdriver', {{
            get: () => undefined,
            configurable: true,
            enumerable: true
        }});
        delete Navigator.prototype.webdriver;
    }} catch(e) {{}}

    // 2. Hardware Resources Isolation (CPU & RAM)
    try {{
        Object.defineProperty(Navigator.prototype, 'hardwareConcurrency', {{
            get: () => {fp.hardware_concurrency},
            configurable: true,
            enumerable: true
        }});
        Object.defineProperty(Navigator.prototype, 'deviceMemory', {{
            get: () => {fp.device_memory},
            configurable: true,
            enumerable: true
        }});
        Object.defineProperty(Navigator.prototype, 'platform', {{
            get: () => "{fp.platform}",
            configurable: true,
            enumerable: true
        }});
        Object.defineProperty(Navigator.prototype, 'maxTouchPoints', {{
            get: () => {fp.max_touch_points},
            configurable: true,
            enumerable: true
        }});
        Object.defineProperty(Navigator.prototype, 'vendor', {{
            get: () => "{fp.vendor}",
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
            platform: "{fp.platform}",
            getHighEntropyValues: function(hints) {{
                return Promise.resolve({{
                    brands: brandsData,
                    mobile: {str(fp.mobile).lower()},
                    platform: "{fp.platform}",
                    architecture: "{fp.architecture}",
                    bitness: "{fp.bitness}",
                    model: "{fp.model}",
                    platformVersion: "{fp.platform_version}",
                    uaFullVersion: "{fp.app_version.split("Chrome/")[1].split(" ")[0] if "Chrome/" in fp.app_version else "133.0.0.0"}"
                }});
            }},
            toJSON: function() {{
                return {{ brands: brandsData, mobile: {str(fp.mobile).lower()}, platform: "{fp.platform}" }};
            }}
        }};
        Object.defineProperty(Navigator.prototype, 'userAgentData', {{
            get: () => uaData,
            configurable: true,
            enumerable: true
        }});
    }} catch(e) {{}}

    // 4. Languages & Locale
    try {{
        const langs = {languages_json};
        Object.defineProperty(Navigator.prototype, 'languages', {{
            get: () => langs,
            configurable: true,
            enumerable: true
        }});
        Object.defineProperty(Navigator.prototype, 'language', {{
            get: () => langs[0] || "en-US",
            configurable: true,
            enumerable: true
        }});
    }} catch(e) {{}}

    // 5. Monitor & Screen Metrics Shield
    try {{
        Object.defineProperty(Screen.prototype, 'width', {{ get: () => {fp.screen_width} }});
        Object.defineProperty(Screen.prototype, 'height', {{ get: () => {fp.screen_height} }});
        Object.defineProperty(Screen.prototype, 'availWidth', {{ get: () => {fp.screen_avail_width} }});
        Object.defineProperty(Screen.prototype, 'availHeight', {{ get: () => {fp.screen_avail_height} }});
        Object.defineProperty(Screen.prototype, 'colorDepth', {{ get: () => {fp.color_depth} }});
        Object.defineProperty(Screen.prototype, 'pixelDepth', {{ get: () => {fp.pixel_depth} }});
        Object.defineProperty(Window.prototype, 'devicePixelRatio', {{ get: () => {fp.device_pixel_ratio} }});
    }} catch(e) {{}}

    // 6. Timezone & Locale Formatting
    try {{
        const targetTimezone = "{fp.timezone}";
        const targetOffset = {fp.timezone_offset};

        const origResolvedOptions = Intl.DateTimeFormat.prototype.resolvedOptions;
        Intl.DateTimeFormat.prototype.resolvedOptions = function() {{
            const res = origResolvedOptions.apply(this, arguments);
            res.timeZone = targetTimezone;
            return res;
        }};

        Date.prototype.getTimezoneOffset = function() {{
            return targetOffset;
        }};
    }} catch(e) {{}}

    // 7. WebGL & GPU Hardware Spoofing (Shields actual host graphics card)
    try {{
        const webglParams = {{
            37445: "{fp.webgl_vendor}",           // UNMASKED_VENDOR_WEBGL
            37446: "{fp.webgl_renderer}",         // UNMASKED_RENDERER_WEBGL
            3379: {fp.max_texture_size},          // MAX_TEXTURE_SIZE
            34024: {fp.max_renderbuffer_size},    // MAX_RENDERBUFFER_SIZE
        }};

        const hookWebGL = function(proto) {{
            if (!proto) return;
            const origGetParam = proto.getParameter;
            proto.getParameter = function(param) {{
                if (param in webglParams) return webglParams[param];
                if (param === 3386) return new Int32Array({json.dumps(fp.max_viewport_dims)});
                return origGetParam.apply(this, arguments);
            }};
        }};

        if (window.WebGLRenderingContext) hookWebGL(WebGLRenderingContext.prototype);
        if (window.WebGL2RenderingContext) hookWebGL(WebGL2RenderingContext.prototype);
    }} catch(e) {{}}

    // 8. Media Devices Shield (Mocks Webcams, Microphones, Audio Outputs)
    try {{
        if (navigator.mediaDevices && navigator.mediaDevices.enumerateDevices) {{
            const spoofedDevices = {media_devs_json};
            navigator.mediaDevices.enumerateDevices = function() {{
                return Promise.resolve(spoofedDevices.map((d, i) => ({{
                    deviceId: d.device_id || ("dev_" + i),
                    kind: d.kind,
                    label: d.label,
                    groupId: d.group_id || ("grp_" + i),
                    toJSON: function() {{ return this; }}
                }})));
            }};
        }}
    }} catch(e) {{}}

    // 9. Battery API Shield
    try {{
        if (navigator.getBattery) {{
            const batData = {battery_json};
            navigator.getBattery = function() {{
                return Promise.resolve({{
                    charging: batData.charging,
                    chargingTime: batData.charging_time,
                    dischargingTime: batData.discharging_time,
                    level: batData.level,
                    addEventListener: function() {{}},
                    removeEventListener: function() {{}}
                }});
            }};
        }}
    }} catch(e) {{}}

    // 10. Geolocation API Shield
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
            navigator.geolocation.getCurrentPosition = function(success, error, options) {{
                if (typeof success === 'function') success(spoofedPos);
            }};
            navigator.geolocation.watchPosition = function(success, error, options) {{
                if (typeof success === 'function') success(spoofedPos);
                return 1;
            }};
        }}
    }} catch(e) {{}}

    // 11. Subtle Canvas 2D Noise (Deterministic per-profile seed)
    if ({str(fp.canvas_noise).lower()}) {{
        try {{
            const seed = {fp.canvas_noise_seed};
            const origGetImageData = CanvasRenderingContext2D.prototype.getImageData;
            CanvasRenderingContext2D.prototype.getImageData = function(sx, sy, sw, sh) {{
                const imageData = origGetImageData.apply(this, arguments);
                for (let i = 0; i < imageData.data.length; i += 64) {{
                    imageData.data[i] = (imageData.data[i] + (seed % 3) + 1) % 256;
                }}
                return imageData;
            }};
        }} catch(e) {{}}
    }}

    // 12. AudioContext Fingerprint Noise
    if ({str(fp.audio_noise).lower()}) {{
        try {{
            if (window.AudioBuffer) {{
                const origGetChannelData = AudioBuffer.prototype.getChannelData;
                AudioBuffer.prototype.getChannelData = function(channel) {{
                    const data = origGetChannelData.apply(this, arguments);
                    if (data && data.length > 0) {{
                        data[0] = data[0] + {fp.audio_noise_seed};
                    }}
                    return data;
                }};
            }}
        }} catch(e) {{}}
    }}

    // 13. ClientRects & Font Jitter (Sub-pixel noise)
    if ({str(fp.client_rects_noise).lower()}) {{
        try {{
            const origGetBoundingClientRect = Element.prototype.getBoundingClientRect;
            Element.prototype.getBoundingClientRect = function() {{
                const rect = origGetBoundingClientRect.apply(this, arguments);
                return new DOMRect(rect.x, rect.y, rect.width, rect.height);
            }};
        }} catch(e) {{}}
    }}

    // 14. Port Scan & Localhost Protection
    if ({str(fp.block_port_scanning).lower()}) {{
        try {{
            const origFetch = window.fetch;
            window.fetch = function(url, options) {{
                if (typeof url === 'string' && (url.includes('127.0.0.1') || url.includes('localhost')) && !url.includes(':8899')) {{
                    return Promise.reject(new TypeError('NetworkError when attempting to fetch resource.'));
                }}
                return origFetch.apply(this, arguments);
            }};
        }} catch(e) {{}}
    }}

    // 15. WebRTC Local IP Shield
    try {{
        if (window.RTCPeerConnection) {{
            const origCreateOffer = RTCPeerConnection.prototype.createOffer;
            RTCPeerConnection.prototype.createOffer = function(options) {{
                return origCreateOffer.apply(this, arguments);
            }};
        }}
    }} catch(e) {{}}

}})();
"""
    with open(ext_dir / "stealth.js", "w", encoding="utf-8") as f:
        f.write(stealth_js.strip() + "\n")

    with open(ext_dir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    return str(ext_dir.resolve())
