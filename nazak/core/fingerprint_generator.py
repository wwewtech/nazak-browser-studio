"""
Ultra-Realistic Hardware & Digital Fingerprint Generator.
Generates fully consistent hardware specifications (GPU, CPU, RAM, Screen, Client Hints, Media Devices, Audio/Canvas Seeds)
guaranteeing complete spoofing and isolation of the host PC characteristics.
"""

import random
import uuid
from typing import Any

from ..models.profile import BatterySpoofConfig, FingerprintConfig, GeolocationSpoofConfig, MediaDeviceInfo

# Realistic GPU combinations
GPU_PRESETS: list[dict[str, Any]] = [
    {
        "vendor": "Google Inc. (NVIDIA)",
        "renderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 4090 Direct3D11 vs_5_0 ps_5_0, D3D11)",
        "unmasked_vendor": "NVIDIA Corporation",
        "unmasked_renderer": "NVIDIA GeForce RTX 4090",
        "cores": [16, 24, 32],
        "ram": [32, 64],
        "os": ["windows"],
    },
    {
        "vendor": "Google Inc. (NVIDIA)",
        "renderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 4080 Direct3D11 vs_5_0 ps_5_0, D3D11)",
        "unmasked_vendor": "NVIDIA Corporation",
        "unmasked_renderer": "NVIDIA GeForce RTX 4080",
        "cores": [12, 16, 24],
        "ram": [32, 64],
        "os": ["windows"],
    },
    {
        "vendor": "Google Inc. (NVIDIA)",
        "renderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 3080 Direct3D11 vs_5_0 ps_5_0, D3D11)",
        "unmasked_vendor": "NVIDIA Corporation",
        "unmasked_renderer": "NVIDIA GeForce RTX 3080",
        "cores": [8, 12, 16],
        "ram": [16, 32],
        "os": ["windows"],
    },
    {
        "vendor": "Google Inc. (NVIDIA)",
        "renderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 3070 Direct3D11 vs_5_0 ps_5_0, D3D11)",
        "unmasked_vendor": "NVIDIA Corporation",
        "unmasked_renderer": "NVIDIA GeForce RTX 3070",
        "cores": [8, 12, 16],
        "ram": [16, 32],
        "os": ["windows"],
    },
    {
        "vendor": "Google Inc. (NVIDIA)",
        "renderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)",
        "unmasked_vendor": "NVIDIA Corporation",
        "unmasked_renderer": "NVIDIA GeForce RTX 3060",
        "cores": [6, 8, 12],
        "ram": [16, 32],
        "os": ["windows"],
    },
    {
        "vendor": "Google Inc. (AMD)",
        "renderer": "ANGLE (AMD, AMD Radeon RX 7800 XT Direct3D11 vs_5_0 ps_5_0, D3D11)",
        "unmasked_vendor": "Advanced Micro Devices, Inc.",
        "unmasked_renderer": "AMD Radeon RX 7800 XT",
        "cores": [8, 12, 16],
        "ram": [16, 32],
        "os": ["windows"],
    },
    {
        "vendor": "Google Inc. (AMD)",
        "renderer": "ANGLE (AMD, AMD Radeon RX 6700 XT Direct3D11 vs_5_0 ps_5_0, D3D11)",
        "unmasked_vendor": "Advanced Micro Devices, Inc.",
        "unmasked_renderer": "AMD Radeon RX 6700 XT",
        "cores": [8, 12, 16],
        "ram": [16, 32],
        "os": ["windows"],
    },
    {
        "vendor": "Google Inc. (Intel)",
        "renderer": "ANGLE (Intel, Intel(R) UHD Graphics 770 Direct3D11 vs_5_0 ps_5_0, D3D11)",
        "unmasked_vendor": "Intel Inc.",
        "unmasked_renderer": "Intel(R) UHD Graphics 770",
        "cores": [6, 8, 12],
        "ram": [16, 32],
        "os": ["windows"],
    },
    {
        "vendor": "Google Inc. (Intel)",
        "renderer": "ANGLE (Intel, Intel(R) Arc(TM) Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)",
        "unmasked_vendor": "Intel Inc.",
        "unmasked_renderer": "Intel(R) Arc(TM) Graphics",
        "cores": [8, 14, 16],
        "ram": [16, 32],
        "os": ["windows"],
    },
    {
        "vendor": "Google Inc. (Apple)",
        "renderer": "ANGLE (Apple, ANGLE Metal Renderer: Apple M3 Max, Version 15.0)",
        "unmasked_vendor": "Apple Inc.",
        "unmasked_renderer": "Apple M3 Max GPU",
        "cores": [14, 16],
        "ram": [36, 64],
        "os": ["mac"],
    },
    {
        "vendor": "Google Inc. (Apple)",
        "renderer": "ANGLE (Apple, ANGLE Metal Renderer: Apple M2 Pro, Version 14.5)",
        "unmasked_vendor": "Apple Inc.",
        "unmasked_renderer": "Apple M2 Pro GPU",
        "cores": [10, 12],
        "ram": [16, 32],
        "os": ["mac"],
    },
    # Audit fix P1-6 (A1): Linux GPU presets must use real Mesa / OpenGL strings.
    # The previous code picked Windows Direct3D11 presets for Linux profiles,
    # producing ANGLE (... Direct3D11 ...) — an impossible combination on Linux.
    {
        "vendor": "Google Inc. (NVIDIA Corporation)",
        "renderer": "ANGLE (NVIDIA Corporation, NVIDIA GeForce RTX 3080/PCIe/SSE2, OpenGL 4.5.0)",
        "unmasked_vendor": "NVIDIA Corporation",
        "unmasked_renderer": "NVIDIA GeForce RTX 3080/PCIe/SSE2",
        "cores": [8, 12, 16],
        "ram": [16, 32],
        "os": ["linux"],
    },
    {
        "vendor": "Google Inc. (AMD)",
        "renderer": "ANGLE (AMD, AMD Radeon RX 6700 XT (radeonsi, navi22, LLVM 15.0.7, DRM 3.49), OpenGL 4.6)",
        "unmasked_vendor": "AMD",
        "unmasked_renderer": "AMD Radeon RX 6700 XT (radeonsi, navi22, LLVM 15.0.7, DRM 3.49)",
        "cores": [8, 12, 16],
        "ram": [16, 32],
        "os": ["linux"],
    },
    {
        "vendor": "Google Inc. (Intel)",
        "renderer": "ANGLE (Intel, Mesa Intel(R) UHD Graphics 770 (ADL-S GT1), OpenGL 4.6)",
        "unmasked_vendor": "Intel",
        "unmasked_renderer": "Mesa Intel(R) UHD Graphics 770 (ADL-S GT1)",
        "cores": [6, 8, 12],
        "ram": [16, 32],
        "os": ["linux"],
    },
]

