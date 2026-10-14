"""
Chrome Browser Process Launcher with Total Host Isolation & Flag Engineering.
"""

import asyncio
import ctypes
import json
import logging
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

import psutil

from ..config import EXTENSIONS_DIR, GOOGLE_TARGET_URLS, PROFILES_DIR, find_chrome_executable
from ..models.profile import BrowserProfile
from ..models.proxy import ProxyConfig, ProxyType
from .cdp_injector import InjectorHandle, build_runtime_user_agent, start_stealth_injector
from .extension_generator import generate_profile_extension
from .local_proxy import AuthForwardProxy

logger = logging.getLogger(__name__)

_CHROME_VERSION_CACHE: dict[str, str | None] = {}

_ALLOWED_URL_SCHEMES = ("http://", "https://", "about:")


def sanitize_launch_url(url: str | None) -> str | None:
    """Validate a launch target before it becomes Chrome's last argv entry.

    Audit D2-P1-3: ``custom_url`` was appended verbatim, so a value starting
    with ``-`` (or ``file:///...``) injected arbitrary Chrome switches / read
    local files. Only http(s) and ``about:`` targets survive; a bare host is
    promoted to https.
    """
    if not url:
        return None
    cleaned = str(url).strip()
    if not cleaned:
        return None
    if cleaned.startswith("-"):
        raise ValueError("URL must not start with '-'")
    if "\\" in cleaned:
        # Windows UNC (`\\server\share`) and device (`\\?\C:\...`) paths were
        # silently "promoted" to https://<that string>, which both violates the
        # documented allow-list and looks like a usable URL to the caller.
        raise ValueError("URL must be http(s) or about:")
    lowered = cleaned.lower()
    if lowered.startswith(("file:", "javascript:", "data:", "blob:", "vbscript:")):
        raise ValueError("URL scheme is not allowed")
    if cleaned.startswith(_ALLOWED_URL_SCHEMES):
        return cleaned
    if "//" not in cleaned.split(":")[0]:
        return "https://" + cleaned.lstrip("/")
    raise ValueError("URL scheme is not allowed")


def _windows_file_version(path: str) -> str | None:
    """Read VS_FIXEDFILEINFO (e.g. '153.0.8010.53') from a PE binary."""
    try:
        size = ctypes.windll.version.GetFileVersionInfoSizeW(path, None)  # type: ignore[attr-defined]
        if not size:
            return None
        buf = ctypes.create_string_buffer(size)
        if not ctypes.windll.version.GetFileVersionInfoW(path, 0, size, buf):  # type: ignore[attr-defined]
            return None
        res = ctypes.c_void_p()
        length = ctypes.c_uint()
        if not ctypes.windll.version.VerQueryValueW(  # type: ignore[attr-defined]
            buf, "\\", ctypes.byref(res), ctypes.byref(length)
        ):
            return None

        class VS_FIXEDFILEINFO(ctypes.Structure):
            _fields_ = [
                ("dwSignature", ctypes.c_uint32),
                ("dwStrucVersion", ctypes.c_uint32),
                ("dwFileVersionMS", ctypes.c_uint32),
                ("dwFileVersionLS", ctypes.c_uint32),
                ("dwProductVersionMS", ctypes.c_uint32),
                ("dwProductVersionLS", ctypes.c_uint32),
                ("dwFileFlagsMask", ctypes.c_uint32),
                ("dwFileFlags", ctypes.c_uint32),
                ("dwFileOS", ctypes.c_uint32),
                ("dwFileType", ctypes.c_uint32),
                ("dwFileSubtype", ctypes.c_uint32),
                ("dwFileDateMS", ctypes.c_uint32),
                ("dwFileDateLS", ctypes.c_uint32),
            ]

        info = ctypes.cast(res, ctypes.POINTER(VS_FIXEDFILEINFO)).contents
        ms, ls = info.dwFileVersionMS, info.dwFileVersionLS
        return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
    except Exception:
        return None


