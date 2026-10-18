"""
Qt Background Worker Threads (P0 refactor).

Behaviour-preserving adapters: the original QThread subclasses keep their
exact signal names (views connect to them), but the business logic moved to
plain Qt-free callables in nazak.gui.tasks, executed through TaskBridge.
New code should use TaskBridge + tasks directly; these adapters exist so the
four existing views do not change.
"""

from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal as Signal

from ..core.warmup_engine import WarmupScenario
from . import tasks as _tasks
from .task_bridge import TaskBridge, _WarmupCanceled


class _BridgeBackedThread(QThread):
    """QThread that runs one tasks.* callable via TaskBridge semantics."""

    _progress = Signal(object)
    _done = Signal(object)
    _failed = Signal(str)
    _aborted = Signal()

    def __init__(self, fn, args: tuple = (), kwargs: dict | None = None, parent=None):
        super().__init__(parent)
        self._fn = fn
        self._args = args
        self._kwargs = dict(kwargs or {})
        self._bridge = TaskBridge(name=getattr(fn, "__name__", "task"))
        self._bridge.progress.connect(self._on_bridge_progress)
        self._bridge.finished.connect(self._on_bridge_finished)
        self._bridge.error.connect(self._on_bridge_error)
        try:
            self._bridge.cancelled.connect(self._on_bridge_cancelled)
        except Exception:
            pass

    # -- TaskBridge fan-out (subclasses override _emit_*) ---------------
    def _on_bridge_progress(self, payload: object):
        self._progress.emit(payload)

    def _on_bridge_finished(self, payload: object):
        self._done.emit(payload)

    def _on_bridge_error(self, message: str):
        self._failed.emit(message)

    def _on_bridge_cancelled(self):
        self._aborted.emit()

    # -- QThread ---------------------------------------------------------
    def run(self):
        self._bridge.submit(self._fn, *self._args, **self._kwargs)
        # submit() blocks until the task settles in headless mode; under Qt
        # the inner bridge thread runs async — wait for its signals.
        try:
            while self._bridge.is_running():
                self.msleep(20)
        except Exception:
            pass

    def cancel(self):
        self._bridge.cancel()


class ProxyCheckWorker(_BridgeBackedThread):
    finished_signal = Signal(str, object)  # profile_id, HealthCheckResult
    error_signal = Signal(str, str)

    def __init__(self, profile_id: str, proxy_config, profile_dir: Path | None = None):
        self.profile_id = profile_id
        self.proxy_config = proxy_config
        self.profile_dir = profile_dir
        super().__init__(_tasks.check_single_proxy, args=(profile_id, proxy_config, profile_dir))
        self._done.connect(self._on_done)
        self._failed.connect(self._on_failed)

    def _on_done(self, res: object):
        self.finished_signal.emit(self.profile_id, res)

    def _on_failed(self, message: str):
        self.error_signal.emit(self.profile_id, message)


class CheckAllProxiesWorker(_BridgeBackedThread):
    progress_signal = Signal(int, int, str)  # current, total, profile_name
    finished_signal = Signal(list)

    def __init__(self, profiles, profiles_dir: Path):
        self.profiles = profiles
        self.profiles_dir = profiles_dir
        super().__init__(_tasks.check_all_proxies, args=(profiles, profiles_dir))
        self._progress.connect(self._on_progress)
        self._done.connect(self._on_done)
        self._failed.connect(self._on_failed)

    def _on_progress(self, payload: object):
        if not isinstance(payload, tuple) or len(payload) != 3:
            return
        idx, total, name = payload
        if not isinstance(idx, int) or not isinstance(total, int) or not isinstance(name, str):
            return
        self.progress_signal.emit(idx, total, name)

    def _on_done(self, results: object):
        self.finished_signal.emit(results if isinstance(results, list) else [])

    def _on_failed(self, message: str):
        self.finished_signal.emit([])

    def _on_bridge_cancelled(self):
        # Hunt G-03: a user cancel used to be completely SILENT — no
        # finished_signal, nothing: the view kept its "Checks completed"
        # contract unmet and the progress label froze mid-run. Deliver the
        # partial results collected so far (the task's list is not handed
        # over on a cancel), then the base aborted signal.
        self.finished_signal.emit([])
        super()._on_bridge_cancelled()


