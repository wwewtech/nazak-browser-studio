"""Round-3b regression tests: stealth.js и binding синхронизатора (R3b-02, R3b-03, R3b-09, R3b-13)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from nazak.core import cdp_injector as ci, extension_generator as eg, synchronizer as sync
from nazak.models.profile import BrowserProfile


def test_r3b_js_number_renders_valid_js_literals():
    assert eg._js_number(float("inf")) == "Infinity"
    assert eg._js_number(float("-inf")) == "-Infinity"
    assert eg._js_number(float("nan")) == "0"
    assert eg._js_number(2) == "2"
    assert eg._js_number(1.5) == "1.5"
    assert eg._js_number(True) == "true"
    assert eg._js_number("junk") == "0"


def test_r3b_generated_stealth_js_has_no_python_number_literals(tmp_path):
    profile = BrowserProfile(id="prof_jsnum", name="JS Number Probe")
    # Обходим валидацию модели намеренно: проверяем защиту в глубину генератора.
    profile.fingerprint.device_pixel_ratio = float("inf")
    profile.fingerprint.audio_noise_seed = float("nan")
    ext_dir = Path(eg.generate_profile_extension(profile, tmp_path / "ext"))
    js = (ext_dir / "stealth.js").read_text(encoding="utf-8")
    assert "=> inf" not in js
    assert "= nan" not in js
    assert "=> Infinity" in js
    assert "= 0 ||" in js


def test_r3b_delay_range_is_clamped():
    assert sync._clamp_delay_range((-5000, 80)) == (0, 80)
    assert sync._clamp_delay_range((99_999, 5)) == (5, sync.MAX_DELAY_MS)
    assert sync._clamp_delay_range(("junk", None)) == (20, 80)
    assert sync._clamp_delay_range((500, 100)) == (100, 500)
    assert sync._clamp_delay_range(None) == (20, 80)


def test_r3b_session_normalizes_delays_and_jitter():
    session = sync.SynchronizerSession("m", ["w"], delay_range_ms=(-1, -1), coordinate_jitter_px=10_000)
    assert session.delay_range_ms == (0, 0)
    assert session.coordinate_jitter_px == sync.MAX_COORDINATE_JITTER_PX
    assert session.events.maxsize == sync.MAX_PENDING_EVENTS
    assert session.dropped_events == 0


def test_r3b_mirror_one_does_not_die_on_negative_delay():
    """Отрицательный интервал раньше бросал ValueError мимо обработчика."""
    mgr = sync.SynchronizerManager(SimpleNamespace(profile_pids={}))
    mirrored: list[str] = []
    mgr._ensure_worker_pages = lambda workers, browser=None: {
        "w1": {"page": SimpleNamespace(), "total": 0},
    }
    mgr._dispatch_event = lambda page, session, event: mirrored.append(event["type"]) or True
    session = SimpleNamespace(
        humanize_jitter=True,
        delay_range_ms=(-5000, -4000),
        coordinate_jitter_px=0,
        worker_profile_ids=["w1"],
        total_replicated_events=0,
    )
    mgr._mirror_one(None, session, {"event": {"type": "click", "x": 1, "y": 2}})
    assert mirrored == ["click"]


def test_r3b_submit_event_drops_instead_of_growing_memory():
    mgr = sync.SynchronizerManager(SimpleNamespace(profile_pids={}))
    session = sync.SynchronizerSession("master", ["w"], delay_range_ms=(0, 0))
    session.active = True
    mgr.current_session = session
    accepted = 0
    for _ in range(sync.MAX_PENDING_EVENTS + 50):
        accepted += int(mgr.submit_event("master", {"type": "click"}))
    assert accepted == sync.MAX_PENDING_EVENTS
    assert session.dropped_events == 50
    assert session.events.qsize() == sync.MAX_PENDING_EVENTS
    # чужой профиль по-прежнему не может подбросить событие
    assert mgr.submit_event("someone_else", {"type": "click"}) is False


def test_r3b_pump_marks_session_inactive_and_records_error(monkeypatch):
    """Мёртвый насос должен быть виден клиенту как неактивная сессия."""
    import sys
    import types

    mgr = sync.SynchronizerManager(SimpleNamespace(profile_pids={}))
    session = sync.SynchronizerSession("m", ["w"])
    session.active = True
    mgr._detach_workers = lambda: None

    def _boom(*_args, **_kwargs):
        raise RuntimeError("no playwright")

    fake_pkg = types.ModuleType("playwright")
    fake_sync = types.ModuleType("playwright.sync_api")
    fake_sync.sync_playwright = _boom  # type: ignore[attr-defined]
    fake_pkg.sync_api = fake_sync  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "playwright", fake_pkg)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_sync)

    mgr._mirror_pump(session)
    assert session.active is False
    assert session.last_error and "no playwright" in session.last_error


def test_r3b_sync_navigate_refuses_non_http_urls():
    mgr = sync.SynchronizerManager(SimpleNamespace(profile_pids={}))
    gotos: list[str] = []
    page = SimpleNamespace(goto=lambda url, **kw: gotos.append(url))
    session = sync.SynchronizerSession("m", ["w"], humanize_jitter=False, delay_range_ms=(0, 0))
    for bad in ("file:///C:/Windows/win.ini", "javascript:1", "data:text/html,x"):
        assert mgr._navigate_worker_sync({"page": page}, "w1", session, bad) is False
    assert gotos == []
    assert mgr._navigate_worker_sync({"page": page}, "w1", session, "https://example.com") is True
    assert gotos == ["https://example.com"]


def test_r3b_sync_navigate_reports_dead_pump(monkeypatch):
    import asyncio

    mgr = sync.SynchronizerManager(SimpleNamespace(profile_pids={}))
    session = sync.SynchronizerSession("m", ["w"])
    session.active = True
    mgr.current_session = session
    dead = SimpleNamespace(is_alive=lambda: False)
    mgr._pump_thread = dead  # type: ignore[assignment]
    assert asyncio.run(mgr.mirror_navigation("https://example.com")) == {"w": False}
    assert session.active is False
    assert mgr.get_status()["active"] is False


def test_r3b_tile_columns_are_clamped(monkeypatch):
    import nazak.core.synchronizer as s

    captured: dict = {}

    class _User32:
        def SystemParametersInfoW(self, *a):
            captured["called"] = True

        def EnumWindows(self, *_a):
            return True

    monkeypatch.setattr(s.sys, "platform", "win32")
    monkeypatch.setattr(s.ctypes, "windll", SimpleNamespace(user32=_User32()), raising=False)
    # пids нет -> функция выходит до арифметики, поэтому проверяем саму формулу
    assert s.tile_windows_win32([]) is False
    source = Path(s.__file__).read_text(encoding="utf-8")
    assert "max(1, min(int(cols), 8))" in source


def _injector(**overrides):
    opts = ci.InjectorOptions(
        ws_endpoint="ws://127.0.0.1:1/devtools/browser/x",
        profile_id="master",
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/133.0.0.0",
        user_agent_metadata={},
        timezone="Europe/Berlin",
        accept_language="en-US,en;q=0.9",
        event_sink=overrides.pop("event_sink", lambda pid, ev: None),
        **overrides,
    )
    return ci.StealthInjector(opts)


def test_r3b_binding_requires_main_frame_default_context():
    inj = _injector()
    inj._session_is_page["sess1"] = True
    inj._main_frame["sess1"] = "F1"
    inj._contexts[10] = ("F1", True)  # main world главного фрейма
    inj._contexts[11] = ("F2", True)  # main world субфрейма
    inj._contexts[12] = ("F1", False)  # изолированный мир
    payload = json.dumps({"type": "click", "x": 1, "y": 2})
    base = {"name": ci.SYNC_BINDING_NAME, "payload": payload}

    assert inj.binding_event_allowed({**base, "executionContextId": 10}, "sess1") == (True, "")
    assert inj.binding_event_allowed({**base, "executionContextId": 11}, "sess1")[0] is False
    assert inj.binding_event_allowed({**base, "executionContextId": 12}, "sess1")[0] is False
    assert inj.binding_event_allowed({**base, "executionContextId": 99}, "sess1")[0] is False
    # OOPIF/iframe-таргет не является top-level страницей
    inj._session_is_page["sess2"] = False
    inj._main_frame["sess2"] = "F9"
    inj._contexts[20] = ("F9", True)
    assert inj.binding_event_allowed({**base, "executionContextId": 20}, "sess2")[0] is False
    # чужой binding
    assert (
        inj.binding_event_allowed({"name": "other", "payload": payload, "executionContextId": 10}, "sess1")[0] is False
    )


def test_r3b_binding_rejects_oversized_payload_and_sinkless_injector():
    inj = _injector()
    inj._session_is_page["s"] = True
    inj._main_frame["s"] = "F"
    inj._contexts[1] = ("F", True)
    big = json.dumps({"type": "click", "value": "x" * (ci.MAX_BINDING_PAYLOAD_BYTES + 10)})
    assert (
        inj.binding_event_allowed({"name": ci.SYNC_BINDING_NAME, "payload": big, "executionContextId": 1}, "s")[0]
        is False
    )
    no_sink = _injector(event_sink=None)
    no_sink._session_is_page["s"] = True
    no_sink._main_frame["s"] = "F"
    no_sink._contexts[1] = ("F", True)
    assert (
        no_sink.binding_event_allowed({"name": ci.SYNC_BINDING_NAME, "payload": "{}", "executionContextId": 1}, "s")[0]
        is False
    )


def test_r3b_binding_rate_limit_and_acceptance_counters():
    import asyncio

    seen: list[dict] = []
    inj = _injector(event_sink=lambda pid, ev: seen.append(ev))
    inj._session_is_page["s"] = True
    inj._main_frame["s"] = "F"
    inj._contexts[1] = ("F", True)
    # Детерминированный лимитер: без пополнения, чтобы тест не зависел от времени.
    inj._binding_bucket = ci._TokenBucket(rate_per_sec=0.0, burst=3.0)
    params = {
        "name": ci.SYNC_BINDING_NAME,
        "payload": json.dumps({"type": "click", "x": 1, "y": 1}),
        "executionContextId": 1,
    }
    for _ in range(3):
        asyncio.run(inj._on_binding_called(params, "s"))
    assert inj.binding_events_accepted == 3
    asyncio.run(inj._on_binding_called(params, "s"))
    assert inj.binding_events_throttled == 1
    assert inj.binding_events_accepted == 3
    assert len(seen) == 3
    # мусорный payload не доходит до sink (лимитер пополняем, иначе сработает он)
    inj._binding_bucket = ci._TokenBucket(rate_per_sec=0.0, burst=5.0)
    asyncio.run(inj._on_binding_called({**params, "payload": "not json"}, "s"))
    assert inj.binding_events_rejected >= 1
    # не-dict payload тоже отвергается
    asyncio.run(inj._on_binding_called({**params, "payload": '["click"]'}, "s"))
    assert inj.binding_events_rejected >= 2
    assert len(seen) == 3


def test_r3b_token_bucket_is_pure_and_refills():
    bucket = ci._TokenBucket(rate_per_sec=10.0, burst=2.0)
    assert bucket.allow(now=0.0) is True
    assert bucket.allow(now=0.0) is True
    assert bucket.allow(now=0.0) is False
    assert bucket.allow(now=1.0) is True  # за секунду накопилось 10 токенов


def test_r3b_no_branded_page_visible_markers_anywhere():
    injected = sync.SYNC_CLIENT_JS
    assert "__nazak" not in injected
    assert ci.SYNC_BINDING_NAME == "__nse_ev"
    assert "__nazak" not in ci.SYNC_BINDING_NAME
    # флаг идемпотентности виден лишь при явном перечислении свойств
    assert "__nse_c" in injected
    assert "configurable: false, enumerable: false" in injected


def test_r3b_generated_stealth_js_has_no_branded_marker(tmp_path):
    profile = BrowserProfile(id="prof_marker", name="Marker Probe")
    js = (Path(eg.generate_profile_extension(profile, tmp_path / "ext")) / "stealth.js").read_text(encoding="utf-8")
    assert "__nazakShieldApplied" not in js
    assert "window.__nsi" in js
