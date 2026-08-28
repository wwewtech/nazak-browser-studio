import time

from nazak.core.process_monitor import ProcessMonitor
from nazak.models.profile import BrowserProfile, ProfileStatus


class MockProfileManager:
    def __init__(self, profiles):
        self.profiles = profiles

    def list_profiles(self):
        return self.profiles

    def update_profile(self, p):
        for i, item in enumerate(self.profiles):
            if item.id == p.id:
                self.profiles[i] = p


class MockBrowserLauncher:
    def __init__(self, running_map):
        self.running_map = running_map

    def is_profile_running(self, profile_id):
        return self.running_map.get(profile_id, False)


def test_process_monitor_detects_exit():
    p1 = BrowserProfile(id="p1", name="Profile 1", status=ProfileStatus.RUNNING, pid=1234)
    pm = MockProfileManager([p1])
    bl = MockBrowserLauncher({"p1": False})  # Process has exited

    events = []

    def callback(pid, status):
        events.append((pid, status))

    monitor = ProcessMonitor(pm, bl, poll_interval=0.1)
    monitor.register_callback(callback)

    monitor.start()
    time.sleep(0.3)
    monitor.stop()

    assert p1.status == ProfileStatus.STOPPED
    assert ("p1", ProfileStatus.STOPPED) in events
