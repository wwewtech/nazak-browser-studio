"""Phase 4: verify proxy credentials are safely JSON-escaped in the generated
Chrome extension's background.js (no JS injection through username/password)."""

import json
from pathlib import Path

from nazak.core.extension_generator import generate_profile_extension


def _make_profile(tmp_path, username: str, password: str):
    from nazak.models.profile import BrowserProfile, GoogleSettings, ProxyConfig

    proxy = ProxyConfig(
        enabled=True,
        host="127.0.0.1",
        port=8000,
        username=username,
        password=password,
    )
    return BrowserProfile(
        id="prof_exttest1",
        name="Ext Test </script><b>bold</b>",
        group="Test",
        proxy=proxy,
        google=GoogleSettings(),
    )


def _read_background_js(ext_dir: str) -> str:
    return (Path(ext_dir) / "background.js").read_text(encoding="utf-8")


def test_backgroundjs_escapes_hostile_credentials(tmp_path):
    hostile_user = 'u" ; process.exit(1); "'
    hostile_pass = 'p"\\\n; alert(1); "'
    profile = _make_profile(tmp_path, hostile_user, hostile_pass)
    ext_dir = generate_profile_extension(profile, tmp_path)
    assert ext_dir is not None
    js = _read_background_js(ext_dir)

    # The hostile code must not survive as *raw* (unescaped) text: JSON escaping
    # must make it an inert string literal, not executable code.
    assert hostile_user not in js
    assert hostile_pass not in js

    # The escaped literals must still decode back to the exact original values.
    assert json.dumps(hostile_user) in js
    assert json.dumps(hostile_pass) in js


def test_manifest_name_json_escaped(tmp_path):
    profile = _make_profile(tmp_path, "user", "pass")
    ext_dir = generate_profile_extension(profile, tmp_path)
    manifest = json.loads((Path(ext_dir) / "manifest.json").read_text(encoding="utf-8"))
    # Name must survive as data (json.dump), not raw HTML/JS.
    assert manifest["name"] == "Nazak Deep Shield - Ext Test </script><b>bold</b>"


def test_no_auth_credentials_when_proxy_has_no_auth(tmp_path):
    from nazak.models.profile import BrowserProfile, GoogleSettings, ProxyConfig

    proxy = ProxyConfig(enabled=True, host="127.0.0.1", port=8000)
    profile = BrowserProfile(id="prof_exttest2", name="NoAuth", group="Test", proxy=proxy, google=GoogleSettings())
    ext_dir = generate_profile_extension(profile, tmp_path)
    assert not (Path(ext_dir) / "background.js").exists()
