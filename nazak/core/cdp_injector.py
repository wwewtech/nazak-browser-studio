"""
CDP Stealth Injector — audit fix P0-1 (plan Этап 1).

Branded Google Chrome 137+ ignores ``--load-extension``, so the generated
stealth extension (and its proxy-auth service worker) never loads. This module
applies the same protection directly over the Chrome DevTools Protocol after
profile launch, which works on any Chrome/Chromium build:

- ``Page.addScriptToEvaluateOnNewDocument`` + generated ``stealth.js`` source
  (all page-world shields: webdriver cloaking, canvas/audio noise, media/battery
  spoof, WebGPU, WebRTC sanitizer, screen/hardware overrides, ...);
- ``Emulation.setTimezoneOverride`` — real JS timezone spoof (the
  ``--time-zone-for-testing`` flag was proven dead in the audit);
- ``Emulation.setUserAgentOverride`` with ``userAgentMetadata`` rebuilt from the
  *actual* running Chrome version — kills the UA/Client-Hints mismatch
  (UA said 133 while brands said 153);
- ``Fetch.authRequired`` — answers proxy 407 challenges with profile
  credentials (replacement for the never-loading ``onAuthRequired`` worker);
- ``Runtime.addBinding`` channel for future synchronizer event forwarding.

The injector lives in a daemon thread with its own event loop so it can start
from any context (FastAPI loop, Qt worker thread, CLI).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:
    import websockets
except ImportError:  # pragma: no cover - dependency guard
    websockets = None  # type: ignore[assignment]

CHROME_VERSION_RE = re.compile(r"Chrome/\d+(?:\.\d+)*")
SYNC_BINDING_NAME = "__nazak_sync_event"


def build_runtime_user_agent(user_agent: str, chrome_version: str) -> str:
    """Replace the (stale) Chrome version inside a UA template with the real one.

    ``build_chrome_args`` still passes ``--user-agent`` with the profile's
    stored value; this CDP override wins at runtime and must agree with
    ``navigator.userAgentData`` brands derived from the same version.
    """
    if not chrome_version:
        return user_agent
    return CHROME_VERSION_RE.sub(f"Chrome/{chrome_version}", user_agent)


def build_user_agent_metadata(fp: Any, chrome_version: str) -> dict[str, Any]:
    """Build CDP ``UserAgentMetadata`` consistent with the runtime UA string."""
    major = chrome_version.split(".")[0] if chrome_version else "0"
    platform_str = "Windows"
    pf = str(getattr(fp, "platform", "Win32")).lower()
    if pf.startswith("mac"):
        platform_str = "macOS"
    elif "linux" in pf:
        platform_str = "Linux"
    return {
        "brands": [
            {"brand": "Google Chrome", "version": major},
            {"brand": "Chromium", "version": major},
            {"brand": "Not(A:Brand", "version": "99"},
        ],
        "fullVersionList": [
            {"brand": "Google Chrome", "version": chrome_version or major},
            {"brand": "Chromium", "version": chrome_version or major},
            {"brand": "Not(A:Brand", "version": "99"},
        ],
        "platform": platform_str,
        "platformVersion": str(getattr(fp, "platform_version", "10.0.0")),
        "architecture": str(getattr(fp, "architecture", "x86")),
        "model": str(getattr(fp, "model", "")),
        "mobile": bool(getattr(fp, "mobile", False)),
        "bitness": str(getattr(fp, "bitness", "64")),
        "uaFullVersion": chrome_version or major,
        "fullVersion": chrome_version or major,
    }


def pick_auth_challenge_response(source: str | None, username: str | None, password: str | None) -> dict[str, str]:
    """Decide the ``Fetch.authRequired`` answer (pure, unit-testable).

    Only proxy challenges with stored credentials receive ``ProvideCredentials``;
    everything else is cancelled so Chrome never shows a blocking native dialog.
    """
    if source == "Proxy" and username and password:
        return {"response": "ProvideCredentials", "username": username, "password": password}
    return {"response": "CancelAuth"}


def _devtools_active_ws(user_data_dir: Path, timeout_sec: float = 6.0) -> str | None:
    """Read ``ws://`` debugger URL from Chromium's DevToolsActivePort file."""
    port_file = user_data_dir / "DevToolsActivePort"
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            if port_file.exists():
                lines = [ln.strip() for ln in port_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
                if len(lines) >= 2:
                    return f"ws://127.0.0.1:{lines[0]}{lines[1]}"
        except OSError:
            pass
        time.sleep(0.15)
    return None


def _json_version_ws(port: int, timeout_sec: float = 5.0) -> str | None:
    """Resolve ``webSocketDebuggerUrl`` from ``/json/version``."""
    deadline = time.time() + timeout_sec
    url = f"http://127.0.0.1:{port}/json/version"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                ws = data.get("webSocketDebuggerUrl")
                if ws:
                    return ws
        except Exception:
            pass
        time.sleep(0.2)
    return None


def read_chrome_version_from_ws_info(ws_url: str | None, timeout_sec: float = 3.0) -> str | None:
    """Best-effort real Chrome version ('153.0.8010.53') from /json/version."""
    if not ws_url:
        return None
    try:
        port = ws_url.split("/")[2].split(":")[1]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=timeout_sec) as resp:
            browser = json.loads(resp.read().decode("utf-8")).get("Browser", "")
        m = re.search(r"(\d+(?:\.\d+)+)", browser)
        return m.group(1) if m else None
    except Exception:
        return None


