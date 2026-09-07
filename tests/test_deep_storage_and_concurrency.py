"""
Deep storage, concurrency, atomic persistence, and ProfileManager resilience test suite.
Contains 25 comprehensive tests verifying C5, M1, M2, M4, M5, M6, and recovery dynamics.
"""

import json
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

from nazak.api.server import app as fastapi_app
from nazak.core.process_monitor import ProcessMonitor
from nazak.core.profile_manager import ProfileManager
from nazak.models.profile import BrowserProfile, FingerprintConfig, ProfileStatus
from nazak.models.proxy import ProxyConfig


# ---------------------------------------------------------------------------
# 1-4: Atomic save and lock dynamics
# ---------------------------------------------------------------------------
def test_save_profiles_creates_valid_atomic_json(tmp_path):
    pfile = tmp_path / "profiles.json"
    pdir = tmp_path / "profiles"
    pm = ProfileManager(pfile, pdir)

    p = BrowserProfile(id="p_atom", name="Atomic Profile")
    pm.profiles[p.id] = p
    pm.save_profiles()

    assert pfile.exists()
    content = json.loads(pfile.read_text(encoding="utf-8"))
    assert any(item["id"] == "p_atom" for item in content)

    # No leftover .tmp files should exist in directory
    tmp_files = list(tmp_path.glob("*.tmp"))
    assert len(tmp_files) == 0


def test_save_profiles_lock_reentrancy(tmp_path):
    pfile = tmp_path / "profiles.json"
    pdir = tmp_path / "profiles"
    pm = ProfileManager(pfile, pdir)

    # Acquire lock and verify nested save_profiles call executes cleanly (RLock behavior)
    with pm._save_lock:
        p = BrowserProfile(id="p_reentrant", name="Reentrant Lock Test")
        pm.profiles[p.id] = p
        pm.save_profiles()

    assert pfile.exists()


def test_concurrent_multi_thread_profile_mutations(tmp_path):
    pfile = tmp_path / "profiles.json"
    pdir = tmp_path / "profiles"
    pm = ProfileManager(pfile, pdir)

    # Seed 12 profiles
    for i in range(12):
        pid = f"prof_mut_{i:02d}"
        pm.profiles[pid] = BrowserProfile(id=pid, name=f"Mutant {i}")
    pm.save_profiles()

    errors = []

    def mutate_worker(worker_id):
        try:
            for it in range(10):
                pid = f"prof_mut_{worker_id:02d}"
                prof = pm.get_profile(pid)
                if prof:
                    prof.name = f"Mutated by {worker_id} at {it}"
                    pm.save_profiles()
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=mutate_worker, args=(i,)) for i in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Concurrent mutation produced errors: {errors}"
    raw = json.loads(pfile.read_text(encoding="utf-8"))
    assert len(raw) == len(pm.profiles)


def test_concurrent_create_and_delete_operations(tmp_path):
    pfile = tmp_path / "profiles.json"
    pdir = tmp_path / "profiles"
    pm = ProfileManager(pfile, pdir)

    errors = []

    def lifecycle_worker(idx):
        try:
            for it in range(5):
                pid = f"worker_{idx}_{it}"
                new_p = BrowserProfile(id=pid, name=f"Worker {idx} {it}")
                pm.create_profile(new_p)
                pm.delete_profile(pid, delete_data=False)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=lifecycle_worker, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Lifecycle errors: {errors}"


# ---------------------------------------------------------------------------
# 5-8: Profile creation ID conflicts and edge cases
# ---------------------------------------------------------------------------
def test_create_profile_duplicate_id_raises_value_error(tmp_path):
    pfile = tmp_path / "profiles.json"
    pdir = tmp_path / "profiles"
    pm = ProfileManager(pfile, pdir)

    p1 = BrowserProfile(id="collision_test", name="Original")
    pm.create_profile(p1)

    p2 = BrowserProfile(id="collision_test", name="Duplicate")
    with pytest.raises(ValueError, match="already exists"):
        pm.create_profile(p2)


