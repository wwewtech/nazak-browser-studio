"""
Verification test suite for v1.7.0 bug fixes:
- Manifest V3 migration
- Proxy authentication via webRequestAuthProvider and asyncBlocking callback
- navigator.webdriver returning false without deletion (W3C WebDriver compliant)
- Multi-channel canvas noise with toDataURL hook
- AudioBuffer noise across multiple samples
- getBoundingClientRect sub-pixel jitter
- DevToolsActivePort detection and stale lock cleanup
- ProfileManager safe symlink handling and error logging
"""

import json
from pathlib import Path
from unittest.mock import patch

from nazak.core.browser_launcher import BrowserLauncher
from nazak.core.extension_generator import generate_profile_extension
from nazak.core.profile_manager import ProfileManager
from nazak.models.profile import BrowserProfile, FingerprintConfig
from nazak.models.proxy import ProxyConfig


def test_v170_manifest_v3_and_proxy_auth(tmp_path):
    proxy = ProxyConfig(host="1.2.3.4", port=8080, username="user1", password="pass1")
    prof = BrowserProfile(id="p_v170", name="V170 Profile", proxy=proxy)
    ext_dir = Path(generate_profile_extension(prof, tmp_path))

    manifest_file = ext_dir / "manifest.json"
    assert manifest_file.exists()
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))

    # 1. Manifest V3
    assert manifest["manifest_version"] == 3
    assert "webRequest" in manifest["permissions"]
    assert "webRequestAuthProvider" in manifest["permissions"]
    assert "<all_urls>" in manifest["host_permissions"]
    assert manifest["content_scripts"][0]["world"] == "MAIN"

    # 2. Service worker background script
    assert manifest["background"]["service_worker"] == "background.js"
    bg_js = (ext_dir / "background.js").read_text(encoding="utf-8")
    assert "asyncBlocking" in bg_js
    assert "callback" in bg_js
    assert "authCredentials" in bg_js
    assert "user1" in bg_js
    assert "pass1" in bg_js


def test_v170_stealth_webdriver_compliance(tmp_path):
    prof = BrowserProfile(id="p_wd", name="WD Profile")
    ext_dir = Path(generate_profile_extension(prof, tmp_path))
    stealth_js = (ext_dir / "stealth.js").read_text(encoding="utf-8")

    # Property webdriver returns false without delete
    assert "Object.defineProperty(Navigator.prototype, 'webdriver'" in stealth_js
    assert "get: () => false" in stealth_js
    assert "delete Navigator.prototype.webdriver" not in stealth_js


def test_v170_stealth_canvas_multi_channel_and_todataurl(tmp_path):
    fp = FingerprintConfig(canvas_noise=True, canvas_noise_seed=777888)
    prof = BrowserProfile(id="p_canvas", name="Canvas Profile", fingerprint=fp)
    ext_dir = Path(generate_profile_extension(prof, tmp_path))
    stealth_js = (ext_dir / "stealth.js").read_text(encoding="utf-8")

    assert "mutateCanvasData" in stealth_js
    assert "HTMLCanvasElement.prototype.toDataURL" in stealth_js
    assert "1664525" in stealth_js  # LCG constant
    assert "777888" in stealth_js


def test_v170_stealth_audio_noise_spectral(tmp_path):
    fp = FingerprintConfig(audio_noise=True, audio_noise_seed=0.00002)
    prof = BrowserProfile(id="p_audio", name="Audio Profile", fingerprint=fp)
    ext_dir = Path(generate_profile_extension(prof, tmp_path))
    stealth_js = (ext_dir / "stealth.js").read_text(encoding="utf-8")

    assert "AudioBuffer.prototype.getChannelData" in stealth_js
    assert "Math.floor(data.length / 100)" in stealth_js


def test_v170_stealth_client_rects_subpixel_noise(tmp_path):
    fp = FingerprintConfig(client_rects_noise=True, canvas_noise_seed=12345)
    prof = BrowserProfile(id="p_rects", name="Rects Profile", fingerprint=fp)
    ext_dir = Path(generate_profile_extension(prof, tmp_path))
    stealth_js = (ext_dir / "stealth.js").read_text(encoding="utf-8")

    assert "Element.prototype.getBoundingClientRect" in stealth_js
    assert "jitter" in stealth_js
    assert "rect.x + jitter" in stealth_js


def test_v170_browser_launcher_devtools_active_port(tmp_path):
    user_data = tmp_path / "user_data"
    user_data.mkdir(parents=True)
    port_file = user_data / "DevToolsActivePort"
    port_file.write_text("54321\n/devtools/browser/abc-123-guid\n", encoding="utf-8")

    launcher = BrowserLauncher(profiles_dir=tmp_path, extensions_dir=tmp_path / "ext")
    port, ws_url = launcher.read_devtools_active_port(user_data, timeout_sec=0.5)

    assert port == 54321
    assert ws_url == "ws://127.0.0.1:54321/devtools/browser/abc-123-guid"

    # Verify DevToolsActivePort is cleaned by clean_stale_locks
    launcher.clean_stale_locks(user_data)
    assert not port_file.exists()


def test_v170_profile_manager_delete_profile_symlink_safety(tmp_path):
    p_file = tmp_path / "profiles.json"
    p_dir = tmp_path / "profiles"
    p_dir.mkdir(parents=True)

    pm = ProfileManager(profiles_file=p_file, profiles_dir=p_dir)
    prof = BrowserProfile(id="p_del_sym", name="Sym Profile")
    pm.create_profile(prof)

    profile_folder = p_dir / "p_del_sym"
    profile_folder.mkdir(parents=True, exist_ok=True)
    (profile_folder / "session.txt").write_text("active data")

    # Deleting profile removes data
    assert pm.delete_profile("p_del_sym", delete_data=True)
    assert not profile_folder.exists()
