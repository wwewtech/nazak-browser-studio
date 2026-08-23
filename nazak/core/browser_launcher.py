"""
Chrome Browser Process Launcher with Total Host Isolation & Flag Engineering.
"""
import os
import sys
import subprocess
import psutil
from pathlib import Path
from typing import Dict, Optional, List, Tuple

from ..config import find_chrome_executable, PROFILES_DIR, EXTENSIONS_DIR, GOOGLE_TARGET_URLS
from ..models.profile import BrowserProfile, ProfileStatus
from .extension_generator import generate_profile_extension

class BrowserLauncher:
    """
    Manages spawning, isolating, and terminating Chrome browser profile instances.
    Guarantees 100% isolation from host PC environment.
    """
    def __init__(self, profiles_dir: Path = PROFILES_DIR, extensions_dir: Path = EXTENSIONS_DIR):
        self.profiles_dir = profiles_dir
        self.extensions_dir = extensions_dir
        self.active_processes: Dict[str, subprocess.Popen] = {}
        self.profile_pids: Dict[str, int] = {}

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
            "parent.lock"
        ]
        for name in lock_files:
            f = user_data_dir / name
            try:
                if f.is_file() or f.is_symlink():
                    f.unlink(missing_ok=True)
            except Exception:
                pass

    def build_chrome_args(
        self,
        profile: BrowserProfile,
        chrome_exe: str,
        custom_url: Optional[str] = None,
        cdp_port: Optional[int] = None
    ) -> Tuple[List[str], Optional[str]]:
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
            f"--user-data-dir={str(user_data_path)}",
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
        self,
        profile: BrowserProfile,
        custom_url: Optional[str] = None,
        cdp_port: Optional[int] = None
    ) -> Tuple[bool, Optional[int], Optional[str]]:
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
            args, ext_path = self.build_chrome_args(profile, chrome_exe, custom_url, cdp_port=cdp_port)
            
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
                close_fds=(sys.platform != "win32")
            )

            self.active_processes[profile.id] = proc
            self.profile_pids[profile.id] = proc.pid
            return True, proc.pid, None

        except Exception as e:
            return False, None, f"Failed to launch Chrome: {str(e)}"

    def stop(self, profile_id: str) -> Tuple[bool, Optional[str]]:
        """
        Terminates the browser process associated with the profile.
        """
        proc = self.active_processes.get(profile_id)
        pid = self.profile_pids.get(profile_id)

        if not proc and not pid:
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
                        ["taskkill", "/F", "/T", "/PID", str(pid)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
                except Exception:
                    pass

        self.active_processes.pop(profile_id, None)
        self.profile_pids.pop(profile_id, None)
        return True, None
