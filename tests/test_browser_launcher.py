from pathlib import Path

import pytest

from nazak.config import find_chrome_executable
from nazak.core.browser_launcher import BrowserLauncher
from nazak.models.profile import BrowserProfile, FingerprintConfig
from nazak.models.proxy import ProxyConfig


def test_build_chrome_arguments(tmp_path):
    pdir = tmp_path / "profiles"
    edir = tmp_path / "extensions"
    bl = BrowserLauncher(profiles_dir=pdir, extensions_dir=edir)

    prof = BrowserProfile(
        id="test_args_prof",
        name="Arg Test Profile",
        proxy=ProxyConfig.parse("http://127.0.0.1:8080"),
        fingerprint=FingerprintConfig(screen_width=1920, screen_height=1080, language="en-US"),
    )

    fake_chrome = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
    args, ext_path = bl.build_chrome_args(prof, fake_chrome, custom_url="https://accounts.google.com")

    arg_str = " ".join(args)
    assert "--user-data-dir=" in arg_str
    assert "test_args_prof" in arg_str
    assert "--proxy-server=http://127.0.0.1:8080" in arg_str
    assert "--disable-blink-features=AutomationControlled" in arg_str
    assert "--force-webrtc-ip-handling-policy=disable_non_proxied_udp" in arg_str
    assert "https://accounts.google.com" in args[-1]
