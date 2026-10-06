# Synchronizer
import asyncio
import ctypes
import logging
import queue
import random
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Audit R3-round2: границы для синхронизатора.
#  * MAX_PENDING_EVENTS — очередь мастер-жестов: без maxsize мёртвый/медленный
#    насос копил события в памяти бесконечно.
#  * MAX_DELAY_MS — интервал джиттера: отрицательное значение уходило в
#    time.sleep вне try и убивало поток-насос (ValueError), а session.active
#    оставался True, т.е. клиент видел активную сессию при мёртвом насосе.
#  * MAX_SYNC_NAVIGATE_WAIT_SEC — ожидание ответа насоса при навигации.
MAX_PENDING_EVENTS = 5000
MAX_COORDINATE_JITTER_PX = 50
MAX_DELAY_MS = 60_000
MAX_SYNC_NAVIGATE_WAIT_SEC = 45.0


def _clamp_delay_range(delay_range_ms: Any) -> tuple[int, int]:
    """Нормализует интервал задержек: неотрицательный, упорядоченный, в границах."""
    try:
        low = int(delay_range_ms[0])
        high = int(delay_range_ms[1])
    except (TypeError, ValueError, IndexError):
        return (20, 80)
    low = max(0, min(low, MAX_DELAY_MS))
    high = max(0, min(high, MAX_DELAY_MS))
    if high < low:
        low, high = high, low
    return (low, high)


# Sync client for master pages: captures user gestures and forwards them through
# the Runtime binding registered by the CDP injector.
# Audit R3-round2: раньше здесь стояли `window.__nazakSyncInstalled = true` и
# `window.__nazak_sync_event` — любая страница могла определить Nazak одной
# строкой. Флаг идемпотентности теперь невидим при обычном перечислении
# (неперечислимое свойство), а имя binding'а нейтральное (SYNC_BINDING_NAME).
SYNC_CLIENT_JS = """
(() => {
  if (window.__nse_c) return;
  Object.defineProperty(window, '__nse_c', {value: true, configurable: false, enumerable: false});
  const send = (type, data) => {
    try {
      if (typeof window.__nse_ev === 'function') {
        window.__nse_ev(JSON.stringify(Object.assign({type}, data)));
      }
    } catch (e) {}
  };
  document.addEventListener('click', (e) => {
    send('click', {x: e.clientX, y: e.clientY, button: e.button === 2 ? 'right' : 'left'});
  }, true);
  document.addEventListener('keydown', (e) => send('keydown', {key: e.key}), true);
  let lastScroll = 0;
  document.addEventListener('scroll', () => {
    const now = Date.now();
    if (now - lastScroll < 250) return;
    lastScroll = now;
    send('scroll', {x: window.scrollX, y: window.scrollY});
  }, {capture: true, passive: true});
  document.addEventListener('input', (e) => {
    const el = e.target;
    send('input', {value: (el && 'value' in el) ? String(el.value).slice(-64) : ''});
  }, true);
})();
"""


def _jittered_point(x: float, y: float, jitter_px: int) -> tuple[int, int]:
    """Apply human-like coordinate jitter (pure, unit-testable)."""
    if jitter_px <= 0:
        return int(x), int(y)
    return int(x) + random.randint(-jitter_px, jitter_px), int(y) + random.randint(-jitter_px, jitter_px)


