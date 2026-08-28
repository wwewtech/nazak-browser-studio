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
from ..core.youtube_uploader import YouTubeUploader
from ..models.health import HealthCheckResult
from ..models.profile import BrowserProfile, ProfileStatus


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

                self.job_update_signal.emit(pid, "uniqueizing", "Уникализация видео и сдвиг частот...")
                ok, out_path, err = self.uniquifier.uniquify_video(self.source_video_path, pid, profile_index=idx)
                if not ok or not out_path:
                    self.job_update_signal.emit(pid, "failed", f"Ошибка видео: {err}")
                    continue

                meta = format_video_metadata(
                    title_template=self.title_template,
                    description_template=self.description_template,
                    profile_name=prof.name,
                    profile_id=pid,
                    tg_channel=self.tg_channel,
                )

                self.job_update_signal.emit(pid, "launching", "Запуск изолированного браузера...")
                cdp_port = 9350 + idx
                launch_ok, pid_num, launch_err = self.browser_launcher.launch(prof, cdp_port=cdp_port)
                if not launch_ok:
                    self.job_update_signal.emit(pid, "failed", f"Ошибка запуска: {launch_err}")
                    continue

                prof.status = ProfileStatus.RUNNING
                prof.pid = pid_num
                self.profile_manager.update_profile(prof)
                await asyncio.sleep(4)

                self.job_update_signal.emit(pid, "uploading", "Загрузка Shorts в YouTube Studio...")

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
                    self.job_update_signal.emit(pid, "published", f"Опубликовано! {video_url or ''}")
                    results.append({"profile_id": pid, "status": "published", "url": video_url})
                else:
                    self.job_update_signal.emit(pid, "failed", upload_err or "Ошибка загрузки")
                    results.append({"profile_id": pid, "status": "failed", "error": upload_err})

                await asyncio.sleep(3)

            return results

        results = loop.run_until_complete(_run_autopost())
        loop.close()
        self.batch_finished_signal.emit(results)
