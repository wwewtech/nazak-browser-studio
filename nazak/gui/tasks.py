"""
GUI background tasks as plain callables (P0 refactor).

Each function is Qt-free: it takes explicit service arguments plus an optional
``(handle, progress)`` pair and returns a plain result. :mod:`nazak.gui.task_bridge`
runs them on a QThread (Qt) or inline (headless/tests); ``workers.py`` keeps thin
QThread adapters with the original signal names so views do not change.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

from .task_bridge import TaskCanceled, _WarmupCanceled


def _is_cancelled(handle) -> bool:
    return bool(handle is not None and getattr(handle, "is_cancelled", False))


def _run_coro_sync(coro_factory):
    """Run a coroutine factory to completion from a sync context.

    No loop → ``asyncio.run`` here. Inside a running loop → side thread with a
    fresh loop (a coroutine can only be awaited on one loop). Exceptions,
    including cooperative :class:`TaskCanceled`, propagate to the caller.
    """

    async def _runner():
        return await coro_factory()

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_runner())

    box: dict[str, Any] = {}

    def _target():
        try:
            box["result"] = asyncio.run(_runner())
        except Exception as exc:
            box["error"] = exc

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join()
    if "error" in box:
        raise box["error"]
    return box.get("result")


def check_single_proxy(profile_id: str, proxy_config, profile_dir: Path | None, handle=None, progress=None):
    """Run one proxy health check (sync entry; internally async)."""
    from ..core.proxy_checker import check_proxy_health

    async def _run():
        return await check_proxy_health(proxy_config, profile_dir=profile_dir)

    return _run_coro_sync(_run)


def check_all_proxies(profiles, profiles_dir: Path, handle=None, progress=None):
    """Sequential health checks with per-profile progress tuples."""
    from ..core.proxy_checker import check_proxy_health

    async def _run_all():
        results = []
        total = len(profiles)
        for idx, p in enumerate(profiles, start=1):
            if _is_cancelled(handle):
                raise TaskCanceled()
            if progress is not None:
                progress((idx, total, p.name))
            res = await check_proxy_health(p.proxy, profile_dir=profiles_dir / p.id)
            results.append((p.id, res))
        return results

    out = _run_coro_sync(_run_all)
    return out if out is not None else []


def rotate_proxy(profile_id: str, rotation_url: str, timeout: float = 8.0, handle=None, progress=None) -> int:
    """Fetch a rotation URL (blocking, short timeout). Returns HTTP status.

    The scheme is pinned to http(s) so urlopen can never be handed file:/ftp:/
    custom schemes (bandit B310) — the URL comes from the user's proxy settings.
    """
    import urllib.request

    if not rotation_url.lower().startswith(("http://", "https://")):
        raise ValueError("rotation_url must be an http:// or https:// URL")

    req = urllib.request.Request(rotation_url, headers={"User-Agent": "Nazak-Studio"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
        return int(getattr(resp, "status", 0) or 0)


def run_warmup_scenario(profile_manager, browser_launcher, scenario, profile_id: str, handle=None, progress=None):
    """Run one warmup scenario with cooperative cancel."""
    from ..core.warmup_engine import ScenarioExecutor

    executor = ScenarioExecutor(browser_launcher, profile_manager)

    def _on_progress(pid: str, idx: int, total: int, desc: str):
        if progress is not None:
            progress((pid, idx, total, desc))
        if _is_cancelled(handle):
            raise _WarmupCanceled()

    async def _run():
        return await executor.run_scenario_on_profile(scenario, profile_id, progress_callback=_on_progress)

    result = _run_coro_sync(_run)
    if result is None:
        result = {}
    if _is_cancelled(handle) and isinstance(result, dict):
        result["canceled"] = True
    return result


def run_autopost_batch(
    profile_manager,
    browser_launcher,
    profile_ids: list[str],
    source_video_path: Path,
    title_template: str,
    description_template: str,
    tg_channel: str = "@your_vpn_bot",
    handle=None,
    progress=None,
):
    """Sequential uniqueize -> launch -> upload loop with cooperative cancel."""
    import asyncio

    from ..core.browser_launcher import get_free_port
    from ..core.spintax import format_video_metadata
    from ..core.video_uniquifier import VideoUniquifier
    from ..core.youtube_uploader import YouTubeUploader
    from ..models.profile import ProfileStatus

    uniquifier = VideoUniquifier()

    async def _run():
        results = []
        for idx, pid in enumerate(profile_ids, start=1):
            if _is_cancelled(handle):
                break
            prof = profile_manager.get_profile(pid)
            if not prof:
                continue
            if progress is not None:
                progress((pid, "uniqueizing", "Creating a unique video variant and shifting frequencies..."))
            ok, out_path, err = uniquifier.uniquify_video(source_video_path, pid, profile_index=idx)
            if not ok or not out_path:
                if progress is not None:
                    progress((pid, "failed", f"Video error: {err}"))
                continue
            meta = format_video_metadata(
                title_template=title_template,
                description_template=description_template,
                profile_name=prof.name,
                profile_id=pid,
                tg_channel=tg_channel,
            )
            if progress is not None:
                progress((pid, "launching", "Launching isolated browser..."))
            cdp_port = get_free_port()
            launch_ok, pid_num, launch_err = browser_launcher.launch(prof, cdp_port=cdp_port)
            if not launch_ok:
                if progress is not None:
                    progress((pid, "failed", f"Launch error: {launch_err}"))
                continue
            prof.status = ProfileStatus.RUNNING
            prof.pid = pid_num
            profile_manager.update_profile(prof)
            # Poll the DevTools endpoint instead of a fixed 4 s sleep (fix F2):
            # returns as soon as Chromium is actually reachable for CDP.
            await browser_launcher.wait_for_cdp(pid, timeout_sec=6.0)
            if progress is not None:
                progress((pid, "uploading", "Uploading Shorts to YouTube Studio..."))

            curr_pid = pid

            async def progress_cb(msg: str, p=curr_pid):
                if progress is not None:
                    progress((p, "uploading", msg))

            uploader = YouTubeUploader(f"http://127.0.0.1:{cdp_port}")
            upload_ok, video_url, upload_err = await uploader.upload_shorts(
                video_path=out_path,
                title=meta["title"],
                description=meta["description"],
                progress_callback=progress_cb,
            )
            browser_launcher.stop(pid)
            prof.status = ProfileStatus.STOPPED
            prof.pid = None
            profile_manager.update_profile(prof)
            if upload_ok:
                if progress is not None:
                    progress((pid, "published", f"Published! {video_url or ''}"))
                results.append({"profile_id": pid, "status": "published", "url": video_url})
            else:
                if progress is not None:
                    progress((pid, "failed", upload_err or "Upload error"))
                results.append({"profile_id": pid, "status": "failed", "error": upload_err})
            await asyncio.sleep(3)
        return results

    out = _run_coro_sync(_run)
    return out if out is not None else []