@dataclass
class InjectorOptions:
    ws_endpoint: str
    user_agent: str
    user_agent_metadata: dict[str, Any]
    timezone: str
    accept_language: str
    proxy_username: str | None = None
    proxy_password: str | None = None
    stealth_source: str = ""
    # Audit fix P0-2: owner profile + gesture sink for the synchronizer
    # (Runtime.__nazak_sync_event binding installed by _apply_session).
    profile_id: str = ""
    event_sink: Callable[[str, dict[str, Any]], None] | None = None


class StealthInjector:
    """Persistent CDP session applying stealth to every page/frameset."""

    def __init__(self, opts: InjectorOptions):
        self.opts = opts
        self.applied = False
        self.sessions_applied = 0
        self.last_error: str | None = None
        self.auth_challenges = 0
        self.auth_errors = 0
        self.requests_paused = 0
        self.requests_continued = 0
        self._ws: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._next_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._stop_event: asyncio.Event | None = None

    def request_stop(self) -> None:
        """Thread-safe-ish stop request (must run on the injector loop)."""
        if self._stop_event is not None:
            self._stop_event.set()
        ws = self._ws
        if ws is not None:
            asyncio.ensure_future(ws.close())

    async def run(self) -> None:
        """Connect to the browser WS endpoint and keep stealth applied forever."""
        if websockets is None:
            raise RuntimeError("websockets package is not installed — stealth injector unavailable")
        self._loop = asyncio.get_running_loop()
        self._stop_event = asyncio.Event()
        self._ws = await websockets.connect(
            self.opts.ws_endpoint,
            max_size=2**22,
            open_timeout=10,
            close_timeout=3,
            ping_interval=20,
            ping_timeout=20,
        )
        pump = asyncio.create_task(self._pump_loop())
        try:
            # Auto-attach to every current and future target (pages, OOPIF...).
            await self._command(
                "Target.setAutoAttach",
                {"autoAttach": True, "waitForDebuggerOnStart": False, "flatten": True},
            )
            res = await self._command("Target.getTargets", {})
            for info in res.get("targetInfos", []):
                if info.get("type") == "page":
                    try:
                        await self._command("Target.attachToTarget", {"targetId": info["targetId"], "flatten": True})
                    except Exception as exc:  # pragma: no cover - defensive
                        logger.debug("attachToTarget failed for %s: %s", info.get("targetId"), exc)
            await self._stop_event.wait()
        finally:
            pump.cancel()
            try:
                await self._ws.close()
            except Exception:
                pass

    async def _command(self, method: str, params: dict[str, Any], session_id: str | None = None) -> dict[str, Any]:
        assert self._ws is not None, "injector not connected"
        self._next_id += 1
        msg: dict[str, Any] = {"id": self._next_id, "method": method, "params": params}
        if session_id:
            msg["sessionId"] = session_id
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[self._next_id] = fut
        await self._ws.send(json.dumps(msg))
        try:
            reply = await asyncio.wait_for(fut, timeout=12)
        except asyncio.TimeoutError:
            self._pending.pop(self._next_id, None)
            logger.debug("CDP command timeout: %s", method)
            return {}
        if "error" in reply:
            logger.debug("CDP command error %s: %s", method, reply["error"])
            return {}
        return reply.get("result", {})

    async def _pump_loop(self) -> None:
        assert self._ws is not None
        try:
            async for raw in self._ws:
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                if "id" in msg:
                    fut = self._pending.pop(msg["id"], None)
                    if fut is not None and not fut.done():
                        fut.set_result(msg)
                else:
                    method = msg.get("method", "")
                    params = msg.get("params", {})
                    sid = msg.get("sessionId")
                    if method == "Target.attachedToTarget":
                        asyncio.create_task(self._on_attached(params))
                    elif method == "Fetch.requestPaused":
                        # Fetch.enable pauses every request until continued —
                        # auto-continue so navigation never stalls.
                        asyncio.create_task(self._continue_paused(params, sid))
                    elif method == "Runtime.bindingCalled":
                        self._on_binding_called(params)
                    elif method == "Fetch.authRequired":
                        try:
                            await self._on_auth_required(params, sid)
                        except Exception as exc:
                            logger.debug("authRequired handling failed: %s", exc)
        finally:
            if self._stop_event is not None:
                self._stop_event.set()

    async def _on_attached(self, params: dict[str, Any]) -> None:
        info = params.get("targetInfo", {})
        if info.get("type") not in ("page", "iframe", "other", "webview"):
            return
        await self._apply_session(params.get("sessionId"))

    async def _apply_session(self, session_id: str | None) -> None:
        if not session_id:
            return
        try:
            await self._command(
                "Target.setAutoAttach",
                {"autoAttach": True, "waitForDebuggerOnStart": False, "flatten": True},
                session_id=session_id,
            )
            await self._command("Page.enable", {}, session_id=session_id)
            src = self.opts.stealth_source
            if src:
                await self._command("Page.addScriptToEvaluateOnNewDocument", {"source": src}, session_id=session_id)
            if self.opts.timezone:
                await self._command(
                    "Emulation.setTimezoneOverride",
                    {"timezoneId": self.opts.timezone},
                    session_id=session_id,
                )
            await self._command(
                "Emulation.setUserAgentOverride",
                {
                    "userAgent": self.opts.user_agent,
                    "userAgentMetadata": self.opts.user_agent_metadata,
                    "acceptLanguage": self.opts.accept_language,
                },
                session_id=session_id,
            )
            await self._command("Runtime.enable", {}, session_id=session_id)
            await self._command("Runtime.addBinding", {"name": SYNC_BINDING_NAME}, session_id=session_id)
            # Proxy 407 challenges are answered via CDP (extension SW never loads).
            # handleAuthRequests is REQUIRED: without it Chrome never emits
            # Fetch.authRequired and the credential answer below stays dead.
            await self._command(
                "Fetch.enable",
                {"patterns": [{"urlPattern": "*"}], "handleAuthRequests": True},
                session_id=session_id,
            )
            if src:
                # Apply immediately to the *current* document (addScript covers future ones).
                await self._command(
                    "Runtime.evaluate",
                    {"expression": src, "awaitPromise": False, "returnByValue": False},
                    session_id=session_id,
                )
            self.sessions_applied += 1
            self.applied = True
        except Exception as exc:  # pragma: no cover - defensive
            self.last_error = str(exc)
            logger.warning("stealth apply failed for session %s: %s", session_id, exc)

    async def _continue_paused(self, params: dict[str, Any], session_id: str | None) -> None:
        self.requests_paused += 1
        try:
            await self._command("Fetch.continueRequest", {"requestId": params["requestId"]}, session_id=session_id)
            self.requests_continued += 1
        except Exception as exc:
            logger.debug("continueRequest failed: %s", exc)

    def _on_binding_called(self, params: dict[str, Any]) -> None:
        """Forward page-side gesture events to the synchronizer sink."""
        if params.get("name") != SYNC_BINDING_NAME:
            return
        sink = self.opts.event_sink
        if not sink or not self.opts.profile_id:
            return
        try:
            event = json.loads(params.get("payload", "{}"))
        except ValueError:
            return
        if isinstance(event, dict) and event.get("type"):
            try:
                sink(self.opts.profile_id, event)
            except Exception as exc:
                logger.debug("sync event sink failed: %s", exc)

    async def _on_auth_required(self, params: dict[str, Any], session_id: str | None) -> None:
        self.auth_challenges += 1
        challenge = params.get("authChallenge", {})
        resp = pick_auth_challenge_response(
            challenge.get("source"),
            self.opts.proxy_username,
            self.opts.proxy_password,
        )
        try:
            await self._command(
                "Fetch.continueWithAuth",
                {"requestId": params["requestId"], "authChallengeResponse": resp},
                session_id=session_id,
            )
        except Exception as exc:
            self.auth_errors += 1
            logger.warning("continueWithAuth failed: %s", exc)


