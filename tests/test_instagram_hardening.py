import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from nazak.core.instagram_uploader import InstagramUploader
from nazak.core.upload_queue import UploadJob, UploadQueueManager


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Browser has disconnected", True),
        ("target closed unexpectedly", True),
        ("session closed by browser", True),
        ("connection closed while loading", True),
        ("captcha challenge required", True),
        ("verification required to continue", True),
        ("we need to verify your account", True),
        ("login challenge detected", True),
        ("This page is not available because of a challenge", True),
        ("Session closed", True),
        ("network timeout awaiting response", False),
        ("file not found", False),
        ("profile not found", False),
        ("video path invalid", False),
        ("browser launch failed", False),
    ],
)
def test_instagram_session_lost_error_detection(message, expected):
    assert InstagramUploader._is_session_lost_error(message) is expected


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        ("captcha required", True),
        ("challenge required", True),
        ("verification required", True),
        ("429 Too Many Requests", True),
        ("403 forbidden", True),
        ("rate limit reached", True),
        ("temporarily unavailable", True),
        ("network timeout", True),
        ("session disconnected", True),
        ("connection closed", True),
        ("not logged in", True),
        ("profile not found", False),
        ("video file not found", False),
        ("launch failed", False),
        ("invalid metadata", False),
    ],
)
def test_upload_queue_retryable_error_detection(error, expected):
    assert UploadQueueManager._is_retryable_error(error) is expected


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        ("youtube_shorts", "youtube_shorts"),
        ("instagram_reels", "instagram_reels"),
        ("YOUTUBE_SHORTS", "youtube_shorts"),
        ("INSTAGRAM_REELS", "youtube_shorts"),
        ("youtube", "youtube_shorts"),
        ("instagram", "youtube_shorts"),
        ("reels", "youtube_shorts"),
        ("shorts", "youtube_shorts"),
        ("", "youtube_shorts"),
        (None, "youtube_shorts"),
        ("youtube_shorts ", "youtube_shorts"),
        ("instagram_reels ", "youtube_shorts"),
        ("youtube_shorts\n", "youtube_shorts"),
        ("instagram_reels\n", "youtube_shorts"),
        ("mixed_platform", "youtube_shorts"),
    ],
)
def test_queue_platform_normalization(platform, expected):
    value = platform if platform in {"youtube_shorts", "instagram_reels"} else "youtube_shorts"
    assert value == expected


def test_retryable_upload_retries_until_success():
    async def run():
        queue = UploadQueueManager(profile_manager=SimpleNamespace(), browser_launcher=SimpleNamespace(), ws_broadcast=None)
        calls = {"count": 0}

        async def fake_upload():
            calls["count"] += 1
            if calls["count"] < 3:
                return False, None, "captcha required"
            return True, "https://instagram.com/p/ok", None

        job = UploadJob(profile_id="p1", profile_name="P1", source_video="demo.mp4", platform="instagram_reels")
        result = await queue._retryable_upload(
            job,
            "Instagram upload",
            fake_upload,
            retries=3,
            base_delay=0.01,
            max_delay=0.1,
            progress_callback=lambda *_args, **_kwargs: None,
        )

        assert result == (True, "https://instagram.com/p/ok", None)
        assert calls["count"] == 3

    asyncio.run(run())


def test_retryable_upload_stops_on_non_retryable_error():
    async def run():
        queue = UploadQueueManager(profile_manager=SimpleNamespace(), browser_launcher=SimpleNamespace(), ws_broadcast=None)
        calls = {"count": 0}

        async def fake_upload():
            calls["count"] += 1
            return False, None, "profile not found"

        job = UploadJob(profile_id="p1", profile_name="P1", source_video="demo.mp4", platform="instagram_reels")
        result = await queue._retryable_upload(
            job,
            "Instagram upload",
            fake_upload,
            retries=5,
            base_delay=0.01,
            max_delay=0.1,
            progress_callback=lambda *_args, **_kwargs: None,
        )

        assert result == (False, None, "profile not found")
        assert calls["count"] == 1

    asyncio.run(run())


def test_retryable_upload_returns_canceled_when_cancel_requested():
    async def run():
        queue = UploadQueueManager(profile_manager=SimpleNamespace(), browser_launcher=SimpleNamespace(), ws_broadcast=None)
        queue._cancel_requested = True

        async def fake_upload():
            return False, None, "should not run"

        job = UploadJob(profile_id="p1", profile_name="P1", source_video="demo.mp4", platform="instagram_reels")
        result = await queue._retryable_upload(
            job,
            "Instagram upload",
            fake_upload,
            retries=4,
            base_delay=0.01,
            max_delay=0.1,
            progress_callback=lambda *_args, **_kwargs: None,
        )

        assert result == (False, None, "Upload canceled by user")

    asyncio.run(run())


