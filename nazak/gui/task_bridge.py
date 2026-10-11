"""
Qt TaskBridge (P0 refactor). One bridge for every background job in the GUI.

Problems it fixes (see nazak/gui/workers.py before the refactor):
- every worker built its own ``asyncio.new_event_loop()`` + ``run_until_complete``,
  which leaks loops, is untestable without Qt widgets, and has no uniform cancel.
- views hand-roll QThread lifetime (audit R3: a re-click overwrote a running
  QThread and crashed the process).

Design:
- :class:`TaskBridge` owns exactly one :class:`QThread` at a time
  (``submit`` refuses while busy — the same guard every view re-implemented).
- business logic lives in plain callables in :mod:`nazak.gui.tasks`
  (sync or async function + progress callback) — importable and unit-testable
  without Qt.
- :class:`TaskBridge` translates task progress/result/error into Qt signals,
  so existing view slots (``finished_signal``/``error_signal``/``progress_signal``
  shapes) keep working.
- headless fallback: when PyQt6 is unavailable (CI without Qt), the task runs
  inline on the calling thread. Views keep the same call sequence.
"""

from __future__ import annotations

import asyncio
import inspect
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

QObject: Any
QThread: Any
Signal: Any

try:  # pragma: no cover - Qt import guard
    from PyQt6.QtCore import QObject as _QObject, QThread as _QThread, pyqtSignal as _QtSignal

    QObject = _QObject
    QThread = _QThread
    Signal = _QtSignal
    _HAS_QT = True
except Exception:  # pragma: no cover

    def _FallbackSignal(*_a: Any, **_k: Any) -> Any:
        class _Noop:
            def connect(self, *a: Any, **k: Any) -> None:
                pass

            def emit(self, *a: Any, **k: Any) -> None:
                pass

        return _Noop()

    Signal = _FallbackSignal
    QThread = None
    _HAS_QT = False


class TaskCanceled(Exception):
    """Raised by tasks (via the cancel flag / progress callback) to abort cleanly."""


class _WarmupCanceled(TaskCanceled):
    """Cooperative warmup abort; caught as TaskCanceled by the bridge thread."""


@dataclass
class TaskHandle:
    name: str
    cancelled: threading.Event = field(default_factory=threading.Event)

    def cancel(self) -> None:
        self.cancelled.set()

    @property
    def is_cancelled(self) -> bool:
        return self.cancelled.is_set()


ProgressCallback = Callable[..., None]
TaskFn = Callable[..., Any]


def _call_with_optional_kw(fn: TaskFn, handle: TaskHandle, progress: ProgressCallback, args, kwargs) -> Any:
    """Call ``fn(*args, handle=..., progress=...)`` when it accepts them."""
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return fn(*args, **kwargs)
    try:
        bound = sig.bind_partial(*args, **kwargs)
    except TypeError:
        return fn(*args, **kwargs)
    params = sig.parameters
    accepts_var_kw = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())
    extra: dict[str, Any] = {}
    unconsumed = [name for name in params if name not in bound.arguments]
    if ("handle" in unconsumed or accepts_var_kw) and "handle" not in bound.arguments:
        extra["handle"] = handle
    if ("progress" in unconsumed or accepts_var_kw) and "progress" not in bound.arguments:
        extra["progress"] = progress
    try:
        return fn(*args, **kwargs, **extra)
    except TypeError:
        if extra:
            return fn(*args, **kwargs)
        raise


def run_task_inline(fn: TaskFn, handle: TaskHandle, progress: ProgressCallback, *args, **kwargs) -> Any:
    """Execute a task callable on the current thread (headless/tests).

    Call convention: tasks declare explicit business params first, then
    ``handle`` / ``progress`` (keyword-or-positional with defaults), sync or
    async. We bind ``handle=``/``progress=`` by keyword and fall back to a
    plain call when the callable does not accept them.
    """
    result = _call_with_optional_kw(fn, handle, progress, args, kwargs)

    if inspect.isawaitable(result):

        async def _runner():
            return await result

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            box: dict[str, Any] = {}

            def _awaitable_target():
                box["result"] = asyncio.run(_runner())

            thread = threading.Thread(target=_awaitable_target, daemon=True)
            thread.start()
            thread.join()
            if "error" in box:
                raise box["error"]
            return box.get("result")
        return asyncio.run(_runner())
    return result


