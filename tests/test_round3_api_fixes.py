"""Round-3 audit regression tests — API-периметр, warmup, секреты (R3-01, R3-10, R3-13, R3-17, R3-28).

Проверяют: отказ старта на не-loopback без токена, `testserver` только в тестах,
`hmac.compare_digest`, allowlist медиа-путей, пиннинг проверенного IP при ротации,
CSRF-щит (`Sec-Fetch-Site`), guard на `/openapi.json`, ограничение длительностей
warmup и понятную ошибку при отсутствии `cryptography`.
"""

import asyncio
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from nazak.api import server
from nazak.core import secrets_store as ss
from nazak.core.warmup_engine import ScenarioExecutor, _clamped_seconds
from nazak.models.profile import BrowserProfile


class _FakeProfileManager:
    def __init__(self, profiles: dict):
        self.profiles = profiles
        self.profiles_dir = Path.cwd()

    def get_profile(self, profile_id):
        return self.profiles.get(profile_id)

    def update_profile(self, profile):
        self.profiles[profile.id] = profile
        return profile


# --------------------------------------------------------------------------- R3-28 warmup bounds
def _warmup_pm():
    """PM с существующим профилем: execute_step первым делом ищет профиль."""
    return _FakeProfileManager({"p1": BrowserProfile(id="p1", name="Warmup Probe")})


def test_r3_warmup_step_durations_are_clamped():
    assert _clamped_seconds(1e12, 2.0) == 600.0
    assert _clamped_seconds(-5, 3.0) == 0.5
    assert _clamped_seconds("abc", 4.0) == 4.0
    assert _clamped_seconds(float("nan"), 4.0) == 4.0
    assert _clamped_seconds(float("inf"), 4.0) == 4.0


def test_r3_warmup_unknown_action_is_not_success():
    from nazak.core.warmup_engine import ScenarioStep

    executor = ScenarioExecutor(browser_launcher=None, profile_manager=_warmup_pm())
    ok = asyncio.run(executor.execute_step(ScenarioStep(action="totally_unknown", params={}), "p1", page=None))
    assert ok is False


def test_r3_warmup_dwell_does_not_sleep_forever():
    from nazak.core.warmup_engine import ScenarioStep

    executor = ScenarioExecutor(browser_launcher=None, profile_manager=_warmup_pm())
    slept: list[float] = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    with patch("nazak.core.warmup_engine.asyncio.sleep", side_effect=fake_sleep):
        ok = asyncio.run(
            executor.execute_step(
                ScenarioStep(action="dwell", params={"min_sec": 1e12, "max_sec": 1e12}), "p1", page=None
            )
        )
    assert ok is True
    assert slept and slept[0] <= 600.0


def test_r3_warmup_navigate_refuses_file_url():
    from nazak.core.warmup_engine import ScenarioStep

    class _RunningLauncher:
        def is_profile_running(self, profile_id):
            return True

        def launch(self, *a, **k):
            return True, 1, None

    executor = ScenarioExecutor(browser_launcher=_RunningLauncher(), profile_manager=_warmup_pm())
    goto_targets: list[str] = []

    class _FakePage:
        async def goto(self, url, **_kwargs):
            goto_targets.append(url)

    ok = asyncio.run(
        executor.execute_step(
            ScenarioStep(action="open_url", params={"url": "file:///C:/Windows/win.ini"}), "p1", page=_FakePage()
        )
    )
    assert ok is False
    assert goto_targets == []


# --------------------------------------------------------------------------- API perimeter
def test_r3_exposure_policy_requires_token_off_loopback(monkeypatch):
    monkeypatch.delenv("NAZAK_API_TOKEN", raising=False)
    server.enforce_exposure_policy("127.0.0.1")  # локально — без токена
    with pytest.raises(SystemExit):
        server.enforce_exposure_policy("0.0.0.0")
    monkeypatch.setenv("NAZAK_API_TOKEN", "s3cret")
    server.enforce_exposure_policy("0.0.0.0")  # с токеном — можно


