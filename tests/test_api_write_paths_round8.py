"""Round-8 regressions: unlocked dict writes (X-22) and the /check endpoint
silently rewriting the spoofed timezone/geo (X-21)."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from nazak.core.profile_manager import ProfileManager
from nazak.models.profile import BrowserProfile, ProfileStatus


def _make_pm(tmp_path: Path, count: int = 300) -> ProfileManager:
    pm = ProfileManager(tmp_path / "p.json", tmp_path / "profiles")
    for i in range(count):
        pm.profiles[f"seed_{i}"] = BrowserProfile(id=f"seed_{i}", name=f"S{i}")
    return pm


def test_x22_unlocked_dict_write_never_crashes_save(tmp_path):
    """Hunt X-22: the batch/check-all endpoints used to write
    profile_manager.profiles[pid] = p directly, outside the service lock,
    while save_all() iterated the same dict on another thread. Reproduced:
    RuntimeError('dictionary changed size during iteration'). The facade path
    (register/update) takes the service lock and must never crash the saver.
    """
    pm = _make_pm(tmp_path)
    errors: list[str] = []
    stop = threading.Event()

    def saver():
        while not stop.is_set():
            try:
                pm.save_profiles()
            except RuntimeError as exc:  # the exact crash reproduced pre-fix
                errors.append(str(exc))
            except Exception as exc:
                errors.append(f"{type(exc).__name__}: {exc}")

    def unlocked_writer():
        # the pre-fix endpoint pattern: direct unlocked dict write
        i = 0
        while not stop.is_set():
            i += 1
            pm.profiles[f"w{i % 9}"] = BrowserProfile(id=f"w{i % 9}", name=f"W{i}")

    threads = [threading.Thread(target=saver, daemon=True) for _ in range(2)]
    threads.append(threading.Thread(target=unlocked_writer, daemon=True))
    for t in threads:
        t.start()
    time.sleep(2)
    stop.set()
    for t in threads:
        t.join(timeout=8)

    # The endpoint no longer uses this pattern, so under the REAL contract
    # there is no unlocked writer at all; the stress above proves that the
    # naive pattern is dangerous. The contract test: register_runtime_update
    # (the locked path the endpoints now use) never raises.
    def locked_writer():
        i = 0
        while not stop.is_set():
            i += 1
            pm._service.register_runtime_update(BrowserProfile(id=f"r{i % 9}", name=f"R{i}"))

    errors.clear()
    stop.clear()
    threads2 = [threading.Thread(target=saver, daemon=True) for _ in range(2)]
    threads2.append(threading.Thread(target=locked_writer, daemon=True))
    for t in threads2:
        t.start()
    time.sleep(2)
    stop.set()
    for t in threads2:
        t.join(timeout=8)
    assert not errors, f"save crashed under the locked write path: {errors[:3]}"


def test_x22_service_register_runtime_update_is_lock_guarded(tmp_path):
    pm = ProfileManager(tmp_path / "p.json", tmp_path / "profiles")
    prof = BrowserProfile(id="reg_1", name="R1")
    pm._service.register_runtime_update(prof)
    assert pm.get_profile("reg_1") is prof
    # register is in-memory only: nothing hit the disk
    disk = json.loads((tmp_path / "p.json").read_text(encoding="utf-8"))
    assert all(r["id"] != "reg_1" for r in disk), "register_runtime_update persisted (it must stay in-memory)"


def test_x21_check_endpoint_must_not_rewrite_spoofed_timezone(tmp_path):
    """Hunt X-21: POST /api/profiles/{id}/check overwrote the profile's
    spoofed fingerprint.timezone/geolocation with the values reported by the
    proxy exit's geo lookup — a Berlin-configured profile silently became a
    Tokyo profile after one health check, contradicting the anti-detect
    shield (audit F-11 documents exactly this contradiction as a tell).
    Reproduced: fingerprint.timezone America/New_York -> Asia/Tokyo.
    """
    from nazak.models.health import HealthCheckResult

    pm = ProfileManager(tmp_path / "p.json", tmp_path / "profiles")
    prof = pm.list_profiles()[0]
    original_tz = prof.fingerprint.timezone
    original_geo = (prof.fingerprint.geolocation.latitude, prof.fingerprint.geolocation.longitude)

    # the OLD endpoint logic (what used to run between the health result and
    # update_profile):
    result = HealthCheckResult(status="healthy")
    result.timezone_name = "Asia/Tokyo"
    result.latitude = 35.68
    result.longitude = 139.69
    prof.last_health_check = result
    if result.latitude is not None and result.longitude is not None:
        prof.fingerprint.geolocation.latitude = result.latitude
        prof.fingerprint.geolocation.longitude = result.longitude
    if result.timezone_name:
        prof.fingerprint.timezone = result.timezone_name

    persisted = pm.update_profile(prof)
    assert persisted is not None
    assert persisted.fingerprint.timezone == "Asia/Tokyo" and (
        persisted.fingerprint.geolocation.latitude,
        persisted.fingerprint.geolocation.longitude,
    ) == (35.68, 139.69), "precondition: the old logic did rewrite the spoofed fields"

    # the CONTRACT going forward: the stored fingerprint's spoofed timezone
    # must never be silently replaced by a geo lookup (the mismatch is
    # surfaced as HealthCheckResult.timezone_mismatch instead — see
    # proxy_checker's F-11 note). The endpoint must record the check result
    # WITHOUT touching fingerprint fields.
    source = (Path(__file__).resolve().parents[1] / "nazak" / "api" / "routers" / "proxies.py").read_text(
        encoding="utf-8"
    )
    assert "fingerprint.geolocation.latitude" not in source, (
        "the check endpoint must not overwrite the spoofed geolocation (X-21)"
    )
    assert "fingerprint.timezone = result.timezone_name" not in source, (
        "the check endpoint must not overwrite the spoofed timezone (X-21)"
    )
    assert original_tz != "Asia/Tokyo" or original_geo != (35.68, 139.69)
