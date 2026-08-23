"""
Suite 2: Browser, CDP, Hardware Shield & Extension Generator Resilience Tests (26 Tests).
"""
import pytest
import json
import tempfile
from pathlib import Path

from nazak.models.profile import (
    BrowserProfile, ProfileStatus, GoogleSettings, FingerprintConfig,
    MediaDeviceInfo, BatterySpoofConfig, GeolocationSpoofConfig
)
from nazak.models.proxy import ProxyConfig, ProxyType
from nazak.core.browser_launcher import BrowserLauncher, find_chrome_executable
from nazak.core.extension_generator import generate_profile_extension


@pytest.fixture
def test_profile():
    devs = [
        MediaDeviceInfo(kind="audioinput", label="Mic HD", device_id="mic123", group_id="grp123"),
        MediaDeviceInfo(kind="videoinput", label="Cam HD", device_id="cam123", group_id="grp123")
    ]
    fp = FingerprintConfig(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/133.0.0.0 Safari/537.36",
        platform="Win32",
        screen_width=1920,
        screen_height=1080,
        screen_avail_width=1920,
        screen_avail_height=1040,
        color_depth=24,
        pixel_depth=24,
        device_pixel_ratio=1.0,
        device_memory=32,
        hardware_concurrency=16,
        language="ru-RU,ru;q=0.9,en-US;q=0.8",
        languages=["ru-RU", "ru", "en-US", "en"],
        timezone="Europe/Moscow",
        timezone_offset=-180,
        webgl_vendor="Google Inc. (NVIDIA)",
        webgl_renderer="ANGLE (NVIDIA, NVIDIA GeForce RTX 3080 Direct3D11 vs_5_0 ps_5_0, D3D11)",
        webgl_unmasked_vendor="NVIDIA Corporation",
        webgl_unmasked_renderer="NVIDIA GeForce RTX 3080",
        media_devices=devs,
        canvas_noise=True,
        canvas_noise_seed=884422,
        audio_noise=True,
        audio_noise_seed=0.0000015,
        client_rects_noise=True,
        battery=BatterySpoofConfig(charging=True, level=0.95),
        geolocation=GeolocationSpoofConfig(enabled=True, latitude=55.7558, longitude=37.6173),
        webrtc_policy="disable_non_proxied_udp",
        block_port_scanning=True
    )
    return BrowserProfile(
        id="prof_test_cdp_01",
        name="Test CDP Profile",
        group="QA",
        proxy=ProxyConfig(type=ProxyType.DIRECT, raw="direct"),
        fingerprint=fp,
        google=GoogleSettings(auto_open_page="youtube_studio"),
        status=ProfileStatus.STOPPED
    )


# -------------------------------------------------------------
# 1. Chrome Command-Line Arguments Construction (8 Tests)
# -------------------------------------------------------------

def test_chrome_args_builder_minimal_profile(test_profile):
    """Minimal direct profile args contain essential anti-detection flags."""
    with tempfile.TemporaryDirectory() as td:
        bl = BrowserLauncher(Path(td)/"profiles", Path(td)/"extensions")
        args, ext_path = bl.build_chrome_args(test_profile, "chrome.exe")
        assert "chrome.exe" in args
        assert any(a.startswith("--user-data-dir=") for a in args)
        assert "--profile-directory=Default" in args
        assert "--disable-blink-features=AutomationControlled" in args


def test_chrome_args_builder_socks5_authenticated_proxy(test_profile):
    """SOCKS5 auth proxy generates extension and proxy argument."""
    test_profile.proxy = ProxyConfig(
        type=ProxyType.SOCKS5,
        host="127.0.0.1",
        port=1080,
        username="proxy_user",
        password="proxy_pass"
    )
    with tempfile.TemporaryDirectory() as td:
        bl = BrowserLauncher(Path(td)/"profiles", Path(td)/"extensions")
        args, ext_path = bl.build_chrome_args(test_profile, "chrome.exe")
        assert "--proxy-server=socks5://127.0.0.1:1080" in args
        assert ext_path is not None
        assert any(a.startswith("--load-extension=") for a in args)


