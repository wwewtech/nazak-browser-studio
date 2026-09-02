"""
Undetectable Stealth YouTube Shorts Uploader.
Connects via CDP to running anti-detect profiles with humanized Bezier mouse curves,
natural keystroke typing, and automatic YouTube Studio workflow execution.
"""

import asyncio
import math
import random
from collections.abc import Callable
from pathlib import Path
from typing import Any


async def notify_progress(progress_callback: Callable | None, message: str):
    if not progress_callback:
        return
    result = progress_callback(message)
    if asyncio.iscoroutine(result):
        await result


class HumanCursor:
    """
    Generates realistic cubic Bezier curve trajectories with natural tremor.
    """

    @staticmethod
    def bezier_point(p0: float, p1: float, p2: float, p3: float, t: float) -> float:
        return (1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t**2 * p2 + t**3 * p3

    @classmethod
    async def move_to(cls, page, target_x: float, target_y: float, current_x: float = 100, current_y: float = 100):
        """Moves mouse to target coords along realistic human trajectory."""
        distance = math.hypot(target_x - current_x, target_y - current_y)
        steps = max(15, int(distance / 25))

        # Random control points for Bezier curve
        ctrl1_x = current_x + (target_x - current_x) * 0.25 + random.uniform(-40, 40)
        ctrl1_y = current_y + (target_y - current_y) * 0.25 + random.uniform(-40, 40)
        ctrl2_x = current_x + (target_x - current_x) * 0.75 + random.uniform(-30, 30)
        ctrl2_y = current_y + (target_y - current_y) * 0.75 + random.uniform(-30, 30)

        for i in range(1, steps + 1):
            t = i / steps
            # Smooth ease-in-out curve
            ease_t = 0.5 - math.cos(t * math.pi) / 2
            x = cls.bezier_point(current_x, ctrl1_x, ctrl2_x, target_x, ease_t) + random.uniform(-1.5, 1.5)
            y = cls.bezier_point(current_y, ctrl1_y, ctrl2_y, target_y, ease_t) + random.uniform(-1.5, 1.5)
            await page.mouse.move(x, y)
            await asyncio.sleep(random.uniform(0.008, 0.022))

        # Final micro-adjustment
        await page.mouse.move(target_x, target_y)
        await asyncio.sleep(random.uniform(0.05, 0.12))


async def human_type(element, text: str):
    """
    Types text character-by-character with randomized human intervals.
    """
    for char in text:
        await element.type(char, delay=random.randint(40, 110))
        if random.random() < 0.06:
            # Natural thinking pause
            await asyncio.sleep(random.uniform(0.25, 0.55))


class YouTubeUploader:
    """
    Automated uploader executing stealth Shorts uploads via CDP.
    """

    def __init__(self, cdp_url: str):
        self.cdp_url = cdp_url

    async def upload_shorts(
        self, video_path: Path, title: str, description: str, progress_callback: Any | None = None
    ) -> tuple[bool, str | None, str | None]:
        """
        Uploads a video to YouTube Studio.
        Returns: (success, published_video_url, error_message)
        """
        from playwright.async_api import async_playwright

        if not video_path.exists():
            return False, None, f"Video file not found: {video_path}"

        async with async_playwright() as p:
            try:
                browser = await p.chromium.connect_over_cdp(self.cdp_url)
                context = browser.contexts[0] if browser.contexts else await browser.new_context()
                page = context.pages[0] if context.pages else await context.new_page()

                await notify_progress(progress_callback, "Navigating to YouTube Studio...")

                await page.goto("https://studio.youtube.com", wait_until="domcontentloaded", timeout=60000)
                await asyncio.sleep(3)

                # Check if account is logged in
                current_url = page.url
                if "accounts.google.com" in current_url or "ServiceLogin" in current_url:
                    await browser.close()
                    return (
                        False,
                        None,
                        "Account session expired or not logged in. Please log in first via '⚡ Google' menu.",
                    )

                # Dismiss 'Welcome to YouTube Studio' modal if present
                try:
                    continue_btn = page.locator(
                        "button:has-text('Continue'), button:has-text('Продолжить'), #continue-button"
                    ).first
                    if await continue_btn.is_visible(timeout=3000):
                        await continue_btn.click()
                        await asyncio.sleep(1.5)
                except Exception:
                    pass

                # Dismiss any tooltips
                try:
                    close_tip = page.locator(
                        "button:has-text('Close'), button:has-text('Dismiss'), button:has-text('Понятно')"
                    ).first
                    if await close_tip.is_visible(timeout=2000):
                        await close_tip.click()
                        await asyncio.sleep(1.0)
                except Exception:
                    pass

                await notify_progress(progress_callback, "Locating upload controls...")

                # 1. Click upload button (center dashboard button or CREATE menu)
                center_upload = page.locator(
                    "button:has-text('Upload videos'), button:has-text('Добавить видео'), #upload-button, [aria-label*='Upload' i]"
                ).first
                if await center_upload.is_visible(timeout=3000):
                    await center_upload.click()
                else:
                    create_btn = page.locator(
                        "#create-icon, [aria-label='Create'], [aria-label='Создать'], button:has-text('CREATE'), button:has-text('СОЗДАТЬ')"
                    ).first
                    await create_btn.wait_for(state="visible", timeout=20000)
                    box = await create_btn.bounding_box()
                    if box:
                        await HumanCursor.move_to(page, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                        await page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                    else:
                        await create_btn.click()
                    await asyncio.sleep(1.5)

                    upload_item = page.locator(
                        "#text-item-0, tp-yt-paper-item:has-text('Upload videos'), tp-yt-paper-item:has-text('Добавить видео')"
                    ).first
                    await upload_item.click()

                await asyncio.sleep(2.5)

                await notify_progress(progress_callback, f"Selecting video file: {video_path.name}...")

                # 3. File Input
                file_input = page.locator("input[type='file']").first
                await file_input.wait_for(state="attached", timeout=20000)
                await file_input.set_input_files(str(video_path.resolve()))
                await asyncio.sleep(5)

                await notify_progress(progress_callback, "Filling metadata (Title & Description)...")

                # 4. Fill Title
                title_box = page.locator(
                    "#title-textarea #textbox, [aria-label*='title' i], [aria-label*='название' i]"
                ).first
                await title_box.wait_for(state="visible", timeout=25000)
                await title_box.click()
                await page.keyboard.press("Control+A")
                await page.keyboard.press("Backspace")
                await asyncio.sleep(0.5)
                await human_type(title_box, title)
                await asyncio.sleep(1.2)

                # 5. Fill Description
                desc_box = page.locator(
                    "#description-textarea #textbox, [aria-label*='description' i], [aria-label*='описание' i]"
                ).first
                if await desc_box.is_visible():
                    await desc_box.click()
                    await human_type(desc_box, description)
                    await asyncio.sleep(1.0)

                # 6. Select "Not Made for Kids"
                not_kids_radio = page.locator(
                    "tp-yt-paper-radio-button[name='VIDEO_MADE_FOR_KIDS_NOT_MFK'], [name='VIDEO_MADE_FOR_KIDS_NOT_MFK']"
                ).first
                if await not_kids_radio.is_visible():
                    await not_kids_radio.click()
                    await asyncio.sleep(1.0)

                await notify_progress(progress_callback, "Advancing visibility steps...")

                # 7. Advance through Next buttons (Elements, Checks, Visibility)
                for _step_idx in range(3):
                    next_btn = page.locator("#next-button").first
                    await next_btn.click()
                    await asyncio.sleep(2.0)

                # 8. Set to "Public"
                await notify_progress(progress_callback, "Setting public visibility...")

                public_radio = page.locator("tp-yt-paper-radio-button[name='PUBLIC'], [name='PUBLIC']").first
                await public_radio.wait_for(state="visible", timeout=15000)
                await public_radio.click()
                await asyncio.sleep(1.5)

                # 9. Click PUBLISH / DONE
                await notify_progress(progress_callback, "Publishing video...")

                done_btn = page.locator("#done-button").first
                await done_btn.click()
                await asyncio.sleep(5)

                # 10. Extract published URL if visible
                video_url = None
                try:
                    url_elem = page.locator("a.ytcp-video-info, a.ytcp-video-metadata-info").first
                    if await url_elem.is_visible():
                        video_url = await url_elem.get_attribute("href")
                except Exception:
                    pass

                await asyncio.sleep(2)
                await browser.close()

                await notify_progress(progress_callback, f"Successfully published! URL: {video_url or 'Published'}")

                return True, video_url or "https://youtube.com/shorts", None

            except Exception as e:
                return False, None, f"YouTube upload error: {e!s}"