def get_chrome_version(chrome_exe: str) -> str | None:
    """Detect the real installed Chrome/Chromium version (cached per executable).

    Used so UA / Client-Hints shields never advertise a stale version
    (audit finding A2b: UA said 133 while brands said 153).
    """
    if not chrome_exe:
        return None
    if chrome_exe in _CHROME_VERSION_CACHE:
        return _CHROME_VERSION_CACHE[chrome_exe]
    version: str | None = None
    try:
        if sys.platform == "win32":
            version = _windows_file_version(chrome_exe)
        if not version:
            out = subprocess.run([chrome_exe, "--version"], capture_output=True, text=True, timeout=5, check=False)
            m = re.search(r"(\d+\.\d+\.\d+\.\d+)", out.stdout or "")
            version = m.group(1) if m else None
    except Exception:
        version = None
    _CHROME_VERSION_CACHE[chrome_exe] = version
    return version


def get_free_port() -> int:
    """Finds an available TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        return s.getsockname()[1]


class BrowserLauncher:
    """
    Manages spawning, isolating, and terminating Chrome browser profile instances.
    Guarantees 100% isolation from host PC environment.
    """

    def __init__(self, profiles_dir: Path = PROFILES_DIR, extensions_dir: Path = EXTENSIONS_DIR):
        self.profiles_dir = profiles_dir
        self.extensions_dir = extensions_dir
        # Registry of live browser sessions. All six dicts below are mutated
        # from the GUI thread, TaskBridge worker threads, the API request
        # pool and the process monitor concurrently, and is_profile_running()
        # performs multi-step read-then-cleanup sequences — an unsynchronized
        # dict race can drop a pid and leak the Chrome process. One RLock
        # guards every access (fix F1).
        self._registry_lock = threading.RLock()
        self.active_processes: dict[str, subprocess.Popen] = {}
        self.profile_pids: dict[str, int] = {}
        self.profile_cdp_ports: dict[str, int] = {}
        self.profile_cdp_ws: dict[str, str] = {}
        # CDP stealth injector session per profile (audit fix P0-1): applies
        # stealth.js / timezone / UA / proxy-auth over DevTools Protocol,
        # because branded Chrome 137+ ignores --load-extension.
        self._injectors: dict[str, InjectorHandle] = {}
        # Loopback auth-injecting proxy for upstream proxies with credentials.
        self._forwarders: dict[str, AuthForwardProxy] = {}
        # Gesture sink for the synchronizer (set by the API bootstrap / GUI).
        self._event_sink = None

    def is_profile_running(self, profile_id: str) -> bool:
        """Checks if profile process is currently alive."""
        with self._registry_lock:
            if profile_id in self.active_processes:
                proc = self.active_processes[profile_id]
                if proc.poll() is None:
                    return True
                self.active_processes.pop(profile_id, None)

            if profile_id in self.profile_pids:
                pid = self.profile_pids[profile_id]
                if psutil.pid_exists(pid):
                    try:
                        p = psutil.Process(pid)
                        if p.is_running() and p.status() != psutil.STATUS_ZOMBIE:
                            return True
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                self.profile_pids.pop(profile_id, None)
            self.profile_cdp_ports.pop(profile_id, None)
            self.profile_cdp_ws.pop(profile_id, None)
        self._stop_injector(profile_id)
        self._stop_forwarder(profile_id)
        return False

    def clean_stale_locks(self, user_data_dir: Path):
        """
        Removes Chromium SingletonLock and socket artifacts to prevent startup lock errors.
        """
        lock_files = [
            "SingletonLock",
            "SingletonCookie",
            "SingletonSocket",
            "lockfile",
            "parent.lock",
            "DevToolsActivePort",
        ]
        for name in lock_files:
            f = user_data_dir / name
            try:
                if f.is_file() or f.is_symlink():
                    f.unlink(missing_ok=True)
            except Exception:
                pass

    def _random_window_position(self, fp) -> str:
        """A plausible per-launch window position (anti-detect audit F-01).

        Every real user's window lands slightly differently (taskbar side,
        drag habits, monitor layout); a farm that opens every browser at the
        same pixel position is a one-line cluster signature. The position is
        randomized inside the spoofed screen, biased toward the top-left
        quadrant where humans usually leave their window, and never lets the
        window extend past the spoofed screen bounds.
        """
        import random as _random

        try:
            screen_w = int(getattr(fp, "screen_width", 0) or 1920)
            screen_h = int(getattr(fp, "screen_height", 0) or 1080)
        except Exception:
            screen_w, screen_h = 1920, 1080
        # Window chrome/borders allowance so the window stays on-screen.
        margin_x = max(0, (screen_w - int(screen_w * 0.8)) // 2)
        margin_y = max(0, (screen_h - int(screen_h * 0.8)) // 2)
        x = _random.randint(8, max(8, margin_x + 120))
        y = _random.randint(8, max(8, margin_y + 80))
        return f"{x},{y}"

    def build_chrome_args(
        self, profile: BrowserProfile, chrome_exe: str, custom_url: str | None = None, cdp_port: int | None = None
    ) -> tuple[list[str], str | None]:
        """
        Constructs the strict isolation command line arguments for Chromium launch.
        """
        user_data_path = self.profiles_dir / profile.id
        user_data_path.mkdir(parents=True, exist_ok=True)
        self.clean_stale_locks(user_data_path)

        ext_path = generate_profile_extension(
            profile,
            self.extensions_dir,
            chrome_version=get_chrome_version(chrome_exe),
            cdp_port=cdp_port,
        )
        fp = profile.fingerprint
        proxy = profile.proxy
        # Keep the flag-level UA consistent with the runtime CDP override.
        launch_ua = build_runtime_user_agent(fp.user_agent, get_chrome_version(chrome_exe) or "")

        args = [
            chrome_exe,
            f"--user-data-dir={user_data_path!s}",
            "--profile-directory=Default",
            "--no-first-run",
            "--no-default-browser-check",
            # Anti-detect (audit F-17): --disable-blink-features=AutomationControlled
            # is a *Puppeteer* flag — it never affected regular Chrome and only
            # marked the argv as automation tooling. navigator.webdriver is
            # spoofed in the stealth layer instead.
            "--disable-infobars",
            "--disable-features=IsolateOrigins,site-per-process,TranslateUI,UserAgentClientHint",
            f"--force-webrtc-ip-handling-policy={fp.webrtc_policy}",
            "--enforce-webrtc-ip-permission-check",
            f"--window-size={fp.screen_width},{fp.screen_height}",
            # Anti-detect (audit F-01): a fixed 40,40 opening position is a
            # pixel-identical cluster signature across a whole farm — every
            # real user drags their window differently. Randomized per launch,
            # kept inside the spoofed screen so screenX/screenY stay plausible.
            f"--window-position={self._random_window_position(fp)}",
            f"--user-agent={launch_ua}",
            "--password-store=basic",
            "--use-mock-keychain",
            "--allow-running-insecure-content",
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-client-side-phishing-detection",
            "--disable-sync",
            "--metrics-recording-only",
            "--disable-default-apps",
            "--disable-hang-monitor",
            "--disable-prompt-on-repost",
            "--disable-breakpad",
        ]

        primary_lang = fp.language.split(",")[0].strip() if fp.language else "en-US"
        args.append(f"--lang={primary_lang}")
        if fp.timezone:
            args.append(f"--time-zone-for-testing={fp.timezone}")
        if cdp_port:
            args.append(f"--remote-debugging-port={cdp_port}")

        if not proxy.is_direct():
            chrome_proxy = proxy.to_chrome_proxy_arg()
            if chrome_proxy:
                args.append(f"--proxy-server={chrome_proxy}")

        if ext_path:
            args.append(f"--load-extension={ext_path}")
            args.append(f"--disable-extensions-except={ext_path}")

        target_url = "about:blank"
        if custom_url:
            target_url = sanitize_launch_url(custom_url) or target_url
        elif profile.google.auto_open_page in GOOGLE_TARGET_URLS:
            target_url = GOOGLE_TARGET_URLS[profile.google.auto_open_page]
        elif profile.google.custom_url:
            target_url = sanitize_launch_url(profile.google.custom_url) or target_url

        args.append(target_url)
        return args, ext_path

    def _stop_injector(self, profile_id: str) -> None:
        with self._registry_lock:
            handle = self._injectors.pop(profile_id, None)
        if handle is not None:
            try:
                handle.stop(timeout=2.0)
            except Exception:  # pragma: no cover - defensive
                logger.debug("injector stop failed for %s", profile_id, exc_info=True)

    def _stop_forwarder(self, profile_id: str) -> None:
        with self._registry_lock:
            forwarder = self._forwarders.pop(profile_id, None)
        if forwarder is not None:
            try:
                forwarder.stop()
            except Exception:  # pragma: no cover - defensive
                logger.debug("forwarder stop failed for %s", profile_id, exc_info=True)

    def set_event_sink(self, sink) -> None:
        """Register the synchronizer gesture sink (audit fix P0-2)."""
        self._event_sink = sink

    def get_stealth_status(self, profile_id: str) -> dict[str, Any] | None:
        """CDP stealth injector status (None when injector never started)."""
        with self._registry_lock:
            handle = self._injectors.get(profile_id)
        return handle.status() if handle else None

    def launch(
        self, profile: BrowserProfile, custom_url: str | None = None, cdp_port: int | None = None
    ) -> tuple[bool, int | None, str | None]:
        """
        Launches the browser for the given profile.
        Returns: (success, pid, error_message)
        """
        if self.is_profile_running(profile.id):
            return False, self.profile_pids.get(profile.id), "Profile is already running"

        chrome_exe = find_chrome_executable()
        if not chrome_exe:
            return False, None, "Google Chrome or Chromium executable not found on system"

        try:
            # Always open a CDP port: branded Chrome 137+ ignores
            # --load-extension, so stealth is applied over DevTools Protocol.
            if cdp_port is None:
                cdp_port = get_free_port()
            user_data_path = self.profiles_dir / profile.id
            # Proxy with credentials: Chrome cannot embed them in --proxy-server,
            # so route through a loopback forwarder that adds Proxy-Authorization.
            self._stop_forwarder(profile.id)
            launch_profile = profile
            if (
                profile.proxy.has_auth()
                and profile.proxy.type in (ProxyType.HTTP, ProxyType.HTTPS)
                and profile.proxy.host
                and profile.proxy.port
            ):
                forwarder = AuthForwardProxy(
                    profile.proxy.host,
                    profile.proxy.port,
                    profile.proxy.username or "",
                    profile.proxy.password or "",
                )
                try:
                    fwd_port = forwarder.start()
                    self._forwarders[profile.id] = forwarder
                    launch_profile = profile.model_copy(
                        update={
                            "proxy": ProxyConfig(type=ProxyType.HTTP, host="127.0.0.1", port=fwd_port),
                        }
                    )
                except Exception as exc:  # pragma: no cover - defensive
                    logger.warning("auth forwarder start failed: %s", exc)
                    self._stop_forwarder(profile.id)
            args, ext_path = self.build_chrome_args(launch_profile, chrome_exe, custom_url, cdp_port=cdp_port)
            popen_kwargs: dict[str, Any] = {
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
                "stdin": subprocess.DEVNULL,
                "close_fds": (sys.platform != "win32"),
            }
            env = os.environ.copy()
            if profile.fingerprint and profile.fingerprint.timezone:
                env["TZ"] = profile.fingerprint.timezone
            popen_kwargs["env"] = env

            if sys.platform == "win32":
                popen_kwargs["creationflags"] = 0x08000000 | subprocess.CREATE_NEW_PROCESS_GROUP

            proc = subprocess.Popen(args, **popen_kwargs)

            with self._registry_lock:
                self.active_processes[profile.id] = proc
                self.profile_pids[profile.id] = proc.pid
                if cdp_port:
                    self.profile_cdp_ports[profile.id] = cdp_port
                    # Attach the CDP stealth injector (resolves DevToolsActivePort
                    # in its own thread once Chromium has opened the endpoint).
                    self._stop_injector(profile.id)
            if cdp_port:
                handle = start_stealth_injector(
                    fingerprint=profile.fingerprint,
                    proxy=profile.proxy,
                    user_data_dir=user_data_path,
                    port=cdp_port,
                    ext_path=ext_path,
                    profile_id=profile.id,
                    event_sink=self._event_sink,
                )
                if handle is not None:
                    with self._registry_lock:
                        self._injectors[profile.id] = handle
            return True, proc.pid, None

        except Exception as e:
            self._stop_forwarder(profile.id)
            return False, None, f"Failed to launch Chrome: {e!s}"

    def read_devtools_active_port(self, user_data_dir: Path, timeout_sec: float = 4.0) -> tuple[int | None, str | None]:
        """
        Reads DevToolsActivePort generated by Chromium upon remote debugging initialization.
        Returns: (actual_port, websocket_debugger_url)
        """
        port_file = user_data_dir / "DevToolsActivePort"
        start_time = time.time()
        while time.time() - start_time < timeout_sec:
            if port_file.exists():
                try:
                    content = port_file.read_text(encoding="utf-8").strip()
                    lines = [line.strip() for line in content.splitlines() if line.strip()]
                    if len(lines) >= 2:
                        actual_port = int(lines[0])
                        ws_path = lines[1]
                        ws_url = f"ws://127.0.0.1:{actual_port}{ws_path}"
                        return actual_port, ws_url
                except Exception:
                    pass
            time.sleep(0.1)
        return None, None

    async def wait_for_cdp(self, profile_id: str, timeout_sec: float = 6.0) -> bool:
        """Async-friendly wait until Chromium exposes its DevTools endpoint.

        Replaces the old fixed ``await asyncio.sleep(4)`` after a launch: that
        either slept too long (CDP up in 0.5 s) or too little (slow disk, the
        endpoint appeared at 5 s and the upload already failed to connect).
        Polls the DevToolsActivePort file (and the known CDP port as a second
        signal) and returns as soon as the endpoint is reachable.
        """
        user_data_path = self.profiles_dir / profile_id
        deadline = time.monotonic() + timeout_sec
        port_file = user_data_path / "DevToolsActivePort"
        while time.monotonic() < deadline:
            if port_file.exists():
                try:
                    content = port_file.read_text(encoding="utf-8").strip()
                    lines = [line.strip() for line in content.splitlines() if line.strip()]
                    if len(lines) >= 2:
                        return True
                except Exception:
                    pass
            # Second signal: the assigned port answers /json/version.
            with self._registry_lock:
                port = self.profile_cdp_ports.get(profile_id)
            if port and self.resolve_cdp_ws_url(port, timeout_sec=0.3):
                return True
            await asyncio.sleep(0.25)
        return False

    def resolve_cdp_ws_url(self, port: int, timeout_sec: float = 5.0) -> str | None:
        """
        Queries Chromium's /json/version endpoint to obtain the WebSocket debugger URL.
        """
        start_time = time.time()
        url = f"http://127.0.0.1:{port}/json/version"
        while time.time() - start_time < timeout_sec:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Nazak-Studio"})
                with urllib.request.urlopen(req, timeout=1.0) as resp:  # nosec B310 - loopback CDP endpoint
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8"))
                        ws_url = data.get("webSocketDebuggerUrl")
                        if ws_url:
                            return ws_url
            except Exception:
                time.sleep(0.15)
        return None

    def get_cdp_info(self, profile_id: str) -> dict[str, Any] | None:
        """Returns CDP port and WebSocket URL if profile is running with CDP enabled."""
        if not self.is_profile_running(profile_id):
            return None
        with self._registry_lock:
            port = self.profile_cdp_ports.get(profile_id)
            if not port:
                return None
        user_data_path = self.profiles_dir / profile_id
        _, active_ws = self.read_devtools_active_port(user_data_path, timeout_sec=0.2)
        with self._registry_lock:
            ws = active_ws or self.profile_cdp_ws.get(profile_id)
        if not ws:
            ws = self.resolve_cdp_ws_url(port, timeout_sec=1.0)
        if ws:
            with self._registry_lock:
                self.profile_cdp_ws[profile_id] = ws
        ws_url = ws or f"ws://127.0.0.1:{port}/devtools/browser"
        stealth = self.get_stealth_status(profile_id)
        return {
            "port": port,
            "ws_endpoint": ws_url,
            "wsEndpoint": ws_url,
            "http_endpoint": f"http://127.0.0.1:{port}",
            # True once the CDP injector applied stealth.js/TZ/UA/proxy-auth.
            "stealth_applied": bool(stealth and stealth.get("applied")),
            "stealth": stealth,
        }

    def launch_with_cdp(
        self, profile: BrowserProfile, custom_url: str | None = None, port: int | None = None
    ) -> tuple[bool, int | None, int | None, str | None, str | None]:
        """
        Launches profile with an assigned CDP remote debugging port and resolves its WebSocket URL.
        Returns: (success, pid, port, ws_endpoint, error_message)
        """
        assigned_port = port or get_free_port()
        ok, pid, err = self.launch(profile, custom_url=custom_url, cdp_port=assigned_port)
        if not ok:
            return False, None, None, None, err

        user_data_path = self.profiles_dir / profile.id
        detected_port, ws_url = self.read_devtools_active_port(user_data_path, timeout_sec=3.0)
        final_port = detected_port or assigned_port

        if not ws_url:
            ws_url = self.resolve_cdp_ws_url(final_port, timeout_sec=3.0)

        if not ws_url:
            ws_url = f"ws://127.0.0.1:{final_port}/devtools/browser"

        with self._registry_lock:
            self.profile_cdp_ports[profile.id] = final_port
            self.profile_cdp_ws[profile.id] = ws_url
        return True, pid, final_port, ws_url, None

    def stop(self, profile_id: str) -> tuple[bool, str | None]:
        """
        Terminates the browser process associated with the profile.
        """
        self._stop_injector(profile_id)
        self._stop_forwarder(profile_id)
        with self._registry_lock:
            proc = self.active_processes.get(profile_id)
            pid = self.profile_pids.get(profile_id)

            if not proc and not pid:
                self.profile_cdp_ports.pop(profile_id, None)
                self.profile_cdp_ws.pop(profile_id, None)
                return True, "Profile is not currently running"

        try:
            if pid and psutil.pid_exists(pid):
                parent = psutil.Process(pid)
                for child in parent.children(recursive=True):
                    try:
                        child.terminate()
                    except Exception:
                        pass
                parent.terminate()
                parent.wait(timeout=2.0)
        except Exception:
            if pid and sys.platform == "win32":
                try:
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                    )
                except Exception:
                    pass

        with self._registry_lock:
            self.active_processes.pop(profile_id, None)
            self.profile_pids.pop(profile_id, None)
            self.profile_cdp_ports.pop(profile_id, None)
            self.profile_cdp_ws.pop(profile_id, None)
        return True, None