def test_chrome_args_builder_http_proxy_flag(test_profile):
    """HTTP proxy without auth sets --proxy-server=http://host:port."""
    test_profile.proxy = ProxyConfig(type=ProxyType.HTTP, host="10.0.0.1", port=8080)
    with tempfile.TemporaryDirectory() as td:
        bl = BrowserLauncher(Path(td)/"profiles", Path(td)/"extensions")
        args, ext_path = bl.build_chrome_args(test_profile, "chrome.exe")
        assert "--proxy-server=http://10.0.0.1:8080" in args


def test_chrome_args_builder_custom_screen_and_window_size(test_profile):
    """Window size matches profile resolution exactly."""
    test_profile.fingerprint.screen_width = 2560
    test_profile.fingerprint.screen_height = 1440
    with tempfile.TemporaryDirectory() as td:
        bl = BrowserLauncher(Path(td)/"profiles", Path(td)/"extensions")
        args, _ = bl.build_chrome_args(test_profile, "chrome.exe")
        assert "--window-size=2560,1440" in args


def test_chrome_args_builder_webrtc_policies(test_profile):
    """All WebRTC policies are serialized accurately to force-webrtc-ip-handling-policy."""
    policies = [
        "disable_non_proxied_udp",
        "default_public_interface_only",
        "default_public_and_private_interfaces"
    ]
    with tempfile.TemporaryDirectory() as td:
        bl = BrowserLauncher(Path(td)/"profiles", Path(td)/"extensions")
        for pol in policies:
            test_profile.fingerprint.webrtc_policy = pol
            args, _ = bl.build_chrome_args(test_profile, "chrome.exe")
            assert f"--force-webrtc-ip-handling-policy={pol}" in args


def test_chrome_args_builder_user_agent_injection(test_profile):
    """User-Agent argument matches the configured UA."""
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130.0.0.0"
    test_profile.fingerprint.user_agent = ua
    with tempfile.TemporaryDirectory() as td:
        bl = BrowserLauncher(Path(td)/"profiles", Path(td)/"extensions")
        args, _ = bl.build_chrome_args(test_profile, "chrome.exe")
        assert f"--user-agent={ua}" in args


def test_chrome_args_builder_language_flag(test_profile):
    """Primary language is extracted from composite language string."""
    test_profile.fingerprint.language = "de-DE,de;q=0.9,en;q=0.8"
    with tempfile.TemporaryDirectory() as td:
        bl = BrowserLauncher(Path(td)/"profiles", Path(td)/"extensions")
        args, _ = bl.build_chrome_args(test_profile, "chrome.exe")
        assert "--lang=de-DE" in args


def test_chrome_args_builder_empty_language_fallback(test_profile):
    """Empty language falls back safely to en-US."""
    test_profile.fingerprint.language = ""
    with tempfile.TemporaryDirectory() as td:
        bl = BrowserLauncher(Path(td)/"profiles", Path(td)/"extensions")
        args, _ = bl.build_chrome_args(test_profile, "chrome.exe")
        assert "--lang=en-US" in args


# -------------------------------------------------------------
# 2. Extension Generator & Stealth JS Injection (10 Tests)
# -------------------------------------------------------------

def test_extension_generator_valid_manifest_json(test_profile):
    """Extension manifest is valid JSON with Manifest V2 schema."""
    with tempfile.TemporaryDirectory() as td:
        ext_dir = Path(td)
        ext_path = generate_profile_extension(test_profile, ext_dir)
        manifest_file = Path(ext_path) / "manifest.json"
        assert manifest_file.exists()
        data = json.loads(manifest_file.read_text(encoding="utf-8"))
        assert data["manifest_version"] == 2
        assert "permissions" in data
        assert "content_scripts" in data