@dataclass
class InjectorHandle:
    """Handle for a running injector thread (start from any caller context)."""

    ws_endpoint: str = ""
    injector: StealthInjector | None = None
    thread: threading.Thread | None = None
    last_error: str | None = None

    @property
    def applied(self) -> bool:
        return bool(self.injector and self.injector.applied)

    @property
    def alive(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def status(self) -> dict[str, Any]:
        inj = self.injector
        return {
            "applied": self.applied,
            "sessions": inj.sessions_applied if inj else 0,
            "auth_challenges": inj.auth_challenges if inj else 0,
            "auth_errors": inj.auth_errors if inj else 0,
            "requests_paused": inj.requests_paused if inj else 0,
            "requests_continued": inj.requests_continued if inj else 0,
            "ws_endpoint": self.ws_endpoint,
            "error": self.last_error or (inj.last_error if inj else None),
        }

    def wait_applied(self, timeout: float = 10.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.applied:
                return True
            time.sleep(0.1)
        return self.applied

    def stop(self, timeout: float = 3.0) -> None:
        inj = self.injector
        if inj is not None and inj._loop is not None and inj._loop.is_running():
            try:
                inj._loop.call_soon_threadsafe(inj.request_stop)
            except RuntimeError:
                pass
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=timeout)


def load_stealth_source(ext_path: str | None) -> str:
    """Read generated stealth.js (shared with the extension code path)."""
    if not ext_path:
        return ""
    try:
        return (Path(ext_path) / "stealth.js").read_text(encoding="utf-8")
    except OSError:
        return ""


def start_stealth_injector(
    *,
    fingerprint: Any,
    proxy: Any | None = None,
    ws_endpoint: str | None = None,
    user_data_dir: Path | None = None,
    port: int | None = None,
    ext_path: str | None = None,
    profile_id: str = "",
    event_sink: Callable[[str, dict[str, Any]], None] | None = None,
    resolve_timeout_sec: float = 6.0,
) -> InjectorHandle | None:
    """Start the injector in a daemon thread; returns ``None`` if unavailable.

    The thread resolves the CDP WebSocket endpoint (``DevToolsActivePort``
    first, ``/json/version`` as fallback), reads the *real* running Chrome
    version to rebuild UA/Client-Hints consistently, then keeps the stealth
    session alive for the whole profile lifetime.
    """
    if websockets is None:
        logger.warning("websockets not installed — CDP stealth injector disabled")
        return None

    handle = InjectorHandle(ws_endpoint=ws_endpoint or "")
    stealth_src = load_stealth_source(ext_path)

    def _thread_main() -> None:
        try:
            ws = handle.ws_endpoint
            if not ws and user_data_dir is not None:
                ws = _devtools_active_ws(Path(user_data_dir), resolve_timeout_sec)
            if not ws and port:
                ws = _json_version_ws(port, resolve_timeout_sec)
            if not ws:
                handle.last_error = "CDP endpoint could not be resolved"
                logger.warning("stealth injector: %s", handle.last_error)
                return
            handle.ws_endpoint = ws
            chrome_version = read_chrome_version_from_ws_info(ws) or ""
            ua = build_runtime_user_agent(str(fingerprint.user_agent), chrome_version)
            opts = InjectorOptions(
                ws_endpoint=ws,
                user_agent=ua,
                user_agent_metadata=build_user_agent_metadata(fingerprint, chrome_version),
                timezone=str(getattr(fingerprint, "timezone", "") or ""),
                accept_language=str(getattr(fingerprint, "language", "en-US") or "en-US"),
                proxy_username=getattr(proxy, "username", None),
                proxy_password=getattr(proxy, "password", None),
                stealth_source=stealth_src,
                profile_id=profile_id,
                event_sink=event_sink,
            )
            inj = StealthInjector(opts)
            handle.injector = inj
            asyncio.run(inj.run())
        except Exception as exc:
            handle.last_error = str(exc)
            logger.warning("stealth injector stopped: %s", exc)

    thread = threading.Thread(target=_thread_main, daemon=True, name="NazakStealthInjector")
    handle.thread = thread
    thread.start()
    return handle
