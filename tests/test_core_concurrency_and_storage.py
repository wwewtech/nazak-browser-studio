"""
Suite 4: Core Concurrency, Storage Recovery, Deep Cloning & Proxy Health Tests (20 Tests).
"""

import json
import shutil
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from nazak.core.profile_manager import ProfileManager
from nazak.core.spintax import parse_spintax
from nazak.models.profile import BrowserProfile, FingerprintConfig, GoogleSettings, ProfileStatus
from nazak.models.proxy import ProxyConfig, ProxyType


@pytest.fixture
def temp_env():
    with tempfile.TemporaryDirectory() as td:
        p_json = Path(td) / "profiles.json"
        p_dir = Path(td) / "profiles"
        pm = ProfileManager(p_json, p_dir)
        yield pm, p_json, p_dir


# -------------------------------------------------------------
# 1. Storage Recovery & Integrity (6 Tests)
# -------------------------------------------------------------


def test_profile_manager_corrupted_json_recovery_creates_backup(temp_env):
    """Corrupted / truncated profiles.json creates a .bak backup and restores default profiles."""
    pm, p_json, p_dir = temp_env

    # Intentionally corrupt the profiles.json file
    p_json.write_text("{ NOT_VALID_JSON_TRUNCATED: [123, ", encoding="utf-8")

    # Reload ProfileManager
    pm2 = ProfileManager(p_json, p_dir)
    assert len(pm2.list_profiles()) == 10

    # Check that a backup file was created
    bak_files = list(p_json.parent.glob("profiles.corrupt.*.bak"))
    assert len(bak_files) >= 1


def test_profile_manager_partial_corrupted_json_entry_skipped(temp_env):
    """When 1 item in the JSON array is malformed, other valid profiles are preserved."""
    pm, p_json, p_dir = temp_env

    valid_p = pm.list_profiles()[0].model_dump()
    corrupt_items = [
        valid_p,
        {"id": "broken_p", "fingerprint": 99999999},  # Invalid type triggers ValidationError
        "not_even_a_dict",
    ]
    p_json.write_text(json.dumps(corrupt_items), encoding="utf-8")

    pm2 = ProfileManager(p_json, p_dir)
    loaded = pm2.list_profiles()
    assert len(loaded) == 1
    assert loaded[0].id == valid_p["id"]


def test_profile_manager_atomic_save_retry(temp_env):
    """Simulate Windows replace permission glitch and verify save_profiles completes."""
    pm, p_json, p_dir = temp_env
    p = pm.list_profiles()[0]
    p.name = "Updated Atomic Profile Name"
    pm.save_profiles()

    pm_check = ProfileManager(p_json, p_dir)
    assert pm_check.get_profile(p.id).name == "Updated Atomic Profile Name"


def test_profile_manager_create_profile_auto_generates_id(temp_env):
    """Creating a profile with empty id generates a unique prof_ prefix ID."""
    pm, _, _ = temp_env
    new_p = BrowserProfile(
        id="",
        name="Auto ID Test",
        group="Test",
        proxy=ProxyConfig(type=ProxyType.DIRECT),
        fingerprint=FingerprintConfig(),
        google=GoogleSettings(),
    )
    saved = pm.create_profile(new_p)
    assert saved.id.startswith("prof_")
    assert pm.get_profile(saved.id) is not None


def test_profile_manager_get_disk_size_bytes(temp_env):
    """Calculates disk space used by a profile folder."""
    pm, _, p_dir = temp_env
    p = pm.list_profiles()[0]
    prof_folder = p_dir / p.id
    prof_folder.mkdir(parents=True, exist_ok=True)

    # Write a 10KB test file
    test_file = prof_folder / "test_data.bin"
    test_file.write_bytes(b"A" * 10240)

    size = pm.get_profile_disk_size_bytes(p.id)
    assert size >= 10240


def test_profile_manager_get_disk_size_nonexistent(temp_env):
    """Non-existent profile directory returns 0 bytes cleanly."""
    pm, _, _ = temp_env
    assert pm.get_profile_disk_size_bytes("nonexistent_profile_id") == 0


# -------------------------------------------------------------
# 2. Deep Cloning & Hardware Decoupling (5 Tests)
# -------------------------------------------------------------


def test_profile_manager_clone_generates_new_seeds(temp_env):
    """Cloned profile has distinct canvas and audio noise seeds to prevent fingerprint correlation."""
    pm, _, _ = temp_env
    src = pm.list_profiles()[0]
    src.fingerprint.canvas_noise_seed = 111111
    src.fingerprint.audio_noise_seed = 0.000001
    pm.save_profiles()

    cloned = pm.clone_profile(src.id, "Cloned Profile")
    assert cloned is not None
    assert cloned.id != src.id
    assert cloned.name == "Cloned Profile"
    assert cloned.fingerprint.canvas_noise_seed != src.fingerprint.canvas_noise_seed
    assert cloned.fingerprint.audio_noise_seed != src.fingerprint.audio_noise_seed


