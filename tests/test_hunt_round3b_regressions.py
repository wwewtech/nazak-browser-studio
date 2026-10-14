"""Regression tests for hunt round 3 (cross-process lost update + concurrency)."""

from __future__ import annotations

import threading
from pathlib import Path

from nazak.core.profile_manager import ProfileManager
from nazak.models.profile import BrowserProfile


def test_second_manager_writes_are_not_lost_on_save(tmp_path):
    """Hunt C-01: the GUI+CLI lost update.

    Two ProfileManager instances over one profiles.json are two processes'
    views. Instance A creates c1, instance B creates c2, then A creates c3:
    A's save used to clobber B's c2 (last writer wins). The backend now
    detects the foreign rewrite (mtime/size changed since our read) and
    merges the unknown ids before writing.
    """
    pfile, pdir = tmp_path / "p.json", tmp_path / "profiles"

    pm_a = ProfileManager(pfile, pdir)
    pm_a.create_profile(BrowserProfile(id="c1", name="One"))

    pm_b = ProfileManager(pfile, pdir)
    pm_b.create_profile(BrowserProfile(id="c2", name="Two"))

    pm_a.create_profile(BrowserProfile(id="c3", name="Three"))

    reloaded = ProfileManager(pfile, pdir)
    ids = {p.id for p in reloaded.list_profiles()}
    assert {"c1", "c2", "c3"} <= ids, f"lost update: c2 (or more) missing: {sorted(ids)}"


def test_delete_survives_after_foreign_write_merge(tmp_path):
    """The merge must not resurrect a profile deleted by the older process."""
    pfile, pdir = tmp_path / "p.json", tmp_path / "profiles"
    pm_a = ProfileManager(pfile, pdir)
    pm_a.create_profile(BrowserProfile(id="keep", name="Keep"))
    pm_a.create_profile(BrowserProfile(id="drop", name="Drop"))

    pm_b = ProfileManager(pfile, pdir)
    pm_b.create_profile(BrowserProfile(id="foreign", name="Foreign"))

    # A deletes 'drop' — this is the newest intent for that id.
    pm_a.delete_profile("drop")
    reloaded = ProfileManager(pfile, pdir)
    ids = {p.id for p in reloaded.list_profiles()}
    assert "drop" not in ids, "delete resurrected by the foreign merge"
    assert "foreign" in ids, "foreign write lost"
    assert "keep" in ids


def test_threaded_create_never_loses_profiles(tmp_path):
    """4 threads x 20 creates through one manager: nothing may be missing."""
    pfile, pdir = tmp_path / "p.json", tmp_path / "profiles"
    pm = ProfileManager(pfile, pdir)
    seed = len(pm.list_profiles())

    def writer(n: int):
        for i in range(20):
            pm.create_profile(BrowserProfile(id=f"t{n}_{i}", name=f"T{n}i{i}"))

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    final = ProfileManager(pfile, pdir)
    ids = {p.id for p in final.list_profiles()}
    expected = {f"t{n}_{i}" for n in range(4) for i in range(20)}
    missing = sorted(expected - ids)
    assert not missing, f"concurrent writes lost {len(missing)} profile(s): {missing[:5]}"
    assert len(ids) >= seed + 80
