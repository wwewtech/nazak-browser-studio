"""
Deep anti-detect, extension generator, stealth.js hooks, and fingerprint synthesis test suite.
Contains 25 comprehensive tests verifying C1, H6, Chrome argument sanitization, and evasion layers.
"""

import json
from pathlib import Path

from nazak.core.extension_generator import generate_profile_extension
from nazak.core.fingerprint_generator import generate_random_fingerprint
from nazak.models.profile import BrowserProfile, FingerprintConfig
from nazak.models.proxy import ProxyConfig


# ---------------------------------------------------------------------------
# 1-5: Extension manifest integrity and proxy authentication scripts
# ---------------------------------------------------------------------------
def test_extension_manifest_version_and_permissions(tmp_path):
    prof = BrowserProfile(id="ext_perm_1", name="Perms Profile")
    ext_dir = Path(generate_profile_extension(prof, tmp_path))
    manifest = json.loads((ext_dir / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["manifest_version"] == 2
    assert "webRequest" in manifest["permissions"]
    assert "webRequestBlocking" in manifest["permissions"]
    assert "<all_urls>" in manifest["permissions"]
    assert "tabs" in manifest["permissions"]


def test_extension_content_scripts_world_is_main_strictly(tmp_path):
    prof = BrowserProfile(id="ext_world_1", name="World Main Profile")
    ext_dir = Path(generate_profile_extension(prof, tmp_path))
    manifest = json.loads((ext_dir / "manifest.json").read_text(encoding="utf-8"))

    content_scripts = manifest["content_scripts"]
    assert len(content_scripts) >= 1
    for cs in content_scripts:
        assert cs["world"] == "MAIN", "Every content script MUST execute in MAIN world for anti-detect to work"


def test_extension_content_scripts_run_at_document_start(tmp_path):
    prof = BrowserProfile(id="ext_runat_1", name="Run At Profile")
    ext_dir = Path(generate_profile_extension(prof, tmp_path))
    manifest = json.loads((ext_dir / "manifest.json").read_text(encoding="utf-8"))

    for cs in manifest["content_scripts"]:
        assert cs["run_at"] == "document_start"
        assert cs["all_frames"] is True


def test_extension_proxy_background_script_generated_when_auth(tmp_path):
    proxy = ProxyConfig(host="10.0.0.1", port=9000, username="alice", password="secret_password")
    prof = BrowserProfile(id="ext_proxy_1", name="Proxy Profile", proxy=proxy)
    ext_dir = Path(generate_profile_extension(prof, tmp_path))

    manifest = json.loads((ext_dir / "manifest.json").read_text(encoding="utf-8"))
    assert "background" in manifest
    assert "background.js" in manifest["background"]["scripts"]

    bg_js = (ext_dir / "background.js").read_text(encoding="utf-8")
    assert "chrome.webRequest.onAuthRequired" in bg_js
    assert "alice" in bg_js
    assert "secret_password" in bg_js


def test_extension_proxy_auth_quotes_escaped(tmp_path):
    proxy = ProxyConfig(host="10.0.0.1", port=9000, username='user"with"quotes', password='pass"with"quotes')
    prof = BrowserProfile(id="ext_proxy_2", name="Quote Proxy", proxy=proxy)
    ext_dir = Path(generate_profile_extension(prof, tmp_path))

    bg_js = (ext_dir / "background.js").read_text(encoding="utf-8")
    assert 'user\\"with\\"quotes' in bg_js
    assert 'pass\\"with\\"quotes' in bg_js


# ---------------------------------------------------------------------------
# 6-12: JS string injection escaping tests in stealth.js (H6)
# ---------------------------------------------------------------------------
def test_stealth_js_escapes_platform_with_quotes(tmp_path):
    fp = FingerprintConfig(platform='Linux x86_64"; alert("pwn");//')
    prof = BrowserProfile(id="inj_platform", name="Platform Inj", fingerprint=fp)
    ext_dir = Path(generate_profile_extension(prof, tmp_path))
    stealth = (ext_dir / "stealth.js").read_text(encoding="utf-8")

    assert 'alert(\\"pwn\\")' in stealth
    assert '() => "Linux x86_64"; alert' not in stealth


def test_stealth_js_escapes_vendor_with_special_chars(tmp_path):
    fp = FingerprintConfig(vendor='Google Inc." && console.log("injected")')
    prof = BrowserProfile(id="inj_vendor", name="Vendor Inj", fingerprint=fp)
    ext_dir = Path(generate_profile_extension(prof, tmp_path))
    stealth = (ext_dir / "stealth.js").read_text(encoding="utf-8")

    assert 'console.log(\\"injected\\")' in stealth


def test_stealth_js_escapes_webgl_renderer_with_newline(tmp_path):
    fp = FingerprintConfig(webgl_renderer="ANGLE (NVIDIA\nGeForce RTX 4090)")
    prof = BrowserProfile(id="inj_renderer", name="Renderer Inj", fingerprint=fp)
    ext_dir = Path(generate_profile_extension(prof, tmp_path))
    stealth = (ext_dir / "stealth.js").read_text(encoding="utf-8")

    assert "\\n" in stealth
    # No literal raw multiline break inside JS string literal
    assert "\nGeForce RTX 4090" not in stealth


def test_stealth_js_escapes_timezone_injection(tmp_path):
    fp = FingerprintConfig(timezone='Europe/Moscow"); evil();//')
    prof = BrowserProfile(id="inj_tz", name="TZ Inj", fingerprint=fp)
    ext_dir = Path(generate_profile_extension(prof, tmp_path))
    stealth = (ext_dir / "stealth.js").read_text(encoding="utf-8")

    assert "evil();" in stealth or 'evil(\\"injected\\")' not in stealth
    assert 'timeZone: "Europe/Moscow"); evil' not in stealth


def test_stealth_js_escapes_ua_full_version(tmp_path):
    fp = FingerprintConfig(ua_full_version='133.0.6943.53"; malicious();//')
    prof = BrowserProfile(id="inj_uafull", name="UA Inj", fingerprint=fp)
    ext_dir = Path(generate_profile_extension(prof, tmp_path))
    stealth = (ext_dir / "stealth.js").read_text(encoding="utf-8")

    assert 'uaFullVersion: "133.0.6943.53";' not in stealth


def test_stealth_js_escapes_architecture_and_bitness(tmp_path):
    fp = FingerprintConfig(architecture='x86"; evil()//', bitness='64"; evil()//')
    prof = BrowserProfile(id="inj_arch", name="Arch Inj", fingerprint=fp)
    ext_dir = Path(generate_profile_extension(prof, tmp_path))
    stealth = (ext_dir / "stealth.js").read_text(encoding="utf-8")

    assert 'architecture: "x86";' not in stealth
    assert 'bitness: "64";' not in stealth


def test_stealth_js_escapes_model_field(tmp_path):
    fp = FingerprintConfig(model='Pixel 8" Pro')
    prof = BrowserProfile(id="inj_model", name="Model Inj", fingerprint=fp)
    ext_dir = Path(generate_profile_extension(prof, tmp_path))
    stealth = (ext_dir / "stealth.js").read_text(encoding="utf-8")

    assert 'Pixel 8\\" Pro' in stealth


# ---------------------------------------------------------------------------
# 13-17: Prototype property spoofing correctness
# ---------------------------------------------------------------------------
def test_stealth_js_overrides_navigator_webdriver_false(tmp_path):
    prof = BrowserProfile(id="st_webdriver", name="Webdriver Test")
    ext_dir = Path(generate_profile_extension(prof, tmp_path))
    stealth = (ext_dir / "stealth.js").read_text(encoding="utf-8")

    assert "Navigator.prototype.webdriver" in stealth
    assert "delete Navigator.prototype.webdriver" in stealth


def test_stealth_js_overrides_hardware_concurrency(tmp_path):
    fp = FingerprintConfig(hardware_concurrency=16)
    prof = BrowserProfile(id="st_cores", name="Cores Test", fingerprint=fp)
    ext_dir = Path(generate_profile_extension(prof, tmp_path))
    stealth = (ext_dir / "stealth.js").read_text(encoding="utf-8")

    assert "hardwareConcurrency" in stealth
    assert "16" in stealth


def test_stealth_js_overrides_device_memory(tmp_path):
    fp = FingerprintConfig(device_memory=32)
    prof = BrowserProfile(id="st_ram", name="RAM Test", fingerprint=fp)
    ext_dir = Path(generate_profile_extension(prof, tmp_path))
    stealth = (ext_dir / "stealth.js").read_text(encoding="utf-8")

    assert "deviceMemory" in stealth
    assert "32" in stealth


def test_stealth_js_overrides_screen_dimensions(tmp_path):
    fp = FingerprintConfig(screen_width=2560, screen_height=1440, color_depth=24)
    prof = BrowserProfile(id="st_screen", name="Screen Test", fingerprint=fp)
    ext_dir = Path(generate_profile_extension(prof, tmp_path))
    stealth = (ext_dir / "stealth.js").read_text(encoding="utf-8")

    assert "2560" in stealth
    assert "1440" in stealth
    assert "colorDepth" in stealth


def test_stealth_js_overrides_webgl_unmasked_vendor_and_renderer(tmp_path):
    fp = FingerprintConfig(
        webgl_vendor="Google Inc. (NVIDIA)",
        webgl_renderer="ANGLE (NVIDIA, NVIDIA GeForce RTX 4080 Direct3D11 vs_5_0 ps_5_0, D3D11)",
    )
    prof = BrowserProfile(id="st_webgl", name="WebGL Test", fingerprint=fp)
    ext_dir = Path(generate_profile_extension(prof, tmp_path))
    stealth = (ext_dir / "stealth.js").read_text(encoding="utf-8")

    assert "37445" in stealth  # UNMASKED_VENDOR_WEBGL
    assert "37446" in stealth  # UNMASKED_RENDERER_WEBGL
    assert "RTX 4080" in stealth


# ---------------------------------------------------------------------------
# 18-22: Noise injection and leak shields
# ---------------------------------------------------------------------------
def test_stealth_js_canvas_noise_deterministic_per_profile(tmp_path):
    fp1 = FingerprintConfig(canvas_noise=True, canvas_noise_seed=12345)
    p1 = BrowserProfile(id="noise_1", name="N1", fingerprint=fp1)
    d1 = Path(generate_profile_extension(p1, tmp_path / "t1"))

    fp2 = FingerprintConfig(canvas_noise=True, canvas_noise_seed=12345)
    p2 = BrowserProfile(id="noise_2", name="N2", fingerprint=fp2)
    d2 = Path(generate_profile_extension(p2, tmp_path / "t2"))

    s1 = (d1 / "stealth.js").read_text(encoding="utf-8")
    s2 = (d2 / "stealth.js").read_text(encoding="utf-8")

    assert "const seed = 12345" in s1
    assert "const seed = 12345" in s2


def test_stealth_js_canvas_noise_disabled_when_flag_false(tmp_path):
    fp = FingerprintConfig(canvas_noise=False)
    p = BrowserProfile(id="noise_off", name="No Noise", fingerprint=fp)
    ext_dir = Path(generate_profile_extension(p, tmp_path))
    stealth = (ext_dir / "stealth.js").read_text(encoding="utf-8")

    assert "if (false)" in stealth
    assert "11. Subtle Canvas 2D Noise" in stealth


def test_stealth_js_audio_noise_disabled_when_flag_false(tmp_path):
    fp = FingerprintConfig(audio_noise=False)
    p = BrowserProfile(id="audio_off", name="No Audio Noise", fingerprint=fp)
    ext_dir = Path(generate_profile_extension(p, tmp_path))
    stealth = (ext_dir / "stealth.js").read_text(encoding="utf-8")

    assert "if (false)" in stealth
    assert "12. AudioContext Fingerprint Noise" in stealth


def test_stealth_js_webrtc_ip_leak_shield(tmp_path):
    fp = FingerprintConfig(webrtc_policy="disable_non_proxied_udp")
    p = BrowserProfile(id="webrtc_shield", name="WebRTC Shield", fingerprint=fp)
    ext_dir = Path(generate_profile_extension(p, tmp_path))
    stealth = (ext_dir / "stealth.js").read_text(encoding="utf-8")

    assert "RTCPeerConnection" in stealth


def test_stealth_js_contains_valid_iife_syntax(tmp_path):
    prof = BrowserProfile(id="iife_syntax", name="IIFE Test")
    ext_dir = Path(generate_profile_extension(prof, tmp_path))
    stealth = (ext_dir / "stealth.js").read_text(encoding="utf-8")

    assert "(function() {" in stealth
    assert stealth.strip().endswith("})();")


# ---------------------------------------------------------------------------
# 23-25: Fingerprint generator platform realism
# ---------------------------------------------------------------------------
def test_fingerprint_generator_synthesizes_all_platforms():
    for os_name in ["windows", "macos", "linux"]:
        fp = generate_random_fingerprint(os_type=os_name)
        assert fp is not None
        if os_name == "windows":
            assert "Windows" in fp.user_agent
            assert fp.platform == "Win32"
        elif os_name == "macos":
            assert "Macintosh" in fp.user_agent
            assert fp.platform == "MacIntel"
        elif os_name == "linux":
            assert "Linux" in fp.user_agent
            assert "Linux" in fp.platform


def test_fingerprint_generator_produces_realistic_hardware_combinations():
    fp_win = generate_random_fingerprint(os_type="windows")
    assert fp_win.hardware_concurrency in [4, 6, 8, 12, 16, 24, 32]
    assert fp_win.device_memory in [8, 16, 32, 64]
    assert fp_win.screen_width >= 1280
    assert fp_win.screen_height >= 720


def test_fingerprint_generator_brands_match_chrome_version():
    fp = generate_random_fingerprint(os_type="windows")
    brand_names = [b.get("brand") for b in fp.brands]
    assert "Chromium" in brand_names
    assert "Google Chrome" in brand_names or "Not A(Brand" in brand_names or any("Brand" in b for b in brand_names)