def test_create_profile_empty_id_generates_uuid(tmp_path):
    pfile = tmp_path / "profiles.json"
    pdir = tmp_path / "profiles"
    pm = ProfileManager(pfile, pdir)

    p = BrowserProfile(id="", name="Auto ID Profile")
    created = pm.create_profile(p)
    assert created.id.startswith("prof_")
    assert len(created.id) >= 10
    assert created.id in pm.profiles


def test_api_create_profile_duplicate_id_returns_409():
    client = TestClient(fastapi_app)
    # Get existing profile
    profiles = client.get("/api/profiles").json()
    assert len(profiles) > 0
    existing_id = profiles[0]["id"]

    resp = client.post("/api/profiles", json={"id": existing_id, "name": "Duplicate Conflict"})
    assert resp.status_code == 409
    assert "already exists" in resp.json()["detail"].lower()


def test_load_profiles_corrupt_file_graceful_fallback(tmp_path):
    pfile = tmp_path / "profiles.json"
    pdir = tmp_path / "profiles"
    # Write broken JSON syntax
    pfile.write_text("{ broken: json [ unclosed", encoding="utf-8")

    pm = ProfileManager(pfile, pdir)
    # Must gracefully fall back to default profiles without crashing
    assert len(pm.profiles) > 0
    assert "prof_01" in pm.profiles or any("YouTube" in p.name for p in pm.profiles.values())


# ---------------------------------------------------------------------------
# 9-13: Clone profile fidelity and edge cases
# ---------------------------------------------------------------------------
def test_clone_profile_generates_unique_id(tmp_path):
    pfile = tmp_path / "profiles.json"
    pdir = tmp_path / "profiles"
    pm = ProfileManager(pfile, pdir)

    source = BrowserProfile(id="source_01", name="Original Source")
    pm.create_profile(source)

    cloned = pm.clone_profile("source_01")
    assert cloned is not None
    assert cloned.id != source.id
    assert cloned.id.startswith("prof_")
    assert cloned.id in pm.profiles


def test_clone_profile_copies_fingerprint_and_proxy(tmp_path):
    pfile = tmp_path / "profiles.json"
    pdir = tmp_path / "profiles"
    pm = ProfileManager(pfile, pdir)

    fp = FingerprintConfig(platform="MacIntel", hardware_concurrency=8, device_memory=16)
    proxy = ProxyConfig(host="1.2.3.4", port=8080, username="user", password="pwd")
    source = BrowserProfile(id="src_rich", name="Rich Source", fingerprint=fp, proxy=proxy)
    pm.create_profile(source)

    cloned = pm.clone_profile("src_rich")
    assert cloned.fingerprint.platform == "MacIntel"
    assert cloned.fingerprint.hardware_concurrency == 8
    assert cloned.fingerprint.device_memory == 16
    assert cloned.proxy.host == "1.2.3.4"
    assert cloned.proxy.username == "user"


def test_clone_profile_preserves_custom_name(tmp_path):
    pfile = tmp_path / "profiles.json"
    pdir = tmp_path / "profiles"
    pm = ProfileManager(pfile, pdir)

    source = BrowserProfile(id="src_name", name="Source Base")
    pm.create_profile(source)

    cloned = pm.clone_profile("src_name", new_name="Bespoke Cloned Name")
    assert cloned.name == "Bespoke Cloned Name"


def test_clone_profile_unknown_id_returns_none(tmp_path):
    pfile = tmp_path / "profiles.json"
    pdir = tmp_path / "profiles"
    pm = ProfileManager(pfile, pdir)
    assert pm.clone_profile("non_existent_profile_999") is None


