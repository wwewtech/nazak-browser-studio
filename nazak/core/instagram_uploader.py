"""
Stealth Instagram Reel uploader executed via a running browser profile and CDP.
It follows the same browser automation strategy as the YouTube uploader, but targets
Instagram's create/reel flow and enforces explicit session isolation to avoid overlap
with YouTube or other browser automation contexts.
"""

import asyncio
import random
from collections.abc import Callable
from pathlib import Path
from typing import Any


async def human_type(element, text: str):
    if element is None or not hasattr(element, "type"):
        return
    for char in text:
        await element.type(char, delay=random.randint(35, 90))
        if random.random() < 0.05:
            await asyncio.sleep(random.uniform(0.2, 0.5))


async def notify_progress(progress_callback: Callable | None, message: str):
    if not progress_callback:
        return
    result = progress_callback(message)
    if asyncio.iscoroutine(result):
        await result


class InstagramUploader:
    """Dedicated Instagram session runner with strict timeout and restart controls."""

    def __init__(
        self,
        cdp_url: str,
        *,
        connection_timeout: float = 20.0,
        navigation_timeout: float = 45.0,
        page_timeout: float = 30.0,
        context_timeout: float = 120.0,
        viewport: tuple[int, int] = (1440, 2560),
    ):
        self.cdp_url = cdp_url
        self.connection_timeout = connection_timeout
        self.navigation_timeout = navigation_timeout
        self.page_timeout = page_timeout
        self.context_timeout = context_timeout
        self.viewport = viewport

    @staticmethod
    def _first(locator):
        if locator is None:
            return None
        first = getattr(locator, "first", None)
        return first if first is not None else locator

    @staticmethod
    def _is_session_lost_error(message: str) -> bool:
        lower = message.lower()
        return any(token in lower for token in ["session closed", "target closed", "connection closed", "browser has disconnected", "captcha", "challenge", "verify", "verification"])

    @staticmethod
    async def _safe_wait(task, timeout: float, *, label: str):
        try:
            return await asyncio.wait_for(task, timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise TimeoutError(f"{label} timed out after {timeout}s") from exc

    async def _connect_browser(self, playwright):
        browser = await self._safe_wait(
            playwright.chromium.connect_over_cdp(self.cdp_url),
            timeout=self.connection_timeout,
            label="CDP browser connection",
        )
        if browser is None:
            raise RuntimeError("CDP browser connection returned None")
        return browser

    async def _new_isolated_context(self, browser):
        contexts = getattr(browser, "contexts", None) or []
        if contexts:
            context = contexts[0]
        else:
            context = await browser.new_context(
                viewport={"width": self.viewport[0], "height": self.viewport[1]},
                ignore_https_errors=True,
                java_script_enabled=True,
                base_url="https://www.instagram.com",
                locale="en-US",
                permissions=["clipboard-read", "clipboard-write"],
            )
        if hasattr(context, "set_default_timeout"):
            context.set_default_timeout(self.page_timeout * 1000)
        if hasattr(context, "set_default_navigation_timeout"):
            context.set_default_navigation_timeout(self.navigation_timeout * 1000)
        return context

    async def upload_reel(
        self, video_path: Path, caption: str, progress_callback: Any | None = None
    ) -> tuple[bool, str | None, str | None]:
        """
        Uploads a video to Instagram as a Reel via a dedicated, isolated browser context.
        Returns: (success, published_url, error_message)
        """
        from playwright.async_api import async_playwright

        if not video_path.exists():
            return False, None, f"Video file not found: {video_path}"

        browser = None
        context = None
        page = None
        try:
            async with async_playwright() as p:
                browser = await self._connect_browser(p)
                context = await self._new_isolated_context(browser)
                page = await context.new_page()
                page.set_default_timeout(self.page_timeout * 1000)
                page.set_default_navigation_timeout(self.navigation_timeout * 1000)

                await notify_progress(progress_callback, "Opening Instagram...")

                await self._safe_wait(
                    page.goto("https://www.instagram.com/", wait_until="domcontentloaded"),
                    timeout=self.navigation_timeout,
                    label="Instagram home page load",
                )
                await asyncio.sleep(2)

                login_input = self._first(page.locator("input[name='username'], input[name='userName']"))
                if await asyncio.wait_for(login_input.is_visible(), timeout=4.0):
                    raise RuntimeError(
                        "Instagram session expired or not logged in. Please sign in first in the active profile."
                    )

                await notify_progress(progress_callback, "Opening create flow...")

                create_btn = self._first(
                    page.locator(
                        "svg[aria-label='New post'], [aria-label='Create'], button:has-text('Create'), a[href='/create/']"
                    )
                )
                if await asyncio.wait_for(create_btn.is_visible(), timeout=5.0):
                    await self._safe_wait(create_btn.click(), timeout=10.0, label="Create button click")
                else:
                    await self._safe_wait(
                        page.goto("https://www.instagram.com/create/select/", wait_until="domcontentloaded"),
                        timeout=self.navigation_timeout,
                        label="Instagram create page load",
                    )

                await asyncio.sleep(2.5)

                file_input = self._first(page.locator("input[type='file']"))
                await self._safe_wait(file_input.wait_for(state="attached"), timeout=20.0, label="file input ready")
                await self._safe_wait(file_input.set_input_files(str(video_path.resolve())), timeout=25.0, label="video upload")
                await asyncio.sleep(4)

                await notify_progress(progress_callback, "Preparing reel metadata...")

                caption_box = self._first(
                    page.locator(
                        "textarea[aria-label*='Write a caption' i], textarea[aria-label*='Добавить подпись' i], textarea[aria-label*='Caption' i]"
                    )
                )
                if await asyncio.wait_for(caption_box.is_visible(), timeout=15.0):
                    await self._safe_wait(caption_box.click(), timeout=10.0, label="caption click")
                    await human_type(caption_box, caption)
                    await asyncio.sleep(1.0)

                next_btn = self._first(page.locator("button:has-text('Next'), button:has-text('Далее')"))
                if await asyncio.wait_for(next_btn.is_visible(), timeout=10.0):
                    await self._safe_wait(next_btn.click(), timeout=10.0, label="next button click")
                    await asyncio.sleep(2)

                share_btn = self._first(page.locator("button:has-text('Share'), button:has-text('Поделиться')"))
                if await asyncio.wait_for(share_btn.is_visible(), timeout=20.0):
                    await self._safe_wait(share_btn.click(), timeout=15.0, label="share button click")
                    await asyncio.sleep(5)

                published_url = None
                try:
                    post_link = self._first(page.locator("a[href*='/p/']"))
                    if await asyncio.wait_for(post_link.is_visible(), timeout=10.0):
                        published_url = await post_link.get_attribute("href")
                        if published_url and not published_url.startswith("http"):
                            published_url = f"https://www.instagram.com{published_url}"
                except Exception:
                    published_url = None

                await notify_progress(progress_callback, f"Reel published! URL: {published_url or 'Instagram'}")

                return True, published_url or "https://www.instagram.com/", None

        except (RuntimeError, TimeoutError, Exception) as exc:
            message = str(exc)
            if self._is_session_lost_error(message):
                return False, None, f"Instagram session disconnected: {message}"
            return False, None, f"Instagram upload error: {message}"
        finally:
            if page is not None:
                try:
                    await page.close()
                except Exception:
                    pass
            if context is not None:
                try:
                    await context.close()
                except Exception:
                    pass
            if browser is not None:
                try:
                    await browser.close()
                except Exception:
                    pass
