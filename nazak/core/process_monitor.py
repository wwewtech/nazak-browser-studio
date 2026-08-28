"""
Background process watchdog that tracks active Chrome instances and lifecycle state.
"""

import threading
import time
from collections.abc import Callable

from ..models.profile import ProfileStatus


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
                            # User closed browser window
                            p.status = ProfileStatus.STOPPED
                            p.pid = None
                            self.profile_manager.update_profile(p)
                            # Notify listeners
                            for cb in self._callbacks:
                                try:
                                    cb(p.id, ProfileStatus.STOPPED)
                                except Exception:
                                    pass
            except Exception:
                pass
            time.sleep(self.poll_interval)