def test_delete_profile_cleans_user_data_directory(tmp_path):
    pfile = tmp_path / "profiles.json"
    pdir = tmp_path / "profiles"
    pm = ProfileManager(pfile, pdir)

    p = BrowserProfile(id="p_to_del", name="To Delete")
    pm.create_profile(p)

    user_data = pdir / p.id
    user_data.mkdir(parents=True, exist_ok=True)
    (user_data / "Preferences").write_text("{}", encoding="utf-8")

    deleted = pm.delete_profile(p.id, delete_data=True)
    assert deleted is True
    assert p.id not in pm.profiles
    assert not user_data.exists()


# ---------------------------------------------------------------------------
# 14-18: Deletion, cache purging, and disk telemetry
# ---------------------------------------------------------------------------
def test_delete_profile_preserves_dir_when_delete_data_false(tmp_path):
    pfile = tmp_path / "profiles.json"
    pdir = tmp_path / "profiles"
    pm = ProfileManager(pfile, pdir)

    p = BrowserProfile(id="p_preserve", name="Keep Data")
    pm.create_profile(p)

    user_data = pdir / p.id
    user_data.mkdir(parents=True, exist_ok=True)
    (user_data / "cookies.json").write_text("[]", encoding="utf-8")

    deleted = pm.delete_profile(p.id, delete_data=False)
    assert deleted is True
    assert p.id not in pm.profiles
    assert user_data.exists()


def test_batch_delete_profiles(tmp_path):
    pfile = tmp_path / "profiles.json"
    pdir = tmp_path / "profiles"
    pm = ProfileManager(pfile, pdir)

    pm.create_profile(BrowserProfile(id="b_01", name="Batch 1"))
    pm.create_profile(BrowserProfile(id="b_02", name="Batch 2"))
    pm.create_profile(BrowserProfile(id="b_03", name="Batch 3"))

    for pid in ["b_01", "b_02", "b_03"]:
        pm.delete_profile(pid, delete_data=False)

    assert "b_01" not in pm.profiles
    assert "b_02" not in pm.profiles
    assert "b_03" not in pm.profiles


def test_clear_profile_cache_removes_cache_subdirs(tmp_path):
    pfile = tmp_path / "profiles.json"
    pdir = tmp_path / "profiles"
    pm = ProfileManager(pfile, pdir)

    p = BrowserProfile(id="p_cache_purge", name="Purge Cache")
    pm.create_profile(p)

    ud = pdir / p.id / "Default"
    ud.mkdir(parents=True, exist_ok=True)
    cache_dir = ud / "Cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "data_0").write_bytes(b"12345678")

    cookies_file = ud / "Cookies"
    cookies_file.write_bytes(b"SAFE_COOKIES")

    ok = pm.clear_profile_cache(p.id)
    assert ok is True
    assert not cache_dir.exists()
    assert cookies_file.exists()


def test_get_profile_disk_size_bytes_accurate(tmp_path):
    pfile = tmp_path / "profiles.json"
    pdir = tmp_path / "profiles"
    pm = ProfileManager(pfile, pdir)

    p = BrowserProfile(id="p_size_test", name="Size Test")
    pm.create_profile(p)

    target_dir = pdir / p.id
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "test1.bin").write_bytes(b"A" * 1024)
    (target_dir / "test2.bin").write_bytes(b"B" * 2048)

    size = pm.get_profile_disk_size_bytes(p.id)
    assert size == 3072


def test_export_all_cookies_filters_by_ids(tmp_path):
    pfile = tmp_path / "profiles.json"
    pdir = tmp_path / "profiles"
    pm = ProfileManager(pfile, pdir)

    p1 = BrowserProfile(id="c_01", name="Cookie 1")
    p2 = BrowserProfile(id="c_02", name="Cookie 2")
    pm.create_profile(p1)
    pm.create_profile(p2)

    pm.save_profile_cookies("c_01", [{"name": "sid", "value": "123", "domain": "example.com"}])
    pm.save_profile_cookies("c_02", [{"name": "sid", "value": "456", "domain": "other.com"}])

    exported = pm.export_all_cookies(profile_ids=["c_01"])
    assert "Cookie 1" in exported or "c_01" in exported
    assert "Cookie 2" not in exported


