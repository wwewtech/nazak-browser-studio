"""Deep runtime/CLI plumbing probes — a bug hunt, not a re-run of the P0 suites.

Seams that the existing suites do not exercise (see ``test_p0_task_bridge.py``,
``test_upload_queue_cdp_and_cancel.py``, ``test_round3_publish_fixes.py``,
``test_round3_cli_fixes.py``, ``test_round3b_cli_background.py`` and
``test_cli_agent_comfort.py`` for the cases deliberately *not* duplicated here):

* ``nazak.gui.task_bridge``: cancel before start / twice / after finish, error +
  busy-guard release, progress ordering, cancel at the next progress boundary.
* ``nazak.gui.tasks``: cooperative cancel and progress ordering.
* ``nazak.core.upload_queue``: retry policy, batch-pause clamp, ``finally`` sweep.
* ``nazak.core.process_monitor``: transition, notification and lifecycle edges.
* ``nazak.config``: frozen paths, ``ensure_data_dirs`` idempotency, chrome discovery.
* ``nazak.core.video_uniquifier``: ffmpeg lookup and injection-safe argv construction.
* ``nazak.core.extension_generator``: generated JSON/JS validity, credential escaping.
* ``nazak.core.warmup_engine``: plan bounds, URL encoding, ``_PageSession``, batch run.
* ``nazak.cli_cmds.common``: ``@file`` handling, ``confirm`` contract, ``--out`` guard,
  helper contracts and the CLI exit-code surface (``sys.argv`` + ``run_cli`` pattern).

Tests marked ``xfail(strict=False)`` assert the CORRECT behaviour and document a real
product bug found while writing them; the reason string carries the exact repro.
"""

from __future__ import annotations

import asyncio
import contextlib
import glob
import importlib.util
import json
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import time
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from nazak import cli
from nazak.cli_cmds import common as cli_common
from nazak.cli_cmds.common import ApiError, GlobalOptions, UsageError
from nazak.core import upload_queue as uq, video_uniquifier as vu, warmup_engine as warmup
from nazak.core.process_monitor import ProcessMonitor
from nazak.core.publish_status import publish_uncertain
from nazak.core.upload_queue import MAX_BATCH_DELAY_SECONDS, UploadQueueManager
from nazak.gui.task_bridge import TaskBridge, TaskCanceled, TaskHandle, run_task_inline
from nazak.models.profile import BrowserProfile, ProfileStatus

# --------------------------------------------------------------------------- helpers


def _run_cli(argv: list[str]) -> tuple[int, str, str]:
    """Same seam as ``test_cli_agent_comfort``: argv swap + captured streams + exit code."""
    old = sys.argv
    sys.argv = ["nazak", *argv]
    try:
        out, err = StringIO(), StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.run_cli()
        return int(code), out.getvalue(), err.getvalue()
    finally:
        sys.argv = old


def _run_cli_json(argv: list[str]) -> tuple[int, dict]:
    code, out, _ = _run_cli([*argv, "--json"])
    return code, json.loads(out)


