"""Deep bug-hunting tests for the service/domain layer and the parsers.

Coverage targets (one file, no product code touched):

* ``nazak/core/profiles/service.py`` — partial update semantics, clone
  independence, mass-generate bounds, batch cookie import/export, secret
  re-encryption.
* ``nazak/core/spintax.py`` — pathological templates, empty/unicode variants,
  seeded determinism.
* ``nazak/core/account_provisioner.py`` — the RFC 6238 TOTP engine (manual
  implementation forced on) and OAuth ``state`` handling.
* ``nazak/core/fingerprint_generator.py`` — 200-sample statistical/hardware
  invariants.
* ``nazak/core/cookie_manager.py`` — Netscape parse/serialise round-trip
  fidelity.
* ``nazak/core/proxy_checker.py`` — health-result shapes against a fake
  network (no sockets are opened by this module's tests except the SOCKS4
  construction check, which fails before any I/O).

Tests marked ``xfail`` document *unfixed product bugs*: they assert the correct
behaviour and stay red until the product is fixed.
"""

import asyncio
import json
import random
import time
import types
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

import nazak.core.account_provisioner as provisioner
import nazak.core.proxy_checker as proxy_checker
import nazak.core.secrets_store as secrets_store
from nazak.core.cookie_manager import cookies_to_netscape, parse_netscape_cookies
from nazak.core.fingerprint_generator import (
    GPU_PRESETS,
    SCREEN_RESOLUTIONS,
    TIMEZONES,
    generate_random_fingerprint,
)
from nazak.core.profile_manager import ProfileManager
from nazak.core.profiles import service as profile_service
from nazak.core.profiles.constants import MASK, MAX_MASS_GENERATE_COUNT
from nazak.core.spintax import parse_spintax
from nazak.models.health import HealthCheckResult, HealthStatus
from nazak.models.profile import BrowserProfile, FingerprintConfig, GoogleSettings, ProfileStatus
from nazak.models.proxy import ProxyConfig, ProxyType


@pytest.fixture(autouse=True)
def _pin_plain_secrets_mode():
    """Pin the plaintext secrets mode and restore whatever was active before.

    ``secrets_store`` keeps the mode in module globals that other suites mutate;
    these tests assert on readable notes and must not depend on run order.
    """
    previous_mode = secrets_store.get_current_mode()
    previous_passphrase = secrets_store.get_passphrase()
    secrets_store.set_current_mode("plain")
    yield
    secrets_store._in_memory_passphrase = previous_passphrase
    secrets_store._current_mode = previous_mode


def _manager(tmp_path: Path, name: str) -> ProfileManager:
    base = tmp_path / name
    base.mkdir(parents=True, exist_ok=True)
    return ProfileManager(base / "profiles.json", base / "profiles")


def _cookie_batch(value: str, name: str = "SID") -> list[dict]:
    return [
        {
            "name": name,
            "value": value,
            "domain": ".example.com",
            "path": "/",
            "expires": 0,
            "secure": True,
            "httpOnly": True,
        }
    ]


def _cookie(**overrides) -> dict:
    cookie = {
        "name": "n",
        "value": "v",
        "domain": ".example.com",
        "path": "/",
        "expires": 0,
        "secure": False,
        "httpOnly": False,
    }
    cookie.update(overrides)
    return cookie


def _fingerprint_sample(count: int = 200) -> list[tuple[str, object]]:
    os_cycle = ("windows", "mac", "linux")
    return [(os_type, generate_random_fingerprint(os_type=os_type)) for os_type in (os_cycle * count)[:count]]


# ---------------------------------------------------------------------------
# spintax.py
# ---------------------------------------------------------------------------


def test_spintax_pathological_braces_never_hang_or_crash():
    """Unbalanced/extra braces must degrade gracefully instead of exploding."""
    unchanged = {
        "": "",
        "plain text": "plain text",
        "|": "|",
        "{}": "{}",
        "{a|b": "{a|b",  # unclosed block: left verbatim
        "{tg} {promo} {year}": "{tg} {promo} {year}",  # pipe-less placeholders survive
        "{": "{",
        "{" * 2000: "{" * 2000,
    }
    for template, expected in unchanged.items():
        assert parse_spintax(template) == expected

    # A balanced block nested inside an unbalanced one still resolves.
    assert parse_spintax("{a|{b|c}") in ("{a|b", "{a|c")
    assert parse_spintax("{a|b}}") in ("a}", "b}")

    # Wide brace noise must terminate quickly (the parser is not recursive).
    started = time.perf_counter()
    assert isinstance(parse_spintax("{x|y}" * 400), str)
    assert time.perf_counter() - started < 2.0

    # Nesting inside the iteration guard resolves fully; absurd depth must not recurse/hang.
    depth = 25
    nested = "{a|" * depth + "z" + "}" * depth
    assert all(parse_spintax(nested) in ("a", "z") for _ in range(30))

    absurd = "{a|" * 400 + "z" + "}" * 400
    started = time.perf_counter()
    assert isinstance(parse_spintax(absurd), str)
    assert time.perf_counter() - started < 2.0


