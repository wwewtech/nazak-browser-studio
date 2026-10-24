import random
from pathlib import Path

import pytest

from nazak.core.extension_generator import generate_profile_extension
from nazak.core.fingerprint_generator import (
    GPU_PRESETS,
    SCREEN_RESOLUTIONS,
    calculate_tz_offset,
    generate_random_fingerprint,
)
from nazak.core.profile_manager import ProfileManager
from nazak.models import BrowserProfile, FingerprintConfig, ProxyConfig, ProxyType


def test_fingerprint_windows_consistency():
    fp = generate_random_fingerprint("windows")
    assert fp.platform == "Win32"
    assert "Windows NT 10.0" in fp.user_agent
    assert fp.hardware_concurrency in (6, 8, 12, 14, 16, 24, 32)
    assert fp.device_memory in (16, 32, 64)
    assert fp.platform_version == "10.0.0"


def test_fingerprint_mac_consistency():
    fp = generate_random_fingerprint("mac")
    assert fp.platform == "MacIntel"
    assert "Macintosh" in fp.user_agent
    assert fp.platform_version == "15.0.0"
    assert "Apple" in fp.webgl_unmasked_vendor or "Apple" in fp.webgl_vendor


def test_fingerprint_linux_consistency():
    fp = generate_random_fingerprint("linux")
    assert fp.platform == "Linux x86_64"
    assert "Linux x86_64" in fp.user_agent


def test_calculate_tz_offset():
    # Standard time offset checks
    assert isinstance(calculate_tz_offset("America/New_York"), int)
    assert isinstance(calculate_tz_offset("Europe/London"), int)
    assert isinstance(calculate_tz_offset("Asia/Tokyo"), int)
    assert isinstance(calculate_tz_offset("Europe/Berlin"), int)


