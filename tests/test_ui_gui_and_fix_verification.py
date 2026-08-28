"""
Suite 5: GUI, Dialogs & Bug Fixes Verification Tests.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nazak.core.profile_manager import ProfileManager
from nazak.models.profile import BrowserProfile, FingerprintConfig, GoogleSettings, ProfileStatus
from nazak.models.proxy import ProxyConfig, ProxyType


@pytest.fixture
def temp_profile_manager():
    with tempfile.TemporaryDirectory() as td:
        p_json = Path(td) / "profiles.json"
        p_dir = Path(td) / "profiles"
        pm = ProfileManager(p_json, p_dir)
        yield pm, p_dir


def test_cookie_persistence_save_and_load_json(temp_profile_manager):
    """Verifies that ProfileManager.save_profile_cookies persists cookies to disk and load_profile_cookies retrieves them."""
    pm, _ = temp_profile_manager
    p = pm.list_profiles()[0]

    cookies = [
        {"name": "SID", "value": "test_sid_123", "domain": ".google.com", "path": "/", "secure": True},
        {"name": "HSID", "value": "test_hsid_456", "domain": ".google.com", "path": "/", "secure": True},
    ]

    ok = pm.save_profile_cookies(p.id, cookies)
    assert ok is True

    loaded = pm.load_profile_cookies(p.id)
    assert len(loaded) == 2
    assert loaded[0]["name"] == "SID"
    assert loaded[0]["value"] == "test_sid_123"


def test_cookie_persistence_creates_netscape_file(temp_profile_manager):
    """Verifies that ProfileManager.save_profile_cookies also generates valid cookies.txt."""
    pm, p_dir = temp_profile_manager
    p = pm.list_profiles()[0]

    cookies = [{"name": "LOGIN_INFO", "value": "auth_token_xyz", "domain": ".youtube.com", "path": "/", "secure": True}]
    pm.save_profile_cookies(p.id, cookies)

    txt_file = p_dir / p.id / "cookies.txt"
    assert txt_file.exists()
    content = txt_file.read_text(encoding="utf-8")
    assert ".youtube.com" in content
    assert "LOGIN_INFO" in content
    assert "auth_token_xyz" in content


def test_profile_card_none_gpu_safe_formatting(temp_profile_manager):
    """Profile with None / empty GPU strings renders safe default without AttributeError."""
    pm, _ = temp_profile_manager
    p = pm.list_profiles()[0]
    p.fingerprint.webgl_unmasked_renderer = None
    p.fingerprint.webgl_renderer = None

    # Simulate ProfileCard logic
    fp = p.fingerprint
    gpu_raw = (fp.webgl_unmasked_renderer or fp.webgl_renderer or "Integrated GPU") if fp else "Integrated GPU"
    gpu_short = (
        str(gpu_raw)
        .replace("(R)", "")
        .replace("(TM)", "")
        .replace("NVIDIA GeForce ", "")
        .replace("AMD Radeon ", "")
        .replace("Graphics", "")
        .replace("  ", " ")
        .strip()
    )
    assert gpu_short == "Integrated GPU"


def test_profile_card_default_fingerprint_safe_formatting():
    """Profile with default blank fingerprint configuration does not raise exception."""
    p = BrowserProfile(
        id="test_no_fp",
        name="No FP Profile",
        group="Test",
        proxy=ProxyConfig(type=ProxyType.DIRECT),
        fingerprint=FingerprintConfig(),
        google=GoogleSettings(),
    )
    fp = p.fingerprint
    gpu_raw = (fp.webgl_unmasked_renderer or fp.webgl_renderer or "Integrated GPU") if fp else "Integrated GPU"
    assert "RTX" in gpu_raw or "GPU" in gpu_raw or "Intel" in gpu_raw or "AMD" in gpu_raw
    cores = fp.hardware_concurrency if fp else 16
    assert cores >= 4


def test_profile_edit_dialog_switch_state_integrity(temp_profile_manager):
    """Fingerprint switch states (canvas_noise, audio_noise, block_port_scanning) are preserved accurately."""
    pm, _ = temp_profile_manager
    p = pm.list_profiles()[0]
    p.fingerprint.canvas_noise = False
    p.fingerprint.audio_noise = False
    p.fingerprint.block_port_scanning = False
    pm.save_profiles()

    reloaded = pm.get_profile(p.id)
    assert reloaded.fingerprint.canvas_noise is False
    assert reloaded.fingerprint.audio_noise is False
    assert reloaded.fingerprint.block_port_scanning is False


def test_clear_profile_cache_handles_both_default_and_root(temp_profile_manager):
    """clear_profile_cache wipes Cache directories in both root and Default/ subfolders."""
    pm, p_dir = temp_profile_manager
    p = pm.list_profiles()[0]
    cache_dir = p_dir / p.id / "Default" / "Cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "data_0").write_bytes(b"CACHE_BYTES")

    assert cache_dir.exists()
    ok = pm.clear_profile_cache(p.id)
    assert ok is True
    assert not cache_dir.exists()
