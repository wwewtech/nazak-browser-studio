"""
Background process watchdog that tracks active Chrome instances and lifecycle state.
"""

import logging
import threading
import time
from collections.abc import Callable

from ..models.profile import ProfileStatus

logger = logging.getLogger(__name__)


class ProcessMonitor:
    """
    Watches active browser processes and automatically detects when a user closes a window.
    """

    def __init__(self, profile_manager, browser_launcher, poll_interval: float = 1.0):
        self.profile_manager = profile_manager
        self.browser_launcher = browser_launcher
        self.poll_interval = poll_interval
        self._running = False
        self._thread: threading.Thread | None = None
        self._callbacks: list[Callable[[str, ProfileStatus], None]] = []

    def register_callback(self, cb: Callable[[str, ProfileStatus], None]):
        """Registers a listener for profile state transitions."""
        self._callbacks.append(cb)

    def start(self):
        """Starts the background monitoring loop."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True, name="NazakProcessMonitor")
        self._thread.start()

    def stop(self):
        """Stops the monitoring thread."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def _monitor_loop(self):
        """Main loop checking process existence."""
        while self._running:
            try:
                profiles = self.profile_manager.list_profiles()
                for p in profiles:
                    if p.status == ProfileStatus.RUNNING:
                        # Check if process is still alive
                        alive = self.browser_launcher.is_profile_running(p.id)
                        if not alive:
                            # Hunt R-01 (check-then-act race): a relaunch that
                            # landed between our check and a full-object update
                            # got clobbered — the profile said STOPPED while its
                            # fresh browser was alive (the GUI could double-launch
                            # the same user-data-dir). The status transition is a
                            # single atomic compare-and-set now: RUNNING->STOPPED
                            # only if it is still RUNNING when we take the lock.
                            svc = getattr(self.profile_manager, "_service", None)
                            transition_callable = (
                                getattr(svc, "transition_status_if", None) if svc is not None else None
                            )
                            done = False
                            if callable(transition_callable):
                                # Pin the CAS to the pid we OBSERVED as dead: a
                                # relaunch that already installed a new pid must
                                # never be marked stopped by this observation.
                                done = (
                                    transition_callable(
                                        p.id, ProfileStatus.RUNNING, ProfileStatus.STOPPED, expected_pid=p.pid
                                    )
                                    is not None
                                )
                            if not done and hasattr(self.profile_manager, "get_profile"):
                                # Backend without the CAS method: guarded
                                # full-object update (pre-R-01 behaviour).
                                curr = self.profile_manager.get_profile(p.id)
                                if not curr or curr.status != ProfileStatus.RUNNING:
                                    continue
                                curr.status = ProfileStatus.STOPPED
                                curr.pid = None
                                self.profile_manager.update_profile(curr)
                            elif not done:
                                # Minimal manager contract (tests, embedders):
                                # no CAS and no get_profile — mutate the snapshot
                                # we are already holding and push it back.
                                p.status = ProfileStatus.STOPPED
                                p.pid = None
                                self.profile_manager.update_profile(p)
                            # Notify listeners
                            for cb in self._callbacks:
                                try:
                                    cb(p.id, ProfileStatus.STOPPED)
                                except Exception:
                                    pass
            except Exception as exc:
                # Audit R3: a silent `pass` concealed a total breakdown of the monitor.
                logger.debug("process monitor iteration failed: %s", exc)
            time.sleep(self.poll_interval)
