# Synchronizer
import asyncio
import ctypes
import json
import random
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SynchronizerEvent:
    event_type: str
    data: dict[str, Any]
    timestamp: float = field(default_factory=time.time)


class SynchronizerSession:
    def __init__(
        self,
        master_profile_id: str,
        worker_profile_ids: list[str],
        humanize_jitter: bool = True,
        delay_range_ms: tuple[int, int] = (20, 80),
        coordinate_jitter_px: int = 2,
    ):
        self.master_profile_id = master_profile_id
        self.worker_profile_ids = [w for w in worker_profile_ids if w != master_profile_id]
        self.humanize_jitter = humanize_jitter
        self.delay_range_ms = delay_range_ms
        self.coordinate_jitter_px = coordinate_jitter_px
        self.active = False
        self.total_replicated_events = 0
        self.started_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "master_profile_id": self.master_profile_id,
            "worker_profile_ids": self.worker_profile_ids,
            "humanize_jitter": self.humanize_jitter,
            "delay_range_ms": self.delay_range_ms,
            "coordinate_jitter_px": self.coordinate_jitter_px,
            "active": self.active,
            "total_replicated_events": self.total_replicated_events,
            "started_at": self.started_at,
        }


def tile_windows_win32(pids: list[int], cols: int | None = None) -> bool:
    if sys.platform != "win32" or not pids:
        return False
    try:
        user32 = ctypes.windll.user32

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long),
            ]

        work_rect = RECT()
        user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(work_rect), 0)
        screen_w = work_rect.right - work_rect.left
        screen_h = work_rect.bottom - work_rect.top
        hwnds = []

        def enum_windows_callback(hwnd, extra):
            if user32.IsWindowVisible(hwnd):
                lpdw_pid = ctypes.c_ulong()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(lpdw_pid))
                if lpdw_pid.value in pids:
                    length = user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        hwnds.append(hwnd)
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        cb = WNDENUMPROC(enum_windows_callback)
        user32.EnumWindows(cb, 0)
        if not hwnds:
            return False
        total = len(hwnds)
        num_cols = cols or (2 if total <= 4 else (3 if total <= 9 else 4))
        num_rows = (total + num_cols - 1) // num_cols
        cell_w = screen_w // num_cols
        cell_h = screen_h // num_rows
        flags = 0x0004 | 0x0040
        for i, hwnd in enumerate(hwnds):
            r = i // num_cols
            c = i % num_cols
            x = work_rect.left + c * cell_w
            y = work_rect.top + r * cell_h
            user32.SetWindowPos(hwnd, 0, x, y, cell_w, cell_h, flags)
        return True
    except Exception:
        return False


class SynchronizerManager:
    def __init__(self, browser_launcher):
        self.browser_launcher = browser_launcher
        self.current_session: SynchronizerSession | None = None

    def start_session(
        self,
        master_profile_id: str,
        worker_profile_ids: list[str],
        humanize_jitter: bool = True,
        delay_range_ms: tuple[int, int] = (20, 80),
        coordinate_jitter_px: int = 2,
    ) -> SynchronizerSession:
        session = SynchronizerSession(
            master_profile_id=master_profile_id,
            worker_profile_ids=worker_profile_ids,
            humanize_jitter=humanize_jitter,
            delay_range_ms=delay_range_ms,
            coordinate_jitter_px=coordinate_jitter_px,
        )
        session.active = True
        session.started_at = time.time()
        self.current_session = session
        return session

    def stop_session(self) -> SynchronizerSession | None:
        if self.current_session:
            self.current_session.active = False
            s = self.current_session
            self.current_session = None
            return s
        return None

    def get_status(self) -> dict[str, Any]:
        if not self.current_session or not self.current_session.active:
            return {"active": False, "session": None}
        return {"active": True, "session": self.current_session.to_dict()}

    async def mirror_navigation(self, url: str) -> dict[str, bool]:
        if not self.current_session or not self.current_session.active:
            return {}
        results = {}
        for worker_id in self.current_session.worker_profile_ids:
            cdp_info = self.browser_launcher.get_cdp_info(worker_id)
            if not cdp_info:
                results[worker_id] = False
                continue
            port = cdp_info["port"]
            if self.current_session.humanize_jitter:
                delay = random.uniform(*self.current_session.delay_range_ms) / 1000.0
                await asyncio.sleep(delay)
            try:
                nav_url = f"http://127.0.0.1:{port}/json"
                req = urllib.request.Request(nav_url)
                with urllib.request.urlopen(req, timeout=1.5) as resp:
                    tabs = json.loads(resp.read().decode("utf-8"))
                    results[worker_id] = bool(tabs)
            except Exception:
                results[worker_id] = False
        self.current_session.total_replicated_events += 1
        return results

    def tile_active_windows(self, cols: int | None = None) -> bool:
        pids = []
        if self.current_session and self.current_session.active:
            target_ids = [self.current_session.master_profile_id, *self.current_session.worker_profile_ids]
            for pid_str in target_ids:
                pid = self.browser_launcher.profile_pids.get(pid_str)
                if pid:
                    pids.append(pid)
        else:
            pids = list(self.browser_launcher.profile_pids.values())
        return tile_windows_win32(pids, cols=cols)