# Realistic Screen Resolutions with standard aspect ratios
SCREEN_RESOLUTIONS: list[dict[str, float]] = [
    {"width": 1920, "height": 1080, "avail_w": 1920, "avail_h": 1040, "dpr": 1.0},
    {"width": 2560, "height": 1440, "avail_w": 2560, "avail_h": 1400, "dpr": 1.25},
    {"width": 3840, "height": 2160, "avail_w": 3840, "avail_h": 2120, "dpr": 2.0},
    {"width": 1536, "height": 864, "avail_w": 1536, "avail_h": 824, "dpr": 1.0},
    {"width": 1440, "height": 900, "avail_w": 1440, "avail_h": 860, "dpr": 1.0},
    {"width": 1680, "height": 1050, "avail_w": 1680, "avail_h": 1010, "dpr": 1.0},
    {"width": 1920, "height": 1200, "avail_w": 1920, "avail_h": 1160, "dpr": 1.0},
    {"width": 1366, "height": 768, "avail_w": 1366, "avail_h": 728, "dpr": 1.0},
]

# Anti-detect (audit F-10): the pool reflected Chrome 130-133 while the real
# stable channel moved on; a version share that no longer exists in the wild
# is suspicious by itself. The pool now spans a ~1-year window of the stable
# channel. At launch, _fingerprint_with_runtime_chrome_version() additionally
# rebuilds the UA/brands from the REAL installed Chrome build, so the spoofed
# identity always matches the binary that actually renders the page.
_CHROME_UA_VERSIONS = ["142", "141", "140", "139", "138", "137", "136"]