def test_spintax_empty_variants_unicode_and_seeded_determinism():
    """Empty variants are legal members of the choice set and unicode is preserved."""
    assert {parse_spintax("{a||b}") for _ in range(90)} == {"a", "", "b"}
    assert parse_spintax("{|}") == ""
    assert {parse_spintax("{Привет|Héllo|日本語|🎉}") for _ in range(120)} == {
        "Привет",
        "Héllo",
        "日本語",
        "🎉",
    }

    template = "{a|b|c|d|e|f}"
    random.seed(7)
    first = parse_spintax(template)
    random.seed(7)
    assert parse_spintax(template) == first

    picks = set()
    for seed in range(30):
        random.seed(seed)
        picks.add(parse_spintax(template))
    assert len(picks) >= 3  # the branch is random, not fixed

    untouched = "Watch {tg} promo {promo} in {year} — 100% legit"
    assert parse_spintax(untouched) == untouched


# ---------------------------------------------------------------------------
# account_provisioner.py — RFC 6238 TOTP engine
# ---------------------------------------------------------------------------

# RFC 6238 appendix B secret ("12345678901234567890") in base32.
_RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
_RFC6238_VECTORS = {
    59: ("94287082", "287082"),
    1111111109: ("07081804", "081804"),
    1111111111: ("14050471", "050471"),
    1234567890: ("89005924", "005924"),
    2000000000: ("69279037", "279037"),
    20000000000: ("65353130", "353130"),
}


def _freeze_totp_time(monkeypatch, timestamp: float) -> None:
    monkeypatch.setattr(provisioner, "pyotp", None)
    monkeypatch.setattr(provisioner, "time", types.SimpleNamespace(time=lambda: float(timestamp)))


def test_totp_manual_engine_matches_rfc6238_vectors_and_counter_maths(monkeypatch):
    """The pure-Python fallback must reproduce the RFC vectors exactly."""
    for timestamp, (eight_digits, six_digits) in _RFC6238_VECTORS.items():
        _freeze_totp_time(monkeypatch, timestamp)
        assert provisioner.generate_totp_rfc6238(_RFC_SECRET, digits=8) == eight_digits
        assert provisioner.generate_totp_rfc6238(_RFC_SECRET, digits=6) == six_digits

    def code_at(timestamp: float, interval: int = 30) -> str:
        _freeze_totp_time(monkeypatch, timestamp)
        return provisioner.generate_totp_rfc6238(_RFC_SECRET, interval=interval)

    # counter = floor(now / interval): one code covers the whole window
    assert code_at(60) == code_at(61) == code_at(89)
    assert code_at(90) != code_at(89)
    assert code_at(60, interval=60) == code_at(119, interval=60)
    assert code_at(120, interval=60) != code_at(119, interval=60)
    assert code_at(60, interval=30) != code_at(60, interval=60)


def test_totp_manual_engine_agrees_with_pyotp_reference(monkeypatch):
    """Cross-check the hand-rolled HMAC path against pyotp for messy-but-valid secrets."""
    pyotp = pytest.importorskip("pyotp")
    secrets = ["JBSWY3DPEHPK3PXP", "MZXW6YTBOI", "MZXW6YTBOI======", "  jbsw y3dp ehpk 3pxp  "]
    for timestamp in (59, 1700000000, 2000000000):
        monkeypatch.setattr(provisioner, "pyotp", None)
        monkeypatch.setattr(provisioner, "time", types.SimpleNamespace(time=lambda ts=timestamp: float(ts)))
        for secret in secrets:
            normalized = secret.replace(" ", "").strip().upper()
            assert provisioner.generate_totp_rfc6238(secret) == pyotp.TOTP(normalized).at(timestamp)
            assert provisioner.generate_totp_rfc6238(secret, digits=8) == pyotp.TOTP(normalized, digits=8).at(timestamp)


def test_totp_invalid_or_wrong_length_secrets_raise_instead_of_a_fake_code(monkeypatch):
    """A broken seed must raise ValueError — never a plausible-looking "000000"."""
    monkeypatch.setattr(provisioner, "pyotp", None)
    for broken in ("", "   ", "!!!", "JBSWY3DPEHPK3PX1", "ABC", "MZXW6YTBO"):
        with pytest.raises(ValueError):
            provisioner.generate_totp_rfc6238(broken)

    good = provisioner.generate_totp_rfc6238("JBSWY3DPEHPK3PXP")
    assert len(good) == 6 and good.isdigit() and good != "000000"


def test_build_oauth_auth_url_state_survives_a_url_round_trip():
    prov = provisioner.AccountProvisioner(None, None)
    for state in ("a+b", "st&response_type=token", "st#fragment", "tok en=1"):
        url = prov.build_oauth_auth_url(client_id="cid", state=state)
        query = parse_qs(urlparse(url).query)
        assert query.get("state") == [state]
        assert query.get("response_type") == ["code"]


# ---------------------------------------------------------------------------
# fingerprint_generator.py
# ---------------------------------------------------------------------------