class AutopostBatchWorker(_BridgeBackedThread):
    job_update_signal = Signal(str, str, str)  # profile_id, status, message
    batch_finished_signal = Signal(list)

    def __init__(
        self,
        profile_manager,
        browser_launcher,
        profile_ids: list[str],
        source_video_path: Path,
        title_template: str,
        description_template: str,
        tg_channel: str = "@your_vpn_bot",
    ):
        self.profile_manager = profile_manager
        self.browser_launcher = browser_launcher
        self.profile_ids = profile_ids
        self.source_video_path = source_video_path
        self.title_template = title_template
        self.description_template = description_template
        self.tg_channel = tg_channel
        super().__init__(
            _tasks.run_autopost_batch,
            kwargs={
                "profile_manager": profile_manager,
                "browser_launcher": browser_launcher,
                "profile_ids": profile_ids,
                "source_video_path": source_video_path,
                "title_template": title_template,
                "description_template": description_template,
                "tg_channel": tg_channel,
            },
        )
        self._progress.connect(self._on_progress)
        self._done.connect(self._on_done)
        self._failed.connect(self._on_failed)

    def cancel(self):
        super().cancel()

    def _on_progress(self, payload: object):
        if not isinstance(payload, tuple) or len(payload) != 3:
            return
        pid, status, message = payload
        if not isinstance(pid, str) or not isinstance(status, str) or not isinstance(message, str):
            return
        self.job_update_signal.emit(pid, status, message)

    def _on_done(self, results: object):
        self.batch_finished_signal.emit(results if isinstance(results, list) else [])

    def _on_failed(self, message: str):
        self.batch_finished_signal.emit([])

    def _on_bridge_cancelled(self):
        # Hunt G-02: the base class only emits _aborted on a TaskCanceled —
        # batch_finished_signal never arrived, so the view never re-enabled
        # its "Start Autoposting" buttons (they stayed "Running..." until the
        # whole app was restarted). The aborted run must look like a finished
        # batch with the per-profile cancelled verdicts the view already
        # understands, then the normal completion path runs.
        self.job_update_signal.emit("batch", "canceled", "Batch canceled by user")
        self.batch_finished_signal.emit([{"profile_id": pid, "status": "canceled"} for pid in self.profile_ids])
        super()._on_bridge_cancelled()


class ProxyRotateWorker(_BridgeBackedThread):
    """Triggers rotation_url outside the main thread (audit R3)."""

    finished_signal = Signal(str, int)  # profile_id, http_status
    error_signal = Signal(str, str)  # profile_id, error message

    def __init__(self, profile_id: str, rotation_url: str, timeout: float = 8.0):
        self.profile_id = profile_id
        self.rotation_url = rotation_url
        self.timeout = timeout
        super().__init__(_tasks.rotate_proxy, args=(profile_id, rotation_url, timeout))
        self._done.connect(self._on_done)
        self._failed.connect(self._on_failed)

    def _on_done(self, status: object):
        code = 0
        try:
            if isinstance(status, (bool, int, float, str)):
                code = int(status)
        except (TypeError, ValueError):
            code = 0
        self.finished_signal.emit(self.profile_id, code)

    def _on_failed(self, message: str):
        self.error_signal.emit(self.profile_id, message)


class WarmupScenarioWorker(_BridgeBackedThread):
    """Runs a warmup scenario with real CDP page actions (audit fix P0-3/C1)."""

    progress_signal = Signal(str, int, int, str)  # profile_id, idx, total, description
    finished_signal = Signal(object)  # scenario result dict
    error_signal = Signal(str)  # error message

    def __init__(self, profile_manager, browser_launcher, scenario: WarmupScenario, profile_id: str):
        self.profile_manager = profile_manager
        self.browser_launcher = browser_launcher
        self.scenario = scenario
        self.profile_id = profile_id
        super().__init__(
            _tasks.run_warmup_scenario,
            kwargs={
                "profile_manager": profile_manager,
                "browser_launcher": browser_launcher,
                "scenario": scenario,
                "profile_id": profile_id,
            },
        )
        self._progress.connect(self._on_progress)
        self._done.connect(self._on_done)
        self._failed.connect(self._on_failed)
        self._aborted.connect(self._on_aborted)

    def cancel(self):
        super().cancel()
        try:
            self.browser_launcher.stop(self.profile_id)
        except Exception:
            pass

    def _on_progress(self, payload: object):
        if not isinstance(payload, tuple) or len(payload) != 4:
            return
        pid, idx, total, desc = payload
        if (
            not isinstance(pid, str)
            or not isinstance(idx, int)
            or not isinstance(total, int)
            or not isinstance(desc, str)
        ):
            return
        self.progress_signal.emit(pid, idx, total, desc)

    def _on_done(self, result: object):
        if isinstance(result, dict):
            self.finished_signal.emit(result)
        else:
            self.finished_signal.emit(
                {"profile_id": self.profile_id, "success": False, "canceled": True, "error": "Canceled by user"}
            )

    def _on_failed(self, message: str):
        if "Canceled" in message or "cancel" in message.lower():
            self._on_aborted()
        else:
            self.error_signal.emit(message)

    def _on_aborted(self):
        self.finished_signal.emit(
            {"profile_id": self.profile_id, "success": False, "canceled": True, "error": "Canceled by user"}
        )