USER_AGENTS_WINDOWS = [
    f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{v}.0.0.0 Safari/537.36"
    for v in _CHROME_UA_VERSIONS
]
USER_AGENTS_LINUX = [
    f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{v}.0.0.0 Safari/537.36"
    for v in _CHROME_UA_VERSIONS
]
USER_AGENTS_MAC = [
    f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{v}.0.0.0 Safari/537.36"
    for v in _CHROME_UA_VERSIONS
]

# IANA zone names with their STANDARD-time offsets in JS getTimezoneOffset() sign
# (UTC-5 New York -> +300). The offsets below are FALLBACK-ONLY: generation always
# resolves the CURRENT offset (DST-aware) through zoneinfo, because a static offset
# goes stale for half the year (Berlin is -60 in winter, -120 in summer) and a
# timezone/offset mismatch is an instant tell for any consistency check.
TIMEZONES = [
    ("America/New_York", 300),
    ("America/Chicago", 360),
    ("America/Denver", 420),
    ("America/Los_Angeles", 480),
    ("Europe/London", 0),
    ("Europe/Berlin", -60),
    ("Europe/Paris", -60),
    ("Asia/Tokyo", -540),
    ("Australia/Sydney", -600),
]


def calculate_tz_offset(tz_name: str) -> int:
    """Calculates timezone offset in minutes according to JS Date.getTimezoneOffset().

    Always resolves the CURRENT (DST-aware) offset through zoneinfo. The static
    table below is a last-resort fallback for environments without the IANA
    database (no system tzdata and no tzdata wheel): there the offset can be a
    standard-time value during a DST period, which is logged as a warning.
    An unknown zone falls back to UTC (0) instead of an arbitrary US offset.
    """
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        now = datetime.now(ZoneInfo(tz_name))
        offset = now.utcoffset()
        offset_sec = offset.total_seconds() if offset is not None else 0
        # In JS: UTC-5 (New York) is +300, UTC+3 (Moscow) is -180
        return int(-offset_sec / 60)
    except Exception:
        import logging

        logging.getLogger(__name__).warning(
            "calculate_tz_offset: zoneinfo unavailable for %r (missing tzdata?) — "
            "using a static offset; it may be wrong during DST",
            tz_name,
        )
        matching_tz = [t for t in TIMEZONES if t[0] == tz_name]
        if matching_tz:
            return matching_tz[0][1]
        return 0  # unknown zone: UTC, not an arbitrary region