def test_two_hundred_fingerprints_are_unique_on_the_important_axes():
    samples = _fingerprint_sample(200)
    dumps = {json.dumps(fp.model_dump(mode="json"), sort_keys=True) for _os, fp in samples}
    assert len(dumps) == 200

    # F-04: media sets vary per profile (mic+speakers always; a camera may be
    # absent the way real desktops without webcams are). Device/group ids
    # stay unique across whatever set each profile carries.
    device_ids = [device.device_id for _os, fp in samples for device in fp.media_devices]
    group_ids = [device.group_id for _os, fp in samples for device in fp.media_devices]
    assert all(2 <= len(fp.media_devices) <= 3 for _os, fp in samples)
    assert len(set(device_ids)) == len(device_ids)
    assert len(set(group_ids)) == len(group_ids)
    # the (kind, label) set varies across a farm — that is the point of F-04
    label_sets = {tuple(sorted((d.kind, d.label) for d in fp.media_devices)) for _os, fp in samples}
    assert len(label_sets) > 20, f"only {len(label_sets)} distinct device label sets across 200 profiles"

    noise_pairs = {(fp.canvas_noise_seed, fp.audio_noise_seed) for _os, fp in samples}
    assert len(noise_pairs) == 200


def test_fingerprint_platform_ua_client_hints_and_hardware_are_coherent():
    for os_type, fp in _fingerprint_sample(200):
        presets = [gpu for gpu in GPU_PRESETS if gpu["unmasked_renderer"] == fp.webgl_unmasked_renderer]
        assert len(presets) == 1
        gpu = presets[0]
        # cores/RAM must come from the *same* preset as the advertised GPU
        assert os_type in gpu["os"]
        assert fp.webgl_vendor == gpu["vendor"]
        assert fp.webgl_unmasked_vendor == gpu["unmasked_vendor"]
        assert fp.hardware_concurrency in gpu["cores"]
        assert fp.device_memory in gpu["ram"]

        if os_type == "windows":
            assert fp.platform == "Win32" and "Windows NT 10.0" in fp.user_agent
            assert fp.platform_version == "10.0.0"
            assert "Direct3D11" in fp.webgl_renderer
        elif os_type == "mac":
            assert fp.platform == "MacIntel" and "Macintosh" in fp.user_agent
            assert fp.platform_version == "15.0.0"
            assert "Metal" in fp.webgl_renderer
        else:
            assert fp.platform == "Linux x86_64" and "Linux x86_64" in fp.user_agent
            assert fp.platform_version == "6.8.0"
            assert "Direct3D" not in fp.webgl_renderer
            assert "OpenGL" in fp.webgl_renderer or "Mesa" in fp.webgl_renderer

        # Client Hints must advertise the very same Chrome major as the UA string
        major = fp.user_agent.split("Chrome/")[1].split(".")[0]
        brand_versions = {brand["brand"]: brand["version"] for brand in fp.brands}
        assert brand_versions["Google Chrome"] == major
        assert brand_versions["Chromium"] == major
        assert f"Chrome/{major}" in fp.app_version
        assert (fp.architecture, fp.bitness, fp.mobile) == ("x86", "64", False)


def test_fingerprint_screens_locales_and_required_fields_are_sane():
    screen_specs = {(s["width"], s["height"], s["avail_w"], s["avail_h"], s["dpr"]) for s in SCREEN_RESOLUTIONS}
    timezone_names = {name for name, _offset in TIMEZONES}
    # ``model`` is deliberately excluded: desktop Chrome reports an empty model.
    required_text = (
        "user_agent",
        "platform",
        "app_version",
        "vendor",
        "platform_version",
        "language",
        "timezone",
        "webgl_vendor",
        "webgl_renderer",
        "webgl_unmasked_vendor",
        "webgl_unmasked_renderer",
        "webrtc_policy",
    )
    for _os_type, fp in _fingerprint_sample(60):
        screen = (
            fp.screen_width,
            fp.screen_height,
            fp.screen_avail_width,
            fp.screen_avail_height,
            fp.device_pixel_ratio,
        )
        assert screen in screen_specs
        assert fp.screen_avail_width <= fp.screen_width
        assert fp.screen_avail_height <= fp.screen_height
        assert (fp.color_depth, fp.pixel_depth, fp.max_touch_points) == (24, 24, 0)
        assert all(getattr(fp, field).strip() for field in required_text)
        assert fp.language and fp.languages and fp.languages[0] in fp.language
        assert fp.timezone in timezone_names
        assert -720 <= fp.timezone_offset <= 840
        assert fp.timezone_offset % 15 == 0
        assert fp.canvas_noise is True and fp.audio_noise is True and fp.client_rects_noise is True
        assert 10_000 <= fp.canvas_noise_seed <= 999_999
        assert 0.0 < fp.audio_noise_seed < 1.0
        # F-19: battery states vary like real laptops (plugged, draining,
        # mid-charge) instead of a farm of permanently-full ones.
        assert 0.0 < fp.battery.level <= 1.0
        assert fp.geolocation.enabled is True
        assert fp.webrtc_policy == "disable_non_proxied_udp"
        assert fp.block_port_scanning is True and fp.block_sensors is True
        # F-04: mic+speakers always; a webcam may be absent (real desktops too).
        assert {"audioinput", "audiooutput"} <= {device.kind for device in fp.media_devices}
        assert {device.kind for device in fp.media_devices} <= {"audioinput", "audiooutput", "videoinput"}

    # A DST-free zone must yield its real offset when a timezone is requested.
    tokyo = generate_random_fingerprint(target_timezone="Asia/Tokyo")
    assert tokyo.timezone == "Asia/Tokyo"
    assert tokyo.timezone_offset == -540


