import pytest
from pathlib import Path
from nazak.core.profile_manager import ProfileManager
from nazak.core.browser_launcher import BrowserLauncher
from nazak.core.extension_generator import generate_profile_extension
from nazak.models.profile import BrowserProfile, FingerprintConfig, MediaDeviceInfo, BatterySpoofConfig, GeolocationSpoofConfig

def test_default_10_profiles_distinct_hardware(tmp_path):
    pfile = tmp_path / "profiles.json"
    pdir = tmp_path / "profiles"
    pm = ProfileManager(pfile, pdir)
    profiles = pm.list_profiles()
    assert len(profiles) == 10
    
    # Verify all 10 profiles have unique names, screen resolutions, and GPUs
    names = set(p.name for p in profiles)
    assert len(names) == 10
    
    gpus = set(p.fingerprint.webgl_unmasked_renderer for p in profiles)
    assert len(gpus) >= 8  # At least 8 distinct GPU architectures
    
    cores = set(p.fingerprint.hardware_concurrency for p in profiles)
    assert len(cores) >= 4  # Diverse core counts (8, 12, 16, 24, 32)
    
    rams = set(p.fingerprint.device_memory for p in profiles)
    assert len(rams) >= 4   # Diverse RAM (8, 16, 32, 64)

def test_extension_stealth_contains_all_hardware_shielding(tmp_path):
    ext_dir = tmp_path / "ext"
    profile = BrowserProfile(
        name="Test Isolation",
        fingerprint=FingerprintConfig(
            hardware_concurrency=16,
            device_memory=32,
            platform="Win32",
            webgl_vendor="Google Inc. (NVIDIA)",
            webgl_renderer="ANGLE (NVIDIA, NVIDIA GeForce RTX 4090 Direct3D11 vs_5_0 ps_5_0, D3D11)",
            screen_width=2560,
            screen_height=1440,
            canvas_noise=True,
            audio_noise=True,
            client_rects_noise=True,
            block_port_scanning=True
        )
    )
    
    generated_path = generate_profile_extension(profile, ext_dir)
    assert generated_path is not None
    
    stealth_file = Path(generated_path) / "stealth.js"
    assert stealth_file.exists()
    content = stealth_file.read_text(encoding="utf-8")
    
    # 1. WebDriver removal
    assert "navigator.webdriver" in content or "Navigator.prototype, 'webdriver'" in content
    # 2. Hardware isolation
    assert "hardwareConcurrency" in content
    assert "deviceMemory" in content
    # 3. Client Hints / userAgentData
    assert "userAgentData" in content
    assert "getHighEntropyValues" in content
    # 4. Screen metrics
    assert "Screen.prototype, 'width'" in content
    assert "Screen.prototype, 'height'" in content
    # 5. WebGL GPU spoofing
    assert "UNMASKED_RENDERER_WEBGL" in content
    assert "NVIDIA GeForce RTX 4090" in content
    # 6. Media devices spoofing
    assert "mediaDevices.enumerateDevices" in content
    # 7. Battery API
    assert "navigator.getBattery" in content
    # 8. Geolocation
    assert "navigator.geolocation" in content
    # 9. Noise
    assert "getImageData" in content
    assert "getChannelData" in content
    assert "getBoundingClientRect" in content
    # 10. Port scanning
    assert "127.0.0.1" in content

def test_browser_launcher_strict_isolation_flags(tmp_path):
    pdir = tmp_path / "profiles"
    ext_dir = tmp_path / "ext"
    launcher = BrowserLauncher(profiles_dir=pdir, extensions_dir=ext_dir)
    
    profile = BrowserProfile(
        name="Flag Test",
        fingerprint=FingerprintConfig(
            screen_width=1920,
            screen_height=1080,
            webrtc_policy="disable_non_proxied_udp"
        )
    )
    
    args, ext = launcher.build_chrome_args(profile, "C:\\mock\\chrome.exe")
    args_str = " ".join(args)
    
    # Check key isolation flags
    assert "--user-data-dir=" in args_str
    assert "--disable-blink-features=AutomationControlled" in args_str
    assert "--force-webrtc-ip-handling-policy=disable_non_proxied_udp" in args_str
    assert "--window-size=1920,1080" in args_str
    assert "--no-first-run" in args_str
    assert "--no-default-browser-check" in args_str
    assert "--disable-sync" in args_str
    assert "--metrics-recording-only" in args_str
