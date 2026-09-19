"""Phase 6+7: cancel-cleanup sweep + dynamic ports + platform normalization."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from nazak.core import upload_queue as uq
from nazak.core.upload_queue import (
    UploadJob,
    UploadQueueManager,
    is_manual_action_error,
    normalize_upload_platform,
)


class _FakeLauncher:
    def __init__(self):
        self.profile_cdp_ports = {}
        self.stopped = []
        self.launched_ports = []
        self.active_processes = {}

    def launch(self, prof, cdp_port=None):
        pid = getattr(prof, "id", prof)
        self.profile_cdp_ports[pid] = cdp_port or 9300
        self.launched_ports.append(cdp_port)
        self.active_processes[pid] = True
        return True, 9999, None

    def stop(self, pid):
        self.stopped.append(pid)
        self.active_processes.pop(pid, None)

    def is_profile_running(self, pid):
        return pid in self.active_processes


@pytest.fixture()
def mgr():
    launcher = _FakeLauncher()
    m = UploadQueueManager(profile_manager=None, browser_launcher=launcher)
    return m


def test_get_free_port_returns_bindable_loopback_port():
    import socket as _socket

    from nazak.core.browser_launcher import get_free_port

    port = get_free_port()
    assert isinstance(port, int) and 1024 <= port <= 65535
    with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", port))


@pytest.mark.parametrize("platform", ["youtube_shorts", "instagram_reels", None, "bogus", "YOUTUBE_SHORTS"])
def test_batch_upload_allocates_dynamic_port(mgr, platform, monkeypatch):
    from pathlib import Path

    monkeypatch.setattr(uq, "get_free_port", lambda: 45678)
    prof = SimpleNamespace(id="p1", name="P1", status=None, pid=None)
    mgr.profile_manager = SimpleNamespace(get_profile=lambda pid: prof, update_profile=lambda p: None)
    mgr.uniquifier = SimpleNamespace(uniquify_video=lambda *a, **k: (True, Path("v.mp4"), None))

    async def fake_retry(job, task_name, upload_callable, **kwargs):
        return True, "http://x", None

    monkeypatch.setattr(mgr, "_retryable_upload", fake_retry)
    monkeypatch.setattr("nazak.core.upload_queue.format_video_metadata", lambda **k: {"title": "t", "description": "d"})

    import asyncio

    asyncio.run(mgr.run_batch_upload([prof.id], Path("v.mp4"), "t", "d", platform=platform or "youtube_shorts"))
    assert mgr.browser_launcher.launched_ports == [45678]
    assert mgr.browser_launcher.stopped == [prof.id]


def test_cancel_all_stops_launched_profiles(mgr):
    from nazak.core.upload_queue import UploadJob as _J

    for pid in ("p1", "p2", "p3"):
        mgr.jobs[pid] = _J(profile_id=pid, profile_name=pid, source_video="v.mp4")
        mgr.jobs[pid].status = "uploading"
    with patch.object(mgr.browser_launcher, "stop", wraps=mgr.browser_launcher.stop) as _s:
        mgr.cancel_all()
    assert mgr._cancel_requested is True
    for j in mgr.jobs.values():
        assert j.status == "canceled"
        assert j.progress_message == "Upload canceled by user"
    assert sorted(mgr.browser_launcher.stopped) == ["p1", "p2", "p3"]


def test_cancel_all_noop_without_launched():
    mgr = UploadQueueManager(profile_manager=None, browser_launcher=_FakeLauncher())
    mgr.cancel_all()
    assert mgr._cancel_requested is True