# ---------------------------------------------------------------------------
# cookie_manager.py
# ---------------------------------------------------------------------------


def test_netscape_round_trip_keeps_flags_unicode_and_expiry():
    original = [
        _cookie(name="SID", value="abc123", domain=".google.com", expires=1754000000, secure=True, httpOnly=True),
        _cookie(name="sess", value="keep-me", domain="example.com", path="/app", includeSubdomains=True),
        _cookie(name="old", value="expired", domain="legacy.test", expires=946684800),
        _cookie(
            name="ключ",
            value="значение-🎉",
            domain="例え.jp",
            path="/путь",
            expires=1760000000,
            secure=True,
            httpOnly=True,
        ),
    ]
    serialized = cookies_to_netscape(original)
    assert "#HttpOnly_.google.com" in serialized
    assert "\n\n" in serialized  # the header block keeps its blank line

    reparsed = parse_netscape_cookies(serialized)
    assert len(reparsed) == len(original)
    for source, parsed in zip(original, reparsed, strict=True):
        assert parsed["name"] == source["name"]
        assert parsed["value"] == source["value"]
        assert parsed["domain"] == source["domain"]
        assert parsed["path"] == source["path"]
        assert parsed["expires"] == source["expires"]
        assert parsed["secure"] is bool(source["secure"])
        assert parsed["httpOnly"] is bool(source["httpOnly"])

    # A second pass must be byte-stable: the flags survive, they are not re-derived.
    assert cookies_to_netscape(reparsed) == serialized


def test_netscape_round_trip_preserves_value_whitespace_fidelity():
    double_space = [_cookie(name="pref", value="mode=dark  lang=ru", expires=1754000000)]
    reparsed = parse_netscape_cookies(cookies_to_netscape(double_space))
    assert reparsed and reparsed[0]["value"] == "mode=dark  lang=ru"

    padded = [_cookie(name="pad", value="abc ", expires=1754000000)]
    reparsed_padded = parse_netscape_cookies(cookies_to_netscape(padded))
    assert reparsed_padded and reparsed_padded[0]["value"] == "abc "

    empty = [_cookie(name="cleared", value="", expires=1754000000)]
    reparsed_empty = parse_netscape_cookies(cookies_to_netscape(empty))
    assert len(reparsed_empty) == 1
    assert reparsed_empty[0]["name"] == "cleared"
    assert reparsed_empty[0]["value"] == ""


def test_netscape_malformed_lines_are_skipped_without_crashing():
    raw = "\n".join(
        [
            "# a plain comment line",
            "",
            "    \t  ",
            "not\tenough\tfields",
            "ok.test\tFALSE\t/\tFALSE\t0\tkeep\tme",
            "bad.test\tFALSE\t/\tFALSE\tnot-a-number\tname\tval",
        ]
    )
    parsed = parse_netscape_cookies(raw)
    assert [cookie["name"] for cookie in parsed] == ["keep", "name"]
    assert [cookie["expires"] for cookie in parsed] == [0, 0]
    assert all(isinstance(cookie["expires"], int) for cookie in parsed)
    assert parse_netscape_cookies("# only comments\n\n   \n") == []
    assert parse_netscape_cookies("") == []


# ---------------------------------------------------------------------------
# proxy_checker.py — fake network
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code: int = 204, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self) -> dict:
        return self._payload