_KEY_PRESS_FALLBACK = {
    " ": "Space",
    "ArrowUp": "ArrowUp",
    "ArrowDown": "ArrowDown",
    "ArrowLeft": "ArrowLeft",
    "ArrowRight": "ArrowRight",
    "Enter": "Enter",
    "Tab": "Tab",
    "Escape": "Escape",
    "Backspace": "Backspace",
}


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
        # Audit R3-round2: интервал нормализуется здесь, потому что отрицательный
        # delay уходил в time.sleep вне try -> ValueError убивал поток-насос,
        # а session.active оставался True (клиент видел "active" при мёртвом насосе).
        self.delay_range_ms = _clamp_delay_range(delay_range_ms)
        self.coordinate_jitter_px = max(0, min(int(coordinate_jitter_px), MAX_COORDINATE_JITTER_PX))
        self.active = False
        self.total_replicated_events = 0
        self.dropped_events = 0
        self.last_error: str | None = None
        self.started_at: float | None = None
        # Thread-safe event queue: the CDP injector (its own thread) appends
        # master gestures here, the mirror pump thread consumes them.
        # maxsize обязателен: без него мёртвый/медленный насос копил память.
        self.events: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=MAX_PENDING_EVENTS)
        # Control commands (mirror_navigation) executed by the pump thread so
        # every CDP session is opened on ONE thread (Playwright requirement).
        self.commands: queue.Queue[dict[str, Any]] = queue.Queue()

    def to_dict(self) -> dict[str, Any]:
        return {
            "master_profile_id": self.master_profile_id,
            "worker_profile_ids": self.worker_profile_ids,
            "humanize_jitter": self.humanize_jitter,
            "delay_range_ms": self.delay_range_ms,
            "coordinate_jitter_px": self.coordinate_jitter_px,
            "active": self.active,
            "total_replicated_events": self.total_replicated_events,
            "dropped_events": self.dropped_events,
            "last_error": self.last_error,
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
        # Audit R3-round2: cols приходит из API/CLI. Отрицательное значение
        # давало ZeroDivisionError или отрицательную геометрию окна (гасилось
        # общим except и выглядело как «не сработало»), поэтому диапазон 1..8.
        default_cols = 2 if total <= 4 else (3 if total <= 9 else 4)
        try:
            num_cols = max(1, min(int(cols), 8)) if cols is not None else default_cols
        except (TypeError, ValueError):
            num_cols = default_cols
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
        # Synchronous Playwright attachments per worker OWNED by the pump thread:
        # opening all CDP sessions on ONE thread is mandatory — every playwright
        # object is bound to the event loop of the thread that created it.
        self._worker_pages: dict[str, dict[str, Any]] = {}
        self._worker_pw_tmp: Any = None
        self._pump_thread: threading.Thread | None = None

    def start_session(
        self,
        master_profile_id: str,
        worker_profile_ids: list[str],
        humanize_jitter: bool = True,
        delay_range_ms: tuple[int, int] = (20, 80),
        coordinate_jitter_px: int = 2,
    ) -> SynchronizerSession:
        self.stop_session()
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
        self._worker_pages = {}
        self._pump_thread = threading.Thread(
            target=self._mirror_pump, args=(session,), daemon=True, name="NazakSyncPump"
        )
        self._pump_thread.start()
        self._install_sync_client(master_profile_id)
        return session

    def stop_session(self) -> SynchronizerSession | None:
        session = self.current_session
        if session:
            session.active = False
        self.current_session = None
        thread = self._pump_thread
        self._pump_thread = None
        if thread and thread.is_alive():
            # The pump's finally-block owns _detach_workers(): Playwright objects
            # are thread-affine and closing them from this thread raises
            # greenlet "Cannot switch to a different thread" errors.
            thread.join(timeout=2.0)
        if thread is None or not thread.is_alive():
            self._detach_workers()
        return session

    # ------------------------------------------------------------ event source
    def submit_event(self, profile_id: str, event: dict[str, Any]) -> bool:
        """Called by the CDP injector binding thread for a master gesture."""
        session = self.current_session
        if session is None or not session.active or profile_id != session.master_profile_id:
            return False
        if not isinstance(event, dict) or "type" not in event:
            return False
        try:
            # Audit R3-round2: ограниченная очередь + явный счётчик отброшенных
            # событий вместо бесконечного роста памяти.
            session.events.put_nowait({"profile_id": profile_id, "event": event, "ts": time.time()})
        except queue.Full:
            session.dropped_events += 1
            if session.dropped_events % 100 == 1:
                logger.warning(
                    "synchronizer event queue full (%d pending); dropped %d events so far",
                    session.events.maxsize,
                    session.dropped_events,
                )
            return False
        return True

    def _install_sync_client(self, master_profile_id: str) -> None:
        """Evaluate the sync client into master pages (best effort)."""
        cdp_info = None
        try:
            cdp_info = self.browser_launcher.get_cdp_info(master_profile_id)
        except Exception:
            cdp_info = None
        if not cdp_info:
            logger.warning(
                "synchronizer: master %s has no CDP endpoint; gesture capture unavailable", master_profile_id
            )
            return
        import asyncio

        async def _install() -> None:
            # Импорт внутри try: без playwright поток не должен падать
            # необработанным исключением (audit R3-round2).
            from playwright.async_api import async_playwright

            endpoint = cdp_info.get("http_endpoint") if isinstance(cdp_info, dict) else None
            if not endpoint:
                return
            pw = await async_playwright().start()
            try:
                browser = await pw.chromium.connect_over_cdp(endpoint)
                for context in browser.contexts:
                    for page in context.pages:
                        try:
                            await page.evaluate(SYNC_CLIENT_JS)
                        except Exception:
                            pass
                await browser.close()
            finally:
                await pw.stop()

        def _runner() -> None:
            try:
                asyncio.run(_install())
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("synchronizer: gesture capture unavailable (%s)", exc)

        thread = threading.Thread(target=_runner, daemon=True, name="NazakSyncInstall")
        thread.start()

    def get_status(self) -> dict[str, Any]:
        if not self.current_session or not self.current_session.active:
            return {"active": False, "session": None}
        return {"active": True, "session": self.current_session.to_dict()}

    async def mirror_navigation(self, url: str) -> dict[str, bool]:
        """Navigate every worker to the URL (audit fix C2: it used to only probe).

        All CDP sessions are opened on the pump thread (Playwright binds every
        object to the thread that created it), so the command is executed
        there and the outcomes are awaited here.
        """
        session = self.current_session
        if not session or not session.active:
            return {}
        workers = list(session.worker_profile_ids)
        if not workers:
            return {}
        # Audit R3-round2: мёртвый насос не должен заставлять ждать ответа минуты.
        pump = self._pump_thread
        if pump is not None and not pump.is_alive():
            session.active = False
            session.last_error = session.last_error or "mirror pump is not running"
            logger.warning("mirror_navigation: pump thread is dead; session deactivated")
            return {w: False for w in workers}

        outcome_queue: queue.Queue[dict[str, bool]] = queue.Queue()
        session.commands.put({"command": "navigate", "url": url, "reply": outcome_queue})
        try:
            # Bounded queue.get: a dead pump must not leave a blocked executor
            # thread behind after wait_for cancels the await.
            outcomes = await asyncio.wait_for(
                asyncio.to_thread(outcome_queue.get, True, int(MAX_SYNC_NAVIGATE_WAIT_SEC)),
                timeout=MAX_SYNC_NAVIGATE_WAIT_SEC + 10,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("mirror_navigation failed: %s", exc)
            outcomes = {w: False for w in workers}
        session.total_replicated_events += 1
        return dict(outcomes)

    # --------------------------------------------------------------- mirror pump
    def _mirror_pump(self, session: SynchronizerSession) -> None:
        """Consume master gestures and mirror them onto worker pages (blocking pump)."""
        try:
            # Audit R3-round2: импорт внутри try — отсутствие playwright должно
            # быть зафиксировано как last_error сессии, а не как необработанное
            # исключение потока (pytest превращает его в падение теста).
            from playwright.sync_api import sync_playwright

            with sync_playwright() as pw:
                while session.active:
                    command = self._pop_command(session)
                    if command is not None:
                        self._run_command(pw, session, command)
                    try:
                        item = session.events.get_nowait()
                    except queue.Empty:
                        item = None
                    if item is not None:
                        self._mirror_one(pw, session, item)
                    else:
                        time.sleep(0.05)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("synchronizer mirror pump stopped: %s", exc)
            session.last_error = str(exc)
        finally:
            # Audit R3-round2: мёртвый насос обязан быть виден клиенту. Раньше
            # session.active оставался True, get_status() отдавал "active", а
            # mirror_navigation ждал ответа до 110 с.
            session.active = False
            self._detach_workers()

    @staticmethod
    def _pop_command(session: SynchronizerSession) -> dict[str, Any] | None:
        try:
            return session.commands.get_nowait()
        except queue.Empty:
            return None

    def _run_command(self, pw: Any, session: SynchronizerSession, command: dict[str, Any]) -> None:
        if command.get("command") != "navigate":
            return
        workers = list(session.worker_profile_ids)
        pages = self._ensure_worker_pages(workers, browser=pw)
        outcomes: dict[str, bool] = {}
        for worker_id in workers:
            outcomes[worker_id] = self._navigate_worker_sync(pages.get(worker_id), worker_id, session, command["url"])
        reply = command.get("reply")
        if reply is not None:
            try:
                reply.put(outcomes)
            except Exception:
                pass

    def _mirror_one(self, pw: Any, session: SynchronizerSession, item: dict[str, Any]) -> None:
        """Mirror one master gesture onto every worker page (runs on the pump thread)."""
        workers = list(session.worker_profile_ids)
        if not workers:
            return
        pages = self._ensure_worker_pages(workers, browser=pw)
        event = item.get("event", {})
        for worker_id in workers:
            info = pages.get(worker_id)
            if not info or not info.get("page"):
                continue
            try:
                # Audit R3-round2: sleep ВНУТРИ try. Раньше он стоял снаружи, и
                # отрицательный delay (невалидированный --min-delay/min_delay_ms)
                # выбрасывал ValueError мимо обработчика -> насос умирал.
                if session.humanize_jitter:
                    delay_ms = random.uniform(*_clamp_delay_range(session.delay_range_ms))
                    if delay_ms > 0:
                        time.sleep(delay_ms / 1000.0)
                ok = self._dispatch_event(info["page"], session, event)
                info["total"] = int(info.get("total", 0)) + int(bool(ok))
            except Exception as exc:
                logger.warning("sync mirror failed for %s: %s", worker_id, exc)
        session.total_replicated_events += 1

    # ------------------------------------------------------ worker attachments
    def _ensure_worker_pages(self, worker_ids: list[str], browser: Any = None) -> dict[str, dict[str, Any]]:
        """Attach one Playwright page per worker (cached, lazily reconnected)."""
        # Audit R3-round2: сначала проверяем кэш — если все страницы живы,
        # playwright не нужен вовсе (раньше импорт выполнялся всегда и падал
        # там, где зависимость не установлена, хотя работы не требовалось).
        need_attach = [
            worker_id
            for worker_id in worker_ids
            if not (self._worker_pages.get(worker_id) and self._page_alive(self._worker_pages[worker_id]))
        ]
        if not need_attach:
            return {wid: self._worker_pages[wid] for wid in worker_ids if wid in self._worker_pages}

        from playwright.sync_api import sync_playwright

        if browser is None:
            # Lazily start a private Playwright driver only when some worker
            # actually needs attaching (keeps unit tests and read-only paths free).
            browser = sync_playwright().start()
            self._worker_pw_tmp = browser
        for worker_id in worker_ids:
            info = self._worker_pages.get(worker_id)
            if info and self._page_alive(info):
                continue
            try:
                cdp_info = self.browser_launcher.get_cdp_info(worker_id)
                endpoint = cdp_info.get("http_endpoint") if isinstance(cdp_info, dict) else None
                if not endpoint or browser is None:
                    continue
                browser_obj = browser.chromium.connect_over_cdp(endpoint)
                contexts = browser_obj.contexts
                context = contexts[0] if contexts else browser_obj.new_context()
                page = context.pages[0] if context.pages else context.new_page()
                self._worker_pages[worker_id] = {
                    "browser": browser_obj,
                    "context": context,
                    "page": page,
                    "total": 0,
                }
            except Exception as exc:
                logger.warning("synchronizer: worker %s attach failed: %s", worker_id, exc)
                continue
        return dict(self._worker_pages)

    @staticmethod
    def _page_alive(info: dict[str, Any]) -> bool:
        try:
            page = info.get("page")
            if page is None:
                return False
            return not getattr(page, "is_closed", lambda: True)()
        except Exception:
            return False

    def _detach_workers(self) -> None:
        for info in list(self._worker_pages.values()):
            for closer in (info.get("browser"),):
                if closer is not None:
                    try:
                        closer.close()
                    except Exception:
                        pass
        self._worker_pages = {}
        if self._worker_pw_tmp is not None:
            try:
                self._worker_pw_tmp.stop()
            except Exception:
                pass
            self._worker_pw_tmp = None

    def _navigate_worker_sync(
        self, info: dict[str, Any] | None, worker_id: str, session: SynchronizerSession, url: str
    ) -> bool:
        """Navigate one worker page (blocking call, runs in a worker thread)."""
        if not info or not info.get("page"):
            return False
        try:
            # Audit R3-round2: URL приходит из API/CLI. Раньше он уходил в
            # page.goto() как есть, т.е. file://, data: и javascript: открывались
            # в браузерах воркеров (в warmup/launch такая же проверка уже была).
            from .browser_launcher import sanitize_launch_url

            target_url = sanitize_launch_url(url)
        except ValueError as exc:
            logger.warning("synchronizer navigate refused for %s: %s", worker_id, exc)
            return False
        try:
            if session.humanize_jitter:
                delay_ms = random.uniform(*_clamp_delay_range(session.delay_range_ms))
                if delay_ms > 0:
                    time.sleep(delay_ms / 1000.0)
            info["page"].goto(target_url, wait_until="domcontentloaded", timeout=45000)
            return True
        except Exception as exc:
            logger.warning("synchronizer navigate failed for %s: %s", worker_id, exc)
            return False

    # ------------------------------------------------------------ event dispatch
    def _dispatch_event(self, page: Any, session: SynchronizerSession, event: dict[str, Any]) -> bool:
        """Mirror one master gesture onto a worker page (sync Playwright)."""
        etype = str(event.get("type", ""))
        jitter = session.coordinate_jitter_px if session.humanize_jitter else 0
        try:
            if etype == "click":
                x, y = _jittered_point(float(event.get("x", 0)), float(event.get("y", 0)), jitter)
                button = str(event.get("button", "left"))
                page.mouse.click(int(x), int(y), button=button if button in ("left", "right", "middle") else "left")
                return True
            if etype == "scroll":
                wx, wy = _jittered_point(float(event.get("x", 0)), float(event.get("y", 0)), jitter)
                before = page.evaluate("() => ({x: window.scrollX, y: window.scrollY})")
                page.evaluate(f"window.scrollTo({int(wx)}, {int(wy)})")
                after = page.evaluate("() => ({x: window.scrollX, y: window.scrollY})")
                return after != before
            if etype == "keydown":
                key = str(event.get("key", ""))
                if len(key) > 1 and key not in _KEY_PRESS_FALLBACK:
                    return False
                page.keyboard.press(key)
                return True
            if etype == "input":
                value = str(event.get("value", ""))
                page.evaluate(
                    """(suffix) => {
                        const el = document.activeElement;
                        if (el && ('value' in el)) { el.value = (el.value || '') + suffix; }
                        return true;
                    }""",
                    value[-8:] if len(value) > 8 else value,
                )
                return True
        except Exception as exc:
            logger.warning("sync dispatch %s failed: %s", etype, exc)
            return False
        return False

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
