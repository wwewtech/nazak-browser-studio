"""
Nazak Browser Studio - Configuration and System Paths.
Supports both source runtime and frozen PyInstaller standalone executable.
"""
import os
import sys
from pathlib import Path
from typing import List, Optional

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
PROFILES_DIR = DATA_DIR / "profiles"
PROFILES_FILE = DATA_DIR / "profiles.json"
EXTENSIONS_DIR = DATA_DIR / "extensions"
LOGS_DIR = DATA_DIR / "logs"

for p in (DATA_DIR, PROFILES_DIR, EXTENSIONS_DIR, LOGS_DIR):
    p.mkdir(parents=True, exist_ok=True)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8899

# Candidate paths for Chrome / Edge
CHROME_CANDIDATES: List[str] = [
    os.environ.get("CHROME_PATH", ""),
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
    os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
]

def find_chrome_executable() -> Optional[str]:
    """Locates the first available Chrome or Chromium binary."""
    for candidate in CHROME_CANDIDATES:
        if candidate and os.path.isfile(candidate):
            return str(Path(candidate).resolve())
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
    "iphey": "https://iphey.com"
}