def _install_fake_http(monkeypatch, responder, client_args: list[dict]) -> None:
    class _FakeClient:
        def __init__(self, **kwargs):
            client_args.append(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def get(self, url, **kwargs):
            return responder(url)

    class _FakeHttpx:
        Timeout = httpx.Timeout
        AsyncClient = _FakeClient

    monkeypatch.setattr(proxy_checker, "httpx", _FakeHttpx)


def _install_ping(monkeypatch, latency: float | None) -> None:
    async def _ping(*args, **kwargs):
        return latency

    monkeypatch.setattr(proxy_checker, "measure_tcp_ping", _ping)


def test_check_proxy_health_dead_proxy_shape(tmp_path, monkeypatch):
    _install_ping(monkeypatch, None)
    built: list[dict] = []

    def forbidden(url):
        raise AssertionError(f"no HTTP request may leave for a dead proxy: {url}")

    _install_fake_http(monkeypatch, forbidden, built)
    proxy = ProxyConfig(type=ProxyType.HTTP, host="203.0.113.9", port=8080, username="u", password="p")

    result = asyncio.run(proxy_checker.check_proxy_health(proxy, profile_dir=tmp_path / "prof", timeout_sec=0.2))

    assert isinstance(result, HealthCheckResult)
    assert result.status == HealthStatus.DEAD
    assert result.ping_ms is None
    assert "203.0.113.9:8080" in (result.error_message or "")
    assert result.data_isolation_ok is True
    assert result.google.all_ok is False and result.google.google_main is False
    assert built == []
    assert (tmp_path / "prof").is_dir()


def test_check_proxy_health_direct_mode_shapes(tmp_path, monkeypatch):
    _install_ping(monkeypatch, 1.5)
    built: list[dict] = []
    state = {"responder": lambda url: _FakeResponse(204)}

    def responder(url):
        return state["responder"](url)

    _install_fake_http(monkeypatch, responder, built)
    direct = ProxyConfig(type=ProxyType.DIRECT, raw="direct")

    def reachable(url):
        if "ipwho.is" in url:
            return _FakeResponse(
                200,
                {
                    "success": True,
                    "ip": "203.0.113.5",
                    "country": "Netherlands",
                    "country_code": "NL",
                    "city": "Amsterdam",
                    "region": "NH",
                    "timezone": "Europe/Amsterdam",
                    "latitude": 52.3,
                    "longitude": 4.9,
                    "connection": {"isp": "ISP", "asn": 1},
                },
            )
        return _FakeResponse(204)

    state["responder"] = reachable
    healthy = asyncio.run(proxy_checker.check_proxy_health(direct, profile_dir=tmp_path / "a", timeout_sec=0.5))
    assert healthy.status == HealthStatus.HEALTHY
    assert healthy.ping_ms == 1.0  # direct connections skip the TCP probe
    assert healthy.ip == "203.0.113.5" and healthy.country_code == "NL"
    assert healthy.timezone_name == "Europe/Amsterdam"
    assert healthy.latitude == 52.3 and healthy.longitude == 4.9
    assert healthy.google.all_ok is True
    assert healthy.google.latencies_ms
    assert built[-1]["proxy"] is None  # direct mode must not configure a proxy

    def refused(url):
        raise httpx.ConnectError("connection refused")

    state["responder"] = refused
    offline = asyncio.run(proxy_checker.check_proxy_health(direct, profile_dir=tmp_path / "b", timeout_sec=0.5))
    assert offline.status == HealthStatus.ERROR  # no proxy to blame for a direct link
    assert offline.google.all_ok is False
    assert offline.error_message == "Google services unreachable through this connection"

    def only_google_main(url):
        return _FakeResponse(204) if "www.google.com/generate_204" in url else _FakeResponse(503)

    state["responder"] = only_google_main
    degraded = asyncio.run(proxy_checker.check_proxy_health(direct, profile_dir=tmp_path / "c", timeout_sec=0.5))
    assert degraded.status == HealthStatus.DEGRADED
    assert degraded.google.google_main is True
    assert degraded.google.all_ok is False


def test_check_proxy_health_timeouts_and_hostile_geo_payload(tmp_path, monkeypatch):
    _install_ping(monkeypatch, 42.0)
    built: list[dict] = []
    state = {"responder": lambda url: _FakeResponse(204)}

    def responder(url):
        return state["responder"](url)

    _install_fake_http(monkeypatch, responder, built)
    proxy = ProxyConfig(type=ProxyType.HTTP, host="203.0.113.9", port=8080)

    def geo_timeout(url):
        if "ipwho.is" in url:
            raise httpx.TimeoutException("geo lookup timed out")
        if "ipify" in url:
            return _FakeResponse(200, {"ip": "198.51.100.7"})
        raise httpx.TimeoutException("google timed out")

    state["responder"] = geo_timeout
    timed_out = asyncio.run(proxy_checker.check_proxy_health(proxy, profile_dir=tmp_path / "t1", timeout_sec=0.5))
    assert timed_out.status == HealthStatus.DEAD
    assert timed_out.ip == "198.51.100.7"  # ipify fallback kept the routed address
    assert timed_out.ping_ms == 42.0
    assert timed_out.google.all_ok is False
    assert timed_out.google.latencies_ms == {}
    assert built[-1]["proxy"] == proxy.to_httpx_url()

    def refused(url):
        raise httpx.ConnectError("refused")

    state["responder"] = refused
    unreachable = asyncio.run(proxy_checker.check_proxy_health(proxy, profile_dir=tmp_path / "t2", timeout_sec=0.5))
    assert unreachable.status == HealthStatus.DEAD
    assert unreachable.ip is None
    assert "refused" in (unreachable.error_message or "")

    def hostile_geo(url):
        if "ipwho.is" in url:
            return _FakeResponse(
                200,
                json.loads(
                    '{"success":true,"ip":"1.2.3.4","country":"'
                    + "C" * 400
                    + '","timezone":"../../etc/passwd","latitude":Infinity,"longitude":NaN,"city":"\\u0000ok"}'
                ),
            )
        return _FakeResponse(204)

    state["responder"] = hostile_geo
    sanitized = asyncio.run(proxy_checker.check_proxy_health(proxy, profile_dir=tmp_path / "t3", timeout_sec=0.5))
    assert sanitized.status == HealthStatus.HEALTHY
    assert len(sanitized.country or "") <= 128
    assert sanitized.timezone_name is None
    assert sanitized.latitude is None and sanitized.longitude is None
    assert sanitized.city == "ok"


def test_check_proxy_health_supports_socks4_proxy_type(tmp_path, monkeypatch):
    _install_ping(monkeypatch, 15.0)
    proxy = ProxyConfig(type=ProxyType.SOCKS4, host="203.0.113.9", port=1080)
    result = asyncio.run(proxy_checker.check_proxy_health(proxy, profile_dir=tmp_path / "s4", timeout_sec=0.2))
    assert isinstance(result, HealthCheckResult)
    assert result.ping_ms == 15.0
    assert result.status in (HealthStatus.HEALTHY, HealthStatus.DEGRADED, HealthStatus.DEAD, HealthStatus.ERROR)


# ---------------------------------------------------------------------------
# profiles/service.py
# ---------------------------------------------------------------------------


def test_update_with_partial_payload_never_wipes_stored_proxy_credentials(tmp_path):
    pm = _manager(tmp_path, "proxy-update")
    pm.create_profile(
        BrowserProfile(id="prof_cred", name="Cred", proxy=ProxyConfig.parse("http://user1:RealPass@203.0.113.9:8080"))
    )

    # (a) masked echo of the raw string, exactly as the GUI/API sends it back
    pm.update_profile(BrowserProfile(id="prof_cred", proxy=ProxyConfig(raw=f"http://user1:{MASK}@203.0.113.9:8080")))
    masked = pm.get_profile("prof_cred").proxy
    assert (masked.username, masked.password) == ("user1", "RealPass")
    assert (masked.host, masked.port) == ("203.0.113.9", 8080)

    # (b) host/port-only change keeps the credentials and rebuilds the raw string
    pm.update_profile(BrowserProfile(id="prof_cred", proxy=ProxyConfig(host="198.51.100.4", port=3128)))
    moved = pm.get_profile("prof_cred").proxy
    assert (moved.host, moved.port) == ("198.51.100.4", 3128)
    assert (moved.username, moved.password) == ("user1", "RealPass")
    assert "RealPass" in (moved.raw or "")

    # (c) a rename-only payload must not touch the proxy at all, on disk either
    pm.update_profile(BrowserProfile(id="prof_cred", name="Renamed"))
    renamed = pm.get_profile("prof_cred")
    assert renamed.name == "Renamed"
    assert renamed.proxy.password == "RealPass"
    reloaded = ProfileManager(pm.profiles_file, pm.profiles_dir)
    assert reloaded.get_profile("prof_cred").proxy.password == "RealPass"

    # (d) only an explicit "direct" payload clears the proxy
    pm.update_profile(BrowserProfile(id="prof_cred", proxy=ProxyConfig(raw="direct")))
    cleared = pm.get_profile("prof_cred").proxy
    assert cleared.is_direct() is True
    assert cleared.password in (None, "")


def test_update_with_partial_notes_payload_keeps_stored_secrets(tmp_path):
    pm = _manager(tmp_path, "notes-update")
    stored = {
        "account_email": "user@example.com",
        "account_password": "S3cretPass",
        "totp_secret": "JBSWY3DPEHPK3PXP",
    }
    pm.create_profile(
        BrowserProfile(
            id="prof_notes",
            google=GoogleSettings(notes=json.dumps(secrets_store.encrypt_notes(stored, mode="plain"))),
        )
    )
    assert json.loads(pm.get_profile("prof_notes").google.notes)["account_password"] == "S3cretPass"

    pm.update_profile(
        BrowserProfile(id="prof_notes", google=GoogleSettings(notes=json.dumps({"account_email": "other@example.com"})))
    )
    after = json.loads(pm.get_profile("prof_notes").google.notes)
    assert after["account_email"] == "other@example.com"
    assert after.get("account_password") == "S3cretPass"
    assert after.get("totp_secret") == "JBSWY3DPEHPK3PXP"


def test_clone_is_an_independent_profile_with_a_fresh_fingerprint(tmp_path, monkeypatch):
    random.seed(20261012)
    pm = _manager(tmp_path, "clone")
    source = pm.create_profile(
        BrowserProfile(
            id="prof_src",
            name="Source",
            group="Farm",
            proxy=ProxyConfig.parse("socks5://user1:RealPass@203.0.113.9:1080"),
            fingerprint=generate_random_fingerprint(os_type="windows"),
            google=GoogleSettings(
                auto_open_page="youtube_studio",
                tags=["A"],
                notes=json.dumps({"account_password": "pw"}),
            ),
        )
    )
    source_canvas = source.fingerprint.canvas_noise_seed
    source_audio = source.fingerprint.audio_noise_seed

    clone = pm.clone_profile("prof_src")
    assert clone is not None and clone.id != source.id
    assert clone.name == "Source (Copy)"
    assert (clone.status, clone.pid, clone.total_runtime_seconds) == (ProfileStatus.STOPPED, None, 0)
    assert clone.proxy.password == "RealPass"  # the login credentials travel with the clone
    assert clone.google.notes == source.google.notes
    assert clone.fingerprint.canvas_noise_seed != source_canvas
    assert clone.fingerprint.audio_noise_seed != source_audio
    assert clone.fingerprint.media_devices[0].device_id != source.fingerprint.media_devices[0].device_id
    assert clone.fingerprint.user_agent != source.fingerprint.user_agent
    # geo/locale must follow the copied proxy, so they are carried over on purpose
    assert clone.fingerprint.timezone == source.fingerprint.timezone
    assert clone.fingerprint.battery.level == source.fingerprint.battery.level
    # no shared mutable state in either direction
    assert clone.fingerprint.media_devices is not source.fingerprint.media_devices
    clone.fingerprint.media_devices[0].device_id = "mutated-by-clone"
    assert source.fingerprint.media_devices[0].device_id != "mutated-by-clone"
    source.fingerprint.media_devices[0].device_id = "mutated-by-source"
    assert clone.fingerprint.media_devices[0].device_id != "mutated-by-source"
    assert pm.get_profile("prof_src") is not None
    assert ProfileManager(pm.profiles_file, pm.profiles_dir).get_profile(clone.id) is not None

    # a Linux source keeps the Linux platform family (incl. a Mesa/OpenGL renderer)
    linux = pm.create_profile(BrowserProfile(id="prof_lin", fingerprint=generate_random_fingerprint(os_type="linux")))
    linux_clone = pm.clone_profile("prof_lin")
    assert linux_clone.fingerprint.platform == linux.fingerprint.platform == "Linux x86_64"
    assert "Direct3D" not in linux_clone.fingerprint.webgl_renderer

    # the collision guard must redraw until the noise seeds really differ
    collision_source = pm.create_profile(
        BrowserProfile(
            id="prof_col",
            fingerprint=FingerprintConfig(canvas_noise_seed=424242, audio_noise_seed=0.000002),
        )
    )
    draws = {"canvas": 0, "audio": 0}
    real_randint, real_uniform = random.randint, random.uniform

    def fake_randint(a, b):
        draws["canvas"] += 1
        # draw 1 belongs to the fresh fingerprint, draw 2 is the clone's first attempt
        return 424242 if draws["canvas"] == 2 else real_randint(a, b)

    def fake_uniform(a, b):
        draws["audio"] += 1
        return 0.000002 if draws["audio"] == 2 else real_uniform(a, b)

    monkeypatch.setattr(random, "randint", fake_randint)
    monkeypatch.setattr(random, "uniform", fake_uniform)
    collision_clone = pm.clone_profile("prof_col")
    monkeypatch.undo()

    assert draws["canvas"] >= 3 and draws["audio"] >= 3
    assert collision_clone.fingerprint.canvas_noise_seed != collision_source.fingerprint.canvas_noise_seed
    assert collision_clone.fingerprint.audio_noise_seed != collision_source.fingerprint.audio_noise_seed


def test_mass_generate_clamps_count_and_distributes_os_and_proxies(tmp_path, monkeypatch):
    pm = _manager(tmp_path, "mass")
    assert MAX_MASS_GENERATE_COUNT == 200  # shipped bound

    batch = pm.mass_generate_profiles(count=12, os_mix="all")
    assert len(batch) == 12
    assert len({fp.fingerprint.media_devices[0].device_id for fp in batch}) == 12
    assert len({(fp.fingerprint.canvas_noise_seed, fp.fingerprint.audio_noise_seed) for fp in batch}) == 12

    assert {p.fingerprint.platform for p in pm.mass_generate_profiles(count=3, os_mix="mac")} == {"MacIntel"}
    assert {p.fingerprint.platform for p in pm.mass_generate_profiles(count=3, os_mix="linux")} == {"Linux x86_64"}
    assert [p.fingerprint.platform for p in pm.mass_generate_profiles(count=6, os_mix="all")] == [
        "Win32",
        "MacIntel",
        "Linux x86_64",
        "Win32",
        "MacIntel",
        "Linux x86_64",
    ]
    assert {p.fingerprint.platform for p in pm.mass_generate_profiles(count=2, os_mix="solaris")} == {"Win32"}

    proxies = pm.mass_generate_profiles(count=3, proxy_list=["203.0.113.1:8001:u:p", "   ", "203.0.113.2:8002"])
    assert [(p.proxy.host, p.proxy.port) for p in proxies] == [
        ("203.0.113.1", 8001),
        ("203.0.113.2", 8002),
        ("203.0.113.1", 8001),
    ]
    assert proxies[0].proxy.password == "p"
    assert [p.proxy.is_direct() for p in pm.mass_generate_profiles(count=2)] == [True, True]

    tags = ["Farm", "Beta"]
    tagged = pm.mass_generate_profiles(count=2, group="G", tags=tags, auto_open_page="youtube_studio", notes="hello")
    tags.append("MUTATED")
    assert tagged[0].google.tags == ["Farm", "Beta"]
    assert tagged[0].group == "G"
    assert tagged[0].google.auto_open_page == "youtube_studio"
    assert tagged[0].google.notes == "hello"

    # the service-side clamp is what protects the store even if a caller bypasses the API schema
    monkeypatch.setattr(profile_service, "MAX_MASS_GENERATE_COUNT", 3)
    assert len(pm.mass_generate_profiles(count=25)) == 3
    assert len(pm.mass_generate_profiles(count=0)) == 1  # documented minimum of one profile
    assert len(pm.mass_generate_profiles(count=-7)) == 1
    assert pm.mass_generate_profiles(count=1)[0].google.notes == "Generated in batch of 1"


def test_batch_import_cookies_matches_and_reports_failures(tmp_path):
    pm = _manager(tmp_path, "cookies")
    pm.create_profile(BrowserProfile(id="prof_alpha", name="Farm Alpha"))
    pm.create_profile(BrowserProfile(id="prof_beta", name="Farm Beta"))

    result = pm.batch_import_cookies(
        {
            "prof_alpha": _cookie_batch("by-id"),
            "farm beta": _cookie_batch("by-name-lower"),
            "beta": _cookie_batch("by-substring"),
            "nobody": _cookie_batch("orphan"),
            "skipped": [],
        }
    )
    assert result["created"] == 0
    assert result["matched"] == 3
    assert result["failed"] == 1  # only the unmatched key; the empty list is skipped silently
    assert result["profile_ids"] == ["prof_alpha", "prof_beta", "prof_beta"]
    assert pm.load_profile_cookies("prof_alpha") == _cookie_batch("by-id")
    # name match and substring match hit the same profile: last write wins
    assert pm.load_profile_cookies("prof_beta") == _cookie_batch("by-substring")

    created = pm.batch_import_cookies({"Brand New": _cookie_batch("new")}, auto_create_missing=True, group="Imported")
    assert (created["created"], created["matched"], created["failed"]) == (1, 0, 0)
    new_id = created["profile_ids"][0]
    new_profile = pm.get_profile(new_id)
    assert new_profile.group == "Imported"
    assert new_profile.proxy.is_direct() is True
    assert new_profile.fingerprint.user_agent
    assert new_profile.google.tags == ["Cookie Import", "Imported"]
    assert pm.load_profile_cookies(new_id) == _cookie_batch("new")

    assert pm.export_all_cookies([new_id, "prof_alpha"]) == {
        new_id: _cookie_batch("new"),
        "prof_alpha": _cookie_batch("by-id"),
    }
    # unknown ids and unsafe ids are dropped, never resolved as filesystem paths
    assert pm.export_all_cookies(["nope"]) == {}
    assert pm.export_all_cookies(["../evil", "prof;rm -rf", ""]) == {}


def test_batch_import_cookies_blank_key_must_not_target_an_arbitrary_profile(tmp_path):
    pm = _manager(tmp_path, "cookies-blank")
    pm.create_profile(BrowserProfile(id="prof_zzz", name="Zzz"))

    result = pm.batch_import_cookies({"": _cookie_batch("injected"), "   ": _cookie_batch("injected-2")})

    assert result["matched"] == 0
    assert result["failed"] == 2
    assert all(pm.load_profile_cookies(profile.id) == [] for profile in pm.list_profiles())


def test_service_query_helpers_ignore_unsafe_or_unknown_ids(tmp_path):
    pm = _manager(tmp_path, "helpers")

    assert pm.get_profile("../evil") is None
    assert pm.get_profile("") is None
    assert pm.seed_profile_history("does-not-exist") == 0
    assert pm.save_profile_cookies("does-not-exist", _cookie_batch("x")) is False
    assert pm.load_profile_cookies("does-not-exist") == []
    assert pm.export_all_cookies(["../evil", "does-not-exist"]) == {}


def test_reencrypt_all_secrets_skips_blank_and_undecryptable_notes(tmp_path, monkeypatch):
    pm = _manager(tmp_path, "reencrypt")
    pm.create_profile(BrowserProfile(id="prof_blank", google=GoogleSettings(notes="")))
    pm.create_profile(BrowserProfile(id="prof_none", google=GoogleSettings(notes=None)))
    pm.create_profile(BrowserProfile(id="prof_text", google=GoogleSettings(notes="free-form marketing note")))
    pm.create_profile(
        BrowserProfile(id="prof_plain", google=GoogleSettings(notes=json.dumps({"account_password": "pw"})))
    )

    assert pm.reencrypt_all_profile_secrets() == 1
    rewritten = json.loads(pm.get_profile("prof_plain").google.notes)
    assert rewritten["account_password"] == "pw"
    assert rewritten["_secrets_mode"] == "plain"
    assert pm.get_profile("prof_blank").google.notes == ""
    assert pm.get_profile("prof_text").google.notes == "free-form marketing note"

    locked_envelope = json.dumps({"account_password": "nzk1:pwd:AAAA:BBBB", "_secrets_mode": "passphrase"})
    pm.create_profile(BrowserProfile(id="prof_locked", google=GoogleSettings(notes=locked_envelope)))
    assert pm.reencrypt_all_profile_secrets() == 1  # only prof_plain; the unreadable one is skipped
    assert pm.get_profile("prof_locked").google.notes == locked_envelope

    real_reveal = secrets_store.reveal_notes
    real_encrypt = secrets_store.encrypt_notes

    def explode(*args, **kwargs):
        raise RuntimeError("secrets backend unavailable")

    monkeypatch.setattr(secrets_store, "reveal_notes", explode)
    assert pm.reencrypt_all_profile_secrets() == 0
    monkeypatch.setattr(secrets_store, "reveal_notes", real_reveal)

    monkeypatch.setattr(secrets_store, "encrypt_notes", explode)
    assert pm.reencrypt_all_profile_secrets() == 0
    monkeypatch.setattr(secrets_store, "encrypt_notes", real_encrypt)

    # nothing was clobbered by the failed runs
    assert json.loads(pm.get_profile("prof_plain").google.notes)["account_password"] == "pw"
    assert pm.get_profile("prof_locked").google.notes == locked_envelope
