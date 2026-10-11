"""P0 refactor regression: TaskBridge semantics (busy guard, cancel, inline results)."""

import asyncio

import pytest

from nazak.gui.task_bridge import TaskBridge, TaskCanceled, TaskHandle, run_task_inline


def _noop_progress(*_a, **_k):
    pass


def test_p0_inline_sync_task_with_handle_and_progress():
    seen = []

    def task(a, b, handle=None, progress=None):
        assert handle is not None and progress is not None
        progress(("half",))
        seen.append(a + b)
        return a * b

    out = run_task_inline(task, TaskHandle(name="t"), lambda *a, **k: seen.append(a), 2, 3)
    assert out == 6
    assert 5 in seen


def test_p0_inline_async_task():
    async def task(x, handle=None, progress=None):
        await asyncio.sleep(0)
        return x + 1

    assert run_task_inline(task, TaskHandle(name="a"), _noop_progress, 41) == 42


def test_p0_inline_plain_callable_without_handle():
    assert run_task_inline(lambda x: x * 3, TaskHandle(name="p"), _noop_progress, 7) == 21


def test_p0_bridge_busy_guard():
    import threading

    started = threading.Event()
    release = threading.Event()

    def blocking(handle=None, progress=None):
        started.set()
        release.wait(timeout=10)
        return "ok"

    bridge = TaskBridge(name="busy")
    handle = bridge.submit(blocking)
    try:
        assert started.wait(timeout=10)
        with pytest.raises(RuntimeError):
            bridge.submit(blocking)
    finally:
        release.set()
        bridge.wait(timeout_ms=10_000)
    assert bridge._last_result == "ok"
    assert handle is not None


def test_p0_bridge_cancel_flag_visible_to_task():
    observed = {}

    def task(handle=None, progress=None):
        observed["cancelled_at_entry"] = handle.is_cancelled
        handle.cancel()
        observed["cancelled_after"] = handle.is_cancelled
        return "done"

    bridge = TaskBridge(name="cancel")
    bridge.submit(task)
    bridge.wait(timeout_ms=10_000)
    assert observed["cancelled_at_entry"] is False
    assert observed["cancelled_after"] is True


def test_p0_bridge_records_error_headless():
    def boom(handle=None, progress=None):
        raise ValueError("task exploded")

    bridge = TaskBridge(name="err")
    bridge.submit(boom)
    bridge.wait(timeout_ms=10_000)
    assert bridge._last_error == "task exploded"
    assert bridge._last_result is None


def test_p0_tasks_check_all_proxies_progress(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import patch

    import nazak.gui.tasks as tasks
    from nazak.models.health import HealthCheckResult

    async def fake_check(proxy, profile_dir=None):
        return HealthCheckResult(status="healthy", profile_id="x")

    profs = [SimpleNamespace(id="a", name="A", proxy=object()), SimpleNamespace(id="b", name="B", proxy=object())]
    seen = []
    with patch("nazak.core.proxy_checker.check_proxy_health", side_effect=fake_check):
        results = tasks.check_all_proxies(profs, tmp_path, progress=lambda payload: seen.append(payload))
    assert [pid for pid, _ in results] == ["a", "b"]
    assert [p[0] for p in seen] == [1, 2]


def test_p0_tasks_single_proxy_returns_result():
    from unittest.mock import patch

    import nazak.gui.tasks as tasks
    from nazak.models.health import HealthCheckResult

    async def fake_check(proxy_config, profile_dir=None):
        return HealthCheckResult(status="healthy", profile_id="p1")

    with patch("nazak.core.proxy_checker.check_proxy_health", side_effect=fake_check):
        out = tasks.check_single_proxy("p1", object(), None)
    assert isinstance(out, HealthCheckResult)