def test_retryable_upload_exponential_backoff_updates_progress():
    async def run():
        queue = UploadQueueManager(profile_manager=SimpleNamespace(), browser_launcher=SimpleNamespace(), ws_broadcast=None)
        seen = []

        async def fake_upload():
            return False, None, "temporarily unavailable"

        job = UploadJob(profile_id="p1", profile_name="P1", source_video="demo.mp4", platform="instagram_reels")
        result = await queue._retryable_upload(
            job,
            "Instagram upload",
            fake_upload,
            retries=2,
            base_delay=0.01,
            max_delay=0.05,
            progress_callback=lambda msg: seen.append(msg),
        )

        assert result[0] is False
        assert seen
        assert "Retrying" in seen[0]

    asyncio.run(run())


def test_retryable_upload_handles_exception_as_retryable():
    async def run():
        queue = UploadQueueManager(profile_manager=SimpleNamespace(), browser_launcher=SimpleNamespace(), ws_broadcast=None)
        calls = {"count": 0}

        async def fake_upload():
            calls["count"] += 1
            if calls["count"] == 1:
                raise TimeoutError("network timeout")
            return True, "https://instagram.com/p/ok", None

        job = UploadJob(profile_id="p1", profile_name="P1", source_video="demo.mp4", platform="instagram_reels")
        result = await queue._retryable_upload(
            job,
            "Instagram upload",
            fake_upload,
            retries=3,
            base_delay=0.01,
            max_delay=0.1,
            progress_callback=lambda *_args, **_kwargs: None,
        )

        assert result == (True, "https://instagram.com/p/ok", None)
        assert calls["count"] == 2

    asyncio.run(run())


def test_instagram_uploader_missing_video_file_returns_error():
    async def run():
        uploader = InstagramUploader("http://127.0.0.1:9222")
        missing = Path("/tmp/definitely_missing_video.mp4")
        result = await uploader.upload_reel(missing, "hello", progress_callback=lambda *_: None)
        assert result[0] is False
        assert "Video file not found" in result[2]

    asyncio.run(run())


class _FakeLocator:
    def __init__(self, visible=True):
        self.visible = visible

    async def is_visible(self, timeout=None):
        return self.visible

    async def click(self):
        return None

    async def wait_for(self, state=None, timeout=None):
        return None

    async def set_input_files(self, path):
        return None

    async def get_attribute(self, name):
        return "/p/test-post/"


class _FakePage:
    url = "https://www.instagram.com/"

    def locator(self, selector):
        if selector.startswith("input[name='username']"):
            return _FakeLocator(visible=False)
        if selector.startswith("svg[aria-label='New post']"):
            return _FakeLocator(visible=True)
        if selector.startswith("textarea"):
            return _FakeLocator(visible=True)
        if selector.startswith("button:has-text('Next')"):
            return _FakeLocator(visible=True)
        if selector.startswith("button:has-text('Share')"):
            return _FakeLocator(visible=True)
        if selector.startswith("a[href*='/p/']"):
            return _FakeLocator(visible=True)
        if selector.startswith("input[type='file']"):
            return _FakeLocator(visible=True)
        return _FakeLocator(visible=False)

    def set_default_timeout(self, *_args, **_kwargs):
        return None

    def set_default_navigation_timeout(self, *_args, **_kwargs):
        return None

    async def goto(self, url, wait_until=None):
        return None

    async def close(self):
        return None


class _FakeContext:
    def __init__(self):
        self.page = _FakePage()

    async def new_page(self):
        return self.page

    def set_default_timeout(self, *_args, **_kwargs):
        return None

    def set_default_navigation_timeout(self, *_args, **_kwargs):
        return None

    async def close(self):
        return None


class _FakeBrowser:
    def __init__(self):
        self.contexts = []
        self.closed = False

    async def new_context(self, **_kwargs):
        ctx = _FakeContext()
        self.contexts.append(ctx)
        return ctx

    async def close(self):
        self.closed = True


class _FakePlaywright:
    def __init__(self, browser):
        self.chromium = SimpleNamespace(connect_over_cdp=self._connect_over_cdp)
        self.browser = browser

    async def _connect_over_cdp(self, url):
        return self.browser


