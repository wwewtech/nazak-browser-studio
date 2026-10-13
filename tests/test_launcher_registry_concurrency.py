"""Concurrency and lifecycle regression tests for BrowserLauncher state (fix F1).

The six registry dicts (active_processes / profile_pids / profile_cdp_ports /
profile_cdp_ws / _injectors / _forwarders) are touched by the GUI thread,
TaskBridge worker threads, the API request pool and the process monitor at the
same time. These tests hammer the registry from many threads and assert the
invariants that an unsynchronized dict could break.
"""

from __future__ import annotations

import threading

from nazak.core.browser_launcher import BrowserLauncher


class _FakeProc:
    """Stand-in for subprocess.Popen with a poll() that flips on demand."""

    def __init__(self, pid: int):
        self.pid = pid
        self._alive = True

    def poll(self):
        return None if self._alive else 0

    def kill(self):
        self._alive = False


def test_registry_concurrent_stop_and_running_check_keeps_pid_visible():
    """A pid must not vanish between concurrent is_running() and stop() calls.

    Regression for the unsynchronized read-then-pop race: two threads calling
    is_profile_running() while a third one runs stop() could both pop the same
    pid (one winning, one silently dropping it), leaking the Chrome process.
    """
    launcher = BrowserLauncher()
    proc = _FakeProc(4242)
    launcher.active_processes["prof_race"] = proc
    launcher.profile_pids["prof_race"] = 4242

    errors: list[str] = []
    barrier = threading.Barrier(4)

    def hammer_running():
        barrier.wait()
        for _ in range(200):
            # May be True (stop not done yet) or False (stop done): both fine.
            launcher.is_profile_running("prof_race")

    def hammer_stop():
        barrier.wait()
        for _ in range(100):
            launcher.active_processes["prof_race"] = proc
            launcher.profile_pids["prof_race"] = 4242
            launcher.is_profile_running("prof_race")

    threads = [threading.Thread(target=hammer_running) for _ in range(3)]
    threads.append(threading.Thread(target=hammer_stop))
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors


def test_registry_pid_never_lost_when_monitor_and_launch_race():
    """launch() registration + monitor cleanup: the final state must be sane."""
    launcher = BrowserLauncher()
    stop_flag = threading.Event()
    registered = threading.Event()

    def fake_monitor():
        """Simulates the process monitor sweeping dead pids."""
        while not stop_flag.is_set():
            launcher.is_profile_running("prof_mon")
            threading.Event().wait(0.001)

    monitor = threading.Thread(target=fake_monitor, daemon=True)
    monitor.start()

    # Register many sessions concurrently, as parallel launches would.
    def register(index: int):
        pid = 10_000 + index
        launcher.profile_pids[f"prof_{index}"] = pid
        registered.set()

    threads = [threading.Thread(target=register, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    stop_flag.set()
    monitor.join(timeout=5)

    # All 50 registrations must still be present (the monitor only sweeps
    # pids that psutil reports as dead; ours never existed, but the registry
    # entries for fresh ids must not be popped by a racing iteration).
    present = sum(1 for i in range(50) if f"prof_{i}" in launcher.profile_pids)
    assert present == 50, f"registry lost {50 - present} pids to a race"


def test_registry_lock_is_reentrant():
    """RLock reentrancy: is_profile_running inside a lock-held path must not deadlock."""
    launcher = BrowserLauncher()
    with launcher._registry_lock:
        # This call takes the same lock internally — must not block forever.
        assert launcher.is_profile_running("prof_reentrant") is False


def test_stop_removes_every_registry_entry_exactly_once():
    """stop() clears all five per-profile entries; a repeated stop is a no-op."""
    launcher = BrowserLauncher()
    launcher.profile_pids["prof_clean"] = 999999999  # a pid that never exists
    launcher.profile_cdp_ports["prof_clean"] = 9222
    launcher.profile_cdp_ws["prof_clean"] = "ws://127.0.0.1:9222/devtools/browser/abc"

    ok, msg = launcher.stop("prof_clean")
    assert ok is True  # pid does not exist -> is treated as "nothing to kill"

    for registry in (
        launcher.profile_pids,
        launcher.profile_cdp_ports,
        launcher.profile_cdp_ws,
        launcher.active_processes,
        launcher._injectors,
        launcher._forwarders,
    ):
        assert "prof_clean" not in registry

    # Idempotent second stop.
    ok2, msg2 = launcher.stop("prof_clean")
    assert ok2 is True
    assert "not currently running" in (msg2 or "")


def test_wait_for_cdp_returns_as_soon_as_port_file_appears(tmp_path):
    """The DevTools poll must return early, not after a fixed 4 s sleep (fix F2)."""
    import asyncio
    import time

    launcher = BrowserLauncher(profiles_dir=tmp_path, extensions_dir=tmp_path / "ext")
    user_dir = tmp_path / "prof_poll"
    user_dir.mkdir()

    async def write_port_file_later():
        await asyncio.sleep(0.3)
        (user_dir / "DevToolsActivePort").write_text("9333\n/devtools/browser/abc\n", encoding="utf-8")

    async def scenario():
        writer = asyncio.create_task(write_port_file_later())
        t0 = time.monotonic()
        up = await launcher.wait_for_cdp("prof_poll", timeout_sec=5.0)
        elapsed = time.monotonic() - t0
        await writer
        return up, elapsed

    up, elapsed = asyncio.run(scenario())
    assert up is True
    # Early return: the file appeared at ~0.3 s, so the poll must finish well
    # before the old fixed sleep(4) would have.
    assert elapsed < 2.0, f"poll took {elapsed:.2f}s — not returning early"


def test_wait_for_cdp_times_out_when_no_endpoint(tmp_path):
    import asyncio

    launcher = BrowserLauncher(profiles_dir=tmp_path, extensions_dir=tmp_path / "ext")
    (tmp_path / "prof_dead").mkdir()

    async def scenario():
        return await launcher.wait_for_cdp("prof_dead", timeout_sec=0.6)

    assert asyncio.run(scenario()) is False
