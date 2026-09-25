"""
Qt Background Worker Threads.
Executes network diagnostics, browser lifecycle, FFmpeg video processing,
and automated YouTube Shorts posting without blocking the UI thread.
"""

import asyncio
from pathlib import Path
from typing import Any, Optional

from PyQt6.QtCore import QThread, pyqtSignal as Signal

from ..core.proxy_checker import check_proxy_health
from ..core.spintax import format_video_metadata
from ..core.video_uniquifier import VideoUniquifier
from ..core.warmup_engine import ScenarioExecutor, WarmupScenario
from ..core.youtube_uploader import YouTubeUploader
from ..models.health import HealthCheckResult
from ..models.profile import BrowserProfile, ProfileStatus


class _WarmupCanceled(Exception):
    """Raised from the progress callback to abort a running warmup scenario."""


class ProxyCheckWorker(QThread):
    finished_signal = Signal(str, object)  # profile_id, HealthCheckResult
    error_signal = Signal(str, str)

    def __init__(self, profile_id: str, proxy_config, profile_dir: Path | None = None):
        super().__init__()
        self.profile_id = profile_id
        self.proxy_config = proxy_config
        self.profile_dir = profile_dir

    def run(self):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            res = loop.run_until_complete(check_proxy_health(self.proxy_config, profile_dir=self.profile_dir))
            loop.close()
            self.finished_signal.emit(self.profile_id, res)
        except Exception as e:
            self.error_signal.emit(self.profile_id, str(e))


class CheckAllProxiesWorker(QThread):
    progress_signal = Signal(int, int, str)  # current, total, profile_name
    finished_signal = Signal(list)

    def __init__(self, profiles: list[BrowserProfile], profiles_dir: Path):
        super().__init__()
        self.profiles = profiles
        self.profiles_dir = profiles_dir

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def _run_all():
            results = []
            for idx, p in enumerate(self.profiles, start=1):
                self.progress_signal.emit(idx, len(self.profiles), p.name)
                p_dir = self.profiles_dir / p.id
                res = await check_proxy_health(p.proxy, profile_dir=p_dir)
                results.append((p.id, res))
            return results

        results = loop.run_until_complete(_run_all())
        loop.close()
        self.finished_signal.emit(results)


class AutopostBatchWorker(QThread):
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
        super().__init__()
        self.profile_manager = profile_manager
        self.browser_launcher = browser_launcher
        self.profile_ids = profile_ids
        self.source_video_path = source_video_path
        self.title_template = title_template
        self.description_template = description_template
        self.tg_channel = tg_channel
        self.uniquifier = VideoUniquifier()
        self._is_canceled = False

    def cancel(self):
        self._is_canceled = True

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def _run_autopost():
            results = []
            for idx, pid in enumerate(self.profile_ids, start=1):
                if self._is_canceled:
                    break

                prof = self.profile_manager.get_profile(pid)
                if not prof:
                    continue

                self.job_update_signal.emit(
                    pid, "uniqueizing", "Creating a unique video variant and shifting frequencies..."
                )
                ok, out_path, err = self.uniquifier.uniquify_video(self.source_video_path, pid, profile_index=idx)
                if not ok or not out_path:
                    self.job_update_signal.emit(pid, "failed", f"Video error: {err}")
                    continue

                meta = format_video_metadata(
                    title_template=self.title_template,
                    description_template=self.description_template,
                    profile_name=prof.name,
                    profile_id=pid,
                    tg_channel=self.tg_channel,
                )

                self.job_update_signal.emit(pid, "launching", "Launching isolated browser...")
                cdp_port = 9350 + idx
                launch_ok, pid_num, launch_err = self.browser_launcher.launch(prof, cdp_port=cdp_port)
                if not launch_ok:
                    self.job_update_signal.emit(pid, "failed", f"Launch error: {launch_err}")
                    continue

                prof.status = ProfileStatus.RUNNING
                prof.pid = pid_num
                self.profile_manager.update_profile(prof)
                await asyncio.sleep(4)

                self.job_update_signal.emit(pid, "uploading", "Uploading Shorts to YouTube Studio...")

                curr_pid = pid

                async def progress_cb(msg: str, p=curr_pid):
                    self.job_update_signal.emit(p, "uploading", msg)

                uploader = YouTubeUploader(f"http://127.0.0.1:{cdp_port}")
                upload_ok, video_url, upload_err = await uploader.upload_shorts(
                    video_path=out_path,
                    title=meta["title"],
                    description=meta["description"],
                    progress_callback=progress_cb,
                )

                self.browser_launcher.stop(pid)
                prof.status = ProfileStatus.STOPPED
                prof.pid = None
                self.profile_manager.update_profile(prof)

                if upload_ok:
                    self.job_update_signal.emit(pid, "published", f"Published! {video_url or ''}")
                    results.append({"profile_id": pid, "status": "published", "url": video_url})
                else:
                    self.job_update_signal.emit(pid, "failed", upload_err or "Upload error")
                    results.append({"profile_id": pid, "status": "failed", "error": upload_err})

                await asyncio.sleep(3)

            return results

        results = loop.run_until_complete(_run_autopost())
        loop.close()
        self.batch_finished_signal.emit(results)


class WarmupScenarioWorker(QThread):
    """Runs a warmup scenario with real CDP page actions (audit fix P0-3/C1)."""

    progress_signal = Signal(str, int, int, str)  # profile_id, idx, total, description
    finished_signal = Signal(object)  # scenario result dict
    error_signal = Signal(str)  # error message

    def __init__(self, profile_manager, browser_launcher, scenario: WarmupScenario, profile_id: str):
        super().__init__()
        self.profile_manager = profile_manager
        self.browser_launcher = browser_launcher
        self.scenario = scenario
        self.profile_id = profile_id
        self._is_canceled = False

    def cancel(self):
        # Cooperative cancel: stop the browser so in-flight CDP steps fail fast.
        self._is_canceled = True
        try:
            self.browser_launcher.stop(self.profile_id)
        except Exception:
            pass

    def run(self):
        executor = ScenarioExecutor(self.browser_launcher, self.profile_manager)
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            def _on_progress(pid: str, idx: int, total: int, desc: str):
                self.progress_signal.emit(pid, idx, total, desc)
                if self._is_canceled:
                    raise _WarmupCanceled()

            result = loop.run_until_complete(
                executor.run_scenario_on_profile(self.scenario, self.profile_id, progress_callback=_on_progress)
            )
            loop.close()
            if self._is_canceled:
                result["canceled"] = True
            self.finished_signal.emit(result)
        except _WarmupCanceled:
            self.finished_signal.emit(
                {"profile_id": self.profile_id, "success": False, "canceled": True, "error": "Canceled by user"}
            )
        except Exception as e:
            self.error_signal.emit(str(e))