# Anti-detect (audit A-16): the installed font pool is a fingerprint vector.
# A real Windows 10/11 box reports 25-60 families through queryLocalFonts
# (measured on the audit host: 389 font FILES, 40+ families visible to the
# width probe), while the old shield returned a hardcoded list of NINE —
# unrealistically few, and self-contradicting (it advertised a family the
# host does not have, so the rendering probe and the query disagreed).
# The pools below model the real distribution: a large common core plus a
# random tail of optional families, so two profiles differ but both look
# like a real machine.
FONT_POOLS: dict[str, list[str]] = {
    "windows": [
        "Arial",
        "Arial Black",
        "Bahnschrift",
        "Calibri",
        "Cambria",
        "Cambria Math",
        "Candara",
        "Comic Sans MS",
        "Consolas",
        "Constantia",
        "Corbel",
        "Courier New",
        "Ebrima",
        "Franklin Gothic Medium",
        "Gabriola",
        "Garamond",
        "Georgia",
        "HoloLens MDL2 Assets",
        "Impact",
        "Ink Free",
        "Javanese Text",
        "Leelawadee UI",
        "Lucida Console",
        "Lucida Sans Unicode",
        "Malgun Gothic",
        "Marlett",
        "Microsoft Himalaya",
        "Microsoft JhengHei",
        "Microsoft New Tai Lue",
        "Microsoft PhagsPa",
        "Microsoft Sans Serif",
        "Microsoft Tai Le",
        "Microsoft YaHei",
        "Microsoft Yi Baiti",
        "MingLiU-ExtB",
        "MS Gothic",
        "MS PGothic",
        "MS Sans Serif",
        "MV Boli",
        "Myanmar Text",
        "Nirmala UI",
        "Palatino Linotype",
        "Segoe MDL2 Assets",
        "Segoe Print",
        "Segoe Script",
        "Segoe UI",
        "Segoe UI Emoji",
        "Segoe UI Historic",
        "Segoe UI Symbol",
        "SimSun",
        "Sitka Banner",
        "Sitka Display",
        "Sitka Heading",
        "Sitka Small",
        "Sitka Subheading",
        "Sitka Text",
        "Sylfaen",
        "Symbol",
        "Tahoma",
        "Times New Roman",
        "Trebuchet MS",
        "Verdana",
        "Webdings",
        "Wingdings",
        "Yu Gothic",
    ],
    "mac": [
        "American Typewriter",
        "Andale Mono",
        "Arial",
        "Arial Black",
        "Arial Narrow",
        "Arial Rounded MT Bold",
        "Arial Unicode MS",
        "Avenir",
        "Avenir Next",
        "Avenir Next Condensed",
        "Baskerville",
        "Big Caslon",
        "Bodoni 72",
        "Bradley Hand",
        "Chalkboard",
        "Cochin",
        "Comic Sans MS",
        "Copperplate",
        "Courier",
        "Courier New",
        "Didot",
        "Futura",
        "Geneva",
        "Georgia",
        "Gill Sans",
        "Helvetica",
        "Helvetica Neue",
        "Herculanum",
        "Hoefler Text",
        "Iowan Old Style",
        "Kailasa",
        "Kefa",
        "Lucida Grande",
        "Luminari",
        "Marker Felt",
        "Menlo",
        "Monaco",
        "Noteworthy",
        "Optima",
        "Palatino",
        "Papyrus",
        "Phosphate",
        "Rockwell",
        "Savoye LET",
        "SignPainter",
        "Skia",
        "Snell Roundhand",
        "Tahoma",
        "Times",
        "Trattatello",
        "Trebuchet MS",
        "Verdana",
        "Zapfino",
    ],
    "linux": [
        "DejaVu Sans",
        "DejaVu Sans Mono",
        "DejaVu Serif",
        "Liberation Mono",
        "Liberation Sans",
        "Liberation Serif",
        "Ubuntu",
        "Ubuntu Condensed",
        "Ubuntu Mono",
        "Noto Sans",
        "Noto Serif",
        "Noto Mono",
        "Cantarell",
        "Droid Sans Fallback",
        "FreeMono",
        "FreeSans",
        "FreeSerif",
        "Nimbus Mono PS",
        "Nimbus Roman",
        "Nimbus Sans",
        "Nimbus Sans Narrow",
        "C059",
        "P052",
        "Z003",
        "Standard Symbols PS",
        "D050000L",
        "S050000L",
        "Ebrima",
    ],
}

# The families a real machine ALWAYS has (the core) and the optional tail.
# The core is an explicit list (not a prefix of the pool): the order of the
# pool is alphabetical, but the core must contain the families a real
# Windows/macOS/Linux box always ships.
FONT_CORE: dict[str, list[str]] = {
    "windows": [
        "Arial",
        "Arial Black",
        "Calibri",
        "Cambria",
        "Consolas",
        "Courier New",
        "Georgia",
        "Impact",
        "Segoe UI",
        "Tahoma",
        "Times New Roman",
        "Trebuchet MS",
        "Verdana",
        "Webdings",
        "Wingdings",
        "MS Gothic",
        "Microsoft YaHei",
        "SimSun",
        "Marlett",
        "Microsoft Sans Serif",
        "MS Mincho",
        "NSimSun",
    ],
    "mac": [
        "Arial",
        "Arial Black",
        "Arial Narrow",
        "Arial Rounded MT Bold",
        "Arial Unicode MS",
        "Avenir",
        "Avenir Next",
        "Courier",
        "Courier New",
        "Futura",
        "Geneva",
        "Georgia",
        "Helvetica",
        "Helvetica Neue",
        "Lucida Grande",
        "Marker Felt",
        "Menlo",
        "Monaco",
        "Optima",
        "Palatino",
        "Times",
        "Times New Roman",
        "Trebuchet MS",
        "Verdana",
    ],
    "linux": [
        "DejaVu Sans",
        "DejaVu Sans Mono",
        "DejaVu Serif",
        "Liberation Mono",
        "Liberation Sans",
        "Liberation Serif",
        "Noto Sans",
        "Noto Serif",
        "Noto Mono",
        "Ubuntu",
        "Ubuntu Condensed",
        "Ubuntu Mono",
        "FreeMono",
        "FreeSans",
        "FreeSerif",
    ],
}
FONT_TAIL_MIN = 6
FONT_TAIL_MAX = 24