if _HAS_QT:

    class _BridgeThread(QThread):  # type: ignore[valid-type]  # pragma: no cover - Qt runtime only
        def __init__(self, fn: TaskFn, handle: TaskHandle, bridge: TaskBridge, args, kwargs):
            super().__init__()
            self._fn = fn
            self._handle = handle
            self._bridge = bridge
            self._args = args
            self._kwargs = kwargs

        def run(self):
            try:

                def _progress(*p_args, **p_kwargs):
                    self._bridge.progress.emit(*p_args, **p_kwargs)
                    if self._handle.is_cancelled:
                        raise TaskCanceled()

                result = run_task_inline(self._fn, self._handle, _progress, *self._args, **self._kwargs)
                if self._handle.is_cancelled:
                    self._bridge.cancelled.emit()
                else:
                    # Direct record (no event-loop dependency): queued Qt signal
                    # delivery needs a running QApplication, but tests and views
                    # may only wait() on the thread.
                    self._bridge._last_result = result if result is not None else {}
                    self._bridge._last_error = None
                    self._bridge.finished.emit(result if result is not None else {})
            except TaskCanceled:
                self._bridge.cancelled.emit()
            except Exception as exc:
                self._bridge._last_result = None
                self._bridge._last_error = str(exc)
                self._bridge.error.emit(str(exc))


class TaskBridge(QObject):  # type: ignore[valid-type]
    """Owns one background task at a time; Qt signals mirror worker signals."""

    if _HAS_QT:  # pragma: no cover - signal definitions need Qt
        progress = Signal(object)
        finished = Signal(object)
        error = Signal(str)
        cancelled = Signal()

    def __init__(self, name: str = "task"):
        if _HAS_QT:
            super().__init__()
        self.name = name
        self._thread: Any = None
        self._handle: TaskHandle | None = None
        self._last_result: Any = None
        self._last_error: str | None = None

    # -- state ------------------------------------------------------
    def is_running(self) -> bool:
        thread = self._thread
        if thread is None:
            return False
        try:
            return bool(thread.isRunning())
        except Exception:
            return False

    @property
    def handle(self) -> TaskHandle | None:
        return self._handle

    # -- submit -----------------------------------------------------
    def submit(self, fn: TaskFn, *args, **kwargs) -> TaskHandle:
        """Start ``fn`` in the background. Raises RuntimeError while busy."""
        if self.is_running():
            raise RuntimeError(f"TaskBridge[{self.name}] is already running")
        handle = TaskHandle(name=self.name)
        self._handle = handle
        self._last_result = None
        self._last_error = None
        if not _HAS_QT or QThread is None:  # headless: run inline
            try:

                def _progress(*_a, **_k):
                    if handle.is_cancelled:
                        raise TaskCanceled()

                self._last_result = run_task_inline(fn, handle, _progress, *args, **kwargs)
            except TaskCanceled:
                pass
            except Exception as exc:
                self._last_error = str(exc)
            finally:
                self._handle = None
            return handle
        self._thread = _BridgeThread(fn, handle, self, args, kwargs)
        self._thread.finished.connect(self._on_thread_done)
        self._thread.start()
        return handle

    def cancel(self) -> None:
        handle = self._handle
        if handle is not None:
            handle.cancel()

    def wait(self, timeout_ms: int = 30_000) -> bool:
        thread = self._thread
        if thread is None:
            return True
        try:
            return bool(thread.wait(timeout_ms))
        except Exception:
            return False

    def _on_thread_done(self) -> None:  # pragma: no cover - Qt runtime only
        self._thread = None
        self._handle = None
