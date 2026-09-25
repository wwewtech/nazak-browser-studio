"""
Unit Tests for Action Synchronizer and Window Tile Engine.

Audit fix P0-2/C2: the synchronizer must really mirror navigation and gestures
(covered here with fake pages), not just probe /json endpoints.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from nazak.core.synchronizer import (
    SYNC_CLIENT_JS,
    SynchronizerManager,
    SynchronizerSession,
    _jittered_point,
    tile_windows_win32,
)


def test_synchronizer_session_init_and_state():
    session = SynchronizerSession(
        master_profile_id="master_1", worker_profile_ids=["master_1", "worker_a", "worker_b"], humanize_jitter=True
    )
    # Ensure master is filtered out from workers
    assert session.master_profile_id == "master_1"
    assert session.worker_profile_ids == ["worker_a", "worker_b"]
    assert session.humanize_jitter is True
    assert session.active is False

    d = session.to_dict()
    assert d["master_profile_id"] == "master_1"
    assert len(d["worker_profile_ids"]) == 2


def test_synchronizer_manager_lifecycle():
    mock_launcher = MagicMock()
    mock_launcher.profile_pids = {"master_1": 1001, "worker_a": 1002, "worker_b": 1003}
    mock_launcher.get_cdp_info.return_value = {"port": 9222, "ws_endpoint": "ws://..."}

    mgr = SynchronizerManager(mock_launcher)
    status = mgr.get_status()
    assert status["active"] is False

    session = mgr.start_session("master_1", ["worker_a", "worker_b"])
    assert session.active is True
    assert mgr.get_status()["active"] is True

    stopped = mgr.stop_session()
    assert stopped is not None
    assert stopped.active is False
    assert mgr.get_status()["active"] is False


def test_tile_windows_empty_handling():
    # Calling tile_windows with empty list returns False safely without crash
    res = tile_windows_win32([])
    assert res is False


# ---------------------------------------------------------------------------
# Audit C2 fixes: real mirroring (fake pages, no browser needed)
# ---------------------------------------------------------------------------


class _Wheel:
    def __init__(self) -> None:
        self.calls: list[tuple] = []


class _Keyboard:
    def __init__(self) -> None:
        self.presses: list[str] = []

    def press(self, key: str):
        self.presses.append(key)


class _FakeSyncPage:
    def __init__(self) -> None:
        self.clicks: list[tuple] = []
        self.evals: list[tuple] = []
        self.gotos: list[str] = []
        self.mouse = SimpleNamespace(click=self._click)
        self.keyboard = _Keyboard()
        self.is_closed_flag = False
        self._scroll = {"x": 0, "y": 0}

    def _click(self, x, y, button="left"):
        self.clicks.append((x, y, button))

    def evaluate(self, expr, *args):
        self.evals.append((expr, args))
        if "scrollX" in expr:
            return dict(self._scroll)
        if "scrollTo" in expr:
            import re

            m = re.findall(r"-?\d+", expr)
            if len(m) >= 2:
                self._scroll = {"x": int(m[0]), "y": int(m[1])}
        return True

    def goto(self, url, **kwargs):
        self.gotos.append(url)
        return None

    def is_closed(self) -> bool:
        return self.is_closed_flag


def test_jittered_point_bounds_and_identity():
    x, y = _jittered_point(100.0, 200.0, 0)
    assert (x, y) == (100, 200)
    for _ in range(50):
        jx, jy = _jittered_point(100.0, 200.0, 5)
        assert 95 <= jx <= 105
        assert 195 <= jy <= 205


def test_sync_client_js_has_install_guard():
    assert "__nazakSyncInstalled" in SYNC_CLIENT_JS
    assert "__nazak_sync_event" in SYNC_CLIENT_JS
    for etype in ("click", "keydown", "scroll", "input"):
        assert f"'{etype}'" in SYNC_CLIENT_JS or f'"{etype}"' in SYNC_CLIENT_JS


def test_submit_event_routing():
    launcher = MagicMock()
    mgr = SynchronizerManager(launcher)
    assert mgr.submit_event("master_1", {"type": "click"}) is False  # no session
    mgr.start_session("master_1", ["worker_a"])
    try:
        assert mgr.submit_event("master_1", {"type": "click", "x": 10, "y": 20}) is True
        assert mgr.submit_event("worker_a", {"type": "click"}) is False  # only master writes
        assert mgr.submit_event("master_1", {"nope": 1}) is False
    finally:
        mgr.stop_session()


def test_click_dispatch_applies_coordinate_jitter():
    launcher = MagicMock()
    mgr = SynchronizerManager(launcher)
    mgr.start_session("master_1", ["worker_a"], humanize_jitter=True, coordinate_jitter_px=3)
    page = _FakeSyncPage()
    try:
        ok = mgr._dispatch_event(page, mgr.current_session, {"type": "click", "x": 100, "y": 200})
        assert ok is True
        assert len(page.clicks) == 1
        x, y, btn = page.clicks[0]
        assert 97 <= x <= 103 and 197 <= y <= 203
        assert btn == "left"
    finally:
        mgr.stop_session()


def test_click_dispatch_without_humanization_is_exact():
    launcher = MagicMock()
    mgr = SynchronizerManager(launcher)
    mgr.start_session("master_1", ["worker_a"], humanize_jitter=False)
    page = _FakeSyncPage()
    try:
        assert mgr._dispatch_event(page, mgr.current_session, {"type": "click", "x": 100, "y": 200}) is True
        assert page.clicks[0] == (100, 200, "left")
    finally:
        mgr.stop_session()


def test_scroll_dispatch_executes_scrollto():
    launcher = MagicMock()
    mgr = SynchronizerManager(launcher)
    mgr.start_session("master_1", ["worker_a"], humanize_jitter=False)
    page = _FakeSyncPage()
    try:
        ok = mgr._dispatch_event(page, mgr.current_session, {"type": "scroll", "x": 0, "y": 500})
        assert ok is True
        assert page._scroll == {"x": 0, "y": 500}
    finally:
        mgr.stop_session()


def test_keydown_dispatch_presses_single_chars():
    launcher = MagicMock()
    mgr = SynchronizerManager(launcher)
    mgr.start_session("master_1", ["worker_a"])
    page = _FakeSyncPage()
    try:
        assert mgr._dispatch_event(page, mgr.current_session, {"type": "keydown", "key": "a"}) is True
        assert page.keyboard.presses == ["a"]
        assert mgr._dispatch_event(page, mgr.current_session, {"type": "keydown", "key": "F13"}) is False
    finally:
        mgr.stop_session()


def test_mirror_one_replicates_event_to_all_workers():
    launcher = MagicMock()
    mgr = SynchronizerManager(launcher)
    mgr.start_session("master_1", ["wa", "wb"], humanize_jitter=False)
    try:
        pages = {wid: {"page": _FakeSyncPage(), "total": 0, "browser": None} for wid in ("wa", "wb")}
        mgr._worker_pages = pages
        item = {"profile_id": "master_1", "event": {"type": "click", "x": 50, "y": 60}, "ts": 0.0}
        mgr._mirror_one(None, mgr.current_session, item)
        assert mgr._worker_pages["wa"]["page"].clicks == [(50, 60, "left")]
        assert mgr._worker_pages["wb"]["page"].clicks == [(50, 60, "left")]
        assert mgr.current_session.total_replicated_events == 1
    finally:
        mgr.stop_session()


def test_navigate_worker_calls_goto_and_reports():
    launcher = MagicMock()
    mgr = SynchronizerManager(launcher)
    mgr.start_session("master_1", ["wa"], humanize_jitter=False)
    try:
        info = {"page": _FakeSyncPage(), "total": 0, "browser": None}
        ok = mgr._navigate_worker_sync(info, "wa", mgr.current_session, "https://example.com")
        assert ok is True
        assert info["page"].gotos == ["https://example.com"]
        assert mgr._navigate_worker_sync(None, "wa", mgr.current_session, "https://example.com") is False
    finally:
        mgr.stop_session()
