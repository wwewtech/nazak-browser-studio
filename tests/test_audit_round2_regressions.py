"""Regression tests for the DEEP_AUDIT_ROUND2 findings (D2-P0 / D2-P1 / D2-P2).

Cheap, no-browser coverage for the fixes: masked-secret round trips, SSRF and
Chrome-flag injection, merge-on-PUT semantics, export blast radius, and the
fingerprint coherence defects that made every profile identifiable.
"""

import json
import re
from pathlib import Path

import pytest
from starlette.testclient import TestClient

import nazak.core.secrets_store as ss
from nazak.api import server
from nazak.api.server import app
from nazak.core.extension_generator import generate_profile_extension
from nazak.core.profile_manager import ProfileManager
from nazak.models.profile import BrowserProfile

client = TestClient(app)

SECRET_PLAINTEXT = "TopSecretValue123"
TOTP_PLAINTEXT = "JBSWY3DPEHPK3PXP"


@pytest.fixture()
def api(tmp_path, monkeypatch):
    manager = ProfileManager(tmp_path / "profiles.json", tmp_path / "profiles")
    monkeypatch.setattr(server, "profile_manager", manager)
    ss.set_mode_file(tmp_path / "secrets_mode.json")
    yield manager
    ss.set_current_mode("plain")
    ss.set_passphrase(None)
    ss.set_mode_file(None)


def _enable_strong_mode() -> str:
    """dpapi where available, otherwise an explicit passphrase."""
    if ss.IS_WINDOWS:
        ss.set_current_mode("dpapi")
        return "dpapi"
    ss.set_current_mode("passphrase", passphrase="round-two-passphrase")
    return "passphrase"


def _create_profile_with_secrets(profile_id: str = "reg_notes") -> dict:
    payload = {
        "id": profile_id,
        "name": "Regression Notes",
        "google": {
            "notes": json.dumps({"account_password": SECRET_PLAINTEXT, "totp_secret": TOTP_PLAINTEXT}),
        },
    }
    res = client.post("/api/profiles", json=payload)
    assert res.status_code == 200, res.text
    return res.json()


def test_put_of_get_body_never_writes_masks_or_helper_keys(api):
    """(1) GET -> PUT with that exact body keeps the stored envelopes intact."""
    _enable_strong_mode()
    created = _create_profile_with_secrets("reg_roundtrip")

    listing = client.get(f"/api/profiles/{created['id']}")
    assert listing.status_code == 200
    echoed = listing.json()

    res = client.put(f"/api/profiles/{created['id']}", json=echoed)
    assert res.status_code == 200, res.text

    stored = api.get_profile("reg_roundtrip")
    notes = json.loads(stored.google.notes)
    assert notes["account_password"].startswith("nzk1:")
    assert notes["totp_secret"].startswith("nzk1:")
    assert "_totp_raw" not in notes
    # and nothing that only exists for display was written to disk
    disk = (Path(api.profiles_file)).read_text(encoding="utf-8")
    assert "_totp_raw" not in disk


def test_strong_mode_listing_never_returns_plaintext(api):
    """(2) The API response must not contain the known plaintext of any protected field."""
    _enable_strong_mode()
    _create_profile_with_secrets("reg_listing")

    body = client.get("/api/profiles").text
    assert SECRET_PLAINTEXT not in body
    assert TOTP_PLAINTEXT not in body

    single = client.get("/api/profiles/reg_listing").text
    assert SECRET_PLAINTEXT not in single
    assert TOTP_PLAINTEXT not in single


@pytest.mark.parametrize(
    "rotation_url",
    ["file:///C:/Windows/win.ini", "http://169.254.169.254/latest/meta-data/"],
)
def test_rotation_url_refuses_local_targets(api, rotation_url):
    """(3) The rotation trigger must not become a local/SSRF reader."""
    payload = {
        "id": f"reg_rot_{abs(hash(rotation_url)) % 10000}",
        "name": "Rotate",
        "proxy": {"raw": "http://1.2.3.4:8080", "type": "http", "rotation_url": rotation_url},
    }
    res = client.post("/api/profiles", json=payload)
    assert res.status_code == 200, res.text

    out = client.post(f"/api/profiles/{payload['id']}/rotate-proxy")
    assert out.status_code == 400
    assert "Traceback" not in out.text


