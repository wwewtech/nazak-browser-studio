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
    # Hunt A-16: the installed font pool is part of the profile.
    fonts_json = json.dumps(list(getattr(fp, "fonts", []) or []))
    geo_json = json.dumps(fp.geolocation.model_dump())
    battery_json = json.dumps(fp.battery.model_dump())
    platform_json = json.dumps(fp.platform)
    # Hunt A-18: the Client Hints `platform` is the OS NAME ("Windows",
    # "macOS", "Linux") while `navigator.platform` is the legacy API string
    # ("Win32", "MacIntel", "Linux x86_64"). The shield used the legacy
    # string for both, so `navigator.userAgentData.platform` reported
    # "Win32" — a value the UA-CH spec never produces (measured: the real
    # Chrome reports "Windows"), and a one-line check.
    _ch_platform = "Windows"
    _pf_lower = str(fp.platform).lower()
    if "mac" in _pf_lower:
        _ch_platform = "macOS"
    elif "linux" in _pf_lower or "android" in _pf_lower:
        _ch_platform = "Linux"
    ch_platform_json = json.dumps(_ch_platform)
    vendor_json = json.dumps(fp.vendor)
    architecture_json = json.dumps(fp.architecture)
    bitness_json = json.dumps(fp.bitness)
    model_json = json.dumps(fp.model)
    platform_version_json = json.dumps(fp.platform_version)
    ua_full_version = _chrome_full_version(fp.user_agent, fp.app_version)
    ua_full_version_json = json.dumps(ua_full_version)
    # Hunt A-35: fullVersionList carries the FULL version per brand (the
    # sync brands carry only the major). The GREASE entry keeps its own
    # version string from the profile brands (a real Chrome pairs each
    # GREASE brand with a specific version; both orderings exist in the
    # wild, the profile's own order is preserved).
    full_version_list_json = json.dumps(
        [
            {
                "brand": str(b.get("brand")),
                "version": (
                    ua_full_version if str(b.get("brand")) in ("Google Chrome", "Chromium") else str(b.get("version"))
                ),
            }
            for b in fp.brands
        ]
    )
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
// Hunt A-13: the shield must also cover the WORKER global scope. A page that
// spawns a Worker reads the REAL navigator/screen/Intl values there — a
// three-line probe bypassed the whole shield (measured: the worker reported
// the host's hardwareConcurrency/deviceMemory while the main world reported
// the profile's). `window` does not exist in a worker, so the guard and the
// DOM-only sections must be skipped there — but the navigator/Intl/Date
// sections are scope-independent and DO apply.
//
// Hunt A-15: this file is injected as a classic script, so a top-level `var`
// becomes an OWN property of the window — and an enumerable one, visible in
// Object.keys(window). A detector that lists the window's own properties saw
// "__scopeIsWorker" (measured: the real Chrome had 1234 own properties, the
// shielded one 1237, one of them enumerable). The flag is therefore captured
// in an IIFE — it never touches the global object.
(function() {{
const __scopeIsWorker = (typeof window === 'undefined');
// Hunt A-15: the idempotency flag must not be an own property of the window —
// even a non-enumerable one shows up in Object.getOwnPropertyNames(window),
// which is a one-line detector (measured: the real Chrome had 1234 own
// properties, the shielded one 1237). A SYMBOL key is invisible to
// getOwnPropertyNames / Object.keys / for-in, so the flag is stored under a
// per-run symbol. The symbol itself is held in a closure, so the page cannot
// read or forge it.
const __nsiKey = (typeof Symbol === 'function')
    ? Symbol('nazakShieldIdempotent')
    : '__nsi';
const __global = (typeof globalThis !== 'undefined')
    ? globalThis
    : (typeof self !== 'undefined' ? self : (typeof window !== 'undefined' ? window : {{}}));
if (!__scopeIsWorker && __global[__nsiKey]) {{
    // Already applied on this document (extension content script + CDP injector may both run).
}} else {{
if (!__scopeIsWorker) {{
Object.defineProperty(__global, __nsiKey, {{value: true, configurable: false, enumerable: false, writable: false}});
}}
(function() {{
    'use strict';

    // Hunt A-13: the shield also runs in a WORKER's global scope (there is no
    // window, no Screen and no document there). The scope-independent
    // sections (navigator properties, Intl, Date) MUST apply there — a worker
    // probe reads the real values otherwise. The DOM-only sections are
    // skipped via __hasDom.
    const __hasDom = (typeof window !== 'undefined' && typeof document !== 'undefined');

    // Hunt A-26: the objects the shield returns (the battery, the media
    // devices, the GPU adapter info) must look like the native ones: the
    // native instances carry NO own properties — their values live on the
    // prototype as getters (measured: the native BatteryManager's
    // Object.getOwnPropertyNames is "(none)", ours listed seven). A
    // detector reads the prototype chain and the own-property list.
    //
    // The helper builds an instance whose values live on an INTERMEDIATE
    // prototype layer: the instance itself has no own properties, the
    // getters look like native ones, and the native prototypes are never
    // touched (so the host's own objects keep working).
    const __makeNativeLike = function(baseProto, values, methods) {{
        const layer = Object.create(baseProto || Object.prototype);
        Object.keys(values).forEach(function(k) {{
            try {{
                Object.defineProperty(layer, k, {{
                    get: makeNative(function() {{ return values[k]; }}, 'get ' + k),
                    configurable: true, enumerable: true
                }});
            }} catch(e) {{}}
        }});
        // the METHODS also live on the layer, so the instance itself stays
        // free of own properties (exactly like the native objects)
        if (methods) {{
            Object.keys(methods).forEach(function(k) {{
                try {{
                    Object.defineProperty(layer, k, {{
                        value: makeNative(methods[k], k),
                        configurable: true, enumerable: true
                    }});
                }} catch(e) {{}}
            }});
        }}
        return Object.create(layer);
    }};

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

    // =====================================================================
    // STEALTH CORE (audit round 12 — the CreepJS lie-detector replay found
    // 33 "corrupted" APIs out of 53: the shield REPLACED native functions
    // with plain JS functions, and a plain function fails every structural
    // invariant a real one satisfies — 'prototype' in fn, own
    // length/name/prototype keys, extendability, and the illegal-invocation
    // TypeError every native getter must throw when called without a
    // receiver). The core below ports the puppeteer-extra-stealth approach
    // (_utils: replaceWithProxy / replaceGetterWithProxy /
    // stripProxyFromErrors): we never substitute the function — we wrap the
    // NATIVE one in a Proxy, so the function's own shape stays native and
    // only the behaviour changes.
    // =====================================================================

    // A cache of pristine natives, taken BEFORE any hook exists (a page can
    // sniff which functions we use inside our traps and tamper with them).
    const __nativeCache = (function() {{
        return {{
            toStringStr: Function.prototype.toString + '',
            reflectGet: Reflect.get.bind(Reflect),
            reflectApply: Reflect.apply.bind(Reflect)
        }};
    }})();

    // Sanitize the stack of an error thrown inside one of our traps: a
    // Proxy shows up in the stack frames, and CreepJS compares the first
    // frame against known anchors (e.g. 'at Function.toString ') AND the
    // frame COUNT (proxy.js hashes name:stackLen:firstFrame tuples against
    // known browser hashes). Round 13 measured two defects: the anchor
    // frame vanished and the count changed — the hash could never match.
    //
    // The fix: REWRITE every trap frame to the native anchor of the wrapped
    // function, so the anchor line is right. The frame COUNT cannot be
    // faked cheaply (our trap adds real frames), so the count is brought
    // down by SPLICING the extra trap frames after the rewrite — down to
    // the count a plain native throw produces.
    // Round 13: proxy->target registry for the cycle check (a raw
    // getPrototypeOf walk cannot see proxy hops). The reverse map carries
    // target->proxy so the setPrototypeOf trap — which only receives the
    // TARGET as its argument — can also compare against the proxy INSTANCE
    // the chain is actually being built on (measured in node: the chain
    // Object.create(proxy) points at the PROXY, and p === target never
    // fires, so the cycle is installed and a later .toString() dies with
    // RangeError instead of the native TypeError).
    const __proxyTargets = new WeakMap();
    const __proxyOfTarget = new WeakMap();
    const proxyOf = function(fn) {{
        return __proxyTargets.get(fn) || fn;
    }};

    const __stripProxyFromErrors = function(handler) {{
        const newHandler = {{
            setPrototypeOf: function(target, proto) {{
                // Round 13 (case3): the native cycle check must fire BEFORE
                // the chain is installed — otherwise every later method
                // lookup descends through our apply trap and dies with a
                // RangeError. The walk sees BOTH identities: the target
                // (what the engine passes us) and the proxy instance itself
                // (what the page actually chained).
                if (proto === null) {{
                    throw new TypeError('Cannot convert object to primitive value');
                }}
                const self = __proxyOfTarget.get(target) || null;
                let p = proto;
                for (let i = 0; i < 1000 && p !== null && p !== undefined; i++) {{
                    if (p === target || p === self || p === proxyOf(target)) {{
                        // The native throw happens INSIDE Object.setPrototypeOf,
                        // so its first stack frame is
                        // 'at Object.setPrototypeOf (<anonymous>)' — no line
                        // numbers (it is native code). Our trap throws from
                        // injected JS, so its frame carries our line numbers
                        // (measured: 'at Object.setPrototypeOf
                        // (<anonymous>:172:37)'). Shape the stack like the
                        // native one: rewrite OUR frame to the native form
                        // and splice the extra frames the proxy adds.
                        const err = new TypeError('Cyclic __proto__ value');
                        try {{
                            const lines = String(err.stack).split('\\n');
                            const out = [lines[0]];
                            let inserted = false;
                            for (let i = 1; i < lines.length; i++) {{
                                const l = lines[i];
                                if (!inserted && /setPrototypeOf/.test(l)) {{
                                    out.push('    at Object.setPrototypeOf (<anonymous>)');
                                    inserted = true;
                                    // skip every other frame of our trap chain
                                    continue;
                                }}
                                if (/setPrototypeOf/.test(l)) continue;
                                out.push(l);
                            }}
                            if (!inserted) {{
                                out.splice(1, 0, '    at Object.setPrototypeOf (<anonymous>)');
                            }}
                            err.stack = out.join('\\n');
                        }} catch(e) {{}}
                        throw err;
                    }}
                    p = Object.getPrototypeOf(p);
                }}
                return Reflect.setPrototypeOf(target, proto);
            }}
        }};
        Object.getOwnPropertyNames(handler).forEach(function(trap) {{
            if (trap === 'setPrototypeOf') return;
            newHandler[trap] = function() {{
                try {{
                    const __prevLimit = Error.stackTraceLimit;
                    try {{ Error.stackTraceLimit = __prevLimit + 8; }} catch(e) {{}}
                    return handler[trap].apply(this, arguments);
                }} catch (err) {{
                    try {{ Error.stackTraceLimit = __prevLimit; }} catch(e) {{}}
                    if (!err || !err.stack) throw err;
                    try {{
                        const lines = String(err.stack).split('\\n');
                        // 1) our trap frames — measured shape (round 13):
                        //    'at newHandler.<computed> [as apply] (<anonymous>:149:42)'
                        //    appearing exactly twice, consecutively, under the
                        //    message line. Built-in frames (at Error, at eval,
                        //    at Function.toString) never carry our wrapper
                        //    name. This exact pattern is the discriminator.
                        const isTrapFrame = (line) =>
                            /^\\s*at (Object\\.)?newHandler\\.<computed> \\[as \\w+\\]/.test(line) ||
                            // the internal handler[trap].apply(...) frame —
                            // always carries OUR line numbers; built-in frames
                            // like 'at Error (<anonymous>)' never do.
                            /^\\s*at Object\\.apply \\(<anonymous>:\\d+:\\d+\\)\\s*$/.test(line);
                        // 2) splice the trap frames OUT
                        const kept = lines.filter(function(line, index) {{
                            if (index === 0) return true;
                            return !isTrapFrame(line);
                        }});
                        // 3) nested toString proxies: Object.toString -> Function.toString
                        err.stack = kept.join('\\n').replace('at Object.toString (', 'at Function.toString (');
                    }} catch(e) {{}}
                    throw err;
                }}
            }};
        }});
        return newHandler;
    }};

    // Redirect Function.prototype.toString for ONE proxied object back to the
    // native result of the function it replaced (so toString keeps answering
    // the ORIGINAL signature, not a generic native string).
    const __toStringRedirects = new WeakMap();
    const __redirectToString = function(proxyObj, originalObj) {{
        __toStringRedirects.set(proxyObj, originalObj);
    }};

    // Replace obj[prop] (a METHOD) with a Proxy over the NATIVE function.
    // The proxy keeps the native shape (no own prototype/length/name
    // changes), so 'prototype' in fn, ownKeys, class-extends and the
    // interface TypeErrors all stay native. Only apply() is ours.
    const __replaceWithProxy = function(obj, propName, handler) {{
        try {{
            const originalObj = obj[propName];
            if (typeof originalObj !== 'function') return false;
            const proxyObj = new Proxy(originalObj, __stripProxyFromErrors(handler));
            __proxyTargets.set(proxyObj, originalObj);
            __proxyOfTarget.set(originalObj, proxyObj);
            const desc = Object.getOwnPropertyDescriptor(obj, propName) || {{}};
            Object.defineProperty(obj, propName, {{
                value: proxyObj,
                writable: true,
                configurable: true,
                enumerable: desc.enumerable
            }});
            __redirectToString(proxyObj, originalObj);
            return true;
        }} catch(e) {{ return false; }}
    }};

    // Replace a GETTER with a Proxy over the NATIVE getter function. The
    // trap calls the native getter FIRST: an illegal invocation (accessing
    // the property through the constructor, without a receiver) throws the
    // native TypeError with the native stack — exactly like a real getter —
    // and only a legitimate call returns our value.
    const __replaceGetterWithProxy = function(obj, propName, value) {{
        try {{
            const desc = Object.getOwnPropertyDescriptor(obj, propName);
            if (!desc || !desc.get) return false;
            const nativeGet = desc.get;
            const proxyObj = new Proxy(nativeGet, __stripProxyFromErrors({{
                apply: function(target, thisArg, args) {{
                    // Let the native getter run first: it throws the
                    // TypeError a real getter throws when there is no
                    // receiver (CreepJS 'failed illegal error').
                    __nativeCache.reflectApply(target, thisArg, args);
                    return value;
                }}
            }}));
            __proxyTargets.set(proxyObj, nativeGet);
            __proxyOfTarget.set(nativeGet, proxyObj);
            Object.defineProperty(obj, propName, {{
                get: proxyObj,
                set: desc.set,
                configurable: true,
                enumerable: desc.enumerable
            }});
            __redirectToString(proxyObj, nativeGet);
            return true;
        }} catch(e) {{ return false; }}
    }};

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
        // Class 3 fix: the toString proxy itself gets the stealth treatment
        // — its trap frames are stripped from error stacks (CreepJS compares
        // the first stack line of the TypeError that Object.create(fn)
        // .toString() must produce: natively it anchors at
        // 'at Function.toString ', ours used to show 'at Object.toString ').
        const toStringProxy = new Proxy(nativeToString, __stripProxyFromErrors({{
            apply(target, thisArg, argArray) {{
                // A proxied API answers with the toString of the NATIVE
                // function it replaced (the exact original signature).
                if (typeof thisArg === 'function' && __toStringRedirects.has(thisArg)) {{
                    const original = __toStringRedirects.get(thisArg);
                    return __nativeCache.reflectApply(target, original, argArray);
                }}
                if (typeof thisArg === 'function' && overriddenFns.has(thisArg)) {{
                    const name = fnNames.get(thisArg) || thisArg.name || '';
                    return `function ${{name}}() {{ [native code] }}`;
                }}
                return __nativeCache.reflectApply(target, thisArg, argArray);
            }}
        }}));
        __proxyTargets.set(toStringProxy, nativeToString);
        __proxyOfTarget.set(nativeToString, toStringProxy);
        Function.prototype.toString = toStringProxy;
        makeNative(Function.prototype.toString, 'toString');
    }} catch(e) {{}}

    // Hunt A-13: in a WORKER the global navigator is a WorkerNavigator — a
    // DIFFERENT class with its OWN prototype (there is no `Navigator` global
    // at all in a worker scope). Patching only Navigator.prototype left the
    // worker scope untouched, and a page could read the host's
    // hardwareConcurrency / deviceMemory / languages with a three-line
    // Worker probe. Every navigator-level shield is applied to BOTH
    // prototypes when they exist.
    const __navProtos = [];
    if (typeof Navigator !== 'undefined' && Navigator.prototype) __navProtos.push(Navigator.prototype);
    if (typeof WorkerNavigator !== 'undefined' && WorkerNavigator.prototype) __navProtos.push(WorkerNavigator.prototype);
    const __defineNav = function(name, value) {{
        // Class 1 fix: the navigator getters are Proxies over the NATIVE
        // getters. The trap runs the native getter first, so an access
        // without a receiver (Navigator.prototype.webdriver) throws the
        // native TypeError exactly like a real getter (CreepJS
        // 'failed illegal error' fired for all of these before).
        __navProtos.forEach(function(proto) {{
            const done = __replaceGetterWithProxy(proto, name, value);
            if (!done) {{
                // The property may live higher up the prototype chain (e.g.
                // deviceMemory on WorkerNavigator comes from a parent
                // interface). Walk the chain for the native getter and wrap
                // THAT; the wrapper answers for our prototype as a real
                // native getter would.
                let host = Object.getPrototypeOf(proto);
                let wrapped = false;
                while (host && host !== Object.prototype) {{
                    const d = Object.getOwnPropertyDescriptor(host, name);
                    if (d && d.get) {{
                        const nativeGet = d.get;
                        const proxyObj = new Proxy(nativeGet, __stripProxyFromErrors({{
                            apply: function(target, thisArg, args) {{
                                __nativeCache.reflectApply(target, thisArg, args);
                                return value;
                            }}
                        }}));
                        __proxyTargets.set(proxyObj, nativeGet);
                        __proxyOfTarget.set(nativeGet, proxyObj);
                        try {{
                            Object.defineProperty(proto, name, {{
                                get: proxyObj, configurable: true, enumerable: true
                            }});
                            __redirectToString(proxyObj, nativeGet);
                            wrapped = true;
                        }} catch(e) {{}}
                        break;
                    }}
                    host = Object.getPrototypeOf(host);
                }}
                if (!wrapped) {{
                    // no native getter anywhere: define one with the correct
                    // receiver semantics (throw on a receiver-less access)
                    try {{
                        const g = makeNative(function() {{
                            if (this == null) throw new TypeError('Illegal invocation');
                            return value;
                        }}, 'get ' + name);
                        Object.defineProperty(proto, name, {{
                            get: g, configurable: true, enumerable: true
                        }});
                    }} catch(e) {{}}
                }}
            }}
        }});
    }};
    const __navGetter = function(name, value) {{
        // kept for the A-03/A-13 contracts: returns the native-shaped getter
        return value;
    }};

    // 1. Remove Automation Artifacts & navigator.webdriver (W3C WebDriver spec compliant)
    try {{
        __defineNav('webdriver', __navGetter('webdriver', false));
    }} catch(e) {{}}

    // 2. Hardware Resources Isolation (CPU & RAM)
    try {{
        __defineNav('hardwareConcurrency', __navGetter('hardwareConcurrency', {fp.hardware_concurrency}));
        __defineNav('deviceMemory', __navGetter('deviceMemory', {device_memory_json}));
        __defineNav('platform', __navGetter('platform', {platform_json}));
        __defineNav('maxTouchPoints', __navGetter('maxTouchPoints', {fp.max_touch_points}));
        __defineNav('vendor', __navGetter('vendor', {vendor_json}));
    }} catch(e) {{}}

    // 3. User-Agent Data & High-Entropy Client Hints
    try {{
        const brandsData = {brands_json};
        // Hunt A-18: the uaData object must be a real UAData instance — a
        // plain object has Object.prototype's methods, while the real one
        // carries brands/mobile/platform/getHighEntropyValues/toJSON on its
        // OWN prototype (measured: the real Chrome's prototype lists exactly
        // those five). A plain object is a one-line tell.
        const uaDataProto = (typeof NavigatorUAData !== 'undefined' && NavigatorUAData.prototype)
            ? NavigatorUAData.prototype
            : Object.prototype;
        const uaData = Object.create(uaDataProto);
        Object.defineProperty(uaData, 'brands', {{
            value: brandsData, configurable: true, enumerable: true
        }});
        Object.defineProperty(uaData, 'mobile', {{
            value: {str(fp.mobile).lower()}, configurable: true, enumerable: true
        }});
        Object.defineProperty(uaData, 'platform', {{
            value: {ch_platform_json}, configurable: true, enumerable: true
        }});
        Object.defineProperty(uaData, 'getHighEntropyValues', {{
            value: makeNative(function(hints) {{
                // Hunt A-35: the native API returns EXACTLY the requested
                // hints — nothing more (measured: the host's answer to
                // ['architecture','bitness',...] contains no brands/mobile/
                // platform; our old hook answered a fixed set, so
                // 'fullVersionList' came back undefined for any page that
                // requested it — a one-line detector — and the extra fields
                // leaked a non-native response shape).
                const all = {{
                    architecture: {architecture_json},
                    bitness: {bitness_json},
                    model: {model_json},
                    platformVersion: {platform_version_json},
                    uaFullVersion: {ua_full_version_json},
                    fullVersionList: {full_version_list_json},
                    fullVersion: {ua_full_version_json},
                    wow64: false,
                    formFactors: ['Desktop'],
                    brands: brandsData,
                    mobile: {str(fp.mobile).lower()},
                    platform: {ch_platform_json}
                }};
                const req = (hints && hints.length) ? hints : Object.keys(all);
                const out = {{}};
                req.forEach(function(h) {{ if (h in all) out[h] = all[h]; }});
                return Promise.resolve(out);
            }}, 'getHighEntropyValues'),
            configurable: true, enumerable: false, writable: true
        }});
        Object.defineProperty(uaData, 'toJSON', {{
            value: makeNative(function() {{
                return {{ brands: brandsData, mobile: {str(fp.mobile).lower()}, platform: {ch_platform_json} }};
            }}, 'toJSON'),
            configurable: true, enumerable: false, writable: true
        }});
        __defineNav('userAgentData', __navGetter('userAgentData', uaData));
    }} catch(e) {{}}

    // 4. Languages & Locale
    try {{
        const langs = {languages_json};
        __defineNav('languages', __navGetter('languages', langs));
        __defineNav('language', __navGetter('language', langs[0] || "en-US"));
    }} catch(e) {{}}

    // 5. Monitor & Screen Metrics Shield
        if (__hasDom) {{
    try {{
        // Class 1 fix: the screen getters are Proxies over the NATIVE
        // getters (a real getter throws the illegal-invocation TypeError
        // when accessed through Screen.prototype without a receiver).
        __replaceGetterWithProxy(Screen.prototype, 'width', {fp.screen_width});
        __replaceGetterWithProxy(Screen.prototype, 'height', {fp.screen_height});
        __replaceGetterWithProxy(Screen.prototype, 'availWidth', {fp.screen_avail_width});
        __replaceGetterWithProxy(Screen.prototype, 'availHeight', {fp.screen_avail_height});
        __replaceGetterWithProxy(Screen.prototype, 'colorDepth', {fp.color_depth});
        __replaceGetterWithProxy(Screen.prototype, 'pixelDepth', {fp.pixel_depth});
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
            // property is redefined on the instance (as a Proxy over the
            // NATIVE accessor, so the getter keeps its native shape —
            // Class 1); the prototype is kept as a fallback.
            const apply = function(target) {{
                __replaceGetterWithProxy(target, name, value);
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
        // The available AREA's origin must match the window's position.
        __replaceGetterWithProxy(Screen.prototype, 'availLeft', fakeAvailLeft);
        __replaceGetterWithProxy(Screen.prototype, 'availTop', fakeAvailTop);
    }} catch(e) {{}}
        }}

    // 6. Timezone & Locale Formatting
    // Hunt A-01: the Intl/Date hooks are installed once, in section 12d —
    // installing the same hook twice made the second wrapper reference an
    // out-of-scope variable and EVERY Intl.DateTimeFormat().resolvedOptions()
    // call threw a ReferenceError.
    try {{
        // Class 2 fix: a Proxy over the NATIVE getTimezoneOffset — the
        // function keeps its native shape (no own prototype, ownKeys stay
        // length,name, class-extends keeps throwing). Only the returned
        // value is ours.
        __replaceWithProxy(Date.prototype, 'getTimezoneOffset', {{
            apply: function(target, thisArg, args) {{
                return targetOffset;
            }}
        }});
    }} catch(e) {{}}

    // 7. WebGL & GPU Hardware Spoofing (Shields actual host graphics card)
        if (__hasDom) {{
    try {{
        // Hunt A-24: the contexts that requested the WEBGL_debug_renderer_info
        // extension — the UNMASKED_* parameters answer null until then.
        const __extRequested = new WeakSet();
        const webglParams = {{
            37445: {webgl_vendor_json},           // UNMASKED_VENDOR_WEBGL
            37446: {webgl_renderer_json},         // UNMASKED_RENDERER_WEBGL
            3379: {fp.max_texture_size},          // MAX_TEXTURE_SIZE
            34024: {fp.max_renderbuffer_size},    // MAX_RENDERBUFFER_SIZE
        }};

        const hookWebGL = function(proto) {{
            if (!proto) return;
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
                // Hunt A-17: the ALIASED_*_RANGE parameters are PAIRS, and
                // WebGL returns them as a Float32Array — the old code
                // substituted plain numbers and mixed up the two pnumbs
                // (33901 is the POINT size range, 33902/33903/33904 the LINE
                // width range). Measured: the host returned
                // ALIASED_LINE_WIDTH_RANGE = Float32Array(1, 1024) while the
                // shield returned the scalar 1 — the type alone exposed the
                // patch, and the max/min pair was inconsistent.
                33901: new Float32Array([1, 1]),      // ALIASED_POINT_SIZE_RANGE
                33902: new Float32Array([1, 1024]),   // ALIASED_LINE_WIDTH_RANGE
                33903: new Float32Array([1, 1]),      // (legacy aliases)
                33904: new Float32Array([1, 1024]),
                7936: {platform_json}.includes('Win') ? 'WebKit' : 'WebKit',
                7937: 'WebKit WebGL',
            }};
            const merged = Object.assign({{}}, webglParams, derived);
            // Hunt A-24: UNMASKED_VENDOR_WEBGL (37445) and
            // UNMASKED_RENDERER_WEBGL (37446) are EXTENSION parameters: in a
            // real Chrome they return NULL until the extension has been
            // requested, and only then the real values (measured in a plain
            // Chrome: before getExtension -> null, after -> the vendor).
            // The shield answered with the profile's string in BOTH cases,
            // so a detector that reads the parameter without asking for the
            // extension saw a value a real browser never produces. The
            // contexts that requested the extension are tracked, and the
            // parameter answers null until then.
            // Class 2 fix: the hook is a Proxy over the NATIVE getParameter,
            // so the function keeps its native shape.
            __replaceWithProxy(proto, 'getParameter', {{
                apply: function(target, thisArg, args) {{
                    const param = args[0];
                    if (param === 37445 || param === 37446) {{
                        if (!__extRequested.has(thisArg)) return null;
                        return merged[param];
                    }}
                    if (param in merged) return merged[param];
                    return __nativeCache.reflectApply(target, thisArg, args);
                }}
            }});
            // getShaderPrecisionFormat: highp/mediump ranges are stable on
            // desktop GPUs, but read them through our spoof so the
            // WebGLShaderPrecisionFormat object shape cannot leak the host.
            // (Kept as a Proxy over the native for the same Class 2 reason.)
            __replaceWithProxy(proto, 'getShaderPrecisionFormat', {{
                apply: function(target, thisArg, args) {{
                    return __nativeCache.reflectApply(target, thisArg, args);
                }}
            }});
        }};

        if (window.WebGLRenderingContext) hookWebGL(WebGLRenderingContext.prototype);
        if (window.WebGL2RenderingContext) hookWebGL(WebGL2RenderingContext.prototype);
        // WEBGL_debug_info extension exposes UNMASKED_VENDOR/RENDERER through
        // getParameter on the *extension* object — the old hook never covered
        // it, leaking the host GPU. Wrap the extension getter itself.
        //
        // Hunt A-24: the hook covered ONLY WebGLRenderingContext.prototype —
        // a WebGL2 context has a DIFFERENT prototype (measured: the two
        // prototypes are not the same object), so on a WebGL2 context the
        // extension was not hooked and the host GPU leaked. Both prototypes
        // are hooked now. The extension object itself is left untouched (a
        // real WEBGL_debug_renderer_info has no getParameter method — the
        // old code added one, which was itself a tell).
        const hookDebugExtension = function(proto) {{
            if (!proto || !proto.getExtension) return;
            // Class 2 fix: a Proxy over the NATIVE getExtension.
            __replaceWithProxy(proto, 'getExtension', {{
                apply: function(target, thisArg, args) {{
                    const ext = __nativeCache.reflectApply(target, thisArg, args);
                    if (args[0] === 'WEBGL_debug_renderer_info' && ext) {{
                        // the context now answers the UNMASKED_* parameters
                        try {{ __extRequested.add(thisArg); }} catch(e) {{}}
                    }}
                    return ext;
                }}
            }});
        }};
        try {{
            hookDebugExtension(WebGLRenderingContext.prototype);
            if (window.WebGL2RenderingContext) hookDebugExtension(WebGL2RenderingContext.prototype);
        }} catch(e) {{}}
    }} catch(e) {{}}
        }}

    // 8. WebGPU Hardware Emulation (Aligns with WebGL GPU Vendor & Model)
        if (__hasDom) {{
    try {{
        if (navigator.gpu && navigator.gpu.requestAdapter) {{
            const origRequestAdapter = navigator.gpu.requestAdapter;
            // Hunt A-26: the info object was a PLAIN object — a real
            // GPUAdapterInfo has its own prototype and NO own properties
            // (measured: the real Chrome's info has an empty own-property
            // list, ours had four). A detector reads
            // Object.getPrototypeOf(adapter.info).constructor.name and sees
            // "Object" instead of "GPUAdapterInfo".
            const gpuInfoProto = (typeof GPUAdapterInfo !== 'undefined' && GPUAdapterInfo.prototype)
                ? GPUAdapterInfo.prototype
                : Object.prototype;
            const buildGpuInfo = function() {{
                // Hunt A-26: the values live on a prototype layer, so the
                // instance itself carries no own properties (like the native
                // GPUAdapterInfo).
                return __makeNativeLike(gpuInfoProto, {{
                    vendor: {webgpu_vendor_json},
                    architecture: {webgpu_arch_json},
                    device: {webgl_renderer_json},
                    description: {webgl_renderer_json}
                }});
            }};
            const spoofedGpuInfo = buildGpuInfo();
            // Hunt A-14: the override lives on GPU.prototype — a real Chrome
            // keeps requestAdapter there and the navigator.gpu INSTANCE has
            // no own properties (an own property there is a one-line tell).
            const gpuHost = (typeof GPU !== 'undefined' && GPU.prototype && GPU.prototype.requestAdapter)
                ? GPU.prototype
                : navigator.gpu;
            // Class 2 fix: a Proxy over the NATIVE requestAdapter.
            __replaceWithProxy(gpuHost, 'requestAdapter', {{
                apply: function(target, thisArg, args) {{
                    return __nativeCache.reflectApply(target, thisArg, args).then(adapter => {{
                        if (!adapter) return adapter;
                        if (adapter.requestAdapterInfo) {{
                            __replaceWithProxy(adapter, 'requestAdapterInfo', {{
                                apply: function(t2, thisArg2, args2) {{
                                    return Promise.resolve(buildGpuInfo());
                                }}
                            }});
                        }}
                        try {{
                            Object.defineProperty(adapter, 'info', {{
                                get: makeNative(() => buildGpuInfo(), 'get info'),
                                configurable: true,
                                enumerable: true
                            }});
                        }} catch(e) {{}}
                        return adapter;
                    }});
                }}
            }});
        }}
    }} catch(e) {{}}
        }}

    // 9. Media Devices Shield (Mocks Webcams, Microphones, Audio Outputs)
        if (__hasDom) {{
    try {{
        // Hunt A-14: the old code ASSIGNED navigator.mediaDevices.enumerateDevices
        // — that creates an OWN property on the mediaDevices INSTANCE, while a
        // real Chrome keeps the method on MediaDevices.prototype and the
        // instance carries no own properties at all. `Object.getOwnPropertyNames
        // (navigator.mediaDevices)` then exposed the patch. The override now
        // lives on the prototype.
        if (navigator.mediaDevices && navigator.mediaDevices.enumerateDevices) {{
            const spoofedDevices = {media_devs_json};
            const mdHost = (typeof MediaDevices !== 'undefined' && MediaDevices.prototype && MediaDevices.prototype.enumerateDevices)
                ? MediaDevices.prototype
                : navigator.mediaDevices;
            // Hunt A-26: the device entries were PLAIN objects; a real
            // Chrome returns InputDeviceInfo instances (own properties:
            // none, the values live on the prototype). A detector reads
            // Object.getPrototypeOf(device).constructor.name and sees
            // "Object" instead of "InputDeviceInfo".
            const deviceProto = (typeof InputDeviceInfo !== 'undefined' && InputDeviceInfo.prototype)
                ? InputDeviceInfo.prototype
                : Object.prototype;
            const buildDevice = function(d, i) {{
                // Hunt A-26: the values live on a prototype layer, so the
                // instance itself carries no own properties (like the native
                // InputDeviceInfo).
                return __makeNativeLike(deviceProto, {{
                    deviceId: d.device_id || ("dev_" + i),
                    kind: d.kind,
                    label: d.label,
                    groupId: d.group_id || ("grp_" + i)
                }}, {{
                    toJSON: function() {{ return this; }}
                }});
            }};
            // Class 2 fix: a Proxy over the NATIVE enumerateDevices.
            __replaceWithProxy(mdHost, 'enumerateDevices', {{
                apply: function(target, thisArg, args) {{
                    return Promise.resolve(spoofedDevices.map(buildDevice));
                }}
            }});
        }}
    }} catch(e) {{}}
        }}

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
        // Class 1 fix: the plugins/mimeTypes getters are Proxies over the
        // NATIVE getters (native getters throw the illegal-invocation
        // TypeError when accessed through the prototype without a receiver).
        __replaceGetterWithProxy(Navigator.prototype, 'plugins', pluginsFake);
        __replaceGetterWithProxy(Navigator.prototype, 'mimeTypes', mimeTypesFake);
    }} catch(e) {{}}

    // 10. Battery API Shield
        if (__hasDom) {{
    try {{
        // Hunt A-14: the old code ASSIGNED navigator.getBattery, which creates
        // an OWN property on the navigator INSTANCE. A real Chrome keeps
        // getBattery on Navigator.prototype, and the navigator instance has
        // NO own properties at all — so a single
        // `Object.getOwnPropertyNames(navigator)` exposed the patch
        // (measured: the real Chrome returned "(none)", the shielded one
        // returned "getBattery"). The override now lives on the prototype.
        const __batteryHost = (typeof Navigator !== 'undefined' && Navigator.prototype && Navigator.prototype.getBattery)
            ? Navigator.prototype
            : navigator;
        if (__batteryHost.getBattery) {{
            const batData = {battery_json};
            const origGetBattery = __batteryHost.getBattery;
            // Hunt A-26: the battery object was a PLAIN object — a real
            // Chrome returns a BatteryManager instance whose values live on
            // the prototype (measured: the real one has NO own properties,
            // ours had six). A detector reads
            // Object.getPrototypeOf(battery).constructor.name and sees
            // "Object" instead of "BatteryManager".
            const batteryProto = (typeof BatteryManager !== 'undefined' && BatteryManager.prototype)
                ? BatteryManager.prototype
                : Object.prototype;
            // Hunt A-37 (identity): the W3C Battery Status contract resolves
            // EVERY getBattery() call to the SAME BatteryManager singleton
            // (measured: the native Chrome answers b1 === b2 with true). Our
            // buildBattery() constructed a NEW object per call —
            // `await getBattery() === await getBattery()` was false, a
            // two-line detector. The manager is built ONCE and cached.
            // Hunt A-37 (events): the old code stubbed addEventListener/
            // removeEventListener/dispatchEvent as no-op functions — but
            // BatteryManager.prototype ALREADY inherits the real
            // EventTarget methods; the stubs replaced them, so
            // `b.addEventListener === EventTarget.prototype.addEventListener`
            // was false (measured), another identity check. The real
            // prototype chain carries the native event API — no stubs: the
            // values live on a prototype layer, the events stay native.
            const __batterySingleton = __makeNativeLike(batteryProto, {{
                charging: batData.charging,
                chargingTime: batData.charging_time,
                dischargingTime: batData.discharging_time,
                level: batData.level
            }});
            // Class 2 fix: a Proxy over the NATIVE getBattery.
            __replaceWithProxy(__batteryHost, 'getBattery', {{
                apply: function(target, thisArg, args) {{
                    return Promise.resolve(__batterySingleton);
                }}
            }});
        }}
    }} catch(e) {{}}
        }}

    // 11. Geolocation API Shield
        if (__hasDom) {{
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
            // Hunt A-14: the geolocation methods live on Geolocation.prototype
            // in a real Chrome — assigning them to the INSTANCE would add own
            // properties that a detector can list with one line.
            // Class 2 fix: Proxies over the NATIVE methods.
            const geoHost = (typeof Geolocation !== 'undefined' && Geolocation.prototype && Geolocation.prototype.getCurrentPosition)
                ? Geolocation.prototype
                : navigator.geolocation;
            __replaceWithProxy(geoHost, 'getCurrentPosition', {{
                apply: function(target, thisArg, args) {{
                    if (typeof args[0] === 'function') args[0](spoofedPos);
                }}
            }});
            __replaceWithProxy(geoHost, 'watchPosition', {{
                apply: function(target, thisArg, args) {{
                    if (typeof args[0] === 'function') args[0](spoofedPos);
                    return 1;
                }}
            }});
        }}
    }} catch(e) {{}}
        }}

    // 10.1 Local Font Spoofing & queryLocalFonts
        if (__hasDom) {{
    try {{
        // Hunt A-16: the old code returned a HARDCODED list of nine families
        // regardless of the profile — while a real Windows box reports 25-60
        // (measured on the audit host: 40+ families were detectable by width
        // and 389 font files were installed). The list also advertised a
        // family the host does not have, so the queryLocalFonts answer and
        // the rendering probe contradicted each other. The pool is now part
        // of the PROFILE (stable per profile, different between profiles) and
        // the query returns it verbatim.
        const osPlatform = {platform_json}.toLowerCase();
        const profileFonts = {fonts_json};
        let fontList = [];
        if (profileFonts && profileFonts.length) {{
            fontList = profileFonts.map(function(family) {{
                return {{
                    family: family,
                    fullName: family,
                    postscriptName: family.replace(/[^A-Za-z0-9]/g, ''),
                    style: 'Regular'
                }};
            }});
        }} else {{
            // Fallback for profiles created before the font pool existed.
            if (osPlatform.includes('win')) {{
                fontList = [
                    {{ family: "Arial", fullName: "Arial", postscriptName: "ArialMT", style: "Regular" }},
                    {{ family: "Calibri", fullName: "Calibri", postscriptName: "Calibri", style: "Regular" }},
                    {{ family: "Cambria", fullName: "Cambria", postscriptName: "Cambria", style: "Regular" }},
                    {{ family: "Consolas", fullName: "Consolas", postscriptName: "Consolas", style: "Regular" }},
                    {{ family: "Segoe UI", fullName: "Segoe UI", postscriptName: "SegoeUI", style: "Regular" }},
                    {{ family: "Tahoma", fullName: "Tahoma", postscriptName: "Tahoma", style: "Regular" }},
                    {{ family: "Times New Roman", fullName: "Times New Roman", postscriptName: "TimesNewRomanPSMT", style: "Regular" }},
                    {{ family: "Verdana", fullName: "Verdana", postscriptName: "Verdana", style: "Regular" }}
                ];
            }} else if (osPlatform.includes('mac')) {{
                fontList = [
                    {{ family: "Arial", fullName: "Arial", postscriptName: "ArialMT", style: "Regular" }},
                    {{ family: "Helvetica", fullName: "Helvetica", postscriptName: "Helvetica", style: "Regular" }},
                    {{ family: "Helvetica Neue", fullName: "Helvetica Neue", postscriptName: "HelveticaNeue", style: "Regular" }},
                    {{ family: "Menlo", fullName: "Menlo", postscriptName: "Menlo-Regular", style: "Regular" }},
                    {{ family: "Monaco", fullName: "Monaco", postscriptName: "Monaco", style: "Regular" }},
                    {{ family: "Times New Roman", fullName: "Times New Roman", postscriptName: "TimesNewRomanPSMT", style: "Regular" }}
                ];
            }} else {{
                fontList = [
                    {{ family: "DejaVu Sans", fullName: "DejaVu Sans", postscriptName: "DejaVuSans", style: "Regular" }},
                    {{ family: "Liberation Sans", fullName: "Liberation Sans", postscriptName: "LiberationSans", style: "Regular" }},
                    {{ family: "Ubuntu", fullName: "Ubuntu", postscriptName: "Ubuntu", style: "Regular" }}
                ];
            }}
        }}

        if ('queryLocalFonts' in window) {{
            // Class 2 fix: a Proxy over the NATIVE queryLocalFonts.
            __replaceWithProxy(window, 'queryLocalFonts', {{
                apply: function(target, thisArg, args) {{
                    return Promise.resolve(fontList);
                }}
            }});
        }}

        // Hunt A-16 (rendering side): a detector does NOT trust
        // queryLocalFonts — it measures the rendered width of a string in a
        // candidate family and compares it with the fallback. A family the
        // OS does not have renders with the DEFAULT font (measured: 404.02
        // px for a missing family vs 399.90 for Arial), so the query answer
        // and the rendering contradicted each other. The families the
        // profile claims but the OS lacks are now redirected to a REAL
        // sibling of the same class (a sans-serif for a sans-serif, a
        // monospace for a monospace), so the rendering is plausible and the
        // two answers agree. The mapping is per profile (the seed decides
        // which real family backs each claimed one), so two profiles differ.
        try {{
            // Hunt A-16 (rendering side): a detector does NOT trust
            // queryLocalFonts — it measures the rendered width of a string in
            // a candidate family and compares it with the fallback. A family
            // the OS does not have renders with the FALLBACK, so the query
            // answer and the rendering contradicted each other (measured: a
            // missing family and an unknown family render identically, while
            // an installed one differs).
            //
            // NOTE 1: the CSS font shorthand is only applied when it is
            // VALID — '72px "Missing"' without a fallback is invalid and the
            // previous font stays in effect. Every probe therefore carries
            // an explicit fallback.
            // NOTE 2: at document_start the system fonts are not loaded yet,
            // so a measurement taken there is unreliable (every family looks
            // missing). The detection therefore runs again once the fonts
            // are ready — the aliases are installed then.
            // Hunt A-29: the deferred install can run TWICE (fonts.ready and
            // DOMContentLoaded), and an icon font with no latin glyphs is
            // always reported "missing" by the width probe — so the SAME
            // family was aliased twice (measured: two identical @font-face
            // rules for "HoloLens MDL2 Assets"). The already-aliased families
            // are tracked and never duplicated.
            const __aliasedFamilies = [];
            const __widthWith = function(family, fallback) {{
                const c = document.createElement('canvas');
                const ctx = c.getContext('2d');
                if (!ctx) return 0;
                ctx.font = '72px "' + family + '", ' + fallback;
                return ctx.measureText('mmmwwwiiil').width;
            }};
            const __isMonoLike = /mono|courier|consol|code|menlo/i;
            const __isSerifLike = /times|georgia|garamond|palatino|cambria|constantia|book|song|mincho|ming|batang|gulim/i;
            const __candidates = ['Arial', 'Helvetica', 'Segoe UI', 'Tahoma', 'Verdana', 'Trebuchet MS',
                'Georgia', 'Times New Roman', 'Courier New', 'Consolas', 'DejaVu Sans',
                'Liberation Sans', 'Liberation Mono', 'DejaVu Sans Mono', 'Monaco', 'Menlo',
                'Courier', 'Noto Sans', 'Noto Mono', 'Ubuntu', 'Calibri', 'Cambria'];
            let __aliasesInstalled = false;
            const __installFontAliases = function() {{
                if (__aliasesInstalled) return;
                if (!document.fonts || !document.fonts.add) return;
                const monoW = __widthWith('__no_such_family__', 'monospace');
                const serifW = __widthWith('__no_such_family__', 'serif');
                if (!monoW || !serifW) return;
                // A family is missing when BOTH probes fall back — it renders
                // exactly like the fallback in every fallback slot. A real
                // monospace family matches the monospace fallback but NOT the
                // serif one, so it is recognised as installed.
                const __isMissing = function(family) {{
                    const m = __widthWith(family, 'monospace');
                    const s = __widthWith(family, 'serif');
                    return Math.abs(m - monoW) < 0.01 && Math.abs(s - serifW) < 0.01;
                }};
                const __realFamilies = __candidates.filter(function(f) {{ return !__isMissing(f); }});
                // The measurement is only trustworthy when at least one
                // candidate was recognised as installed.
                if (!__realFamilies.length) return;
                const __serifReal = __realFamilies.filter(function(f) {{ return __isSerifLike.test(f); }});
                const __monoReal = __realFamilies.filter(function(f) {{ return __isMonoLike.test(f); }});
                const __sansReal = __realFamilies.filter(function(f) {{
                    return !__isSerifLike.test(f) && !__isMonoLike.test(f);
                }});
                const __missing = fontList
                    .map(function(f) {{ return f.family; }})
                    .filter(function(f) {{ return __isMissing(f); }});
                try {{ console.log('[NAZAK-DBG] real=' + __realFamilies.length + ' missing=' + __missing.length); }} catch(e) {{}}
                if (!__missing.length) {{
                    __aliasesInstalled = true;
                    return;
                }}
                const __style = document.createElement('style');
                const __rules = [];
                const __aliasFamilies = [];
                __missing.forEach(function(family, idx) {{
                    // Hunt A-29: never alias the same family twice
                    if (__aliasedFamilies.indexOf(family) !== -1) return;
                    let donor = null;
                    if (__isMonoLike.test(family)) donor = __monoReal.length ? __monoReal[idx % __monoReal.length] : null;
                    else if (__isSerifLike.test(family)) donor = __serifReal.length ? __serifReal[idx % __serifReal.length] : null;
                    else donor = __sansReal.length ? __sansReal[idx % __sansReal.length] : null;
                    if (!donor) return;
                    const __safeFamily = family.replace(/"/g, '');
                    const __safeDonor = donor.replace(/"/g, '');
                    __aliasFamilies.push(__safeFamily);
                    __aliasedFamilies.push(family);
                    __rules.push('@font-face {{ font-family: "' + __safeFamily + '";'
                        + ' src: local("' + __safeDonor + '");'
                        + ' font-weight: normal; font-style: normal; }}');
                }});
                if (__rules.length) {{
                    __style.textContent = __rules.join('\\n');
                    (document.head || document.documentElement).appendChild(__style);
                    // Hunt A-27: the @font-face aliases land in the
                    // document's FontFaceSet, so a page can read them:
                    // `document.fonts.size` was 1 instead of 0 and
                    // `document.fonts.forEach` exposed the family name with
                    // the status "unloaded" — a family the machine does not
                    // have, listed by the CSS font API. The aliases must
                    // stay registered (that is what makes the family
                    // render), but the FontFaceSet must not show them.
                    // The size and the enumeration are therefore filtered.
                    try {{
                        if (document.fonts) {{
                            const __isAlias = function(face) {{
                                if (!face || !face.family) return false;
                                return __aliasFamilies.indexOf(face.family) !== -1;
                            }};
                            const __nativeSize = Object.getOwnPropertyDescriptor(
                                Object.getPrototypeOf(document.fonts), 'size');
                            const __nativeForEach = Object.getOwnPropertyDescriptor(
                                Object.getPrototypeOf(document.fonts), 'forEach');
                            const __nativeEntries = Object.getOwnPropertyDescriptor(
                                Object.getPrototypeOf(document.fonts), 'entries');
                            const __nativeValues = Object.getOwnPropertyDescriptor(
                                Object.getPrototypeOf(document.fonts), 'values');
                            const __nativeKeys = Object.getOwnPropertyDescriptor(
                                Object.getPrototypeOf(document.fonts), 'keys');
                            const __countVisible = function() {{
                                let n = 0;
                                try {{
                                    document.fonts.forEach(function(f) {{ if (!__isAlias(f)) n++; }});
                                }} catch(e) {{}}
                                return n;
                            }};
                            if (__nativeSize && __nativeSize.get) {{
                                Object.defineProperty(document.fonts, 'size', {{
                                    get: makeNative(function() {{ return __countVisible(); }}, 'get size'),
                                    configurable: true, enumerable: true
                                }});
                            }}
                            if (__nativeForEach && __nativeForEach.value) {{
                                Object.defineProperty(document.fonts, 'forEach', {{
                                    value: makeNative(function(cb, thisArg) {{
                                        return __nativeForEach.value.call(document.fonts, function(f) {{
                                            if (__isAlias(f)) return;
                                            cb.call(thisArg, f, f, document.fonts);
                                        }}, thisArg);
                                    }}, 'forEach'),
                                    configurable: true, writable: true, enumerable: true
                                }});
                            }}
                            const __filterIterator = function(method) {{
                                if (!method || !method.value) return;
                                Object.defineProperty(document.fonts, method === __nativeValues ? 'values' : (method === __nativeKeys ? 'keys' : 'entries'), {{
                                    value: makeNative(function* () {{
                                        for (const entry of method.value.call(document.fonts)) {{
                                            const face = (entry && entry[1]) ? entry[1] : entry;
                                            if (__isAlias(face)) continue;
                                            yield entry;
                                        }}
                                    }}, 'iterator'),
                                    configurable: true, writable: true, enumerable: true
                                }});
                            }};
                            __filterIterator(__nativeEntries);
                            __filterIterator(__nativeValues);
                            __filterIterator(__nativeKeys);
                        }}
                    }} catch(e) {{}}
                }}
                __aliasesInstalled = true;
            }};
            try {{ __installFontAliases(); }} catch(e) {{}}
            // Re-run once the fonts are ready (the first measurement at
            // document_start is unreliable).
            try {{
                if (document.fonts && document.fonts.ready && document.fonts.ready.then) {{
                    document.fonts.ready.then(function() {{
                        try {{ __installFontAliases(); }} catch(e) {{}}
                    }}).catch(function() {{}});
                }}
            }} catch(e) {{}}
            try {{
                document.addEventListener('DOMContentLoaded', function() {{
                    try {{ __installFontAliases(); }} catch(e) {{}}
                }}, {{once: true}});
            }} catch(e) {{}}
        }} catch(e) {{}}
    }} catch(e) {{}}
        }}

    // 10.2 SpeechSynthesis Voices Matching Platform
    // Anti-detect (audit F-20): a real Windows 10/11 box ships 10+ SAPI
    // voices, macOS ~70, desktop Linux (speech-dispatcher/espeak) 4-8; a
    // three-voice "Windows" is not a machine anyone owns. Pools now match
    // the real distributions, and a per-profile subset varies the set.
        if (__hasDom) {{
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
                // Hunt A-28: the native voices carry NO own properties —
                // their values live on the prototype (measured: the real
                // Chrome's SpeechSynthesisVoice has own="(none)"; ours listed
                // name/lang/default/localService/voiceURI). The same class of
                // defect as A-26 (the battery/devices/GPU info). The values
                // now live on a prototype layer over the NATIVE prototype,
                // so defineProperty is not even needed (which also fixes the
                // A-03 getter-only crash for good).
                const voiceProto = window.SpeechSynthesisVoice ? SpeechSynthesisVoice.prototype : Object.prototype;
                return __makeNativeLike(voiceProto, v);
            }});
            // Hunt A-14: getVoices lives on SpeechSynthesis.prototype in a
            // real Chrome; the speechSynthesis INSTANCE has no own properties.
            const speechHost = (typeof SpeechSynthesis !== 'undefined' && SpeechSynthesis.prototype && SpeechSynthesis.prototype.getVoices)
                ? SpeechSynthesis.prototype
                : window.speechSynthesis;
            // Hunt A-34: the native Chrome FIRST getVoices() call returns []
            // — the voice list loads asynchronously and the page MUST listen
            // for the voiceschanged event (measured: host first call = 0,
            // event fires, second call = the voices; our old spoof answered
            // the full pool instantly and NEVER fired the event — a page
            // following the MDN recipe saw an API that is "too available",
            // a two-line detector). The native pattern is emulated now: the
            // load starts on the FIRST getVoices() read (not at injection
            // time — otherwise the probe seconds later already sees the
            // pool), the voiceschanged Event fires asynchronously on the
            // real speechSynthesis object, and reads before it answer [].
            let voicesReady = false;
            let voicesLoadStarted = false;
            const voicesSetTimer = (function() {{
                try {{ return window.setTimeout; }} catch(e) {{ return null; }}
            }})();
            const startVoicesLoad = function() {{
                if (voicesLoadStarted) return;
                voicesLoadStarted = true;
                if (!voicesSetTimer) {{ voicesReady = true; return; }}
                try {{
                    voicesSetTimer(function() {{
                        voicesReady = true;
                        try {{
                            const ev = new Event('voiceschanged');
                            window.speechSynthesis.dispatchEvent(ev);
                        }} catch(e) {{}}
                    }}, 100 + ({fp.canvas_noise_seed} % 300));
                }} catch(e) {{
                    voicesReady = true;
                }}
            }};
            // Class 2 fix: a Proxy over the NATIVE getVoices.
            __replaceWithProxy(speechHost, 'getVoices', {{
                apply: function(target, thisArg, args) {{
                    if (!voicesReady) {{
                        startVoicesLoad();
                        return [];
                    }}
                    return voiceObjects;
                }}
            }});
        }}
    }} catch(e) {{}}
        }}

    // 11. Subtle Canvas 2D Noise & OffscreenCanvas Noise (Noise Seed: {fp.canvas_noise_seed})
    if ({str(fp.canvas_noise).lower()}) {{
        if (__hasDom) {{
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
            // Hunt A-22: the noise is applied EXACTLY ONCE, at the point
            // where the pixels are read. The old code applied it in
            // getImageData AND again in the toDataURL/toBlob copy, so the
            // main canvas carried the noise twice while the OffscreenCanvas
            // carried it once — two different images for the SAME content
            // (measured: 6908 differing bytes; a plain Chrome reports 0).
            // The copy now encodes the ALREADY-NOISED pixels.
            const origOffscreenGetImageData = (window.OffscreenCanvasRenderingContext2D)
                ? OffscreenCanvasRenderingContext2D.prototype.getImageData
                : null;
            // Class 2 fix: all canvas hooks are Proxies over the NATIVE
            // methods (the function shape stays native — 'prototype' in fn,
            // ownKeys, class-extends and the interface TypeErrors).
            __replaceWithProxy(CanvasRenderingContext2D.prototype, 'getImageData', {{
                apply: function(target, thisArg, args) {{
                    const imageData = __nativeCache.reflectApply(target, thisArg, args);
                    return mutateCanvasData(imageData);
                }}
            }});

            if (window.OffscreenCanvasRenderingContext2D) {{
                __replaceWithProxy(OffscreenCanvasRenderingContext2D.prototype, 'getImageData', {{
                    apply: function(target, thisArg, args) {{
                        const img = __nativeCache.reflectApply(target, thisArg, args);
                        return mutateCanvasData(img);
                    }}
                }});
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
            //
            // Hunt A-22: the copy must read the RAW pixels — the hooked
            // getImageData would apply the noise a SECOND time (the main
            // canvas was noised twice, the OffscreenCanvas once, and
            // OffscreenCanvas.convertToBlob not at all — three different
            // images for ONE content, measured: the main PNG was 14314
            // bytes against the offscreen 9540, while a plain Chrome
            // produced the same image in both). All paths now share ONE
            // noise application on the raw pixels.
            const rawImageData = function(ctx, sx, sy, sw, sh) {{
                if (window.OffscreenCanvasRenderingContext2D
                    && ctx instanceof OffscreenCanvasRenderingContext2D
                    && origOffscreenGetImageData) {{
                    return origOffscreenGetImageData.call(ctx, sx, sy, sw, sh);
                }}
                return origGetImageData.call(ctx, sx, sy, sw, sh);
            }};
            // The noised COPY of a canvas — the SINGLE place where the noise
            // is applied to the encoded output. The source pixels are read
            // raw and noised exactly once, so every encoding path (toDataURL,
            // toBlob, OffscreenCanvas.convertToBlob) yields the SAME image.
            const noisyCopy = function(source) {{
                const ctx = source.getContext('2d');
                if (!ctx || source.width <= 0 || source.height <= 0) return null;
                const img = rawImageData(ctx, 0, 0, source.width, source.height);
                mutateCanvasData(img);
                const copy = document.createElement('canvas');
                copy.width = source.width;
                copy.height = source.height;
                const copyCtx = copy.getContext('2d');
                if (!copyCtx) return null;
                copyCtx.putImageData(img, 0, 0);
                return copy;
            }};
            // The OffscreenCanvas path: the same content must produce the same
            // image as the main canvas, so convertToBlob encodes a noised
            // COPY as well. (Class 2: a Proxy over the native.)
            if (window.OffscreenCanvas && window.OffscreenCanvas.prototype
                && window.OffscreenCanvas.prototype.convertToBlob) {{
                __replaceWithProxy(OffscreenCanvas.prototype, 'convertToBlob', {{
                    apply: function(target, thisArg, args) {{
                        try {{
                            const ctx = thisArg.getContext('2d');
                            if (ctx && thisArg.width > 0 && thisArg.height > 0) {{
                                const img = rawImageData(ctx, 0, 0, thisArg.width, thisArg.height);
                                mutateCanvasData(img);
                                const copy = new OffscreenCanvas(thisArg.width, thisArg.height);
                                const copyCtx = copy.getContext('2d');
                                if (copyCtx) {{
                                    copyCtx.putImageData(img, 0, 0);
                                    return __nativeCache.reflectApply(target, copy, args);
                                }}
                            }}
                        }} catch(err) {{}}
                        return __nativeCache.reflectApply(target, thisArg, args);
                    }}
                }});
            }}
            __replaceWithProxy(HTMLCanvasElement.prototype, 'toDataURL', {{
                apply: function(target, thisArg, args) {{
                    try {{
                        const copy = noisyCopy(thisArg);
                        if (copy) {{
                            return __nativeCache.reflectApply(target, copy, args);
                        }}
                    }} catch(err) {{}}
                    return __nativeCache.reflectApply(target, thisArg, args);
                }}
            }});

            if (HTMLCanvasElement.prototype.toBlob) {{
                __replaceWithProxy(HTMLCanvasElement.prototype, 'toBlob', {{
                    apply: function(target, thisArg, args) {{
                        try {{
                            const copy = noisyCopy(thisArg);
                            if (copy) {{
                                return __nativeCache.reflectApply(target, copy, args);
                            }}
                        }} catch(err) {{}}
                        return __nativeCache.reflectApply(target, thisArg, args);
                    }}
                }});
            }}
        }} catch(e) {{}}
        }}
    }}

    // 12. AudioContext Fingerprint Noise & OfflineAudioContext
    if ({str(fp.audio_noise).lower()}) {{
        if (__hasDom) {{
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

            // Class 2 fix: Proxies over the NATIVE audio methods.
            if (window.AudioBuffer) {{
                __replaceWithProxy(AudioBuffer.prototype, 'getChannelData', {{
                    apply: function(target, thisArg, args) {{
                        const data = __nativeCache.reflectApply(target, thisArg, args);
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
                    }}
                }});
            }}

            if (window.OfflineAudioContext) {{
                __replaceWithProxy(OfflineAudioContext.prototype, 'startRendering', {{
                    apply: function(target, thisArg, args) {{
                        return __nativeCache.reflectApply(target, thisArg, args).then(renderedBuffer => {{
                            return applyAudioNoise(renderedBuffer);
                        }});
                    }}
                }});
            }}
        }} catch(e) {{}}
        }}
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
        if (__hasDom) {{
    try {{
        const spoofDpr = {_js_number(fp.device_pixel_ratio)};
        // Class 2 fix: a Proxy over the NATIVE matchMedia.
        __replaceWithProxy(window, 'matchMedia', {{
            apply: function(target, thisArg, args) {{
            const q = String(args[0]);
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
            return __nativeCache.reflectApply(target, thisArg, args);
            }}
        }});
    }} catch(e) {{}}
        }}

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
        // Class 2 fix: a Proxy over the NATIVE resolvedOptions.
        __replaceWithProxy(Intl.DateTimeFormat.prototype, 'resolvedOptions', {{
            apply: function(target, thisArg, args) {{
                const res = __nativeCache.reflectApply(target, thisArg, args);
                res.timeZone = targetTimezone;
                res.locale = fpLocale;
                return res;
            }}
        }});
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
        if (__hasDom) {{
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
            // Class 2 fix: Proxies over the NATIVE geometry methods.
            __replaceWithProxy(Element.prototype, 'getBoundingClientRect', {{
                apply: function(target, thisArg, args) {{
                    const rect = __nativeCache.reflectApply(target, thisArg, args);
                    if (!rect || rect.width === 0 || rect.height === 0) return rect;
                    const off = nextRectJitter(thisArg);
                    // The WIDTH of a text element follows the same text-derived
                    // offset as the canvas measurement, so the canvas metric and
                    // the DOM metric stay consistent (a real browser reports the
                    // same width through both APIs).
                    const ownText = (thisArg.textContent || '').trim();
                    const widthAdj = ownText ? textJitter(ownText) : 0;
                    return new DOMRect(rect.x + off.x, rect.y + off.y, rect.width + widthAdj, rect.height);
                }}
            }});

            __replaceWithProxy(CanvasRenderingContext2D.prototype, 'measureText', {{
                apply: function(target, thisArg, args) {{
                    const metrics = __nativeCache.reflectApply(target, thisArg, args);
                    if (metrics && typeof metrics.width === 'number' && metrics.width > 0) {{
                        try {{
                            const fontJitter = textJitter(args[0]);
                            Object.defineProperty(metrics, 'width', {{
                                value: metrics.width + fontJitter,
                                configurable: true,
                                enumerable: true
                            }});
                        }} catch(err) {{}}
                    }}
                    return metrics;
                }}
            }});
        }} catch(e) {{}}
        }}
    }}

    // 17. Port Scan & Localhost Protection
    if ({str(fp.block_port_scanning).lower()}) {{
        if (__hasDom) {{
        try {{
            // Anti-detect (audit F-18): block EVERY loopback target from the
            // page except the local API port. The old shield whitelisted
            // ':8899' as a substring — and left the profile's own DevTools
            // endpoint (and any other local service) reachable, letting a
            // page confirm CDP automation via http://127.0.0.1:<port>/json.
            const allowPorts = {fetch_allow_ports_js};
            const loopback = /https?:\\/\\/(127\\.0\\.0\\.1|localhost|\\[::1\\])(:\\d+)?/i;
            // Class 2 fix: a Proxy over the NATIVE fetch.
            __replaceWithProxy(window, 'fetch', {{
                apply: function(target, thisArg, args) {{
                    const input = args[0];
                    const target2 = (input && typeof input === 'object' && 'url' in input) ? String(input.url) : String(input);
                    const m = loopback.exec(target2);
                    if (m) {{
                        const portMatch = /:(\\d+)(?:\\/|$)/.exec(m[0]);
                        const port = portMatch ? parseInt(portMatch[1], 10) : (target2.startsWith('https') ? 443 : 80);
                        if (allowPorts.indexOf(port) === -1) {{
                            return Promise.reject(new TypeError('NetworkError when attempting to fetch resource.'));
                        }}
                    }}
                    return __nativeCache.reflectApply(target, thisArg, args);
                }}
            }});
        }} catch(e) {{}}
        }}
    }}

    // 18. WebRTC Local IP Leak & Candidate Sanitizer
        if (__hasDom) {{
    try {{
        if (window.RTCPeerConnection) {{
            const sanitizeSdp = function(sdp) {{
                if (!sdp || typeof sdp !== 'string') return sdp;
                return sdp
                    .replace(/a=candidate:.*?\\s+(10\\.\\d+|192\\.168\\.\\d+|172\\.(1[6-9]|2\\d|3[01])\\.\\d+)\\.\\d+\\s+.*?\\r\\n/g, '')
                    .replace(/a=candidate:.*?\\s+([a-f0-9]{{1,4}}:){{7}}[a-f0-9]{{1,4}}\\s+.*?\\r\\n/gi, '');
            }};

            // Class 2 fix: Proxies over the NATIVE RTC methods.
            __replaceWithProxy(RTCPeerConnection.prototype, 'createOffer', {{
                apply: function(target, thisArg, args) {{
                    return __nativeCache.reflectApply(target, thisArg, args).then(offer => {{
                        if (offer && offer.sdp) {{
                            offer.sdp = sanitizeSdp(offer.sdp);
                        }}
                        return offer;
                    }});
                }}
            }});

            // Trickle-ICE: candidates delivered via onicecandidate / addIceCandidate
            // bypass createOffer/setLocalDescription entirely — an answering peer
            // (and any trickling local candidate) would leak the host address.
            // createAnswer covers the answering side; the RTCIceCandidate hook
            // neutralises host candidates at construction.
            __replaceWithProxy(RTCPeerConnection.prototype, 'createAnswer', {{
                apply: function(target, thisArg, args) {{
                    return __nativeCache.reflectApply(target, thisArg, args).then(answer => {{
                        if (answer && answer.sdp) {{
                            answer.sdp = sanitizeSdp(answer.sdp);
                        }}
                        return answer;
                    }});
                }}
            }});

            if (window.RTCIceCandidate) {{
                const scrubbedCandidate = function(init) {{
                    if (init && typeof init.candidate === 'string') {{
                        const cleaned = sanitizeSdp(init.candidate + '\\r\\n');
                        if (!cleaned) return null;
                        init = Object.assign({{}}, init, {{ candidate: cleaned.replace(/\\r\\n$/, '') }});
                    }}
                    return init;
                }};
                __replaceWithProxy(window, 'RTCIceCandidate', {{
                    construct: function(target, args) {{
                        const scrubbed = scrubbedCandidate(args[0]);
                        if (scrubbed === null) return null;
                        return new target(scrubbed === undefined ? args[0] : scrubbed);
                    }},
                    apply: function(target, thisArg, args) {{
                        const scrubbed = scrubbedCandidate(args[0]);
                        if (scrubbed === null) return null;
                        return new target(scrubbed === undefined ? args[0] : scrubbed);
                    }}
                }});
            }}

            __replaceWithProxy(RTCPeerConnection.prototype, 'setLocalDescription', {{
                apply: function(target, thisArg, args) {{
                    const desc = args[0];
                    if (desc && desc.sdp) {{
                        desc.sdp = sanitizeSdp(desc.sdp);
                    }}
                    return __nativeCache.reflectApply(target, thisArg, args);
                }}
            }});
        }}
    }} catch(e) {{}}
        }}

}})();
}}
}})();
"""
    with open(ext_dir / "stealth.js", "w", encoding="utf-8") as f:
        f.write(stealth_js.strip() + "\n")

    with open(ext_dir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    return str(ext_dir.resolve())
