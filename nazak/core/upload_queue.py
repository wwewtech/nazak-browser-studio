"""
Automated Batch Upload Queue Coordinator.
Sequentially or concurrently schedules video uniqueization, browser launch with CDP,
and stealth YouTube Shorts uploads across multiple isolated profiles.
"""

import asyncio
import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..models.profile import ProfileStatus
from .instagram_uploader import InstagramUploader
from .spintax import format_video_metadata
from .video_uniquifier import VideoUniquifier
from .youtube_uploader import YouTubeUploader

RETRYABLE_UPLOAD_ERRORS = (
    "captcha",
    "challenge",
    "verify",
    "verification",
    "timeout",
    "temporarily unavailable",
    "429",
    "403",
    "rate limit",
    "network",
    "session disconnected",
    "connection closed",
    "not logged in",
)


async def notify_progress(progress_callback: Callable | None, message: str):
    if not progress_callback:
        return
    result = progress_callback(message)
    if asyncio.iscoroutine(result):
        await result


@dataclass
class UploadJob:
    profile_id: str
    profile_name: str
    source_video: str
    platform: str = "youtube_shorts"
    unique_video: str | None = None
    title: str = ""
    description: str = ""
    status: str = "pending"  # pending, uniqueizing, launching, uploading, published, failed, canceled
    video_url: str | None = None
    error: str | None = None
    progress_message: str = "In queue"
    started_at: str | None = None
    completed_at: str | None = None