def _wait_until(predicate, timeout: float = 2.0) -> bool:
    """Bounded poll (10 ms steps) — never a long fixed sleep."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return bool(predicate())


def _parse_query(url: str) -> dict:
    return parse_qs(urlparse(url).query)


class _RecordingSignal:
    """Instance-level stand-in for a Qt signal: records payloads, keeps the order."""

    def __init__(self) -> None:
        self.payloads: list[tuple] = []

    def emit(self, *args) -> None:
        self.payloads.append(args)

    @property
    def count(self) -> int:
        return len(self.payloads)

    def connect(self, *_a, **_k) -> None:  # pragma: no cover - Qt signature compatibility
        pass


class _FakeStdin:
    def __init__(self, tty: bool) -> None:
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty

    def read(self) -> str:
        return ""


class _FakeLauncher:
    def __init__(self, launch_ok: bool = True) -> None:
        self.stopped: list[str] = []
        self.launch_calls: list[tuple] = []
        self.launch_ok = launch_ok

    def launch(self, prof, custom_url=None, cdp_port=None):
        self.launch_calls.append((getattr(prof, "id", prof), custom_url, cdp_port))
        return (self.launch_ok, 4242, None if self.launch_ok else "launch refused")

    def stop(self, profile_id):
        self.stopped.append(profile_id)
        return True, None

    def is_profile_running(self, _profile_id) -> bool:
        return False

    async def wait_for_cdp(self, _profile_id, timeout_sec=6.0):
        return True


class _FakeProfileManager:
    """Profile manager double shared by the queue and process-monitor probes."""

    def __init__(self, profiles, fail_update_after: int | None = None) -> None:
        self.profiles = {p.id: p for p in profiles}
        self.updates = 0
        self.fail_update_after = fail_update_after

    def list_profiles(self):
        return list(self.profiles.values())

    def get_profile(self, profile_id):
        return self.profiles.get(profile_id)

    def update_profile(self, profile):
        self.updates += 1
        if self.fail_update_after is not None and self.updates > self.fail_update_after:
            raise RuntimeError("update exploded")
        self.profiles[profile.id] = profile
        return profile


def _uploader_factory(results, on_call=None):
    """Uploader double: returns ``results`` in order (the last entry repeats)."""
    state = {"calls": 0}

    class _Uploader:
        def __init__(self, *_a, **_k) -> None:
            pass

        async def upload_shorts(self, **_kwargs):
            index = state["calls"]
            state["calls"] += 1
            if on_call is not None:
                on_call(index)
            return results[min(index, len(results) - 1)]

        async def upload_reel(self, **_kwargs):
            return await self.upload_shorts(**_kwargs)

    _Uploader.state = state
    return _Uploader


class _FakeUniquifier:
    def __init__(self, *_a, **_k) -> None:
        pass

    def uniquify_video(self, *_a, **_k):
        return True, Path("out.mp4"), None


def _make_queue(profile_ids, **manager_kwargs):
    profiles = [BrowserProfile(id=pid, name=pid.upper()) for pid in profile_ids]
    launcher = _FakeLauncher()
    manager = UploadQueueManager(_FakeProfileManager(profiles, **manager_kwargs), launcher)
    manager.uniquifier = _FakeUniquifier()
    return manager, launcher


# --------------------------------------------------------------------------- task bridge


def test_task_handle_cancel_transitions_and_late_cancel():
    handle = TaskHandle(name="probe")
    assert handle.is_cancelled is False
    handle.cancel()
    handle.cancel()  # idempotent: a second cancel is a no-op
    assert handle.is_cancelled is True
    assert TaskHandle(name="probe").is_cancelled is False, "cancel() leaked into a fresh handle"

    # cancel before start: there is no handle yet, so the call must be a silent no-op
    idle = TaskBridge(name="idle")
    idle.cancel()
    assert idle.wait(timeout_ms=1) is True

    seen = {}

    def task(handle=None, progress=None):
        seen["cancelled"] = handle.is_cancelled
        return "payload"

    idle.submit(task)
    assert idle.wait(timeout_ms=5_000) is True
    assert seen["cancelled"] is False, "a cancel issued before submit() poisoned the next task"
    assert idle._last_result == "payload"

    # cancel after finish: must not clobber the recorded result
    idle.cancel()
    assert idle._last_result == "payload"
    assert idle._last_error is None
    assert idle.is_running() is False


def test_task_bridge_error_releases_busy_guard_and_preserves_message():
    bridge = TaskBridge(name="errors")
    errors = _RecordingSignal()
    bridge.error = errors

    def boom(handle=None, progress=None):
        raise ValueError("kaboom-42")

    handle = bridge.submit(boom)
    assert bridge.wait(timeout_ms=5_000) is True
    assert bridge._last_result is None
    assert bridge._last_error == "kaboom-42"
    assert errors.payloads == [("kaboom-42",)]
    assert handle.is_cancelled is False
    assert bridge.is_running() is False

    # busy guard released after an error: the next submit must not raise RuntimeError
    bridge.submit(lambda handle=None, progress=None: "second")
    assert bridge.wait(timeout_ms=5_000) is True
    assert bridge._last_result == "second"
    assert bridge._last_error is None

    # waiting with a timeout on a finished task is an immediate True
    assert bridge.wait(timeout_ms=1) is True
    assert TaskBridge(name="fresh").wait(timeout_ms=1) is True  # never submitted

    # run_task_inline keeps the exception TYPE and the message (the bridge only sees str())
    class CustomError(RuntimeError):
        pass

    def raising_sync():
        raise CustomError("typed-message")

    with pytest.raises(CustomError, match="typed-message"):
        run_task_inline(raising_sync, TaskHandle(name="t"), lambda *_a, **_k: None)

    async def raising_async():
        raise KeyError("async-key")

    with pytest.raises(KeyError, match="async-key"):
        run_task_inline(raising_async, TaskHandle(name="t2"), lambda *_a, **_k: None)


def test_task_bridge_progress_order_and_cancel_at_progress_boundary():
    bridge = TaskBridge(name="progress")
    progress, cancelled = _RecordingSignal(), _RecordingSignal()
    bridge.progress = progress
    bridge.cancelled = cancelled

    def task(handle=None, progress=None):
        progress("step-1")
        progress("step-2")
        return {"ok": True}

    bridge.submit(task)
    assert bridge.wait(timeout_ms=5_000) is True
    assert progress.payloads == [("step-1",), ("step-2",)], "progress payloads lost or reordered"
    assert bridge._last_result == {"ok": True}
    assert cancelled.count == 0

    # a cancel must be honoured at the next progress boundary: the task is aborted,
    # not reported as a success, and no error is fabricated
    mid = TaskBridge(name="mid")
    mid_progress, mid_cancelled = _RecordingSignal(), _RecordingSignal()
    mid.progress = mid_progress
    mid.cancelled = mid_cancelled
    reached: list[str] = []

    def cancellable(handle=None, progress=None):
        mid.cancel()
        progress("first")
        reached.append("after-progress")
        return "must-not-be-recorded"

    mid_handle = mid.submit(cancellable)
    assert mid.wait(timeout_ms=5_000) is True
    assert mid_progress.payloads == [("first",)]
    assert mid_cancelled.count == 1
    assert reached == [], "the task kept running after being cancelled"
    assert mid._last_result is None
    assert mid._last_error is None
    assert mid_handle.is_cancelled is True


# --------------------------------------------------------------------------- gui tasks


def test_tasks_run_autopost_batch_progress_order_and_cancel_before_start(monkeypatch, tmp_path):
    monkeypatch.setattr("nazak.core.video_uniquifier.VideoUniquifier", _FakeUniquifier)
    monkeypatch.setattr("nazak.core.youtube_uploader.YouTubeUploader", _uploader_factory([(True, "http://vid", None)]))
    monkeypatch.setattr("nazak.core.browser_launcher.get_free_port", lambda: 9400)
    monkeypatch.setattr("nazak.core.spintax.format_video_metadata", lambda **_k: {"title": "T", "description": "D"})
    slept: list[float] = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    import nazak.gui.tasks as gui_tasks

    pm = _FakeProfileManager([BrowserProfile(id=pid, name=pid.upper()) for pid in ("a", "b")])
    launcher = _FakeLauncher()
    events: list[tuple] = []

    result = gui_tasks.run_autopost_batch(
        pm, launcher, ["a", "b"], tmp_path / "in.mp4", "t", "d", progress=events.append
    )
    assert result == [
        {"profile_id": "a", "status": "published", "url": "http://vid"},
        {"profile_id": "b", "status": "published", "url": "http://vid"},
    ]
    assert [e[1] for e in events] == ["uniqueizing", "launching", "uploading", "published"] * 2
    assert [e[0] for e in events] == ["a"] * 4 + ["b"] * 4
    assert launcher.stopped == ["a", "b"], "the browser of a finished profile was left running"
    assert all(p.status is ProfileStatus.STOPPED and p.pid is None for p in pm.profiles.values())
    # The fixed 4 s post-launch sleep is gone (replaced by the DevTools poll in
    # _FakeLauncher.wait_for_cdp); the inter-profile settle pause remains.
    assert 3 in slept, "the inter-profile settle pause disappeared"
    assert 4 not in slept, "the fixed post-launch sleep(4) must be gone (poll instead)"

    # a cancel that arrives before the first profile must stop the batch at once
    cancelled_handle = TaskHandle(name="autopost")
    cancelled_handle.cancel()
    idle_launcher = _FakeLauncher()
    idle_events: list[tuple] = []
    assert (
        gui_tasks.run_autopost_batch(
            pm,
            idle_launcher,
            ["a"],
            tmp_path / "in.mp4",
            "t",
            "d",
            handle=cancelled_handle,
            progress=idle_events.append,
        )
        == []
    )
    assert idle_launcher.launch_calls == [] and idle_events == []

    # the same contract for the other two cooperative-cancel entry points
    with pytest.raises(TaskCanceled):
        gui_tasks.check_all_proxies(
            [SimpleNamespace(id="a", name="A", proxy=None)],
            tmp_path,
            handle=cancelled_handle,
            progress=lambda _payload: None,
        )

    scenario = warmup.WarmupScenario(
        id="deep_cancel", name="Deep cancel", steps=[warmup.ScenarioStep("dwell", {"min_sec": 0.01, "max_sec": 0.02})]
    )
    warmup_pm = SimpleNamespace(get_profile=lambda pid: SimpleNamespace(id=pid, name=pid.upper()))
    warmup_launcher = SimpleNamespace(
        is_profile_running=lambda _pid: True, get_cdp_info=lambda _pid: None, stop=lambda _pid: None
    )
    warmup_handle = TaskHandle(name="warmup")
    warmup_events: list[tuple] = []

    def cancel_on_progress(payload):
        warmup_events.append(payload)
        warmup_handle.cancel()

    with pytest.raises(TaskCanceled):
        gui_tasks.run_warmup_scenario(
            warmup_pm, warmup_launcher, scenario, "w1", handle=warmup_handle, progress=cancel_on_progress
        )
    assert warmup_events and warmup_events[0][0] == "w1"


# --------------------------------------------------------------------------- run_task_inline


def test_run_task_inline_never_reruns_task_after_body_typeerror():
    calls: list[int] = []

    def task(a, handle=None, progress=None):
        calls.append(a)
        raise TypeError("boom from inside the task body")

    with pytest.raises(TypeError):
        run_task_inline(task, TaskHandle(name="t"), lambda *_a, **_k: None, 1)
    assert calls == [1], f"task body executed {len(calls)} times"

    # control: any other exception type is propagated after a single execution
    value_calls: list[int] = []

    def other(a, handle=None, progress=None):
        value_calls.append(a)
        raise ValueError("x")

    with pytest.raises(ValueError):
        run_task_inline(other, TaskHandle(name="t2"), lambda *_a, **_k: None, 1)
    assert value_calls == [1]


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_run_task_inline_propagates_async_error_inside_running_loop():
    async def failing():
        raise RuntimeError("async-must-propagate")

    async def driver():
        return run_task_inline(failing, TaskHandle(name="t"), lambda *_a, **_k: None)

    with pytest.raises(RuntimeError, match="async-must-propagate"):
        asyncio.run(driver())


# --------------------------------------------------------------------------- upload queue


def test_retryable_upload_policy_and_backoff_clamp(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    manager = UploadQueueManager(None, _FakeLauncher())

    async def scenario():
        manual_calls: list[int] = []

        async def manual():
            manual_calls.append(1)
            return (False, None, "captcha required")

        out = await manager._retryable_upload(SimpleNamespace(progress_message=""), "Upload", manual)
        assert out == (False, None, "captcha required")
        assert len(manual_calls) == 1, "a manual-action error was retried"

        uncertain_calls: list[int] = []

        async def uncertain():
            uncertain_calls.append(1)
            return (False, None, publish_uncertain("Share was clicked"))

        out = await manager._retryable_upload(SimpleNamespace(progress_message=""), "Upload", uncertain)
        assert out[2].startswith("publish-uncertain")
        assert len(uncertain_calls) == 1, "an unresolved publication was retried (duplicate post)"

        retry_calls: list[int] = []

        async def flaky():
            retry_calls.append(1)
            return (False, None, "network timeout")

        out = await manager._retryable_upload(
            SimpleNamespace(progress_message=""), "Upload", flaky, retries=3, base_delay=2.0, max_delay=8.0
        )
        assert out == (False, None, "network timeout")
        assert len(retry_calls) == 4, f"expected 1+3 attempts, got {len(retry_calls)}"
        assert len(sleeps) == 3
        assert sleeps == sorted(sleeps), f"backoff is not monotonic: {sleeps}"
        assert max(sleeps) <= 8.0 + 1.25, f"backoff ignored max_delay: {sleeps}"

        exploding_calls: list[int] = []

        async def exploding():
            exploding_calls.append(1)
            raise RuntimeError("socket vanished")

        out = await manager._retryable_upload(SimpleNamespace(progress_message=""), "Upload", exploding)
        assert out[0] is False and "socket vanished" in out[2]
        assert len(exploding_calls) == 1, "a non-retryable exception was retried"

        cancel_manager = UploadQueueManager(None, _FakeLauncher())
        cancel_calls: list[int] = []

        async def cancelling():
            cancel_calls.append(1)
            cancel_manager._cancel_requested = True
            return (False, None, "network timeout")

        out = await cancel_manager._retryable_upload(SimpleNamespace(progress_message=""), "Upload", cancelling)
        assert out == (False, None, "Upload canceled by user")
        assert len(cancel_calls) == 1, "the retry loop kept uploading after a cancel"

    asyncio.run(scenario())


def test_batch_pause_is_clamped_and_cancel_all_is_idempotent(monkeypatch, tmp_path):
    monkeypatch.setattr("nazak.core.youtube_uploader.YouTubeUploader", _uploader_factory([(True, "http://vid", None)]))
    monkeypatch.setattr(uq, "get_free_port", lambda: 45678)
    monkeypatch.setattr(uq, "format_video_metadata", lambda **_k: {"title": "t", "description": "d"})
    monkeypatch.setattr("nazak.core.upload_queue.random.randint", lambda _a, b: b)
    slept: list[float] = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    manager, _launcher = _make_queue(("p1", "p2"))
    asyncio.run(
        manager.run_batch_upload(
            ["p1", "p2"], tmp_path / "in.mp4", "t", "d", delay_between_accounts_sec=10**9, platform="youtube_shorts"
        )
    )
    pauses = [s for s in slept if s > 60]
    assert pauses, f"no account pause was taken at all: {slept}"
    # jitter is added after the clamp, hence the <=5 s allowance over the documented bound
    assert max(pauses) <= MAX_BATCH_DELAY_SECONDS + 5, f"a 10**9-second pause reached asyncio.sleep: {pauses}"
    assert max(pauses) < 7200, "the batch parks for years while is_running stays True"

    # cancel_all twice must stop each browser the queue owns exactly once
    launcher = _FakeLauncher()
    cancel_manager = UploadQueueManager(None, launcher)
    for pid in ("p1", "p2"):
        cancel_manager.jobs[pid] = uq.UploadJob(profile_id=pid, profile_name=pid, source_video="v.mp4")
        cancel_manager.jobs[pid].status = "uploading"
        cancel_manager._launched_here.add(pid)
    cancel_manager.cancel_all()
    cancel_manager.cancel_all()
    assert sorted(launcher.stopped) == ["p1", "p2"], f"double stop/leak: {launcher.stopped}"
    assert cancel_manager._launched_here == set()
    assert all(j.status == "canceled" for j in cancel_manager.jobs.values())


def test_batch_cancel_midflight_keeps_job_canceled(monkeypatch, tmp_path):
    holder: dict = {}

    def cancel_on_first_upload(index):
        if index == 0:
            holder["manager"].cancel_all()

    uploader = _uploader_factory([(False, None, "network timeout")], on_call=cancel_on_first_upload)
    monkeypatch.setattr("nazak.core.youtube_uploader.YouTubeUploader", uploader)
    monkeypatch.setattr(uq, "get_free_port", lambda: 45678)
    monkeypatch.setattr(uq, "format_video_metadata", lambda **_k: {"title": "t", "description": "d"})
    slept: list[float] = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    manager, launcher = _make_queue(("a", "b"))
    holder["manager"] = manager

    asyncio.run(manager.run_batch_upload(["a", "b"], tmp_path / "in.mp4", "t", "d"))
    assert manager.jobs["a"].status == "canceled", "a user-cancelled job was reported as failed"
    assert manager.jobs["a"].error is None
    assert manager.jobs["b"].status == "canceled"
    assert set(launcher.stopped) == {"a"}, f"the launched browser was not swept on cancel: {launcher.stopped}"


def test_batch_unexpected_error_sweeps_launched_browser(monkeypatch, tmp_path):
    monkeypatch.setattr("nazak.core.youtube_uploader.YouTubeUploader", _uploader_factory([(True, "http://vid", None)]))
    monkeypatch.setattr(uq, "get_free_port", lambda: 45678)
    monkeypatch.setattr(uq, "format_video_metadata", lambda **_k: {"title": "t", "description": "d"})
    slept: list[float] = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    # update_profile() explodes right after the browser was launched
    manager, launcher = _make_queue(("c",), fail_update_after=0)

    with pytest.raises(RuntimeError, match="update exploded"):
        asyncio.run(manager.run_batch_upload(["c"], tmp_path / "in.mp4", "t", "d"))

    assert launcher.stopped == ["c"], "the finally-sweep left a Chrome process behind"
    assert manager._launched_here == set()
    assert manager.is_running is False
    assert manager.jobs["c"].status == "failed", "the job stayed stuck in launching/uploading"
    assert manager.jobs["c"].error


# --------------------------------------------------------------------------- process monitor


def test_process_monitor_transitions_notifications_and_lifecycle():
    # 1. RUNNING profile whose pid disappeared -> STOPPED + one notification + pid cleared
    profile = BrowserProfile(id="pm_a", name="PM A", status=ProfileStatus.RUNNING, pid=4321)
    pm = _FakeProfileManager([profile])
    launcher = _FakeLauncher()
    events: list[tuple] = []
    monitor = ProcessMonitor(pm, launcher, poll_interval=0.01)
    monitor.register_callback(lambda pid, status: events.append((pid, status)))
    monitor.start()
    assert _wait_until(lambda: bool(events)), "the monitor never noticed the dead pid"
    monitor.stop()
    assert profile.status is ProfileStatus.STOPPED
    assert profile.pid is None
    assert events == [("pm_a", ProfileStatus.STOPPED)], f"callback not fired exactly once: {events}"
    assert monitor._running is False

    # 2. start() twice keeps a single thread; stop()/stop() and stop()-before-start are safe
    again = ProcessMonitor(pm, launcher, poll_interval=0.01)
    again.stop()  # never started
    again.start()
    thread = again._thread
    again.start()
    assert again._thread is thread, "a second start() spawned a second watchdog thread"
    again.stop()
    again.stop()
    assert again._running is False

    # 3. a stale RUNNING object in list_profiles must not be touched when get_profile says STOPPED
    stale = BrowserProfile(id="pm_b", name="PM B", status=ProfileStatus.RUNNING, pid=99)
    iterated = threading.Event()
    calls = {"n": 0}

    class _StalePM:
        def list_profiles(self):
            calls["n"] += 1
            if calls["n"] >= 3:
                iterated.set()
            return [stale]

        def get_profile(self, _pid):
            return SimpleNamespace(id="pm_b", status=ProfileStatus.STOPPED)

        def update_profile(self, prof):
            return prof

    stale_events: list[tuple] = []
    stale_monitor = ProcessMonitor(_StalePM(), _FakeLauncher(), poll_interval=0.01)
    stale_monitor.register_callback(lambda pid, status: stale_events.append((pid, status)))
    stale_monitor.start()
    assert iterated.wait(timeout=2.0), "the monitor loop did not run"
    stale_monitor.stop()
    assert stale_events == []
    assert stale.status is ProfileStatus.RUNNING and stale.pid == 99

    # 4. a raising callback and a raising list_profiles() must not kill the loop
    boom_profile = BrowserProfile(id="pm_c", name="PM C", status=ProfileStatus.RUNNING, pid=7)
    boom_pm = _FakeProfileManager([boom_profile])
    seen: list[str] = []

    def bad_callback(pid, _status):
        seen.append(f"bad:{pid}")
        raise RuntimeError("callback boom")

    def good_callback(pid, _status):
        seen.append(f"good:{pid}")

    boom_monitor = ProcessMonitor(boom_pm, _FakeLauncher(), poll_interval=0.01)
    boom_monitor.register_callback(bad_callback)
    boom_monitor.register_callback(good_callback)
    boom_monitor.start()
    assert _wait_until(lambda: len(seen) >= 2), "a raising callback aborted the notification fan-out"
    boom_monitor.stop()
    assert seen == ["bad:pm_c", "good:pm_c"]

    flaky_calls = {"n": 0}

    class _FlakyPM:
        def list_profiles(self):
            flaky_calls["n"] += 1
            if flaky_calls["n"] <= 2:
                raise RuntimeError("db is down")
            return []

        def get_profile(self, _pid):
            return None

        def update_profile(self, prof):
            return prof

    flaky_monitor = ProcessMonitor(_FlakyPM(), _FakeLauncher(), poll_interval=0.01)
    flaky_monitor.start()
    survived = _wait_until(lambda: flaky_calls["n"] >= 3)
    alive = flaky_monitor._thread.is_alive()
    flaky_monitor.stop()
    assert survived and alive, "an exception in list_profiles() killed the monitor thread"


# --------------------------------------------------------------------------- config


def test_find_chrome_executable_candidate_and_path_order(monkeypatch):
    from nazak import config as cfg

    target = next(c for c in cfg.CHROME_CANDIDATES if c)
    monkeypatch.setattr(os.path, "isfile", lambda p: os.path.normcase(str(p)) == os.path.normcase(target))
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    assert cfg.find_chrome_executable() == str(Path(target).resolve())

    # nothing on disk: fall back to PATH in the documented order
    path_hit = "/opt/deep-probe/bin/chromium-not-a-candidate"
    monkeypatch.setattr(os.path, "isfile", lambda p: os.path.normcase(str(p)) == os.path.normcase(path_hit))
    asked: list[str] = []

    def fake_which(name):
        asked.append(name)
        return path_hit if name == "chromium" else None

    monkeypatch.setattr(shutil, "which", fake_which)
    assert cfg.find_chrome_executable() == str(Path(path_hit).resolve())
    assert asked[:3] == ["google-chrome", "google-chrome-stable", "chromium"]


def test_find_chrome_executable_picks_newest_playwright_revision(monkeypatch):
    from nazak import config as cfg

    older = "/home/u/.cache/ms-playwright/chromium-907/chrome-linux/chrome"
    newer = "/home/u/.cache/ms-playwright/chromium-1200/chrome-linux/chrome"
    monkeypatch.setattr(os.path, "isfile", lambda p: "ms-playwright" in str(p))
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    monkeypatch.setattr(glob, "glob", lambda _pattern: [older, newer])
    assert "chromium-1200" in str(cfg.find_chrome_executable())


def _load_config_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_config_data_dir_override_ensure_dirs_and_frozen_web_dir(monkeypatch, tmp_path):
    from nazak import config as cfg

    source = Path(cfg.__file__)
    portable = tmp_path / "portable-data"
    monkeypatch.setenv("NAZAK_DATA_DIR", str(portable))
    fresh = _load_config_module("nazak_config_fresh", source)

    assert not portable.exists(), "importing nazak.config created the data tree"
    expected_paths = {
        "DATA_DIR": portable,
        "PROFILES_DIR": portable / "profiles",
        "PROFILES_FILE": portable / "profiles.json",
        "EXTENSIONS_DIR": portable / "extensions",
        "LOGS_DIR": portable / "logs",
    }
    for attribute, expected in expected_paths.items():
        assert getattr(fresh, attribute) == expected, attribute

    assert fresh.ensure_data_dirs() == portable
    for created in (portable, fresh.PROFILES_DIR, fresh.EXTENSIONS_DIR, fresh.LOGS_DIR):
        assert created.is_dir()
    fresh._data_dirs_ready = False  # force the slow path again: mkdir(exist_ok=True) is idempotent
    assert fresh.ensure_data_dirs() == portable
    assert fresh._data_dirs_ready is True

    # frozen build: the bundled web assets win, otherwise the dir next to the exe
    exe_dir = tmp_path / "app"
    bundle = exe_dir / "_internal"
    bundled_web = bundle / "nazak" / "web"
    bundled_web.mkdir(parents=True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_dir / "nazak.exe"))

    frozen = _load_config_module("nazak_config_frozen", source)
    assert frozen.IS_FROZEN is True
    assert (frozen.BASE_DIR, frozen.WEB_DIR.resolve()) == (exe_dir.resolve(), bundled_web.resolve())

    shutil.rmtree(bundled_web)
    fallback = _load_config_module("nazak_config_frozen_fallback", source)
    assert fallback.WEB_DIR.resolve() == (exe_dir / "nazak" / "web").resolve()


# --------------------------------------------------------------------------- video uniquifier


def test_find_ffmpeg_ignores_relative_candidate_without_localappdata(monkeypatch, tmp_path):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    rogue = tmp_path / "Microsoft" / "WinGet" / "Links" / "ffmpeg.exe"
    rogue.parent.mkdir(parents=True)
    rogue.write_bytes(b"not really ffmpeg")
    monkeypatch.chdir(tmp_path)
    found = vu.find_ffmpeg()
    assert found is None, f"a relative candidate was resolved against the CWD: {found}"


def test_uniquify_video_lookup_and_failure_paths(monkeypatch, tmp_path):
    # 1. PATH lookup wins and is returned verbatim
    monkeypatch.setattr(shutil, "which", lambda _name: "/custom/bin/ffmpeg")
    assert vu.find_ffmpeg() == "/custom/bin/ffmpeg"

    # 2. no ffmpeg at all -> loud failure, nothing left on disk
    monkeypatch.setattr(vu, "find_ffmpeg", lambda: None)
    out_dir = tmp_path / "out"
    uniquifier = vu.VideoUniquifier(output_dir=out_dir)
    assert uniquifier.is_ffmpeg_available() is False
    source = tmp_path / "source.mp4"
    source.write_bytes(b"0" * 4096)
    ok, out_path, err = uniquifier.uniquify_video(source, "prof_1")
    assert (ok, out_path) == (False, None)
    assert "FFmpeg not found" in str(err)
    assert list(out_dir.iterdir()) == []

    # a missing source is reported before any ffmpeg concern
    ok, out_path, err = uniquifier.uniquify_video(tmp_path / "missing.mp4", "prof_1")
    assert ok is False and out_path is None and "Source video not found" in str(err)

    # 3. hostile source names must stay ONE argv element (no shell, no splitting).
    # Windows forbids only < > : " / \ | ? * and control chars, so the payload below is
    # a legal file name that would wreak havoc if it ever reached a shell.
    uniquifier.ffmpeg_path = str(tmp_path / "fake-ffmpeg")
    hostile = tmp_path / "cl ip; rm -rf $HOME 'quoted' && echo $(whoami) #hash %COMSPEC% [x] {y}.mp4"
    hostile.write_bytes(b"0" * 4096)
    captured: dict = {}

    def successful_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        Path(cmd[-1]).write_bytes(b"1" * 4096)
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(vu.subprocess, "run", successful_run)
    ok, out_path, err = uniquifier.uniquify_video(hostile, "prof_2")
    assert (ok, err) == (True, None)
    cmd = captured["cmd"]
    assert isinstance(cmd, list), "arguments were passed as a command string"
    assert cmd[0] == uniquifier.ffmpeg_path
    assert captured["kwargs"].get("shell") is None, "shell=True would re-interpret hostile names"
    assert cmd[cmd.index("-i") + 1] == str(hostile)
    assert cmd.count(str(hostile)) == 1
    assert out_path is not None
    assert Path(cmd[-1]) == out_path
    assert Path(out_path).parent == out_dir
    assert "prof_2" in Path(out_path).name

    # a leading dash in a *relative* source name is still a single argv element
    monkeypatch.chdir(tmp_path)
    dash = Path("-y leading-dash.mp4")
    dash.write_bytes(b"0" * 4096)
    ok, out_path, err = uniquifier.uniquify_video(dash, "prof_dash")
    assert ok is True, f"a leading-dash file name broke the ffmpeg call: {err}"
    assert captured["cmd"][captured["cmd"].index("-i") + 1] == "-y leading-dash.mp4"

    # 4. non-zero exit: no partial output may survive
    def failing_run(cmd, **kwargs):
        Path(cmd[-1]).write_bytes(b"1" * 4096)
        return SimpleNamespace(returncode=1, stderr="x" * 500 + "tail-marker", stdout="")

    monkeypatch.setattr(vu.subprocess, "run", failing_run)
    ok, out_path, err = uniquifier.uniquify_video(source, "prof_3")
    assert (ok, out_path) == (False, None)
    assert "rc=1" in str(err) and "tail-marker" in str(err)
    assert not (out_dir / f"prof_3_unique_{source.stem}.mp4").exists()

    # 5. a tiny/empty output is a failure too
    def tiny_run(cmd, **kwargs):
        Path(cmd[-1]).write_bytes(b"1")
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(vu.subprocess, "run", tiny_run)
    ok, out_path, err = uniquifier.uniquify_video(source, "prof_tiny")
    assert ok is False and out_path is None
    assert not (out_dir / f"prof_tiny_unique_{source.stem}.mp4").exists()

    # 6. execution error: the partial file is removed and the reason is reported
    def exploding_run(cmd, **kwargs):
        Path(cmd[-1]).write_bytes(b"1" * 4096)
        raise OSError("cannot execute")

    monkeypatch.setattr(vu.subprocess, "run", exploding_run)
    ok, out_path, err = uniquifier.uniquify_video(source, "prof_4")
    assert ok is False and out_path is None
    assert "FFmpeg execution error" in str(err) and "cannot execute" in str(err)
    assert not (out_dir / f"prof_4_unique_{source.stem}.mp4").exists()


# --------------------------------------------------------------------------- extension generator


def test_extension_generation_and_metadata_helpers(tmp_path):
    from nazak.core import extension_generator as eg
    from nazak.models.profile import GoogleSettings, ProxyConfig

    hostile_user = 'u"\\ ; alert(1) //'
    hostile_pass = "p\"\n${x}; 'quoted' \\ backslash"
    profile = BrowserProfile(
        id="deep_ext",
        name='Hostile "name"\n</script><b>',
        proxy=ProxyConfig(enabled=True, host="1.2.3.4", port=8080, username=hostile_user, password=hostile_pass),
        google=GoogleSettings(),
    )
    ext_dir = Path(eg.generate_profile_extension(profile, tmp_path))
    assert {p.name for p in ext_dir.iterdir()} == {"manifest.json", "stealth.js", "background.js"}

    manifest = json.loads((ext_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_version"] == 3
    assert manifest["version"] == "3.0.0"
    assert manifest["name"] == f"Nazak Deep Shield - {profile.name}"
    assert manifest["content_scripts"][0]["js"] == ["stealth.js"]

    background = (ext_dir / "background.js").read_text(encoding="utf-8")
    username_literal = re.search(r'username:\s*("(?:[^"\\]|\\.)*")', background)
    password_literal = re.search(r'password:\s*("(?:[^"\\]|\\.)*")', background)
    assert username_literal is not None and password_literal is not None
    assert json.loads(username_literal.group(1)) == hostile_user
    assert json.loads(password_literal.group(1)) == hostile_pass
    assert hostile_pass not in background, "hostile credentials landed raw in background.js"

    if shutil.which("node"):
        for script in ("stealth.js", "background.js"):
            check = subprocess.run(
                ["node", "--check", str(ext_dir / script)], capture_output=True, text=True, check=False
            )
            assert check.returncode == 0, f"{script} is not valid JS: {check.stderr[-400:]}"

    # pure metadata helpers used by the generated stealth source
    assert eg._nvidia_arch("NVIDIA GeForce RTX 4090") == "ada lovelace"
    assert eg._nvidia_arch("GeForce GTX 980") == "maxwell"
    assert eg._nvidia_arch("GeForce GTX 660") == "kepler"
    assert eg._nvidia_arch("Intel UHD") == "turing"
    assert eg._amd_arch("AMD Radeon RX 7900 XTX") == "rdna 3"
    assert eg._amd_arch("Radeon RX 580") == "rdna 1"
    assert eg._amd_arch("unknown") == "rdna 2"
    assert eg._quantized_device_memory(16) == 8
    assert eg._quantized_device_memory(3) == 2
    assert eg._quantized_device_memory(0) == 1
    assert eg._quantized_device_memory(None) == 1
    assert eg._chrome_full_version("Mozilla/5.0 Chrome/153.0.8010.53 Safari/537.36") == "153.0.8010.53"
    assert eg._chrome_full_version(None, None) == "133.0.0.0"
    assert eg._chrome_full_version("no version here") == "133.0.0.0"


# --------------------------------------------------------------------------- warmup engine


def test_warmup_plan_bounds_and_determinism():
    unknown = warmup.WarmupPlan(profile_id="p", niche="not-a-niche", steps_count=999)
    assert unknown.niche == "ecommerce", "an unknown niche was not normalised"
    assert unknown.steps_count == 20, "steps_count is not clamped to 20"
    assert len(unknown.queries) == len(warmup.WARMUP_NICHES["ecommerce"])
    assert set(unknown.queries) <= set(warmup.WARMUP_NICHES["ecommerce"])
    assert len(set(unknown.queries)) == len(unknown.queries), "duplicate queries in one plan"
    summary = unknown.to_dict()
    assert summary["steps_count"] == len(unknown.queries)
    assert summary["estimated_duration_minutes"] == len(unknown.queries) * 1.5

    assert warmup.WarmupPlan("p", niche=None, steps_count=0).steps_count == 1
    assert len(warmup.WarmupPlan("p", niche="crypto", steps_count=20).queries) == len(warmup.WARMUP_NICHES["crypto"])

    state = random.getstate()
    try:
        random.seed(20260101)
        first = warmup.WarmupPlan("p", niche="tech", steps_count=3).queries
        random.seed(20260101)
        second = warmup.WarmupPlan("p", niche="tech", steps_count=3).queries
    finally:
        random.setstate(state)
    assert first == second, "plan generation is not reproducible for a fixed seed"


def test_generate_warmup_urls_encodes_query_parameters(monkeypatch):
    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    query = "headphones & speakers cheap"
    urls = warmup.generate_warmup_urls([query])
    assert len(urls) == 1
    parsed = _parse_query(urls[0])
    assert parsed["q"] == [query], f"the search term was split by the URL parser: {parsed}"

    class _Page:
        def __init__(self):
            self.gotos: list[str] = []

        async def goto(self, url, **_kwargs):
            self.gotos.append(url)

    class _Launcher:
        def is_profile_running(self, _pid):
            return True

        def launch(self, *_a, **_k):  # pragma: no cover - not used with a running browser
            return True, 1, None

    executor = warmup.ScenarioExecutor(_Launcher(), SimpleNamespace(get_profile=lambda pid: SimpleNamespace(id=pid)))
    page = _Page()
    step = warmup.ScenarioStep("google_search", {"query": query})

    async def run():
        return await executor.execute_step(step, "p1", page=page)

    assert asyncio.run(run()) is True
    assert _parse_query(page.gotos[0])["q"] == [query], f"the google_search step lost the query: {page.gotos}"


def test_page_session_open_failure_and_batch_warmup_formatting(monkeypatch):
    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    monkeypatch.setitem(sys.modules, "playwright", None)
    monkeypatch.setitem(sys.modules, "playwright.async_api", None)

    session = warmup._PageSession()
    assert asyncio.run(session.open("http://127.0.0.1:1")) is False, "a failed attach was reported as success"
    assert session.page is None and session._browser is None and session._pw is None

    async def close_twice():
        await session.close()
        await session.close()

    asyncio.run(close_twice())

    attached = warmup._PageSession()
    attached.page = object()
    assert asyncio.run(attached.open("http://127.0.0.1:1")) is True  # short-circuit, no playwright needed
    asyncio.run(attached.close())
    assert attached.page is None

    class _WarmupPM:
        def __init__(self):
            self.profiles = {"w1": SimpleNamespace(id="w1", name="W1")}

        def get_profile(self, pid):
            return self.profiles.get(pid)

        def update_profile(self, prof):
            return prof

    launcher = SimpleNamespace(
        is_profile_running=lambda _pid: True, get_cdp_info=lambda _pid: None, stop=lambda _pid: None
    )
    executor = warmup.ScenarioExecutor(launcher, _WarmupPM())
    scenario = warmup.WarmupScenario(
        id="deep_batch",
        name="Deep batch",
        steps=[warmup.ScenarioStep("dwell", {"min_sec": 0.01, "max_sec": 0.02})],
    )
    summary = asyncio.run(executor.run_batch_warmup(scenario, ["w1", "ghost"], max_concurrency=99))
    assert summary["total_profiles"] == 2
    assert summary["successful"] == 1
    by_id = {item["profile_id"]: item for item in summary["results"] if "profile_id" in item}
    assert by_id["w1"]["success"] is True and by_id["w1"]["completed_steps"] == 1
    assert by_id["ghost"]["success"] is False and by_id["ghost"]["error"] == "Profile not found"
    assert executor.is_running is False, "run_batch_warmup leaked is_running=True"

    exploding = warmup.ScenarioExecutor(launcher, _WarmupPM())

    async def boom(*_a, **_k):
        raise RuntimeError("worker boom")

    monkeypatch.setattr(exploding, "run_scenario_on_profile", boom)
    summary = asyncio.run(exploding.run_batch_warmup(scenario, ["w1"], max_concurrency=0))
    assert summary["successful"] == 0
    assert summary["results"][0]["success"] is False and "worker boom" in summary["results"][0]["error"]

    assert asyncio.run(executor._ensure_page(warmup._PageSession(), "w1")) is None


# --------------------------------------------------------------------------- cli_cmds.common


def test_read_input_text_rejects_bad_files(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "stdin", _FakeStdin(tty=False))
    directory = tmp_path / "a-directory"
    directory.mkdir()
    with pytest.raises(UsageError, match="каталог"):
        cli_common.read_input_text(explicit=f"@{directory}")
    with pytest.raises(UsageError, match="каталог"):
        cli_common.read_input_text(file=str(directory))

    oversized = tmp_path / "oversized.txt"
    with open(oversized, "wb") as handle:
        handle.seek(cli_common._MAX_INPUT_BYTES + 1)
        handle.write(b"x")
    with pytest.raises(UsageError, match="слишком большой"):
        cli_common.read_input_text(explicit=f"@{oversized}")
    with pytest.raises(UsageError, match="не найден"):
        cli_common.read_input_text(explicit=f"@{tmp_path / 'missing.txt'}")

    # invalid UTF-8 is replaced, never raised, and the rest of the payload survives
    legacy = tmp_path / "legacy.txt"
    legacy.write_bytes(b"\xff\xfeuser:pass@host:8080")
    text = cli_common.read_input_text(explicit=f"@{legacy}")
    assert isinstance(text, str) and "user:pass@host:8080" in text

    assert cli_common.read_input_text(explicit="plain payload") == "plain payload"


def test_read_input_text_strips_utf8_bom(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "stdin", _FakeStdin(tty=False))
    bom_file = tmp_path / "bom.txt"
    bom_file.write_bytes(b"\xef\xbb\xbfuser:pass@host:8080\n")
    text = cli_common.read_input_text(explicit=f"@{bom_file}")
    assert "\ufeff" not in text, f"BOM leaked into the payload: {text[:12]!r}"
    assert text.startswith("user:pass@host:8080")


def test_common_helpers_and_server_request_contracts(tmp_path, monkeypatch):
    # resolve_out_path: only an explicit --force/--yes may clobber a file
    existing = tmp_path / "existing.json"
    existing.write_text("keep me", encoding="utf-8")
    with pytest.raises(UsageError, match="Пустой путь"):
        cli_common.resolve_out_path("", GlobalOptions())
    with pytest.raises(UsageError, match="каталог"):
        cli_common.resolve_out_path(str(tmp_path), GlobalOptions())
    with pytest.raises(UsageError, match="уже существует"):
        cli_common.resolve_out_path(str(existing), GlobalOptions())
    with pytest.raises(UsageError, match="не существует"):
        cli_common.resolve_out_path(str(tmp_path / "nope" / "x.json"), GlobalOptions())
    assert cli_common.resolve_out_path(str(existing), GlobalOptions(yes=True)) == existing
    assert cli_common.resolve_out_path(str(existing), GlobalOptions(), force=True) == existing
    assert existing.read_text(encoding="utf-8") == "keep me"

    # id parsing / "all" expansion
    assert cli_common.parse_ids(" a , b ,, c ") == ["a", "b", "c"]
    assert cli_common.parse_ids(["a,b", " c "]) == ["a", "b", "c"]
    assert cli_common.parse_ids(None) == [] and cli_common.parse_ids("") == []
    fake_pm = SimpleNamespace(list_profiles=lambda: [SimpleNamespace(id="p1"), SimpleNamespace(id="p2")])
    monkeypatch.setattr(cli_common, "get_managers", lambda: (fake_pm, None))
    assert cli_common.resolve_ids(["all"], allow_all=True) == ["p1", "p2"]
    assert cli_common.resolve_ids([], allow_all=True) == ["p1", "p2"]
    assert cli_common.resolve_ids(["*"], allow_all=True) == ["p1", "p2"]
    assert cli_common.resolve_ids(["x"], allow_all=False) == ["x"]

    # secret masking helpers
    masked = cli_common.mask_proxy_dict(
        {"password": "pw", "raw": "http://u:pw@h:1", "rotation_url": "http://r", "host": "h"}
    )
    assert masked["password"] == "***" and masked["rotation_url"] == "***"
    assert masked["raw"] == "http://u:***@h:1" and masked["host"] == "h"
    assert cli_common.mask_notes_json("free text") is None
    assert cli_common.mask_notes_json("[1, 2]") is None
    notes = json.dumps(
        {"account_password": "SECRET", "totp_secret": "TOTP", "_totp_raw": "RAW", "_secrets_mode": "plain"}
    )
    assert json.loads(cli_common.mask_notes_json(notes)) == {
        "account_password": "***",
        "totp_secret": "***",
        "_secrets_mode": "plain",
    }
    assert json.loads(cli_common.mask_notes_json(notes, reveal=True)) == {
        "account_password": "SECRET",
        "totp_secret": "TOTP",
        "_secrets_mode": "plain",
    }

    # emit helpers keep the agent contract on both streams
    out = StringIO()
    with contextlib.redirect_stdout(out):
        cli_common.emit({"a": 1}, GlobalOptions())  # human mode still prints parseable JSON
    assert json.loads(out.getvalue()) == {"a": 1}

    out, err = StringIO(), StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        assert cli_common.emit_success("fine", GlobalOptions(verbose=True), {"k": "v"}) == 0
        assert cli_common.emit_error("bad", GlobalOptions()) == cli_common.EXIT_USAGE
    assert "fine" in out.getvalue() and '"k": "v"' in out.getvalue()
    assert "bad" in err.getvalue() and "Ошибка" in err.getvalue()

    # server_request: HTTP status -> exception mapping, no socket is opened
    with pytest.raises(RuntimeError, match="server mode not enabled"):
        cli_common.server_request(GlobalOptions(), "GET", "/api/system/info")

    import httpx

    class _Response:
        def __init__(self, status_code, payload=None, text=""):
            self.status_code = status_code
            self._payload = payload
            self.text = text

        def json(self):
            if self._payload is None:
                raise ValueError("not json")
            return self._payload

    installed: dict = {}

    def install(response):
        class _Client:
            def __init__(self, **kwargs):
                installed["kwargs"] = kwargs

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

            def request(self, method, path, **kwargs):
                installed["request"] = (method, path, kwargs)
                return response

        monkeypatch.setattr(httpx, "Client", _Client)

    install(_Response(200, {"ok": True}))
    opt = GlobalOptions(server="http://127.0.0.1:8899/", api_key="token-1")
    assert cli_common.server_request(opt, "GET", "/api/x") == {"ok": True}
    assert installed["kwargs"]["base_url"] == "http://127.0.0.1:8899"
    assert installed["kwargs"]["headers"] == {"X-API-Key": "token-1"}
    assert installed["request"][:2] == ("GET", "/api/x")

    install(_Response(404, {"detail": "Profile not found"}))
    with pytest.raises(ApiError) as exc:
        cli_common.server_request(GlobalOptions(server="http://127.0.0.1:8899"), "GET", "/api/x")
    assert exc.value.status == 404 and "Profile not found" in str(exc.value.detail)

    install(_Response(500, None, "traceback"))
    with pytest.raises(RuntimeError, match="server error HTTP 500"):
        cli_common.server_request(GlobalOptions(server="http://127.0.0.1:8899"), "GET", "/api/x")

    install(_Response(400, None, "<html>"))
    with pytest.raises(RuntimeError, match="non-JSON HTTP 400"):
        cli_common.server_request(GlobalOptions(server="http://127.0.0.1:8899"), "GET", "/api/x")

    install(_Response(200, None, "<html>"))
    with pytest.raises(RuntimeError, match="non-JSON HTTP 200"):
        cli_common.server_request(GlobalOptions(server="http://127.0.0.1:8899"), "GET", "/api/x")


def test_cli_confirm_contract_and_exit_codes(tmp_path, monkeypatch):
    # the CLI keeps a lazy manager singleton: drop it so the probe profile is visible for
    # the calls below (same convention as test_round3_cli_fixes) and never leave it behind
    cli_common._managers = None
    monkeypatch.setattr(sys, "stdin", _FakeStdin(tty=False))

    # non-interactive: confirm() must answer "no" without touching input()
    assert cli_common.is_interactive() is False
    assert cli_common.confirm("Delete everything?", GlobalOptions()) is False
    out, err = StringIO(), StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        ok, code = cli_common.require_confirm("Delete?", GlobalOptions(as_json=True), "profile delete p --yes")
    assert (ok, code) == (False, cli_common.EXIT_CONFLICT)
    payload = json.loads(out.getvalue())
    assert payload["hint"] == "profile delete p --yes" and payload["code"] == cli_common.EXIT_CONFLICT
    assert cli_common.confirm("Delete?", GlobalOptions(yes=True)) is True

    # interactive: EOF and "n" refuse (exit 0 = "cancelled"), "yes" proceeds
    monkeypatch.setattr(sys, "stdin", _FakeStdin(tty=True))

    def raise_eof(*_a, **_k):
        raise EOFError

    monkeypatch.setattr("builtins.input", raise_eof)
    assert cli_common.confirm("Delete?", GlobalOptions()) is False
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: "n")
    assert cli_common.require_confirm("Delete?", GlobalOptions(), "hint") == (False, cli_common.EXIT_OK)
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: "yes")
    assert cli_common.require_confirm("Delete?", GlobalOptions(), "hint") == (True, None)

    # back to a non-interactive agent session for the end-to-end CLI calls
    monkeypatch.setattr(sys, "stdin", _FakeStdin(tty=False))

    # end-to-end through run_cli(): a directory behind @path is a usage error, not data
    code, payload = _run_cli_json(["proxy", "test", f"@{tmp_path}"])
    assert code == cli_common.EXIT_USAGE == 2
    assert payload["success"] is False and "каталог" in payload["error"]

    code, payload = _run_cli_json(["proxy", "test", f"@{tmp_path / 'missing.txt'}"])
    assert code == 2 and "не найден" in payload["error"]

    code, _out, _err = _run_cli(["--not-a-flag", "profile", "list"])
    assert code == 2

    # human (non-JSON) refusal must explain the next step on stderr and keep stdout clean
    code, created = _run_cli_json(["profile", "ensure", "--name", "Deep CLI Confirm Probe"])
    assert code == 0 and created["profile_id"]
    profile_id = created["profile_id"]
    try:
        code, out, err = _run_cli(["profile", "delete", profile_id])
        assert code == cli_common.EXIT_CONFLICT == 4
        assert out.strip() == ""
        assert "Подсказка" in err and "--yes" in err
    finally:
        _run_cli(["--yes", "profile", "delete", profile_id, "--json"])
        cli_common._managers = None  # never leak a manager that has seen the probe profile
