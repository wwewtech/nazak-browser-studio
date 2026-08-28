import json
from pathlib import Path

import pytest

from nazak.core.extension_generator import generate_profile_extension
from nazak.models.profile import BrowserProfile, FingerprintConfig
from nazak.models.proxy import ProxyConfig, ProxyType


def test_generate_stealth_extension(tmp_path):
    fp = FingerprintConfig(
        user_agent="Mozilla/5.0 Custom Test UA",
        screen_width=2560,
        screen_height=1440,
        hardware_concurrency=12,
        device_memory=32,
        language="ru-RU,ru;q=0.9",
        webgl_vendor="NVIDIA Corporation",
        webgl_renderer="NVIDIA GeForce RTX 4090",
    )
    prof = BrowserProfile(
        id="test_prof_01", name="Test Profile", proxy=ProxyConfig(type=ProxyType.DIRECT), fingerprint=fp
    )

    ext_dir_str = generate_profile_extension(prof, tmp_path)
    assert ext_dir_str is not None
    ext_dir = Path(ext_dir_str)
    assert ext_dir.exists()

    manifest_file = ext_dir / "manifest.json"
    assert manifest_file.exists()
    with open(manifest_file, encoding="utf-8") as f:
        manifest = json.load(f)
    assert manifest["manifest_version"] == 2
    assert "webRequest" in manifest["permissions"]

    stealth_file = ext_dir / "stealth.js"
    assert stealth_file.exists()
    stealth_content = stealth_file.read_text(encoding="utf-8")
    assert "webdriver" in stealth_content
    assert "2560" in stealth_content
    assert "1440" in stealth_content
    assert "NVIDIA GeForce RTX 4090" in stealth_content


def test_generate_auth_proxy_extension(tmp_path):
    prof = BrowserProfile(
        id="test_prof_auth",
        name="Auth Proxy Profile",
        proxy=ProxyConfig.parse("socks5://testuser:supersecret@127.0.0.1:1080"),
    )

    ext_dir_str = generate_profile_extension(prof, tmp_path)
    ext_dir = Path(ext_dir_str)

    bg_file = ext_dir / "background.js"
    assert bg_file.exists()
    bg_content = bg_file.read_text(encoding="utf-8")
    assert "testuser" in bg_content
    assert "supersecret" in bg_content
    assert "onAuthRequired" in bg_content
