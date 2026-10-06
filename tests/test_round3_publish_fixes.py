"""Round-3 audit regression tests — честность публикации и ретраев (R3-06, R3-11, R3-25).

Проверяют: нормализацию платформы, политику ретраев (`403` не ретраится,
`publish-uncertain` запрещает повтор), отсутствие «зависших» job'ов и то, что
`cancel_all` не гасит сессии, которые очередь не поднимала.
"""

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from nazak.core.publish_status import is_publish_uncertain, publish_uncertain
from nazak.core.upload_queue import UploadQueueManager, normalize_upload_platform
from nazak.models.profile import BrowserProfile


# --------------------------------------------------------------------------- R3-06 / R3-11 / R3-25
def test_r3_platform_normalization_is_case_insensitive():
    assert normalize_upload_platform("Instagram_Reels") == "instagram_reels"
    assert normalize_upload_platform("  YOUTUBE_SHORTS ") == "youtube_shorts"
    assert normalize_upload_platform(None) == "youtube_shorts"


def test_r3_403_is_not_retryable_and_publish_uncertain_blocks_retry():
    assert UploadQueueManager._is_retryable_error("HTTP 403 Forbidden") is False
    assert UploadQueueManager._is_retryable_error("connection closed by peer") is True
    assert UploadQueueManager._is_retryable_error(publish_uncertain("clicked")) is False
    assert is_publish_uncertain(publish_uncertain("clicked")) is True


class _FakeLauncher:
    def __init__(self):
        self.stopped: list[str] = []

    def launch(self, profile, custom_url=None, cdp_port=None):
        return True, 4242, None

    def stop(self, profile_id):
        self.stopped.append(profile_id)
        return True, None

    def is_profile_running(self, profile_id):
        return False


class _FakeProfileManager:
    def __init__(self, profiles: dict):
        self.profiles = profiles
        self.profiles_dir = Path.cwd()

    def get_profile(self, profile_id):
        return self.profiles.get(profile_id)

    def update_profile(self, profile):
        self.profiles[profile.id] = profile
        return profile


class _FakeUploader:
    """Загрузчик-двойник: считает вызовы и возвращает заданный результат."""

    calls = 0
    result: tuple = (True, "https://youtu.be/x", None)
    platform = "youtube_shorts"

    def __init__(self, *_args, **_kwargs):
        pass

    async def upload_shorts(self, **_kwargs):
        type(self).calls += 1
        return type(self).result

    async def upload_reel(self, **_kwargs):
        type(self).calls += 1
        return type(self).result


def test_r3_publish_uncertain_is_not_retried():
    launcher = _FakeLauncher()
    pm = _FakeProfileManager({"r3_ap": BrowserProfile(id="r3_ap", name="R3 AP")})
    mgr = UploadQueueManager(pm, launcher)
    _FakeUploader.calls = 0
    _FakeUploader.result = (False, None, publish_uncertain("Instagram: Share was clicked, result unverified"))
    mgr.uniquifier.uniquify_video = lambda *a, **k: (True, Path("out.mp4"), None)

    with (
        patch("nazak.core.upload_queue.get_free_port", return_value=9333),
        patch("nazak.core.upload_queue.InstagramUploader", _FakeUploader),
        patch("nazak.core.upload_queue.YouTubeUploader", _FakeUploader),
    ):
        asyncio.run(
            mgr.run_batch_upload(
                profile_ids=["r3_ap"],
                source_video_path=Path("in.mp4"),
                title_template="t",
                description_template="d",
                platform="instagram_reels",
            )
        )
    assert _FakeUploader.calls == 1, "публикация после клика Share была повторена"
    job = mgr.jobs["r3_ap"]
    assert job.status == "failed"
    assert job.error and is_publish_uncertain(job.error)
    assert "ретрай запрещён" in job.progress_message


def test_r3_retryable_error_is_still_retried():
    launcher = _FakeLauncher()
    pm = _FakeProfileManager({"r3_rt": BrowserProfile(id="r3_rt", name="R3 RT")})
    mgr = UploadQueueManager(pm, launcher)
    _FakeUploader.calls = 0
    _FakeUploader.result = (False, None, "network timeout while uploading")
    mgr.uniquifier.uniquify_video = lambda *a, **k: (True, Path("out.mp4"), None)

    async def _no_sleep(_seconds):
        return None

    with (
        patch("nazak.core.upload_queue.get_free_port", return_value=9333),
        patch("nazak.core.upload_queue.YouTubeUploader", _FakeUploader),
        patch("nazak.core.upload_queue.asyncio.sleep", side_effect=_no_sleep),
    ):
        asyncio.run(
            mgr.run_batch_upload(
                profile_ids=["r3_rt"],
                source_video_path=Path("in.mp4"),
                title_template="t",
                description_template="d",
            )
        )
    assert _FakeUploader.calls == 4, f"ожидалось 4 попытки (1+3 ретрая), получено {_FakeUploader.calls}"


def test_r3_cancel_all_does_not_kill_foreign_browsers():
    launcher = _FakeLauncher()
    pm = _FakeProfileManager({"r3_x": BrowserProfile(id="r3_x", name="X")})
    mgr = UploadQueueManager(pm, launcher)
    _FakeUploader.calls = 0
    _FakeUploader.result = (True, "https://youtu.be/x", None)

    async def _no_sleep(_seconds):
        return None

    mgr.uniquifier.uniquify_video = lambda *a, **k: (True, Path("out.mp4"), None)
    with (
        patch("nazak.core.upload_queue.get_free_port", return_value=9333),
        patch("nazak.core.upload_queue.YouTubeUploader", _FakeUploader),
        patch("nazak.core.upload_queue.asyncio.sleep", side_effect=_no_sleep),
    ):
        asyncio.run(
            mgr.run_batch_upload(
                profile_ids=["r3_x"],
                source_video_path=Path("in.mp4"),
                title_template="t",
                description_template="d",
            )
        )
    assert launcher.stopped == ["r3_x"], "очередь обязана закрыть СВОЙ браузер после батча"
    launcher.stopped.clear()
    mgr.jobs["r3_x"].status = "uploading"  # имитируем «зависший» job
    mgr.cancel_all()
    assert launcher.stopped == [], "cancel_all убил браузер, который очередь не поднимала"


def test_r3_unexpected_error_leaves_no_stuck_job():
    class _ExplodingUniquifier:
        def uniquify_video(self, *a, **k):
            raise RuntimeError("boom")

    launcher = _FakeLauncher()
    pm = _FakeProfileManager({"r3_e": BrowserProfile(id="r3_e", name="E")})
    mgr = UploadQueueManager(pm, launcher)
    mgr.uniquifier = _ExplodingUniquifier()

    with pytest.raises(RuntimeError):
        asyncio.run(
            mgr.run_batch_upload(
                profile_ids=["r3_e"],
                source_video_path=Path("in.mp4"),
                title_template="t",
                description_template="d",
            )
        )
    assert mgr.jobs["r3_e"].status == "failed"
    assert mgr.jobs["r3_e"].status != "uploading"