def _pick_fonts(os_type: str) -> list[str]:
    """Pick a realistic per-profile font pool.

    The core families (always present on that OS) come first, then a random
    tail of optional ones — so the list is plausible for the platform, stable
    for the profile, and different between profiles.
    """
    pool = FONT_POOLS.get(os_type, FONT_POOLS["windows"])
    core = [f for f in FONT_CORE.get(os_type, FONT_CORE["windows"]) if f in pool]
    core_pool = [f for f in pool if f not in core]
    tail_size = min(len(core_pool), random.randint(FONT_TAIL_MIN, FONT_TAIL_MAX))
    tail = random.sample(core_pool, tail_size) if tail_size else []
    return core + tail


# Anti-detect (audit F-04): real machines carry wildly different audio/video
# peripherals, and enumerateDevices() exposes the kind+label set even without
# permission. A farm where every profile reports the SAME three labels is a
# one-line cluster signature. Pools model the actual market distribution.
MICROPHONE_LABELS = [
    "Microphone (High Definition Audio Device)",
    "Microphone (Realtek(R) Audio)",
    "Microphone (Intel Smart Sound Technology for Digital Microphones)",
    "Microphone Array (Intel Smart Sound Technology)",
    "Microphone (NVIDIA Virtual Audio Device Wave Extensible) (WDM)",
    "Mikrofon (2- USB Audio Device)",
    "Mikrofon (Realtek(R) Audio)",
    "Default - Microphone (Realtek High Definition Audio)",
]
SPEAKER_LABELS = [
    "Speakers (Realtek High Definition Audio)",
    "Lautsprecher (Realtek(R) Audio)",
    "Speakers (High Definition Audio Device)",
    "Headphones (Realtek High Definition Audio Audio)",
    "Digital Output (S/PDIF) (High Definition Audio Device)",
    "Headset Earphone (2- Hands-Free AG Audio)",
]
CAMERA_LABELS = [
    "HD WebCam Pro",
    "Integrated Webcam",
    "Integrated Camera",
    "USB2.0 HD UVC WebCam",
    "Logitech BRIO",
    "HD Camera",
    "Front Full HD Camera",
    "FaceTime HD Camera",
]
# Fraction of desktops with no camera at all (anti-detect audit F-04): a farm
# where every profile has exactly one webcam is itself unusual.
CAMERA_ABSENT_PROBABILITY = 0.08


def _pick_media_devices() -> list[MediaDeviceInfo]:
    """A plausible per-profile device set (kind+label hashed by detectors)."""
    devices: list[MediaDeviceInfo] = []
    devices.append(
        MediaDeviceInfo(
            kind="audioinput",
            label=random.choice(MICROPHONE_LABELS),
            device_id=uuid.uuid4().hex,
            group_id=uuid.uuid4().hex,
        )
    )
    devices.append(
        MediaDeviceInfo(
            kind="audiooutput",
            label=random.choice(SPEAKER_LABELS),
            device_id=uuid.uuid4().hex,
            group_id=uuid.uuid4().hex,
        )
    )
    if random.random() >= CAMERA_ABSENT_PROBABILITY:
        devices.append(
            MediaDeviceInfo(
                kind="videoinput",
                label=random.choice(CAMERA_LABELS),
                device_id=uuid.uuid4().hex,
                group_id=uuid.uuid4().hex,
            )
        )
    return devices


def _pick_battery() -> BatterySpoofConfig:
    """Battery state varies like a real laptop (audit F-19).

    A farm of 100 permanently-charged (charging=True, level~1.0) laptops is a
    statistical outlier: real devices discharge during use. Mix in discharged
    and mid-charge states with realistic times.
    """
    if random.random() < 0.55:
        # Plugged in, mostly full.
        return BatterySpoofConfig(charging=True, level=random.choice([0.95, 0.98, 1.0]), charging_time=0)
    if random.random() < 0.5:
        # On battery, mid-charge and draining.
        level = random.choice([0.23, 0.41, 0.52, 0.64, 0.77, 0.85])
        return BatterySpoofConfig(charging=False, level=level, charging_time=random.randint(30, 240))
    # Charging from a low state.
    return BatterySpoofConfig(
        charging=True, level=random.choice([0.15, 0.28, 0.36]), charging_time=random.randint(40, 160)
    )


