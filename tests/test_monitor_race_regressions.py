"""Regression tests for hunt round 4: process-monitor status race (R-01).

The monitor's check-then-act window: it observes a RUNNING profile whose
process died, and between its check and its full-object update a relaunch
lands (new pid, alive process). The stale update used to clobber the fresh
RUNNING state — the profile said STOPPED while its browser was alive, and
the GUI could double-launch the same user-data-dir.

Fix: transition_status_if — an atomic compare-and-set pinned to the pid the
monitor OBSERVED as dead. A relaunch with a new pid must never be marked
stopped by a stale death observation.
"""

from __future__ import annotations

import time
import types
from pathlib import Path

from nazak.core.process_monitor import ProcessMonitor
from nazak.core.profile_manager import ProfileManager
from nazak.models.profile import BrowserProfile, ProfileStatus, ProfileStatus as PS


def _pm_with_running(tmp_path: Path, pid: int = 111) -> ProfileManager:
    pm = ProfileManager(tmp_path / "p.json", tmp_path / "profiles")
    prof = pm.create_profile(BrowserProfile(id="race", name="Race"))
    prof.status = ProfileStatus.RUNNING
    prof.pid = pid
    pm.update_profile(prof)
    return pm


def test_cas_transitions_running_to_stopped_atomically(tmp_path):
    pm = _pm_with_running(tmp_path)
    svc = pm._service
    res = svc.transition_status_if("race", ProfileStatus.RUNNING, ProfileStatus.STOPPED, expected_pid=111)
    assert res is not None and res.status == ProfileStatus.STOPPED and res.pid is None
    final = pm.get_profile("race")
    assert final.status == ProfileStatus.STOPPED and final.pid is None


def test_cas_no_ops_when_pid_changed_underneath(tmp_path):
    """R-01 core: a relaunch installed a new pid — the stale observation dies."""
    pm = _pm_with_running(tmp_path, pid=111)
    svc = pm._service
    # The relaunch lands first (fresh pid 222).
    stored = svc.profiles["race"]
    stored.pid = 222
    # The monitor's observation (pid 111 dead) must NOT stop the fresh launch.
    res = svc.transition_status_if("race", ProfileStatus.RUNNING, ProfileStatus.STOPPED, expected_pid=111)
    assert res is None, "stale death observation clobbered a fresh relaunch"
    final = pm.get_profile("race")
    assert final.status == ProfileStatus.RUNNING and final.pid == 222


def test_cas_no_ops_when_status_already_changed(tmp_path):
    pm = _pm_with_running(tmp_path)
    svc = pm._service
    stored = svc.profiles["race"]
    stored.status = ProfileStatus.STOPPED
    res = svc.transition_status_if("race", ProfileStatus.RUNNING, ProfileStatus.STOPPED, expected_pid=111)
    assert res is None
    assert pm.get_profile("race").status == ProfileStatus.STOPPED


def test_cas_unknown_profile_returns_none(tmp_path):
    pm = _pm_with_running(tmp_path)
    svc = pm._service
    assert svc.transition_status_if("ghost", PS.RUNNING, PS.STOPPED, expected_pid=1) is None
    assert svc.transition_status_if("bad id!", PS.RUNNING, PS.STOPPED) is None


def test_monitor_does_not_clobber_a_relaunch(tmp_path):
    """End-to-end: the monitor marks a dead profile stopped, but a profile
    whose pid changed under it (relaunch) stays RUNNING."""
    pm = _pm_with_running(tmp_path, pid=111)
    alive = {"race": False}
    launcher = types.SimpleNamespace(is_profile_running=lambda pid: alive.get(pid, False))
    monitor = ProcessMonitor(pm, launcher, poll_interval=0.01)
    events: list[tuple[str, ProfileStatus]] = []
    monitor.register_callback(lambda pid, st: events.append((pid, st)))
    monitor.start()
    try:
        # Death observed while pid is 111: normal transition must happen.
        deadline = time.time() + 2.0
        while time.time() < deadline and not events:
            time.sleep(0.002)
        assert events, "monitor never reported the death"
        assert pm.get_profile("race").status == ProfileStatus.STOPPED
    finally:
        monitor.stop()

    # Now relaunch with a new pid and let a STALE observation race in: the
    # monitor already saw pid 111 dead before; with the pid-pinned CAS it
    # cannot touch the pid-222 launch.
    prof = pm.get_profile("race")
    prof.status = ProfileStatus.RUNNING
    prof.pid = 222
    pm.update_profile(prof)
    res = pm._service.transition_status_if("race", ProfileStatus.RUNNING, ProfileStatus.STOPPED, expected_pid=111)
    assert res is None, "stale pid observation clobbered the relaunch"
    final = pm.get_profile("race")
    assert final.status == ProfileStatus.RUNNING and final.pid == 222


def test_monitor_reports_death_when_pid_matches(tmp_path):
    """The happy path still works: dead pid == observed pid -> STOPPED + event."""
    pm = _pm_with_running(tmp_path, pid=111)
    alive = {"race": False}
    launcher = types.SimpleNamespace(is_profile_running=lambda pid: alive.get(pid, False))
    monitor = ProcessMonitor(pm, launcher, poll_interval=0.01)
    events: list[tuple[str, ProfileStatus]] = []
    monitor.register_callback(lambda pid, st: events.append((pid, st)))
    monitor.start()
    try:
        deadline = time.time() + 2.0
        while time.time() < deadline and not events:
            time.sleep(0.002)
        assert events == [("race", ProfileStatus.STOPPED)]
        final = pm.get_profile("race")
        assert final.status == ProfileStatus.STOPPED and final.pid is None
    finally:
        monitor.stop()