@pytest.mark.parametrize(
    "custom_url",
    ["--disable-web-security", "file:///C:/Windows/win.ini"],
)
def test_launch_refuses_flag_and_file_urls(api, custom_url):
    """(4) custom_url is Chrome's last argv entry — it must never be a flag or file."""
    res = client.post("/api/profiles", json={"id": "reg_launch", "name": "Launch"})
    assert res.status_code == 200, res.text
    out = client.post("/api/profiles/reg_launch/launch", json={"custom_url": custom_url})
    assert out.status_code == 400
    # generic message, no internals echoed back
    assert "Traceback" not in out.text


def test_partial_put_preserves_identity_and_secrets(api):
    """(5) A partial body must not reset proxy secrets, timezone, GPU or noise seeds."""
    from nazak.models.proxy import ProxyConfig, ProxyType

    _enable_strong_mode()
    created = _create_profile_with_secrets("reg_partial")

    seeded = api.get_profile("reg_partial")
    seeded.proxy = ProxyConfig(
        type=ProxyType.HTTP,
        host="9.9.9.9",
        port=8080,
        username="user",
        password="stored-pw",
        rotation_url="https://rot.example.com/new-ip",
    )
    seeded.fingerprint.timezone = "Europe/Berlin"
    seeded.fingerprint.webgl_renderer = "ANGLE (NVIDIA, NVIDIA GeForce RTX 4090 Direct3D11 vs_5_0 ps_5_0, D3D11)"
    api.update_profile(seeded)

    full = client.get("/api/profiles/reg_partial").json()

    stored_before = api.get_profile("reg_partial")
    password_before = stored_before.proxy.password
    rotation_before = stored_before.proxy.rotation_url
    timezone_before = stored_before.fingerprint.timezone
    renderer_before = stored_before.fingerprint.webgl_renderer
    canvas_before = stored_before.fingerprint.canvas_noise_seed

    res = client.put("/api/profiles/reg_partial", json={"name": "Renamed Partial"})
    assert res.status_code == 200, res.text

    stored = api.get_profile("reg_partial")
    assert stored.name == "Renamed Partial"
    assert stored.proxy.password == password_before
    assert stored.proxy.rotation_url == rotation_before
    assert stored.fingerprint.timezone == timezone_before
    assert stored.fingerprint.webgl_renderer == renderer_before
    assert stored.fingerprint.canvas_noise_seed == canvas_before
    notes = json.loads(stored.google.notes)
    assert notes["account_password"].startswith("nzk1:")
    # full body is still accepted unchanged for the fields it does send
    res = client.put("/api/profiles/reg_partial", json=full)
    assert res.status_code == 200, res.text


def test_bulk_cookie_export_requires_explicit_profile_ids(api):
    """(6) Omitting / emptying profile_ids must never widen the export to the whole park."""
    _create_profile_with_secrets("reg_bulk")
    for empty in ({}, {"profile_ids": []}):
        out = client.post("/api/cookies/bulk-export", json=empty)
        assert out.status_code == 400
        assert "cookies" not in out.json()


def test_device_memory_is_spec_quantized_and_audio_seeds_differ(tmp_path):
    """(7) deviceMemory must be in the Device Memory spec set; fresh profiles differ."""
    profile = BrowserProfile(id="reg_devmem", name="Device Memory")
    ext_dir = Path(generate_profile_extension(profile, tmp_path))
    stealth = (ext_dir / "stealth.js").read_text(encoding="utf-8")
    match = re.search(r"\(\) => ([0-9.]+), 'get deviceMemory'", stealth)
    assert match, "deviceMemory getter not found in stealth.js"
    assert float(match.group(1)) in (0.25, 0.5, 1, 2, 4, 8)

    first = BrowserProfile(name="A")
    second = BrowserProfile(name="B")
    assert first.fingerprint.audio_noise_seed != second.fingerprint.audio_noise_seed
    assert first.fingerprint.canvas_noise_seed != second.fingerprint.canvas_noise_seed
