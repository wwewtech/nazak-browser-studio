"""Regression tests for the second hunting round (proxy parser + bundle + netscape)."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from nazak.core.cookie_manager import cookies_to_netscape, parse_netscape_cookies
from nazak.core.profiles.bundles import import_bundle
from nazak.models.profile import BrowserProfile
from nazak.models.proxy import ProxyConfig, ProxyType, sanitize_port


# ---------------------------------------------------------------------------
# P-02: colon-form password containing '@'
# ---------------------------------------------------------------------------
def test_colon_form_password_with_at_sign_beats_at_branch():
    p = ProxyConfig.parse("host.com:8080:user:p@ss")
    assert p.type == ProxyType.HTTP
    assert p.host == "host.com"
    assert p.port == 8080
    assert p.username == "user"
    assert p.password == "p@ss"


def test_url_form_password_with_at_sign_still_works():
    p = ProxyConfig.parse("user:p@ss@host.com:8080")
    assert p.host == "host.com"
    assert p.username == "user"
    assert p.password == "p@ss"


# ---------------------------------------------------------------------------
# P-03: explicit invalid ports fail loudly; shorthand keeps the default
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("bad", ["127.0.0.1:999999", "127.0.0.1:0", "127.0.0.1:-1", "127.0.0.1:65536"])
def test_explicit_out_of_range_port_raises(bad):
    with pytest.raises(ValueError, match=r"1\.\.65535"):
        ProxyConfig.parse(bad)


def test_non_numeric_port_is_shorthand_not_error():
    p = ProxyConfig.parse("proxy.example.com:notaport")
    assert p.host == "proxy.example.com"
    assert p.port == 8080


def test_sanitize_port_contract():
    assert sanitize_port("443") == 443
    assert sanitize_port(None, default=1080) == 1080
    assert sanitize_port("junk", default=1080) == 1080
    with pytest.raises(ValueError):
        sanitize_port(0)
    with pytest.raises(ValueError):
        sanitize_port(70000)


# ---------------------------------------------------------------------------
# P-04: rotation hash spellings
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "rot"),
    [
        ("https://proxy.example.com:443#rotation=http://rot.example/", "http://rot.example/"),
        ("1.2.3.4:8080#rotate=http://r.example/x", "http://r.example/x"),
        ("1.2.3.4:8080#url=http://u.example/y", "http://u.example/y"),
        ("1.2.3.4:8080#http://plain.example/z", "http://plain.example/z"),
        ("1.2.3.4:8080|http://rot.example/", "http://rot.example/"),
    ],
)
def test_rotation_separator_spellings(raw, rot):
    p = ProxyConfig.parse(raw)
    assert p.rotation_url == rot


def test_port_survives_rotation_split():
    p = ProxyConfig.parse("https://proxy.example.com:443#rotation=http://rot.example/")
    assert p.port == 443
    assert p.username is None


def test_trailing_separator_without_url(tmp_path=None):
    p = ProxyConfig.parse("host:1080|")
    assert p.host == "host" and p.port == 1080 and p.rotation_url is None
    p2 = ProxyConfig.parse("host:1080#")
    assert p2.host == "host" and p2.port == 1080


# ---------------------------------------------------------------------------
# H-12: bundle hostile entries are rejected up front
# ---------------------------------------------------------------------------
def _bundle(tmp_path: Path, entries: dict, cookies: str = "[]") -> Path:
    path = tmp_path / "b.nazak"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("profile.json", json.dumps({"id": "probe", "name": "Probe"}))
        zf.writestr("cookies.json", cookies)
        for name, content in entries.items():
            zf.writestr(name, content)
    return path


def test_bundle_rejects_windows_reserved_device_names(tmp_path):
    pm = tmp_path / "profiles"
    pm.mkdir()
    assert import_bundle(pm, _bundle(tmp_path, {"data/CON.txt": "x"})) is None
    assert import_bundle(pm, _bundle(tmp_path, {"data/NUL.bin": "x"})) is None
    assert import_bundle(pm, _bundle(tmp_path, {"data/com1.txt": "x"})) is None


def test_bundle_rejects_trailing_dot_space_names(tmp_path):
    pm = tmp_path / "profiles"
    pm.mkdir()
    assert import_bundle(pm, _bundle(tmp_path, {"data/trailing. ": "x"})) is None


def test_bundle_rejects_control_character_names(tmp_path):
    pm = tmp_path / "profiles"
    pm.mkdir()
    assert import_bundle(pm, _bundle(tmp_path, {"data/ba\nd.txt": "x"})) is None


def test_bundle_rejects_non_list_cookies_json(tmp_path):
    pm = tmp_path / "profiles"
    pm.mkdir()
    assert import_bundle(pm, _bundle(tmp_path, {"data/x.txt": "x"}, cookies='{"not": "a list"}')) is None


def test_bundle_accepts_normal_entries(tmp_path):
    pm = tmp_path / "profiles"
    pm.mkdir()
    res = import_bundle(pm, _bundle(tmp_path, {"data/ok.txt": "fine", "data/sub/inner.txt": "deep"}))
    assert res is not None
    root = pm / str(res.id)
    assert (root / "ok.txt").read_text(encoding="utf-8") == "fine"
    assert (root / "sub" / "inner.txt").read_text(encoding="utf-8") == "deep"


def test_bundle_rejection_leaves_no_partial_dir(tmp_path):
    pm = tmp_path / "profiles"
    pm.mkdir()
    import_bundle(pm, _bundle(tmp_path, {"data/ok.txt": "x", "data/CON.txt": "y"}))
    leftovers = [p for p in pm.rglob("*") if p.is_dir()]
    assert not leftovers, f"partial profile dirs left behind: {leftovers}"


# ---------------------------------------------------------------------------
# H-10: netscape export with tabs in name/value
# ---------------------------------------------------------------------------
def test_netscape_export_marks_tab_cookies_instead_of_corrupting():
    cookies = [
        {"name": "good", "value": "v", "domain": ".example.com", "path": "/", "expires": 0},
        {"name": "tab\tname", "value": "v", "domain": ".example.com", "path": "/", "expires": 0},
    ]
    text = cookies_to_netscape(cookies)
    assert "good" in text
    assert "SKIPPED (tab in name/value" in text
    reparsed = parse_netscape_cookies(text)
    names = {c["name"] for c in reparsed}
    assert "good" in names
    assert "tab\tname" not in names  # the unrepresentable cookie is dropped, not mangled