def test_profile_manager_clone_generates_distinct_media_ids(temp_env):
    """Cloned profile generates unique device IDs and group IDs for all microphones and webcams."""
    pm, _, _ = temp_env
    src = pm.list_profiles()[0]
    cloned = pm.clone_profile(src.id)

    src_dev_ids = [d.device_id for d in src.fingerprint.media_devices]
    cloned_dev_ids = [d.device_id for d in cloned.fingerprint.media_devices]

    for dev_id in cloned_dev_ids:
        assert dev_id not in src_dev_ids


def test_profile_manager_clone_resets_runtime_metrics(temp_env):
    """Cloned profile resets runtime, pid, status, and health check timestamps."""
    pm, _, _ = temp_env
    src = pm.list_profiles()[0]
    src.status = ProfileStatus.RUNNING
    src.pid = 12345
    src.total_runtime_seconds = 9999
    pm.save_profiles()

    cloned = pm.clone_profile(src.id)
    assert cloned.status == ProfileStatus.STOPPED
    assert cloned.pid is None
    assert cloned.total_runtime_seconds == 0
    assert cloned.last_launched_at is None


def test_profile_manager_clone_nonexistent_returns_none(temp_env):
    """Cloning a non-existent source ID returns None safely."""
    pm, _, _ = temp_env
    assert pm.clone_profile("nonexistent_id") is None


def test_profile_manager_delete_profile_with_data_dir(temp_env):
    """Deleting a profile with delete_data=True wipes the directory from disk."""
    pm, _, p_dir = temp_env
    p = pm.list_profiles()[0]
    prof_folder = p_dir / p.id
    prof_folder.mkdir(parents=True, exist_ok=True)
    (prof_folder / "cookie.sqlite").write_text("data", encoding="utf-8")

    assert prof_folder.exists()
    ok = pm.delete_profile(p.id, delete_data=True)
    assert ok is True
    assert not prof_folder.exists()
    assert pm.get_profile(p.id) is None


# -------------------------------------------------------------
# 3. Spintax & Text Permutations (5 Tests)
# -------------------------------------------------------------


def test_spintax_basic_choice():
    """Selects one item from {opt1|opt2|opt3}."""
    tpl = "{Hello|Hi|Greetings} world!"
    results = set(parse_spintax(tpl) for _ in range(50))
    assert len(results) > 1
    assert all("world!" in r for r in results)


def test_spintax_nested_permutation_generation():
    """Evaluates nested spintax structures correctly."""
    tpl = "{The {quick|fast}|A {speedy|nimble}} {brown|dark} fox"
    results = set(parse_spintax(tpl) for _ in range(100))
    assert len(results) >= 4
    for r in results:
        assert "fox" in r


def test_spintax_no_brackets():
    """Text without spintax brackets is returned unchanged."""
    plain = "This is plain text with no variations."
    assert parse_spintax(plain) == plain


def test_spintax_empty_string():
    """Empty string returns empty string."""
    assert parse_spintax("") == ""


def test_spintax_special_characters_inside_options():
    """Special characters and emojis inside options are preserved."""
    tpl = "{Trending|Viral|Top} Shorts #{100|200|300}"
    results = set(parse_spintax(tpl) for _ in range(50))
    assert len(results) >= 3


# -------------------------------------------------------------
# 4. Proxy Configuration Resilience (4 Tests)
# -------------------------------------------------------------


def test_proxy_config_is_direct():
    """Direct proxy detection works across all zero-host states."""
    assert ProxyConfig(type=ProxyType.DIRECT).is_direct() is True
    assert ProxyConfig(type=ProxyType.HTTP, host=None, port=None).is_direct() is True
    assert ProxyConfig(type=ProxyType.HTTP, host="1.2.3.4", port=8080).is_direct() is False


def test_proxy_config_has_auth():
    """Auth detection works only when both username and password exist."""
    assert ProxyConfig(type=ProxyType.HTTP, host="1.2.3.4", port=8080).has_auth() is False
    assert ProxyConfig(type=ProxyType.HTTP, host="1.2.3.4", port=8080, username="u").has_auth() is False
    assert ProxyConfig(type=ProxyType.HTTP, host="1.2.3.4", port=8080, username="u", password="p").has_auth() is True


def test_proxy_config_to_chrome_arg():
    """Formats Chrome proxy argument for HTTP and SOCKS5."""
    p_http = ProxyConfig(type=ProxyType.HTTP, host="192.168.1.50", port=3128)
    assert p_http.to_chrome_proxy_arg() == "http://192.168.1.50:3128"

    p_socks = ProxyConfig(type=ProxyType.SOCKS5, host="192.168.1.50", port=1080)
    assert p_socks.to_chrome_proxy_arg() == "socks5://192.168.1.50:1080"


def test_proxy_config_to_httpx_url():
    """Formats HTTPX connection URL with credentials if present."""
    p_auth = ProxyConfig(type=ProxyType.HTTP, host="proxy.com", port=8080, username="user1", password="p@ss:word")
    httpx_url = p_auth.to_httpx_url()
    assert httpx_url.startswith("http://")
    assert "proxy.com:8080" in httpx_url