def test_extension_generator_stealth_js_created(test_profile):
    """stealth.js is created and populated with JavaScript hooks."""
    with tempfile.TemporaryDirectory() as td:
        ext_path = generate_profile_extension(test_profile, Path(td))
        stealth_file = Path(ext_path) / "stealth.js"
        assert stealth_file.exists()
        code = stealth_file.read_text(encoding="utf-8")
        assert "Navigator.prototype" in code
        assert "WebGLRenderingContext" in code


def test_extension_generator_webgl_vendor_renderer_injection(test_profile):
    """WebGL vendor and renderer are injected accurately into stealth.js."""
    with tempfile.TemporaryDirectory() as td:
        ext_path = generate_profile_extension(test_profile, Path(td))
        code = (Path(ext_path) / "stealth.js").read_text(encoding="utf-8")
        assert "RTX 3080" in code
        assert "Google Inc. (NVIDIA)" in code


def test_extension_generator_canvas_seed_injection(test_profile):
    """Canvas noise seed is injected into getImageData hook."""
    test_profile.fingerprint.canvas_noise_seed = 991122
    with tempfile.TemporaryDirectory() as td:
        ext_path = generate_profile_extension(test_profile, Path(td))
        code = (Path(ext_path) / "stealth.js").read_text(encoding="utf-8")
        assert "991122" in code


def test_extension_generator_audio_seed_injection(test_profile):
    """Audio noise seed is injected into AudioBuffer hook."""
    test_profile.fingerprint.audio_noise_seed = 0.0000033
    with tempfile.TemporaryDirectory() as td:
        ext_path = generate_profile_extension(test_profile, Path(td))
        code = (Path(ext_path) / "stealth.js").read_text(encoding="utf-8")
        assert "0.0000033" in code or "3.3e-06" in code


def test_extension_generator_client_rects_noise(test_profile):
    """ClientRects noise injection hook is generated."""
    with tempfile.TemporaryDirectory() as td:
        ext_path = generate_profile_extension(test_profile, Path(td))
        code = (Path(ext_path) / "stealth.js").read_text(encoding="utf-8")
        assert "getClientRects" in code or "getBoundingClientRect" in code


def test_extension_generator_battery_spoof_injection(test_profile):
    """Battery getBattery spoof returns configured level."""
    test_profile.fingerprint.battery = BatterySpoofConfig(charging=True, level=0.88)
    with tempfile.TemporaryDirectory() as td:
        ext_path = generate_profile_extension(test_profile, Path(td))
        code = (Path(ext_path) / "stealth.js").read_text(encoding="utf-8")
        assert "0.88" in code


def test_extension_generator_geolocation_spoof_injection(test_profile):
    """Geolocation coordinates are injected into navigator.geolocation.getCurrentPosition."""
    test_profile.fingerprint.geolocation = GeolocationSpoofConfig(enabled=True, latitude=40.7128, longitude=-74.0060)
    with tempfile.TemporaryDirectory() as td:
        ext_path = generate_profile_extension(test_profile, Path(td))
        code = (Path(ext_path) / "stealth.js").read_text(encoding="utf-8")
        assert "40.7128" in code
        assert "-74.006" in code


def test_extension_generator_media_devices_injection(test_profile):
    """Mock media devices are enumerated in navigator.mediaDevices.enumerateDevices."""
    with tempfile.TemporaryDirectory() as td:
        ext_path = generate_profile_extension(test_profile, Path(td))
        code = (Path(ext_path) / "stealth.js").read_text(encoding="utf-8")
        assert "mic123" in code
        assert "cam123" in code


def test_extension_generator_proxy_auth_background_js(test_profile):
    """Authenticated proxy generates background.js with onAuthRequired handler."""
    test_profile.proxy = ProxyConfig(type=ProxyType.HTTP, host="1.2.3.4", port=8080, username="u1", password="p1")
    with tempfile.TemporaryDirectory() as td:
        ext_path = generate_profile_extension(test_profile, Path(td))
        bg_file = Path(ext_path) / "background.js"
        assert bg_file.exists()
        code = bg_file.read_text(encoding="utf-8")
        assert "onAuthRequired" in code
        assert '"u1"' in code
        assert '"p1"' in code