def test_fingerprint_timezone_offset_is_dst_honest():
    """Zone and getTimezoneOffset() value must agree at generation time.

    Regression: the random path used to copy the STATIC table offset, so half
    the year a fingerprint carried e.g. Europe/Berlin with -60 while the real
    current offset (and the injected getter) is -120 — a one-line consistency
    check catches it.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo

    for _ in range(30):
        fp = generate_random_fingerprint(random.choice(["windows", "mac", "linux"]))
        now = datetime.now(ZoneInfo(fp.timezone))
        expected = int(-(now.utcoffset().total_seconds() if now.utcoffset() is not None else 0) / 60)
        assert fp.timezone_offset == expected, f"{fp.timezone}: stored {fp.timezone_offset}, real {expected}"


def test_fingerprint_explicit_timezone_resolves_current_offset():
    fp = generate_random_fingerprint("windows", target_timezone="Europe/Berlin")
    assert fp.timezone == "Europe/Berlin"
    assert fp.timezone_offset == calculate_tz_offset("Europe/Berlin")


def test_clone_profile_generates_distinct_seeds_and_uuids(tmp_path):
    pm = ProfileManager(tmp_path / "profiles.json", tmp_path / "data")
    prof1 = pm.get_profile("prof_01")
    cloned = pm.clone_profile("prof_01", "Cloned Profile 01")

    assert cloned is not None
    assert cloned.id != prof1.id
    # Canvas seed must be distinct
    assert cloned.fingerprint.canvas_noise_seed != prof1.fingerprint.canvas_noise_seed
    # Audio seed must be distinct
    assert cloned.fingerprint.audio_noise_seed != prof1.fingerprint.audio_noise_seed
    # Media devices UUIDs must be distinct
    c_devs = [d.device_id for d in cloned.fingerprint.media_devices]
    p_devs = [d.device_id for d in prof1.fingerprint.media_devices]
    assert set(c_devs).isdisjoint(set(p_devs))


def test_all_10_profiles_have_distinct_canvas_and_audio_seeds(tmp_path):
    pm = ProfileManager(tmp_path / "profiles.json", tmp_path / "data")
    profs = pm.list_profiles()
    canvas_seeds = [p.fingerprint.canvas_noise_seed for p in profs]
    audio_seeds = [p.fingerprint.audio_noise_seed for p in profs]
    assert len(canvas_seeds) == len(set(canvas_seeds))
    assert len(audio_seeds) == len(set(audio_seeds))


def test_extension_generator_stealth_script_content(tmp_path):
    pm = ProfileManager(tmp_path / "profiles.json", tmp_path / "data")
    prof = pm.get_profile("prof_01")
    ext_path = generate_profile_extension(prof, tmp_path / "exts")
    assert ext_path is not None
    stealth_file = Path(ext_path) / "stealth.js"
    assert stealth_file.exists()
    content = stealth_file.read_text(encoding="utf-8")

    # Check all key stealth hooks
    # Hunt A-13: the navigator-level hooks go through the dual-prototype
    # helper (Navigator + WorkerNavigator), so the worker scope is covered too.
    assert "__defineNav('webdriver'" in content
    assert "__defineNav('hardwareConcurrency'" in content
    assert "__defineNav('deviceMemory'" in content
    # Stealth core (round 12): the screen/canvas/audio/geometry hooks are
    # Proxies over the NATIVE functions (getter/method), not replacements.
    assert "__replaceGetterWithProxy(Screen.prototype, 'width'" in content
    assert "__replaceGetterWithProxy(Screen.prototype, 'height'" in content
    assert "WebGLRenderingContext.prototype" in content
    assert "navigator.mediaDevices.enumerateDevices" in content
    assert "navigator.getBattery" in content
    assert "'getCurrentPosition'" in content
    assert "__replaceWithProxy(CanvasRenderingContext2D.prototype, 'getImageData'" in content
    assert "__replaceWithProxy(AudioBuffer.prototype, 'getChannelData'" in content
    assert "__replaceWithProxy(Element.prototype, 'getBoundingClientRect'" in content
    assert "127.0.0.1" in content
    # Hunt A-14: the instance-level overrides moved to their prototypes, so
    # the media devices / battery / geolocation hooks are now installed on
    # MediaDevices.prototype / Navigator.prototype / Geolocation.prototype.
    assert "MediaDevices.prototype" in content
    assert "'getBattery'" in content
    assert "Geolocation.prototype" in content


def test_extension_generator_auth_background_script(tmp_path):
    pm = ProfileManager(tmp_path / "profiles.json", tmp_path / "data")
    prof = pm.get_profile("prof_01")
    prof.proxy = ProxyConfig(type=ProxyType.HTTP, host="1.1.1.1", port=8080, username="u1", password="p1")
    ext_path = generate_profile_extension(prof, tmp_path / "exts")

    bg_file = Path(ext_path) / "background.js"
    assert bg_file.exists()
    bg_content = bg_file.read_text(encoding="utf-8")
    assert "chrome.webRequest.onAuthRequired" in bg_content
    assert "u1" in bg_content
    assert "p1" in bg_content


def test_client_hints_brands_generation():
    fp = generate_random_fingerprint("windows")
    assert len(fp.brands) >= 3
    brand_names = [b["brand"] for b in fp.brands]
    assert "Google Chrome" in brand_names
    assert "Chromium" in brand_names


def test_screen_resolution_aspect_ratios():
    for scr in SCREEN_RESOLUTIONS:
        assert scr["width"] > scr["height"]
        assert scr["avail_w"] <= scr["width"]
        assert scr["avail_h"] < scr["height"]
        assert scr["dpr"] in (1.0, 1.25, 2.0)


def test_gpu_presets_all_have_required_keys():
    for g in GPU_PRESETS:
        assert "vendor" in g
        assert "renderer" in g
        assert "unmasked_vendor" in g
        assert "unmasked_renderer" in g
        assert len(g["cores"]) > 0
        assert len(g["ram"]) > 0


def test_media_devices_types():
    # F-04: mic+speakers always; a webcam may be absent (like real desktops
    # without one) — a mandatory camera on every profile was a farm tell.
    fp = generate_random_fingerprint("windows")
    kinds = [d.kind for d in fp.media_devices]
    assert "audioinput" in kinds
    assert "audiooutput" in kinds
    assert set(kinds) <= {"audioinput", "audiooutput", "videoinput"}
    # Across a sample, most profiles DO carry a camera (the pool only drops
    # it ~8% of the time).
    with_cam = sum(
        1 for _ in range(60) if "videoinput" in [d.kind for d in generate_random_fingerprint("windows").media_devices]
    )
    assert with_cam >= 40, f"only {with_cam}/60 profiles have a camera"


def test_battery_spoof_config_defaults():
    # F-19: battery states vary like real laptops (plugged in, draining,
    # mid-charge) — a farm of always-charging/always-full batteries is a
    # statistical outlier. Sanity: a plausible level, never 0 or >1.
    fp = generate_random_fingerprint("windows")
    assert 0.0 < fp.battery.level <= 1.0
    if fp.battery.charging:
        assert fp.battery.level > 0.05
    else:
        assert fp.battery.charging_time >= 0
    # Across a sample the states must actually vary (the old behaviour was
    # charging=True + level in {0.95, 0.98, 1.0} for every profile).
    states = set()
    for _ in range(40):
        b = generate_random_fingerprint("windows").battery
        states.add((b.charging, round(b.level, 2)))
    assert len(states) > 5, f"battery states did not vary: {sorted(states)[:10]}"


def test_webrtc_policy_is_set():
    fp = generate_random_fingerprint("windows")
    assert fp.webrtc_policy == "disable_non_proxied_udp"


def test_geolocation_config_enabled():
    fp = generate_random_fingerprint("windows")
    assert fp.geolocation.enabled is True


def test_custom_timezone_and_language():
    fp = generate_random_fingerprint("windows", target_timezone="Europe/Paris", language="fr-FR,fr;q=0.9")
    assert fp.timezone == "Europe/Paris"
    assert fp.language == "fr-FR,fr;q=0.9"
    assert "fr-FR" in fp.languages


def test_port_scanning_protection_flag():
    fp = generate_random_fingerprint("windows")
    assert fp.block_port_scanning is True


def test_color_depth_standard_24():
    fp = generate_random_fingerprint("windows")
    assert fp.color_depth == 24
    assert fp.pixel_depth == 24


def test_max_touch_points_zero_for_desktop():
    fp = generate_random_fingerprint("windows")
    assert fp.max_touch_points == 0


def test_mac_gpu_metal_renderer_naming():
    fp = generate_random_fingerprint("mac")
    assert "Apple" in fp.webgl_renderer or "Metal" in fp.webgl_renderer or "Apple" in fp.webgl_unmasked_renderer