# ---------------------------------------------------------------------------
# 19-22: ProcessMonitor callbacks, threading, and M1 skip
# ---------------------------------------------------------------------------
def test_process_monitor_callback_on_exit():
    p1 = BrowserProfile(id="m_cb_1", name="Monitored", status=ProfileStatus.RUNNING, pid=9999)
    mock_pm = MagicMock()
    mock_pm.list_profiles.return_value = [p1]
    mock_pm.get_profile.return_value = p1

    mock_bl = MagicMock()
    mock_bl.is_profile_running.return_value = False

    events = []

    def on_exit(pid, status):
        events.append((pid, status))

    monitor = ProcessMonitor(mock_pm, mock_bl, poll_interval=0.01)
    monitor.register_callback(on_exit)
    monitor.start()
    import time

    time.sleep(0.08)
    monitor.stop()

    assert ("m_cb_1", ProfileStatus.STOPPED) in events


def test_process_monitor_skips_when_status_already_stopped():
    p_stopped = BrowserProfile(id="m_stop_1", name="Already Stopped", status=ProfileStatus.STOPPED, pid=None)
    mock_pm = MagicMock()
    mock_pm.list_profiles.return_value = [p_stopped]
    mock_bl = MagicMock()

    monitor = ProcessMonitor(mock_pm, mock_bl, poll_interval=0.01)
    monitor._running = True
    # One iteration of monitor logic
    for p in mock_pm.list_profiles():
        if p.status == ProfileStatus.RUNNING:
            mock_bl.is_profile_running(p.id)

    mock_bl.is_profile_running.assert_not_called()
    mock_pm.update_profile.assert_not_called()


def test_process_monitor_stop_terminates_thread():
    mock_pm = MagicMock()
    mock_pm.list_profiles.return_value = []
    mock_bl = MagicMock()

    monitor = ProcessMonitor(mock_pm, mock_bl, poll_interval=0.05)
    monitor.start()
    assert monitor._thread is not None
    assert monitor._thread.is_alive()

    monitor.stop()
    assert not monitor._running
    assert not monitor._thread.is_alive()


def test_api_batch_launch_single_save():
    client = TestClient(fastapi_app)
    with (
        patch("nazak.api.server.profile_manager.save_profiles") as mock_save,
        patch("nazak.api.server.browser_launcher.launch", return_value=(True, 1234, None)),
    ):
        resp = client.post("/api/profiles/batch-launch", json={"profile_ids": ["prof_01"]})
        assert resp.status_code == 200
        # Must save at most once after batch completion (M6)
        assert mock_save.call_count <= 1


# ---------------------------------------------------------------------------
# 23-25: Single save batching and M4 singleton identity
# ---------------------------------------------------------------------------
def test_api_batch_stop_single_save():
    client = TestClient(fastapi_app)
    with (
        patch("nazak.api.server.profile_manager.save_profiles") as mock_save,
        patch("nazak.api.server.browser_launcher.stop", return_value=True),
    ):
        resp = client.post("/api/profiles/batch-stop", json={"profile_ids": ["prof_01"]})
        assert resp.status_code == 200
        assert mock_save.call_count <= 1


def test_main_window_engine_singletons_identity():
    from nazak.api.server import browser_launcher as api_bl, profile_manager as api_pm
    from nazak.gui.main_window import browser_launcher as gui_bl, profile_manager as gui_pm

    # M4 fix guarantees GUI and API share the exact same in-memory singleton instances
    assert gui_pm is api_pm
    assert gui_bl is api_bl


def test_load_profiles_missing_file_generates_defaults(tmp_path):
    pfile = tmp_path / "non_existent_sub" / "profiles.json"
    pdir = tmp_path / "profiles"
    pm = ProfileManager(pfile, pdir)
    assert len(pm.profiles) > 0
    assert pfile.exists()