# -------------------------------------------------------------
# 3. Browser Process & Launcher Operations (8 Tests)
# -------------------------------------------------------------

def test_browser_launcher_is_running_nonexistent_profile():
    """Non-existent or stopped profile returns False for is_profile_running."""
    with tempfile.TemporaryDirectory() as td:
        bl = BrowserLauncher(Path(td), Path(td))
        assert bl.is_profile_running("non_existent_id") is False


def test_browser_launcher_stop_non_running_profile_idempotent():
    """Stopping a non-running profile is safe and idempotent."""
    with tempfile.TemporaryDirectory() as td:
        bl = BrowserLauncher(Path(td), Path(td))
        ok, msg = bl.stop("never_started_id")
        assert ok is True


def test_browser_launcher_find_chrome_executable():
    """Finds Chrome or Chromium executable on Windows."""
    exe = find_chrome_executable()
    # If Chrome is installed on test machine, should be a valid string path
    if exe is not None:
        assert Path(exe).exists()


def test_browser_launcher_cdp_port_argument_injection(test_profile):
    """CDP port parameter is appended to arguments when provided."""
    with tempfile.TemporaryDirectory() as td:
        bl = BrowserLauncher(Path(td), Path(td))
        args, _ = bl.build_chrome_args(test_profile, "chrome.exe", cdp_port=9333)
        assert "--remote-debugging-port=9333" in args


def test_browser_launcher_custom_url_navigation_override(test_profile):
    """Passing custom_url overrides profile auto_open_page target."""
    with tempfile.TemporaryDirectory() as td:
        bl = BrowserLauncher(Path(td), Path(td))
        args, _ = bl.build_chrome_args(test_profile, "chrome.exe", custom_url="https://duckduckgo.com")
        assert "https://duckduckgo.com" in args
        assert "studio.youtube.com" not in args


def test_browser_launcher_google_preset_urls(test_profile):
    """Presets like youtube_studio, google_ads, and google_login resolve to correct targets."""
    with tempfile.TemporaryDirectory() as td:
        bl = BrowserLauncher(Path(td), Path(td))
        
        test_profile.google.auto_open_page = "youtube_studio"
        args1, _ = bl.build_chrome_args(test_profile, "chrome.exe")
        assert any("studio.youtube.com" in a for a in args1)
        
        test_profile.google.auto_open_page = "google_ads"
        args2, _ = bl.build_chrome_args(test_profile, "chrome.exe")
        assert any("ads.google.com" in a for a in args2)
        
        test_profile.google.auto_open_page = "google_login"
        args3, _ = bl.build_chrome_args(test_profile, "chrome.exe")
        assert any("accounts.google.com" in a for a in args3)


def test_browser_launcher_custom_url_in_profile(test_profile):
    """Custom URL configured in profile is targeted when auto_open_page is custom."""
    test_profile.google.auto_open_page = "custom"
    test_profile.google.custom_url = "https://browserleaks.com/canvas"
    with tempfile.TemporaryDirectory() as td:
        bl = BrowserLauncher(Path(td), Path(td))
        args, _ = bl.build_chrome_args(test_profile, "chrome.exe")
        assert "https://browserleaks.com/canvas" in args


def test_browser_launcher_active_process_cleanup_on_stop():
    """Stopping a profile clears it from active_processes dict."""
    with tempfile.TemporaryDirectory() as td:
        bl = BrowserLauncher(Path(td), Path(td))
        bl.active_processes["p1"] = None
        bl.profile_pids["p1"] = 9999999
        bl.stop("p1")
        assert "p1" not in bl.active_processes
        assert "p1" not in bl.profile_pids