def test_r3_testserver_host_is_gated_by_env():
    expected = os.environ.get("NAZAK_ALLOW_TEST_HOST", "").strip().lower() in ("1", "true", "yes", "y")
    assert ("testserver" in server._LOCAL_HOSTS) is expected
    assert server._is_local_host("evil.example.com") is False


def test_r3_api_key_compare_is_constant_time(monkeypatch):
    monkeypatch.setenv("NAZAK_API_TOKEN", "token-value")
    assert server._is_api_token_valid({"x-api-key": "token-value"}) is True
    assert server._is_api_token_valid({"x-api-key": "token-valuX"}) is False
    assert server._is_api_token_valid({}) is False


def test_r3_media_source_extension_allowlist(tmp_path):
    txt = tmp_path / "notes.txt"
    txt.write_text("secret", encoding="utf-8")
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        server.resolve_media_source(str(txt))
    assert exc.value.status_code == 400
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"\x00" * 2048)
    assert server.resolve_media_source(str(video)) == video
    with pytest.raises(HTTPException):
        server.resolve_media_source("definitely_missing_clip.mp4")
    with pytest.raises(HTTPException):
        server.resolve_media_source(str(tmp_path))


def test_r3_rotate_proxy_pins_validated_ip(monkeypatch):
    """R3-13: соединение идёт на проверенный IP, а не на повторный DNS."""
    recorded: list[tuple] = []

    monkeypatch.setattr(server, "_resolve_host_ips", lambda host, port: ["93.184.216.34"])

    def fake_create_connection(address, *args, **kwargs):
        recorded.append(tuple(address))
        raise OSError("stop here")

    monkeypatch.setattr(server.socket, "create_connection", fake_create_connection)
    target = server._rotation_target("http://rotation.example.com/change")
    assert target == ("rotation.example.com", 80, "93.184.216.34")

    prof = BrowserProfile(id="r3_rot", name="R3 Rot")
    prof.proxy.rotation_url = "http://rotation.example.com/change"
    monkeypatch.setattr(server.profile_manager, "get_profile", lambda pid: prof)
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        asyncio.run(server.rotate_profile_proxy_endpoint("r3_rot"))
    assert exc.value.status_code == 502
    assert recorded and recorded[0] == ("93.184.216.34", 80), f"DNS не запиннен: {recorded}"


def test_r3_rotation_url_still_refuses_local_targets():
    assert server._reject_rotation_url("file:///C:/Windows/win.ini") is not None
    assert server._reject_rotation_url("http://169.254.169.254/latest/meta-data/") is not None
    assert server._reject_rotation_url("http://127.0.0.1:8899/") is not None


def test_r3_cross_site_and_docs_are_guarded():
    from starlette.testclient import TestClient

    client = TestClient(server.app)
    ok = client.get("/api/system/info", headers={"host": "127.0.0.1"})
    assert ok.status_code == 200
    blocked = client.get("/api/system/info", headers={"host": "127.0.0.1", "sec-fetch-site": "cross-site"})
    assert blocked.status_code == 403
    docs = client.get("/openapi.json", headers={"host": "evil.example.com"})
    assert docs.status_code == 403, "схема API отдаётся при чужом Host"
    docs_local = client.get("/openapi.json", headers={"host": "127.0.0.1"})
    assert docs_local.status_code == 200


# --------------------------------------------------------------------------- secrets hardening
def test_r3_passphrase_mode_requires_cryptography(monkeypatch):
    monkeypatch.setattr(ss, "_HAS_CRYPTOGRAPHY", False)
    with pytest.raises(ss.SecretsError):
        ss.normalize_mode("passphrase")
    with pytest.raises(ss.SecretsError):
        ss.encrypt_secret("value", mode="passphrase", passphrase="x")


def test_r3_secrets_mode_listing_still_works_for_plain(monkeypatch):
    monkeypatch.setattr(ss, "_HAS_CRYPTOGRAPHY", True, raising=False)
    assert ss.normalize_mode("plain") == "plain"