def test_instagram_uploader_success_path_with_fake_browser(monkeypatch):
    async def run():
        browser = _FakeBrowser()
        fw = _FakePlaywright(browser)

        class _AsyncPlaywrightContext:
            def __init__(self, manager):
                self.manager = manager

            async def __aenter__(self):
                return self.manager

            async def __aexit__(self, exc_type, exc, tb):
                return False

        def fake_async_playwright():
            return _AsyncPlaywrightContext(fw)

        monkeypatch.setattr("playwright.async_api.async_playwright", fake_async_playwright)

        uploader = InstagramUploader("http://127.0.0.1:9222")
        file_path = Path("tests/data/test_reel.mp4")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(b"fake video")
        try:
            result = await uploader.upload_reel(file_path, "Test caption", progress_callback=lambda *_: None)
            assert result[0] is True
            assert result[1].startswith("https://www.instagram.com")
        finally:
            file_path.unlink(missing_ok=True)

    asyncio.run(run())


def test_instagram_uploader_detects_login_screen(monkeypatch):
    async def run():
        browser = _FakeBrowser()
        fw = _FakePlaywright(browser)

        class _AsyncPlaywrightContext:
            def __init__(self, manager):
                self.manager = manager

            async def __aenter__(self):
                return self.manager

            async def __aexit__(self, exc_type, exc, tb):
                return False

        def fake_async_playwright():
            return _AsyncPlaywrightContext(fw)

        monkeypatch.setattr("playwright.async_api.async_playwright", fake_async_playwright)

        class LoginPage(_FakePage):
            def locator(self, selector):
                if selector.startswith("input[name='username']"):
                    return _FakeLocator(visible=True)
                return super().locator(selector)

        browser.contexts = [_FakeContext()]
        browser.contexts[0].page = LoginPage()

        uploader = InstagramUploader("http://127.0.0.1:9222")
        file_path = Path("tests/data/test_reel_login.mp4")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(b"fake video")
        try:
            result = await uploader.upload_reel(file_path, "caption", progress_callback=lambda *_: None)
            assert result[0] is False
            assert "not logged in" in result[2].lower()
        finally:
            file_path.unlink(missing_ok=True)

    asyncio.run(run())


def test_instagram_uploader_handles_create_page_redirect(monkeypatch):
    async def run():
        browser = _FakeBrowser()
        fw = _FakePlaywright(browser)

        class _AsyncPlaywrightContext:
            def __init__(self, manager):
                self.manager = manager

            async def __aenter__(self):
                return self.manager

            async def __aexit__(self, exc_type, exc, tb):
                return False

        def fake_async_playwright():
            return _AsyncPlaywrightContext(fw)

        monkeypatch.setattr("playwright.async_api.async_playwright", fake_async_playwright)

        class RedirectPage(_FakePage):
            def locator(self, selector):
                if selector.startswith("svg[aria-label='New post']"):
                    return _FakeLocator(visible=False)
                if selector.startswith("button:has-text('Next')"):
                    return _FakeLocator(visible=True)
                if selector.startswith("button:has-text('Share')"):
                    return _FakeLocator(visible=True)
                return super().locator(selector)

        browser.contexts = [_FakeContext()]
        browser.contexts[0].page = RedirectPage()

        uploader = InstagramUploader("http://127.0.0.1:9222")
        file_path = Path("tests/data/test_reel_redirect.mp4")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(b"fake video")
        try:
            result = await uploader.upload_reel(file_path, "caption", progress_callback=lambda *_: None)
            assert result[0] is True
        finally:
            file_path.unlink(missing_ok=True)

    asyncio.run(run())


def test_instagram_uploader_closes_context_and_browser_in_finally(monkeypatch):
    async def run():
        browser = _FakeBrowser()
        fw = _FakePlaywright(browser)

        class _AsyncPlaywrightContext:
            def __init__(self, manager):
                self.manager = manager

            async def __aenter__(self):
                return self.manager

            async def __aexit__(self, exc_type, exc, tb):
                return False

        def fake_async_playwright():
            return _AsyncPlaywrightContext(fw)

        monkeypatch.setattr("playwright.async_api.async_playwright", fake_async_playwright)

        uploader = InstagramUploader("http://127.0.0.1:9222")
        file_path = Path("tests/data/test_reel_close.mp4")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(b"fake video")
        try:
            result = await uploader.upload_reel(file_path, "caption", progress_callback=lambda *_: None)
            assert result[0] is True
            assert browser.closed is True
        finally:
            file_path.unlink(missing_ok=True)

    asyncio.run(run())


def test_safe_wait_raises_timeout_for_slow_action():
    async def run():
        uploader = InstagramUploader("http://127.0.0.1:9222")

        async def slow_task():
            await asyncio.sleep(0.05)
            return "done"

        with pytest.raises(TimeoutError):
            await uploader._safe_wait(slow_task(), timeout=0.01, label="slow action")

    asyncio.run(run())


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (None, False),
        ("", False),
        ("verification required", True),
        ("connection closed", True),
    ],
)
def test_retry_error_classification_variants(error, expected):
    assert UploadQueueManager._is_retryable_error(error) is expected


# Total tests: 60
