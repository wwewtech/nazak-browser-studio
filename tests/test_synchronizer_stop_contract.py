"""Synchronizer stop/restart lifecycle contracts (fix F8 guard).

stop_session() must join the pump thread: the pump owns thread-affine Playwright
objects, and a restart that does not wait for the old pump would leave two pumps
mirroring gestures (double events) or cross-thread Playwright calls.
"""

from __future__ import annotations

import threading
import time
from unittest.mock import patch

from nazak.core.synchronizer import SynchronizerManager, SynchronizerSession


class _FakeLauncher:
    pass


def test_stop_session_joins_the_pump_thread():
    mgr = SynchronizerManager(_FakeLauncher())

    pump_alive = threading.Event()
    pump_can_finish = threading.Event()

    def fake_pump(session):
        session.active = True
        pump_alive.set()
        # Simulate a pump mid-work: it only exits once told to.
        while session.active and not pump_can_finish.is_set():
            time.sleep(0.01)
        pump_alive.clear()

    # Wire a fake pump thread the way start_session would.
    session = SynchronizerSession(master_profile_id="m", worker_profile_ids=["w"])
    session.active = True
    mgr.current_session = session
    mgr._pump_thread = threading.Thread(target=fake_pump, args=(session,), daemon=True, name="NazakSyncPump")
    mgr._pump_thread.start()
    assert pump_alive.wait(timeout=5)

    returned = mgr.stop_session()
    assert returned is session
    assert mgr.current_session is None
    # The pump observed active=False and the join returned before the test ends.
    pump_can_finish.set()
    assert mgr._pump_thread is None


def test_restart_waits_for_previous_pump_before_spawning_a_new_one():
    mgr = SynchronizerManager(_FakeLauncher())
    started_sessions = []

    first_active = threading.Event()

    def slow_pump(session):
        session.active = True
        first_active.set()
        for _ in range(200):  # up to ~2s, exiting early once inactive
            if not session.active:
                break
            time.sleep(0.01)

    def fake_start_thread(session):
        started_sessions.append(session)
        t = threading.Thread(target=slow_pump, args=(session,), daemon=True)
        t.start()
        return t

    with (
        patch.object(mgr, "_install_sync_client"),
        patch.object(SynchronizerManager, "_mirror_pump", side_effect=slow_pump, create=True),
    ):
        s1 = mgr.start_session("m1", ["w1"])
        assert first_active.wait(timeout=5)
        assert mgr._pump_thread is not None
        first_pump = mgr._pump_thread

        s2 = mgr.start_session("m2", ["w2"])  # restart must stop the old pump
        assert s1.active is False, "the first session must be deactivated by the restart"
        assert mgr._pump_thread is not first_pump, "a new pump must be spawned"
        # Give the first pump a moment to observe inactive and exit.
        time.sleep(0.05)
        mgr.stop_session()
