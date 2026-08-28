"""
Chrome Browser Process Launcher with Total Host Isolation & Flag Engineering.
"""

import json
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

import psutil

from ..config import EXTENSIONS_DIR, GOOGLE_TARGET_URLS, PROFILES_DIR, find_chrome_executable
from ..models.profile import BrowserProfile
from .extension_generator import generate_profile_extension


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
        self.active_processes: dict[str, subprocess.Popen] = {}
        self.profile_pids: dict[str, int] = {}
        self.profile_cdp_ports: dict[str, int] = {}
        self.profile_cdp_ws: dict[str, str] = {}

    def is_profile_running(self, profile_id: str) -> bool:
        """Checks if profile process is currently alive."""
        if profile_id in self.active_processes:
            proc = self.active_processes[profile_id]
            if proc.poll() is None:
                return True
            else:
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
        return False

    def clean_stale_locks(self, user_data_dir: Path):
        """
        Removes Chromium SingletonLock and socket artifacts to prevent startup lock errors.
        """
        lock_files = ["SingletonLock", "SingletonCookie", "SingletonSocket", "lockfile", "parent.lock"]
        for name in lock_files:
            f = user_data_dir / name
            try:
                if f.is_file() or f.is_symlink():
                    f.unlink(missing_ok=True)
            except Exception:
                pass

    def build_chrome_args(
        self, profile: BrowserProfile, chrome_exe: str, custom_url: str | None = None, cdp_port: int | None = None
    ) -> tuple[list[str], str | None]:
        """
        Constructs the strict isolation command line arguments for Chromium launch.
        """
        user_data_path = self.profiles_dir / profile.id
        user_data_path.mkdir(parents=True, exist_ok=True)
        self.clean_stale_locks(user_data_path)

        ext_path = generate_profile_extension(profile, self.extensions_dir)
        fp = profile.fingerprint
        proxy = profile.proxy

        args = [
            chrome_exe,
            f"--user-data-dir={user_data_path!s}",
            "--profile-directory=Default",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            "--disable-features=IsolateOrigins,site-per-process,TranslateUI,UserAgentClientHint",
            f"--force-webrtc-ip-handling-policy={fp.webrtc_policy}",
            "--enforce-webrtc-ip-permission-check",
            f"--window-size={fp.screen_width},{fp.screen_height}",
            "--window-position=40,40",
            f"--user-agent={fp.user_agent}",
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
            target_url = custom_url
        elif profile.google.auto_open_page in GOOGLE_TARGET_URLS:
            target_url = GOOGLE_TARGET_URLS[profile.google.auto_open_page]
        elif profile.google.custom_url:
            target_url = profile.google.custom_url

        args.append(target_url)
        return args, ext_path

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
            args, _ext_path = self.build_chrome_args(profile, chrome_exe, custom_url, cdp_port=cdp_port)

            creation_flags = 0
            if sys.platform == "win32":
                # CREATE_NO_WINDOW (0x08000000) and CREATE_NEW_PROCESS_GROUP (0x00000200)
                creation_flags = 0x08000000 | subprocess.CREATE_NEW_PROCESS_GROUP

            proc = subprocess.Popen(
                args,
                creationflags=creation_flags,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                close_fds=(sys.platform != "win32"),
            )

            self.active_processes[profile.id] = proc
            self.profile_pids[profile.id] = proc.pid
            if cdp_port:
                self.profile_cdp_ports[profile.id] = cdp_port
            return True, proc.pid, None

        except Exception as e:
            return False, None, f"Failed to launch Chrome: {e!s}"

    def resolve_cdp_ws_url(self, port: int, timeout_sec: float = 5.0) -> str | None:
        """
        Queries Chromium's /json/version endpoint to obtain the WebSocket debugger URL.
        """
        start_time = time.time()
        url = f"http://127.0.0.1:{port}/json/version"
        while time.time() - start_time < timeout_sec:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Nazak-Studio"})
                with urllib.request.urlopen(req, timeout=1.0) as resp:
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
        port = self.profile_cdp_ports.get(profile_id)
        if not port:
            return None
        ws = self.profile_cdp_ws.get(profile_id) or self.resolve_cdp_ws_url(port, timeout_sec=1.0)
        if ws:
            self.profile_cdp_ws[profile_id] = ws
        return {
            "port": port,
            "ws_endpoint": ws or f"ws://127.0.0.1:{port}/devtools/browser",
            "http_endpoint": f"http://127.0.0.1:{port}",
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

        self.profile_cdp_ports[profile.id] = assigned_port
        ws_url = (
            self.resolve_cdp_ws_url(assigned_port, timeout_sec=6.0)
            or f"ws://127.0.0.1:{assigned_port}/devtools/browser"
        )
        self.profile_cdp_ws[profile.id] = ws_url
        return True, pid, assigned_port, ws_url, None

    def stop(self, profile_id: str) -> tuple[bool, str | None]:
        """
        Terminates the browser process associated with the profile.
        """
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

        self.active_processes.pop(profile_id, None)
        self.profile_pids.pop(profile_id, None)
        self.profile_cdp_ports.pop(profile_id, None)
        self.profile_cdp_ws.pop(profile_id, None)
        return True, None