def generate_random_fingerprint(
    os_type: str = "windows", target_timezone: str | None = None, language: str = "en-US,en;q=0.9"
) -> FingerprintConfig:
    """
    Generates a completely randomized, statistically coherent hardware and digital fingerprint.
    """
    if os_type in ("mac", "macos"):
        ua = random.choice(USER_AGENTS_MAC)
        platform = "MacIntel"
        avail_gpus = [g for g in GPU_PRESETS if "mac" in g["os"]]
    elif os_type == "linux":
        ua = random.choice(USER_AGENTS_LINUX)
        platform = "Linux x86_64"
        avail_gpus = [g for g in GPU_PRESETS if "linux" in g["os"]]
    else:
        ua = random.choice(USER_AGENTS_WINDOWS)
        platform = "Win32"
        avail_gpus = [g for g in GPU_PRESETS if "windows" in g["os"]]

    gpu = random.choice(avail_gpus)
    screen = random.choice(SCREEN_RESOLUTIONS)
    cores = random.choice(gpu["cores"])
    ram = random.choice(gpu["ram"])

    if target_timezone:
        tz_name = target_timezone
        tz_offset = calculate_tz_offset(target_timezone)
    else:
        # DST honesty: resolve the CURRENT offset for the picked zone, never the
        # static table value — otherwise the fingerprint carries winter offsets
        # in summer (e.g. Europe/Berlin -60 vs real -120) while the page's own
        # Date math and the injected getTimezoneOffset disagree with the zone.
        tz_name = random.choice(TIMEZONES)[0]
        tz_offset = calculate_tz_offset(tz_name)

    langs_list = [lang.strip().split(";")[0] for lang in language.split(",") if lang.strip()]

    # Extract chrome version (F-10: fallback tracks the pool's newest entry)
    c_ver = _CHROME_UA_VERSIONS[0]
    if "Chrome/" in ua:
        try:
            c_ver = ua.split("Chrome/")[1].split(".")[0]
        except Exception:
            pass

    # Anti-detect (audit F-09): the GREASE brand version is keyed to the
    # browser major version the way real Chrome does it (Not(A:Brand;v=99
    # belongs to the 1xx series; 12x+ ships v=8/24/99 depending on build).
    major = int(c_ver) if str(c_ver).isdigit() else 133
    grease_version = "99" if major < 120 else random.choice(["8", "24", "99"])
    grease_brand = random.choice(["Not(A:Brand", "Not A(Brand", "Not?A?Brand"])
    brands = [
        {"brand": grease_brand, "version": grease_version},
        {"brand": "Google Chrome", "version": c_ver},
        {"brand": "Chromium", "version": c_ver},
    ]

    media_devs = _pick_media_devices()
    battery = _pick_battery()
    fonts = _pick_fonts(os_type)

    return FingerprintConfig(
        user_agent=ua,
        platform=platform,
        app_version=f"5.0 ({platform}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{c_ver}.0.0.0 Safari/537.36",
        brands=brands,
        # Linux kernels report their version string via Client Hints, not "10.0.0"
        platform_version="15.0.0" if os_type in ("mac", "macos") else ("6.8.0" if os_type == "linux" else "10.0.0"),
        screen_width=int(screen["width"]),
        screen_height=int(screen["height"]),
        screen_avail_width=int(screen["avail_w"]),
        screen_avail_height=int(screen["avail_h"]),
        device_pixel_ratio=float(screen["dpr"]),
        color_depth=24,
        pixel_depth=24,
        device_memory=int(ram),
        hardware_concurrency=int(cores),
        language=language,
        languages=langs_list,
        timezone=tz_name,
        timezone_offset=tz_offset,
        webgl_vendor=str(gpu["vendor"]),
        webgl_renderer=str(gpu["renderer"]),
        webgl_unmasked_vendor=str(gpu["unmasked_vendor"]),
        webgl_unmasked_renderer=str(gpu["unmasked_renderer"]),
        media_devices=media_devs,
        fonts=fonts,
        canvas_noise=True,
        canvas_noise_seed=random.randint(10000, 999999),
        audio_noise=True,
        audio_noise_seed=random.uniform(0.0000005, 0.000005),
        client_rects_noise=True,
        battery=battery,
        geolocation=GeolocationSpoofConfig(enabled=True),
        webrtc_policy="disable_non_proxied_udp",
        block_port_scanning=True,
    )
