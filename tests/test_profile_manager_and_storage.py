import json
from pathlib import Path

import pytest

from nazak.core.fingerprint_generator import generate_random_fingerprint
from nazak.core.profile_manager import ProfileManager
from nazak.models import BrowserProfile, ProfileStatus, ProxyConfig, ProxyType


def test_profile_manager_initialization_creates_10_profiles(tmp_path):
    pm = ProfileManager(tmp_path / "profiles.json", tmp_path / "data")
    profs = pm.list_profiles()
    assert len(profs) == 10
    assert (tmp_path / "profiles.json").exists()


def test_profile_manager_get_existing_and_nonexisting(tmp_path):
    pm = ProfileManager(tmp_path / "profiles.json", tmp_path / "data")
    assert pm.get_profile("prof_01") is not None
    assert pm.get_profile("nonexistent_id") is None


def test_profile_manager_create_and_delete(tmp_path):
    pm = ProfileManager(tmp_path / "profiles.json", tmp_path / "data")
    new_prof = BrowserProfile(
        id="custom_01",
        name="Custom Profile",
        proxy=ProxyConfig(type=ProxyType.DIRECT),
        fingerprint=generate_random_fingerprint(),
    )
    pm.create_profile(new_prof)
    assert pm.get_profile("custom_01") is not None
    assert len(pm.list_profiles()) == 11

    # Delete profile
    ok = pm.delete_profile("custom_01", delete_data=True)
    assert ok is True
    assert pm.get_profile("custom_01") is None
    assert len(pm.list_profiles()) == 10


def test_profile_manager_delete_nonexisting(tmp_path):
    pm = ProfileManager(tmp_path / "profiles.json", tmp_path / "data")
    assert pm.delete_profile("unknown_xyz") is False


def test_profile_manager_update_existing(tmp_path):
    pm = ProfileManager(tmp_path / "profiles.json", tmp_path / "data")
    prof = pm.get_profile("prof_01")
    prof.name = "Updated Name"
    updated = pm.update_profile(prof)
    assert updated is not None
    assert updated.name == "Updated Name"
    assert pm.get_profile("prof_01").name == "Updated Name"


def test_profile_manager_update_nonexisting(tmp_path):
    pm = ProfileManager(tmp_path / "profiles.json", tmp_path / "data")
    dummy = BrowserProfile(id="fake_id", name="Fake", fingerprint=generate_random_fingerprint())
    assert pm.update_profile(dummy) is None


def test_profile_manager_corrupted_json_recovery(tmp_path):
    p_file = tmp_path / "profiles.json"
    p_file.write_text("{corrupted_json::", encoding="utf-8")

    pm = ProfileManager(p_file, tmp_path / "data")
    # Should recover gracefully and initialize default profiles
    assert len(pm.list_profiles()) == 10


def test_profile_manager_empty_json_recovery(tmp_path):
    p_file = tmp_path / "profiles.json"
    p_file.write_text("", encoding="utf-8")

    pm = ProfileManager(p_file, tmp_path / "data")
    assert len(pm.list_profiles()) == 10


def test_profile_disk_size_empty(tmp_path):
    pm = ProfileManager(tmp_path / "profiles.json", tmp_path / "data")
    size = pm.get_profile_disk_size_bytes("prof_01")
    assert size == 0


def test_profile_disk_size_with_files(tmp_path):
    p_dir = tmp_path / "data" / "prof_01"
    p_dir.mkdir(parents=True)
    (p_dir / "test.bin").write_bytes(b"A" * 1024)
    (p_dir / "sub").mkdir()
    (p_dir / "sub" / "test2.bin").write_bytes(b"B" * 2048)

    pm = ProfileManager(tmp_path / "profiles.json", tmp_path / "data")
    size = pm.get_profile_disk_size_bytes("prof_01")
    assert size == 3072


def test_profile_disk_size_nonexistent(tmp_path):
    pm = ProfileManager(tmp_path / "profiles.json", tmp_path / "data")
    assert pm.get_profile_disk_size_bytes("nonexistent_profile") == 0


def test_clear_profile_cache(tmp_path):
    p_dir = tmp_path / "data" / "prof_01" / "Default" / "Cache"
    p_dir.mkdir(parents=True)
    (p_dir / "cache_file.data").write_text("cached_data")

    pm = ProfileManager(tmp_path / "profiles.json", tmp_path / "data")
    ok = pm.clear_profile_cache("prof_01")
    assert ok is True
    assert not p_dir.exists()


def test_clear_profile_cache_nonexistent_profile(tmp_path):
    pm = ProfileManager(tmp_path / "profiles.json", tmp_path / "data")
    assert pm.clear_profile_cache("fake_profile") is True


def test_clone_nonexistent_profile(tmp_path):
    pm = ProfileManager(tmp_path / "profiles.json", tmp_path / "data")
    assert pm.clone_profile("fake_profile") is None


def test_profile_manager_persists_to_disk(tmp_path):
    p_file = tmp_path / "profiles.json"
    pm1 = ProfileManager(p_file, tmp_path / "data")
    prof = pm1.get_profile("prof_01")
    prof.google.notes = "Special marketing profile"
    pm1.update_profile(prof)

    # Instantiate fresh PM from same file
    pm2 = ProfileManager(p_file, tmp_path / "data")
    assert pm2.get_profile("prof_01").google.notes == "Special marketing profile"