class UploadQueueManager:
    """
    Manages automated posting tasks across multiple profiles.
    """

    def __init__(self, profile_manager, browser_launcher, ws_broadcast: Callable | None = None):
        self.profile_manager = profile_manager
        self.browser_launcher = browser_launcher
        self.ws_broadcast = ws_broadcast
        self.uniquifier = VideoUniquifier()
        self.jobs: dict[str, UploadJob] = {}
        self.is_running = False
        self._cancel_requested = False
        self._batch_lock = asyncio.Lock()
        self._profile_locks: dict[str, asyncio.Lock] = {}

    async def broadcast(self, event: str, data: dict[str, Any]):
        if self.ws_broadcast:
            try:
                await self.ws_broadcast(event, data)
            except Exception:
                pass

    def get_jobs_status(self) -> list[dict[str, Any]]:
        return [
            {
                "profile_id": j.profile_id,
                "profile_name": j.profile_name,
                "source_video": j.source_video,
                "platform": j.platform,
                "unique_video": j.unique_video,
                "title": j.title,
                "status": j.status,
                "video_url": j.video_url,
                "error": j.error,
                "progress_message": j.progress_message,
                "started_at": j.started_at,
                "completed_at": j.completed_at,
            }
            for j in self.jobs.values()
        ]

    def cancel_all(self):
        self._cancel_requested = True
        for j in self.jobs.values():
            if j.status in ("pending", "uniqueizing", "launching", "uploading"):
                j.status = "canceled"
                j.progress_message = "Upload canceled by user"

    @staticmethod
    def _is_retryable_error(err: str | None) -> bool:
        if not err:
            return False
        lowered = err.lower()
        return any(token in lowered for token in RETRYABLE_UPLOAD_ERRORS)

    async def _retryable_upload(
        self,
        job: UploadJob,
        task_name: str,
        upload_callable,
        *,
        retries: int = 3,
        base_delay: float = 2.0,
        max_delay: float = 30.0,
        progress_callback: Callable | None = None,
    ) -> tuple[bool, str | None, str | None]:
        last_error = None
        for attempt in range(1, retries + 2):
            if self._cancel_requested:
                return False, None, "Upload canceled by user"
            try:
                ok, url, err = await upload_callable()
                if ok:
                    return True, url, None
                last_error = err or "Upload failed"
                if not self._is_retryable_error(last_error):
                    return False, None, last_error
            except Exception as exc:  # pragma: no cover - defensive path for unexpected runtime failures
                last_error = f"{task_name} error: {exc!s}"
                if not self._is_retryable_error(last_error):
                    return False, None, last_error

            if attempt > retries:
                break

            delay = min(base_delay * (2 ** (attempt - 1)), max_delay) + random.uniform(0.25, 1.25)
            job.progress_message = f"{task_name} failed. Retrying in {delay:.1f}s (attempt {attempt}/{retries})..."
            await notify_progress(progress_callback, job.progress_message)
            await asyncio.sleep(delay)

        return False, None, last_error or f"{task_name} failed after retries"

    async def run_batch_upload(
        self,
        profile_ids: list[str],
        source_video_path: Path,
        title_template: str,
        description_template: str,
        tg_channel: str = "@your_vpn_bot",
        delay_between_accounts_sec: int = 10,
        platform: str = "youtube_shorts",
    ):
        """
        Executes the full automated uniqueize + upload workflow across chosen profiles.
        """
        async with self._batch_lock:
            if self.is_running:
                return
            self.is_running = True
            self._cancel_requested = False
            self.jobs = {}

        platform_name = platform if platform in {"youtube_shorts", "instagram_reels"} else "youtube_shorts"

        try:
            for pid in profile_ids:
                prof = self.profile_manager.get_profile(pid)
                pname = prof.name if prof else pid
                self.jobs[pid] = UploadJob(
                    profile_id=pid,
                    profile_name=pname,
                    source_video=str(source_video_path.name),
                    platform=platform_name,
                )

            await self.broadcast("autopost_batch_started", {"total": len(profile_ids)})

            for idx, pid in enumerate(profile_ids, start=1):
                if self._cancel_requested:
                    break

                job = self.jobs[pid]
                profile_lock = self._profile_locks.setdefault(pid, asyncio.Lock())
                async with profile_lock:
                    prof = self.profile_manager.get_profile(pid)
                    if not prof:
                        job.status = "failed"
                        job.error = "Profile not found"
                        continue

                    job.started_at = datetime.now(timezone.utc).isoformat()
                    job.status = "uniqueizing"
                    job.progress_message = "Generating unique video hash & audio shift..."
                    await self.broadcast(
                        "autopost_job_update", {"profile_id": pid, "status": job.status, "message": job.progress_message}
                    )

                    ok, out_path, err = self.uniquifier.uniquify_video(source_video_path, pid, profile_index=idx)
                    if not ok or not out_path:
                        job.status = "failed"
                        job.error = f"Video uniqueization failed: {err}"
                        job.progress_message = "Uniqueization error"
                        await self.broadcast(
                            "autopost_job_update", {"profile_id": pid, "status": "failed", "error": job.error}
                        )
                        continue

                    job.unique_video = str(out_path.resolve())

                    meta = format_video_metadata(
                        title_template=title_template,
                        description_template=description_template,
                        profile_name=prof.name,
                        profile_id=pid,
                        tg_channel=tg_channel,
                    )
                    job.title = meta["title"]
                    job.description = meta["description"]

                    job.status = "launching"
                    job.progress_message = "Launching isolated anti-detect browser session..."
                    await self.broadcast(
                        "autopost_job_update", {"profile_id": pid, "status": job.status, "message": job.progress_message}
                    )

                    cdp_port = 9300 + idx
                    launch_ok, pid_num, launch_err = self.browser_launcher.launch(prof, cdp_port=cdp_port)
                    if not launch_ok:
                        job.status = "failed"
                        job.error = f"Browser launch failed: {launch_err}"
                        job.progress_message = "Launch error"
                        await self.broadcast(
                            "autopost_job_update", {"profile_id": pid, "status": "failed", "error": job.error}
                        )
                        continue

                    prof.status = ProfileStatus.RUNNING
                    prof.pid = pid_num
                    self.profile_manager.update_profile(prof)
                    await asyncio.sleep(4)

                    job.status = "uploading"
                    target_label = "YouTube Studio" if platform_name == "youtube_shorts" else "Instagram"
                    job.progress_message = f"Uploading to {target_label}..."
                    await self.broadcast(
                        "autopost_job_update", {"profile_id": pid, "status": job.status, "message": job.progress_message}
                    )

                    curr_job = job
                    curr_pid = pid

                    async def on_progress(msg: str, j=curr_job, p=curr_pid):
                        j.progress_message = msg
                        await self.broadcast("autopost_job_update", {"profile_id": p, "status": j.status, "message": msg})

                    if platform_name == "instagram_reels":
                        uploader = InstagramUploader(f"http://127.0.0.1:{cdp_port}")

                        async def upload_task(
                            video_path=out_path,
                            current_job=job,
                            platform_uploader=uploader,
                            progress=on_progress,
                        ):
                            return await platform_uploader.upload_reel(
                                video_path=video_path,
                                caption=current_job.description,
                                progress_callback=progress,
                            )

                        upload_ok, video_url, upload_err = await self._retryable_upload(
                            job,
                            task_name="Instagram upload",
                            upload_callable=upload_task,
                            retries=3,
                            base_delay=2.0,
                            progress_callback=on_progress,
                        )
                    else:
                        uploader = YouTubeUploader(f"http://127.0.0.1:{cdp_port}")

                        async def upload_task(
                            video_path=out_path,
                            current_job=job,
                            platform_uploader=uploader,
                            progress=on_progress,
                        ):
                            return await platform_uploader.upload_shorts(
                                video_path=video_path,
                                title=current_job.title,
                                description=current_job.description,
                                progress_callback=progress,
                            )

                        upload_ok, video_url, upload_err = await self._retryable_upload(
                            job,
                            task_name="YouTube upload",
                            upload_callable=upload_task,
                            retries=3,
                            base_delay=2.0,
                            progress_callback=on_progress,
                        )

                    self.browser_launcher.stop(pid)
                    prof.status = ProfileStatus.STOPPED
                    prof.pid = None
                    self.profile_manager.update_profile(prof)

                    job.completed_at = datetime.now(timezone.utc).isoformat()
                    if upload_ok:
                        job.status = "published"
                        job.video_url = video_url
                        job.progress_message = "Published successfully!"
                        await self.broadcast(
                            "autopost_job_update",
                            {
                                "profile_id": pid,
                                "status": "published",
                                "video_url": video_url,
                                "message": "Published successfully!",
                            },
                        )
                    else:
                        job.status = "failed"
                        job.error = upload_err
                        job.progress_message = upload_err or "Upload failed"
                        await self.broadcast(
                            "autopost_job_update",
                            {
                                "profile_id": pid,
                                "status": "failed",
                                "error": upload_err,
                                "message": upload_err or "Upload failed",
                            },
                        )

                    if idx < len(profile_ids) and not self._cancel_requested:
                        delay = random.randint(max(5, delay_between_accounts_sec - 3), delay_between_accounts_sec + 5)
                        await asyncio.sleep(delay)

        finally:
            self.is_running = False
            await self.broadcast("autopost_batch_finished", {"results": self.get_jobs_status()})
