"""
Ultra-Realistic Hardware & Digital Fingerprint Generator.
Generates fully consistent hardware specifications (GPU, CPU, RAM, Screen, Client Hints, Media Devices, Audio/Canvas Seeds)
guaranteeing complete spoofing and isolation of the host PC characteristics.
"""

import random
import uuid

from ..models.profile import BatterySpoofConfig, FingerprintConfig, GeolocationSpoofConfig, MediaDeviceInfo

# Realistic GPU combinations
GPU_PRESETS = [
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
]

# Realistic Screen Resolutions with standard aspect ratios
SCREEN_RESOLUTIONS = [
    {"width": 1920, "height": 1080, "avail_w": 1920, "avail_h": 1040, "dpr": 1.0},
    {"width": 2560, "height": 1440, "avail_w": 2560, "avail_h": 1400, "dpr": 1.25},
    {"width": 3840, "height": 2160, "avail_w": 3840, "avail_h": 2120, "dpr": 2.0},
    {"width": 1536, "height": 864, "avail_w": 1536, "avail_h": 824, "dpr": 1.0},
    {"width": 1440, "height": 900, "avail_w": 1440, "avail_h": 860, "dpr": 1.0},
    {"width": 1680, "height": 1050, "avail_w": 1680, "avail_h": 1010, "dpr": 1.0},
    {"width": 1920, "height": 1200, "avail_w": 1920, "avail_h": 1160, "dpr": 1.0},
    {"width": 1366, "height": 768, "avail_w": 1366, "avail_h": 728, "dpr": 1.0},
]

USER_AGENTS_WINDOWS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
]

USER_AGENTS_LINUX = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
]

USER_AGENTS_MAC = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]

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
    """Calculates timezone offset in minutes according to JS Date.getTimezoneOffset()."""
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        now = datetime.now(ZoneInfo(tz_name))
        offset = now.utcoffset()
        offset_sec = offset.total_seconds() if offset is not None else 0
        # In JS: UTC-5 (New York) is +300, UTC+3 (Moscow) is -180
        return int(-offset_sec / 60)
    except Exception:
        matching_tz = [t for t in TIMEZONES if t[0] == tz_name]
        if matching_tz:
            return matching_tz[0][1]
        return 300


def generate_random_fingerprint(
    os_type: str = "windows", target_timezone: str | None = None, language: str = "en-US,en;q=0.9"
) -> FingerprintConfig:
    """
    Generates a completely randomized, statistically coherent hardware and digital fingerprint.
    """
    if os_type == "mac":
        ua = random.choice(USER_AGENTS_MAC)
        platform = "MacIntel"
        avail_gpus = [g for g in GPU_PRESETS if "mac" in g["os"]]
    elif os_type == "linux":
        ua = random.choice(USER_AGENTS_LINUX)
        platform = "Linux x86_64"
        avail_gpus = [g for g in GPU_PRESETS if "windows" in g["os"]]
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
        tz_name, tz_offset = random.choice(TIMEZONES)

    langs_list = [lang.strip().split(";")[0] for lang in language.split(",") if lang.strip()]

    # Extract chrome version
    c_ver = "133"
    if "Chrome/" in ua:
        try:
            c_ver = ua.split("Chrome/")[1].split(".")[0]
        except Exception:
            pass

    brands = [
        {"brand": "Not(A:Brand", "version": "99"},
        {"brand": "Google Chrome", "version": c_ver},
        {"brand": "Chromium", "version": c_ver},
    ]

    media_devs = [
        MediaDeviceInfo(
            kind="audioinput",
            label="Microphone (High Definition Audio Device)",
            device_id=uuid.uuid4().hex,
            group_id=uuid.uuid4().hex,
        ),
        MediaDeviceInfo(
            kind="audiooutput",
            label="Speakers (Realtek High Definition Audio)",
            device_id=uuid.uuid4().hex,
            group_id=uuid.uuid4().hex,
        ),
        MediaDeviceInfo(
            kind="videoinput", label="HD WebCam Pro", device_id=uuid.uuid4().hex, group_id=uuid.uuid4().hex
        ),
    ]

    battery = BatterySpoofConfig(charging=True, level=random.choice([0.95, 0.98, 1.0]), charging_time=0)

    return FingerprintConfig(
        user_agent=ua,
        platform=platform,
        app_version=f"5.0 ({platform}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{c_ver}.0.0.0 Safari/537.36",
        brands=brands,
        platform_version="15.0.0" if os_type == "mac" else "10.0.0",
        screen_width=screen["width"],
        screen_height=screen["height"],
        screen_avail_width=screen["avail_w"],
        screen_avail_height=screen["avail_h"],
        device_pixel_ratio=screen["dpr"],
        color_depth=24,
        pixel_depth=24,
        device_memory=ram,
        hardware_concurrency=cores,
        language=language,
        languages=langs_list,
        timezone=tz_name,
        timezone_offset=tz_offset,
        webgl_vendor=gpu["vendor"],
        webgl_renderer=gpu["renderer"],
        webgl_unmasked_vendor=gpu["unmasked_vendor"],
        webgl_unmasked_renderer=gpu["unmasked_renderer"],
        media_devices=media_devs,
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
