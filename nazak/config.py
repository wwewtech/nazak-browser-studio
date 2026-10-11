"""
Nazak Browser Studio - Configuration and System Paths.
Supports both source runtime and frozen PyInstaller standalone executable.
"""

import os
import re
import sys
from pathlib import Path

# Detect frozen executable state
IS_FROZEN = getattr(sys, "frozen", False)

if IS_FROZEN:
    # Running as compiled .exe
    EXE_DIR = Path(sys.executable).resolve().parent
    BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", EXE_DIR))
    BASE_DIR = EXE_DIR
    WEB_DIR = BUNDLE_DIR / "nazak" / "web"
    if not WEB_DIR.exists():
        WEB_DIR = EXE_DIR / "nazak" / "web"
else:
    # Running from source
    BASE_DIR = Path(__file__).resolve().parent.parent
    WEB_DIR = BASE_DIR / "nazak" / "web"

DATA_DIR = BASE_DIR / "data"
# Overridable data root: test runs / portable installs set NAZAK_DATA_DIR before
# importing this module so nothing ever mutates the production data folder.
_env_data_dir = os.environ.get("NAZAK_DATA_DIR")
if _env_data_dir:
    DATA_DIR = Path(_env_data_dir).expanduser()
PROFILES_DIR = DATA_DIR / "profiles"
PROFILES_FILE = DATA_DIR / "profiles.json"
EXTENSIONS_DIR = DATA_DIR / "extensions"
LOGS_DIR = DATA_DIR / "logs"

# P1: importing this module must not touch the filesystem. Directory creation is
# explicit and idempotent, triggered by the real entry points (main(), the API
# composition root, CLI helpers) instead of import side effects — so `import
# nazak.config` in a test or a tool cannot mutate a user's data folder.
_data_dirs_ready = False


def ensure_data_dirs() -> Path:
    """Create the runtime data tree once; returns ``DATA_DIR``.

    Safe to call from any entry point and from multiple threads/processes:
    ``mkdir(parents=True, exist_ok=True)`` is idempotent, and the fast path is
    guarded by a module-level flag so repeated calls are cheap.
    """
    global _data_dirs_ready
    if not _data_dirs_ready:
        for p in (DATA_DIR, PROFILES_DIR, EXTENSIONS_DIR, LOGS_DIR):
            p.mkdir(parents=True, exist_ok=True)
        _data_dirs_ready = True
    return DATA_DIR


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8899

# Autopost demo defaults (kept in config, not hardcoded across endpoints).
DEFAULT_AUTOPOST_TITLE_TEMPLATE = "{Video|New video|Fresh upload} {2026} #shorts"
DEFAULT_AUTOPOST_DESCRIPTION_TEMPLATE = "New upload via Nazak Browser Studio.\\n\\n#shorts"
DEFAULT_AUTOPOST_TG_CHANNEL = "@your_channel"

# Candidate paths for Chrome / Chromium / Edge / Brave / Arc
CHROME_CANDIDATES: list[str] = [
    os.environ.get("CHROME_PATH", ""),
    # Windows paths
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
    os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    # macOS standard Applications
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Arc.app/Contents/MacOS/Arc",
    # macOS user Applications
    os.path.expanduser("~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    os.path.expanduser("~/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
    os.path.expanduser("~/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
    os.path.expanduser("~/Applications/Chromium.app/Contents/MacOS/Chromium"),
    # Linux standard paths
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/brave-browser",
    "/snap/bin/chromium",
    "/usr/local/bin/chrome",
]


def find_chrome_executable() -> str | None:
    """
    Locates the first available Chrome, Chromium, Brave, Edge, or Playwright binary.
    Supports Windows, macOS (Apple Silicon / Intel), and Linux.
    """
    import glob
    import shutil

    # 1. Check direct candidates list
    for candidate in CHROME_CANDIDATES:
        if candidate and os.path.isfile(candidate):
            return str(Path(candidate).resolve())

    # 2. Check system PATH
    for bin_name in (
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "brave-browser",
        "msedge",
        "chrome",
    ):
        p = shutil.which(bin_name)
        if p and os.path.isfile(p):
            return str(Path(p).resolve())

    # 3. Dynamic search in Playwright cache directories across platforms
    playwright_patterns = [
        # macOS Playwright cache
        os.path.expanduser("~/Library/Caches/ms-playwright/chromium-*/chrome-mac/Chromium.app/Contents/MacOS/Chromium"),
        os.path.expanduser(
            "~/Library/Caches/ms-playwright/chromium-*/chrome-mac-arm64/Chromium.app/Contents/MacOS/Chromium"
        ),
        # Linux Playwright cache
        os.path.expanduser("~/.cache/ms-playwright/chromium-*/chrome-linux/chrome"),
        # Windows Playwright cache
        os.path.expandvars(r"%LOCALAPPDATA%\ms-playwright\chromium-*\chrome-win\chrome.exe"),
        os.path.expanduser(r"~\AppData\Local\ms-playwright\chromium-*\chrome-win\chrome.exe"),
    ]
    for pattern in playwright_patterns:
        matches = glob.glob(pattern)
        if matches:
            # Sort by the revision number, not lexicographically: as plain strings
            # "chromium-907" sorts after "chromium-1200", so the oldest cached
            # Chromium used to win and an outdated browser was launched.
            def _revision(path: str) -> int:
                found = re.search(r"chromium-(\d+)", path)
                return int(found.group(1)) if found else -1

            for match in sorted(matches, key=_revision, reverse=True):
                if os.path.isfile(match):
                    return str(Path(match).resolve())

    return None


GOOGLE_TARGET_URLS = {
    "blank": "about:blank",
    "google_search": "https://www.google.com",
    "google_login": "https://accounts.google.com/signin/v2/identifier",
    "google_ads": "https://ads.google.com/intl/en/home/",
    "youtube_studio": "https://studio.youtube.com",
    "youtube": "https://www.youtube.com",
    "whoer_check": "https://whoer.net",
    "browserleaks": "https://browserleaks.com/ip",
    "iphey": "https://iphey.com",
}
