"""
Deep perimeter fuzzing for ``nazak/api/security.py`` (and the ``local_only_guard``
in ``nazak/api/server.py``).

Scope: NEW attack payloads only. ``tests/test_deep_security_and_traversal.py``
already owns the classic traversal/shell-metachar charset and the endpoint-level
CORS matrix; ``tests/test_proxy_rotation_and_mobile.py`` owns the endpoint-level
rotation refusals; ``tests/test_api_origin_and_ws.py`` owns the same-origin matrix;
``tests/test_round3_api_fixes.py`` owns the media-extension and dict-based token
cases. Everything below attacks a different spelling of the same boundaries:
UNC / device paths, percent-encoded and unicode traversal, non-string ids,
Windows reserved device names, userinfo in Origin, non-ASCII API keys, the
raw proxy string, IPv4-embedded IPv6 (NAT64) rotation targets, DNS-rebinding
answer sets, the pinned connection classes, and the guard's static-file
short-circuit.

No network, no browser, no sleeps: DNS and ``socket.create_connection`` are
patched, and every assertion is on the SECURE behaviour. Genuinely broken
behaviour is kept as an assertion and marked ``xfail`` with a ``BUG:`` reason.
"""

import asyncio
import socket
import ssl
import urllib.error
import urllib.request

import pytest
from fastapi import HTTPException, WebSocketDisconnect
from starlette.datastructures import Headers
from starlette.responses import JSONResponse

import nazak.api.security as security
from nazak.api import server
from nazak.core.secrets_store import UNAVAILABLE_PLACEHOLDER
from nazak.models.proxy import ProxyConfig


# --------------------------------------------------------------------------- fakes
class _FakeURL:
    def __init__(self, path: str) -> None:
        self.path = path


class _FakeRequest:
    def __init__(self, path: str, headers: dict[str, str]) -> None:
        self.url = _FakeURL(path)
        self.headers = Headers(headers)


class _FakeRawSocket:
    """Stands in for the TCP socket returned by socket.create_connection."""


class _FakeTLSContext(ssl.SSLContext):
    """A real SSLContext with a captured ``wrap_socket``.

    Subclassing the real context keeps every attribute the stdlib may read
    (``verify_mode``, ``check_hostname``, ``minimum_version``, …) present, which
    plain attribute stubs were not: on Python 3.10/3.11 the tunnel setup read an
    attribute the stub did not define.
    """

    def __new__(cls, *args, **kwargs):
        # ssl.SSLContext consumes the protocol in __new__, not __init__.
        return super().__new__(cls, ssl.PROTOCOL_TLS_CLIENT)

    def __init__(self) -> None:
        self.calls: list[tuple[object, str | None]] = []

    def wrap_socket(self, raw, server_hostname=None):
        self.calls.append((raw, server_hostname))
        return _FakeRawSocket()


class _FakeWebSocket:
    def __init__(self, headers: dict[str, str]) -> None:
        self.headers = Headers(headers)
        self.closed: list[int] = []
        self.accepted = False

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        self.closed.append(code)

    async def accept(self) -> None:
        self.accepted = True

    async def receive_text(self) -> str:
        raise WebSocketDisconnect()


class _FakeManager:
    def __init__(self) -> None:
        self.connected: list[object] = []
        self.disconnected: list[object] = []

    async def connect(self, websocket) -> None:
        self.connected.append(websocket)
        await websocket.accept()

    def disconnect(self, websocket) -> None:
        self.disconnected.append(websocket)


async def _ok_response(_request) -> JSONResponse:
    return JSONResponse({"ok": True})


def _guard(path: str, headers: dict[str, str]):
    return asyncio.run(server.local_only_guard(_FakeRequest(path, headers), _ok_response))


def _launch_url_accepted(url: str) -> bool:
    try:
        security._require_launch_url(url)
    except HTTPException:
        return False
    return True


# --------------------------------------------------------------------------- validate_pid
def test_validate_pid_rejects_traversal_unc_encoded_and_non_string_payloads():
    payloads = [
        "\\\\server\\share\\prof",
        "\\\\?\\C:\\Windows\\win.ini",
        "//server/share/prof",
        "/etc/passwd",
        "..\\..\\prof",
        ".../.../prof",
        "..%5cprof",
        "%2e%2e%2fprof",
        "%2e%2e%5cprof",
        "..%252fprof",
        "..\uff0fprof",
        "\uff0e\uff0eprof",
        "..\u200b/prof",
        "\u2024\u2024/prof",
        "..\u0000/profile",
    ]
    for payload in payloads:
        with pytest.raises(HTTPException) as exc:
            security.validate_pid(payload)
        assert exc.value.status_code == 400, payload

    for non_string in [None, 123, 0, True, b"prof", ["prof"], {"prof": 1}]:
        with pytest.raises(HTTPException) as exc:
            security.validate_pid(non_string)
        assert exc.value.status_code == 400, non_string


def test_validate_pid_rejects_windows_reserved_device_names():
    accepted = []
    for payload in ["CON", "con", "NUL", "nul", "AUX", "PRN", "COM1", "LPT1", "NUL.mp4"]:
        try:
            security.validate_pid(payload)
            accepted.append(payload)
        except HTTPException:
            continue
    assert accepted == [], f"reserved Windows device names accepted as profile ids: {accepted}"


# --------------------------------------------------------------------------- host / origin
def test_is_local_host_rejects_alternate_loopback_spellings():
    for local in ["localhost", "LOCALHOST", "127.0.0.1", "127.0.0.1:8899", "[::1]:8899", "[::1]"]:
        assert security._is_local_host(local) is True, local

    for foreign in [
        "127.0.0.1.",  # trailing dot (FQDN form) must not be trusted
        "localhost.",
        "127.1",  # short-form IPv4 loopback
        "2130706433",  # decimal IPv4 loopback
        "0x7f000001",  # hex IPv4 loopback
        "::1",  # bare IPv6 without brackets is not a valid Host
        "127.0.0.1.evil.example.com",
        "localhost.evil.example.com",
        "127.0.0.1@evil.example.com",
        "127.0.0.1:8899:evil",
        "evil.example.com:8899",
        "",
        None,
    ]:
        assert security._is_local_host(foreign) is False, foreign


def test_origin_matching_refuses_userinfo_and_non_http_schemes():
    host = "127.0.0.1:8899"
    # allow-list short-circuit for falsy origins (non-browser clients) is the documented contract
    assert security._is_local_origin(None) is True
    assert security._is_local_origin("") is True
    assert security._is_local_origin("http://127.0.0.1:8899/") is True

    for foreign in [
        "http://evil.example.com@127.0.0.1:8899",  # userinfo must not hide the real origin host
        "http://127.0.0.1:8899@evil.example.com",
        "http://user:pass@localhost:8899",
        "http://127.0.0.1:8899.evil.example.com",
        "http://sub.localhost:8899",
        "https://evil.example.com",
        "ftp://127.0.0.1:8899",
        "file://127.0.0.1:8899",
        "ws://127.0.0.1:8899",
        "null",
        "urn:nazak",
        "//127.0.0.1:8899",
        "HTTP://127.0.0.1:8899",  # scheme matching is case-sensitive: fail closed
    ]:
        assert security._origin_matches_request(foreign, host) is False, foreign
        assert security._is_local_origin(foreign) is False, foreign

    assert security._origin_matches_request(None, host) is True
    assert security._origin_matches_request("http://127.0.0.1:8899", host) is True


def test_port_trust_registration_and_patch_seam_fallbacks(monkeypatch):
    trusted_ports: set[int] = set()
    monkeypatch.setattr(security, "_ALLOWED_PORTS", trusted_ports)
    monkeypatch.setattr(server, "_ALLOWED_PORTS", trusted_ports)

    security.configure_local_access(54321)
    assert security._is_local_origin("http://localhost:54321") is True
    assert security._is_local_origin("http://127.0.0.1:54322") is False

    security.configure_local_access(0)  # port 0 is not a bindable trust grant
    assert 0 not in trusted_ports
    assert security._is_local_origin("http://localhost:0") is False

    # the guard honours a server-module override when it is a port set ...
    monkeypatch.setattr(server, "_ALLOWED_PORTS", {60001})
    assert security._get_allowed_ports() == {60001}
    # ... and falls back to its own copy when the override is not a set
    monkeypatch.setattr(server, "_ALLOWED_PORTS", [60001])
    assert security._get_allowed_ports() is security._ALLOWED_PORTS

    # resolver seam: a broken server hook must fall back to the local resolver
    monkeypatch.setattr(server, "_resolve_host_ips", None)
    assert security._resolve_resolver() is security._resolve_host_ips
    monkeypatch.setattr(server, "_resolve_host_ips", lambda host, port: ["93.184.216.34"])
    assert security._resolve_resolver()("rotate.example.com", 443) == ["93.184.216.34"]


# --------------------------------------------------------------------------- API token
def test_api_token_exact_match_and_case_insensitive_header_lookup(monkeypatch):
    monkeypatch.setenv("NAZAK_API_TOKEN", "s3cret-token")
    assert security.api_token_configured() is True
    assert security._is_api_token_valid(Headers({"X-API-Key": "s3cret-token"})) is True
    assert security._is_api_token_valid(Headers({"x-api-key": "S3CRET-TOKEN"})) is False
    assert security._is_api_token_valid(Headers({"x-api-key": "s3cret-token "})) is False
    assert security._is_api_token_valid(Headers({"x-api-key": "s3cret-tokenx"})) is False
    assert security._is_api_token_valid(Headers({"x-api-key": ""})) is False
    assert security._is_api_token_valid(Headers({})) is False
    assert security._is_api_token_valid(Headers({"x-forwarded-x-api-key": "s3cret-token"})) is False

    monkeypatch.delenv("NAZAK_API_TOKEN", raising=False)
    assert security.api_token_configured() is False
    # unset token: the loopback Host/Origin guard is the perimeter (documented mode)
    assert security._is_api_token_valid(Headers({})) is True

    # whitespace-only token is not "configured", so exposure is refused and no real key passes
    monkeypatch.setenv("NAZAK_API_TOKEN", "   ")
    assert security.api_token_configured() is False
    assert security._is_api_token_valid(Headers({})) is False
    assert security._is_api_token_valid(Headers({"x-api-key": "s3cret-token"})) is False
    with pytest.raises(SystemExit):
        security.enforce_exposure_policy("0.0.0.0")


def test_api_token_comparison_uses_constant_time_primitive(monkeypatch):
    monkeypatch.setenv("NAZAK_API_TOKEN", "s3cret-token")
    seen: list[tuple[object, object]] = []

    def spy(provided, expected):
        seen.append((provided, expected))
        return False

    monkeypatch.setattr("hmac.compare_digest", spy)
    assert security._is_api_token_valid(Headers({"x-api-key": "guess"})) is False
    assert seen == [(b"guess", b"s3cret-token")], (
        "the comparison must go through hmac.compare_digest with ASCII-safe bytes"
    )


def test_api_token_non_ascii_values_are_rejected_not_crashing(monkeypatch):
    monkeypatch.setenv("NAZAK_API_TOKEN", "s3cret-token")
    assert security._is_api_token_valid(Headers({"x-api-key": "s\u00e9cret"})) is False
    monkeypatch.setenv("NAZAK_API_TOKEN", "s\u00e9cret-token")
    assert security._is_api_token_valid(Headers({"x-api-key": "s3cret-token"})) is False


# --------------------------------------------------------------------------- masking
def test_masking_helpers_mask_secrets_in_fields_and_raw():
    proxy = ProxyConfig(
        type="http",
        host="198.51.100.9",
        port=8080,
        username="user",
        password="sup3r-secret",
        rotation_url="https://rotate.example.com/?key=abc",
    )
    masked = security._mask_proxy_for_api(proxy)
    assert masked["password"] == "***"
    assert masked["rotation_url"] == "***"
    assert masked["username"] == "user"
    assert masked["host"] == "198.51.100.9"
    assert "sup3r-secret" not in repr(masked)

    # credential present only inside `raw` (password field empty) must still be masked
    raw_proxy = ProxyConfig(
        type="socks5", host="198.51.100.9", port=1080, raw="socks5://user:rawtopsecret@198.51.100.9:1080"
    )
    masked_raw = security._mask_proxy_for_api(raw_proxy)
    assert "rawtopsecret" not in masked_raw["raw"]
    assert "***@198.51.100.9:1080" in masked_raw["raw"]

    unicode_proxy = ProxyConfig(
        type="http",
        host="198.51.100.9",
        port=8080,
        password="p\u00e4\u00a7",
        raw="http://u:p\u00e4\u00a7@198.51.100.9:8080",
    )
    assert "p\u00e4\u00a7" not in security._mask_proxy_for_api(unicode_proxy)["raw"]

    for masked_value in [None, 12345, b"bytes", "", "   ", "***", f"  {UNAVAILABLE_PLACEHOLDER}  ", "<encrypted: x>"]:
        assert security._is_display_mask_value(masked_value) is True, masked_value
    for real_value in ["https://rotate.example.com/?key=abc", "***real", "<encrypt"]:
        assert security._is_display_mask_value(real_value) is False, real_value


def test_mask_proxy_for_api_keeps_short_passwords_out_of_raw():
    proxy = ProxyConfig(
        type="http",
        host="198.51.100.9",
        port=8080,
        username="pworker",
        password="pw",
        raw="http://pworker:pw@198.51.100.9:8080",
    )
    masked = security._mask_proxy_for_api(proxy)
    assert masked["password"] == "***"
    assert ":pw@" not in masked["raw"], masked["raw"]


# --------------------------------------------------------------------------- launch URL / media source
def test_require_launch_url_rejects_file_scripts_flags_and_device_paths():
    for payload in [
        "file:///C:/Windows/win.ini",
        "FILE:///etc/passwd",
        "javascript:alert(document.domain)",
        "data:text/html;base64,PHNjcmlwdD4=",
        "blob:https://evil.example.com/abc",
        "vbscript:msgbox(1)",
        "-headless",
        "--user-data-dir=C:/x",
        "//evil.example.com/steal",
        " file:///C:/Windows/win.ini",
    ]:
        with pytest.raises(HTTPException) as exc:
            security._require_launch_url(payload)
        assert exc.value.status_code == 400, payload

    for allowed in ["https://example.com/ok", "http://127.0.0.1:8899/", "about:blank"]:
        assert security._require_launch_url(allowed) == allowed
    assert security._require_launch_url("") is None
    assert security._require_launch_url(None) is None

    file_like = ["\\\\?\\C:\\Windows\\win.ini", "\\\\server\\share\\payload.mp4", "C:\\Windows\\win.ini"]
    accepted = [payload for payload in file_like if _launch_url_accepted(payload)]
    assert accepted == [], f"file-like device/UNC paths are not refused: {accepted}"


def test_resolve_media_source_boundaries(tmp_path):
    for blank in ["", "   ", "\t\n", "  \t  "]:
        with pytest.raises(HTTPException) as exc:
            security.resolve_media_source(blank)
        assert exc.value.status_code == 400, repr(blank)

    with pytest.raises(HTTPException) as exc:
        security.resolve_media_source("file:///C:/Windows/win.ini.mp4")
    assert exc.value.status_code == 400

    with pytest.raises(HTTPException):
        security.resolve_media_source("~/nazak-no-such-clip.mp4")

    video = tmp_path / "CLIP.MP4"
    video.write_bytes(b"\x00" * 16)
    assert security.resolve_media_source(str(video)) == video  # extension check is case-insensitive

    with pytest.raises(HTTPException):
        security.resolve_media_source(f"{video} ")  # Windows silently strips the trailing space

    double_extension = tmp_path / "clip.mp4.exe"
    double_extension.write_bytes(b"x")
    with pytest.raises(HTTPException):
        security.resolve_media_source(str(double_extension))


def test_remove_quietly_deletes_files_and_swallows_filesystem_errors(tmp_path):
    temporary_bundle = tmp_path / "profile.nazak"
    temporary_bundle.write_bytes(b"bundle")
    security._remove_quietly(temporary_bundle)
    assert not temporary_bundle.exists()

    security._remove_quietly(tmp_path / "already-gone.nazak")  # missing path must not raise
    security._remove_quietly(tmp_path)  # a directory cannot be unlinked: still must not raise
    assert tmp_path.exists()


# --------------------------------------------------------------------------- rotation SSRF
def test_rotation_target_refuses_private_loopback_and_reserved_literals():
    payloads = [
        "http://0.0.0.0/",
        "http://10.0.0.1/",
        "http://172.16.5.5/",
        "http://192.168.7.7/",
        "http://198.18.0.1/",
        "http://240.0.0.1/",
        "http://[::ffff:7f00:1]/",
        "http://[fd00::1]/",
        "http://[fe80::1]/",
        "http://[2001:db8::1]/",
        "http://[2002:7f00:1::]/",  # 6to4 embedding 127.0.0.1
        "http://[2001:0000:4136:e378:8000:63bf:3fff:fdd2]/",  # Teredo
        "http://[64:ff9b:1::7f00:1]/",  # local-use NAT64 prefix
    ]
    for url in payloads:
        assert security._reject_rotation_url(url) is not None, url
    assert security._rotation_target("http://10.0.0.1/") == "host must be a public address"
    # control: public IPv4/IPv6 literals are still allowed (the filter is not blanket-deny)
    assert security._rotation_target("http://93.184.216.34/") == ("93.184.216.34", 80, "93.184.216.34")
    assert security._rotation_target("http://[2606:4700::1111]/") == ("2606:4700::1111", 80, "2606:4700::1111")


def test_ipv4_embedded_ipv6_rotation_urls_bypass_public_address_check():
    # controls: the plain and IPv4-mapped spellings are refused
    assert security._reject_rotation_url("http://169.254.169.254/latest/meta-data/") is not None
    assert security._reject_rotation_url("http://[::ffff:169.254.169.254]/") is not None
    assert security._reject_rotation_url("http://[::ffff:127.0.0.1]/") is not None

    embedded = [
        "http://[64:ff9b::a9fe:a9fe]/",  # NAT64 view of the cloud metadata service
        "http://[64:ff9b::7f00:1]/",  # NAT64 view of 127.0.0.1
        "http://[::a9fe:a9fe]/",  # deprecated IPv4-compatible form
        "http://[::7f00:1]/",
    ]
    accepted = [url for url in embedded if security._reject_rotation_url(url) is None]
    assert accepted == [], f"IPv4-embedded IPv6 rotation targets accepted: {accepted}"


def test_rotation_target_reports_malformed_hostless_and_garbage_resolutions(monkeypatch):
    assert security._rotation_target("http://rotate.example.com:99999/") == "malformed URL"
    assert security._rotation_target("http://rotate.example.com:not-a-port/") == "malformed URL"
    assert security._rotation_target("http://[::1/") == "malformed URL"
    assert security._rotation_target("http:///no-host") == "URL has no host"
    assert security._rotation_target("http://") == "URL has no host"
    assert security._rotation_target("ftp://rotate.example.com/") == "only http(s) URLs are allowed"
    assert security._rotation_target("file:///C:/rotate") == "only http(s) URLs are allowed"

    monkeypatch.setattr(server, "_resolve_host_ips", lambda host, port: [])
    assert security._rotation_target("http://rotate.example.com/") == "host cannot be resolved"

    monkeypatch.setattr(server, "_resolve_host_ips", lambda host, port: ["not-an-address"])
    assert security._rotation_target("http://rotate.example.com/") == "host cannot be resolved"

    # decimal / octal / short-form IPv4 spellings must not survive the resolved-address check
    for host in ["2130706433", "0177.0.0.1", "127.1", "0x7f000001"]:
        monkeypatch.setattr(server, "_resolve_host_ips", lambda h, p: ["127.0.0.1"])
        assert security._reject_rotation_url(f"http://{host}/") is not None, host

    # DNS rebinding / round-robin answer sets mixing a public with a private address
    for answers in [
        ["93.184.216.34", "10.0.0.1"],
        ["10.0.0.1", "93.184.216.34"],
        ["93.184.216.34", "169.254.169.254"],
    ]:
        monkeypatch.setattr(server, "_resolve_host_ips", lambda h, p, _answers=answers: list(_answers))
        assert security._rotation_target("http://rotate.example.com/") == "host must be a public address"

    monkeypatch.setattr(server, "_resolve_host_ips", lambda host, port: ["93.184.216.34"])
    assert security._rotation_target("https://rotate.example.com/change") == (
        "rotate.example.com",
        443,
        "93.184.216.34",
    )


def test_resolve_host_ips_swallows_dns_failures_and_short_circuits_literals(monkeypatch):
    calls: list[tuple[str, int]] = []

    def failing_getaddrinfo(host, port, **kwargs):
        calls.append((host, port))
        raise socket.gaierror("dns disabled in tests")

    monkeypatch.setattr(socket, "getaddrinfo", failing_getaddrinfo)
    assert security._resolve_host_ips("no-such-host.invalid", 80) == []
    assert security._resolve_host_ips("rotate.example.com", 443) == []
    assert calls == [("no-such-host.invalid", 80), ("rotate.example.com", 443)]

    # IP literals never touch DNS: pinning must not depend on the resolver
    calls.clear()
    assert security._resolve_host_ips("127.0.0.1", 80) == ["127.0.0.1"]
    assert security._resolve_host_ips("::1", 443) == ["::1"]
    assert calls == []

    def unicode_getaddrinfo(host, port, **kwargs):
        raise UnicodeError("bad idna label")

    monkeypatch.setattr(socket, "getaddrinfo", unicode_getaddrinfo)
    assert security._resolve_host_ips("\u043f\u0440\u0438\u043c\u0435\u0440.\u0440\u0444", 80) == []

    def os_error_getaddrinfo(host, port, **kwargs):
        raise OSError("resolver exploded")

    monkeypatch.setattr(socket, "getaddrinfo", os_error_getaddrinfo)
    assert security._resolve_host_ips("rotate.example.com", 80) == []


# --------------------------------------------------------------------------- pinned fetch
def test_build_pinned_opener_disables_proxies_refuses_redirects_and_pins_ip(monkeypatch):
    dialed: list[tuple[str, int]] = []

    def fake_create_connection(address, *args, **kwargs):
        dialed.append(tuple(address))
        raise OSError("network disabled in tests")

    monkeypatch.setattr(socket, "create_connection", fake_create_connection)
    # a decoy proxy in the environment must never be consulted for a pinned fetch
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9999")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9999")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9999")
    monkeypatch.setenv("https_proxy", "http://127.0.0.1:9999")

    opener = security._build_pinned_opener("203.0.113.9")
    http_handlers = [handler for handler in opener.handlers if isinstance(handler, urllib.request.HTTPHandler)]
    assert http_handlers, "opener has no HTTP handler"
    assert all(getattr(handler, "_pinned_ip", None) == "203.0.113.9" for handler in http_handlers)
    assert any(isinstance(handler, security._NoRedirectHandler) for handler in opener.handlers)

    # ProxyHandler({}) suppresses urllib's default env/system proxy handler; if that
    # suppression is ever dropped, the request below goes to the decoy proxy instead of
    # the validated IP (verified by removing it locally).
    proxy_maps = [handler.proxies for handler in opener.handlers if isinstance(handler, urllib.request.ProxyHandler)]
    assert all(not proxies for proxies in proxy_maps), f"proxy handler would defeat IP pinning: {proxy_maps}"

    request = urllib.request.Request("http://rotation.example.com/change")
    with pytest.raises(OSError):
        opener.open(request, timeout=2)
    assert dialed == [("203.0.113.9", 80)], f"request did not dial the validated IP directly: {dialed}"

    with pytest.raises(urllib.error.HTTPError) as exc:
        security._NO_REDIRECT_HANDLER.redirect_request(
            request, None, 307, "Temporary Redirect", {}, "http://evil.example.com/"
        )
    assert exc.value.code == 307


def test_pinned_connection_classes_dial_validated_ip_not_dns(monkeypatch):
    dialed: list[tuple[object, object]] = []
    raw_sockets: list[_FakeRawSocket] = []

    def fake_create_connection(address, *args, **kwargs):
        raw = _FakeRawSocket()
        raw_sockets.append(raw)
        dialed.append((tuple(address), args[0] if args else kwargs.get("timeout")))
        return raw

    monkeypatch.setattr(socket, "create_connection", fake_create_connection)

    plain = security._PinnedHTTPConnection("rotate.example.com", port=8080, pinned_ip="203.0.113.9", timeout=7)
    assert plain.host == "rotate.example.com"  # Host header keeps the vhost, the socket goes to the IP
    plain.connect()
    assert dialed == [(("203.0.113.9", 8080), 7)]
    assert plain.sock is raw_sockets[-1]

    tls = _FakeTLSContext()
    secure = security._PinnedHTTPSConnection("rotate.example.com", pinned_ip="203.0.113.9", timeout=7, context=tls)
    secure.connect()
    assert dialed[-1][0] == ("203.0.113.9", 443)
    assert tls.calls == [(raw_sockets[-1], "rotate.example.com")], "TLS SNI must stay on the validated hostname"

    http_handler = security._PinnedHTTPHandler("203.0.113.9")
    captured: dict[str, object] = {}

    def capture_http(factory, request):
        captured["http"] = factory
        return "HTTP"

    http_handler.do_open = capture_http
    assert http_handler.http_open(urllib.request.Request("http://rotate.example.com/")) == "HTTP"
    pinned_http = captured["http"]("rotate.example.com", timeout=5)
    assert isinstance(pinned_http, security._PinnedHTTPConnection)
    assert pinned_http._pinned_ip == "203.0.113.9"

    secure_handler = security._PinnedHTTPSHandler("203.0.113.9")
    captured.clear()

    def capture_https(factory, request):
        captured["https"] = factory
        return "HTTPS"

    secure_handler.do_open = capture_https
    assert secure_handler.https_open(urllib.request.Request("https://rotate.example.com/")) == "HTTPS"
    pinned_https = captured["https"]("rotate.example.com", timeout=5)
    assert isinstance(pinned_https, security._PinnedHTTPSConnection)
    assert pinned_https._pinned_ip == "203.0.113.9"


# --------------------------------------------------------------------------- headers / CSP
def test_apply_security_headers_sets_expected_headers_with_api_only_no_store():
    for path in ["/api/system/info", "/v1.0/browser_profiles", "/", "/docs", "/static/x.js"]:
        response = security._apply_security_headers(JSONResponse({"ok": True}), path)
        for header, expected in security.SECURITY_HEADERS.items():
            assert response.headers[header] == expected, (path, header)
        if path.startswith(("/api", "/v1.0")):
            assert response.headers["Cache-Control"] == "no-store", path
        else:
            assert "Cache-Control" not in response.headers, path


def test_security_header_constants_have_no_wildcards_or_weak_directives():
    directives = {
        part.strip().split(" ", 1)[0]: part.strip() for part in security.CSP_POLICY.split(";") if part.strip()
    }
    assert directives["default-src"] == "default-src 'self'"
    assert directives["script-src"] == "script-src 'self'"
    assert directives["font-src"] == "font-src 'self'"
    assert directives["img-src"] == "img-src 'self' data: blob:"
    assert directives["connect-src"].startswith("connect-src 'self'")
    assert directives["form-action"] == "form-action 'self'"
    assert "*" not in security.CSP_POLICY
    assert "unsafe-eval" not in security.CSP_POLICY
    assert "unsafe-inline" not in directives["script-src"]
    assert security.SECURITY_HEADERS["X-Frame-Options"] == "DENY"
    assert security.SECURITY_HEADERS["Cross-Origin-Opener-Policy"] == "same-origin"
    assert security.SECURITY_HEADERS["Cross-Origin-Resource-Policy"] == "same-origin"
    assert security.SECURITY_HEADERS["X-Content-Type-Options"] == "nosniff"
    permissions = security.SECURITY_HEADERS["Permissions-Policy"]
    for feature in ["geolocation=()", "camera=()", "microphone=()", "usb=()", "serial=()"]:
        assert feature in permissions


# --------------------------------------------------------------------------- guard middleware
def test_local_only_guard_blocks_foreign_host_origin_cross_site_and_tokenless_api(monkeypatch):
    monkeypatch.delenv("NAZAK_API_TOKEN", raising=False)
    blocked_host = _guard("/api/system/info", {"host": "evil.example.com"})
    assert blocked_host.status_code == 403
    assert blocked_host.headers["X-Frame-Options"] == "DENY"
    assert "evil.example.com" not in blocked_host.body.decode()
    assert (
        _guard("/api/system/info", {"host": "127.0.0.1:8899", "origin": "https://evil.example.com"}).status_code == 403
    )
    assert _guard("/api/system/info", {"host": "127.0.0.1:8899", "origin": "http://127.0.0.1:9000"}).status_code == 403
    assert _guard("/api/system/info", {"host": "127.0.0.1:8899", "sec-fetch-site": "cross-site"}).status_code == 403

    allowed = _guard(
        "/api/system/info",
        {"host": "127.0.0.1:8899", "origin": "http://127.0.0.1:8899", "sec-fetch-site": "same-origin"},
    )
    assert allowed.status_code == 200
    assert allowed.headers["Cache-Control"] == "no-store"

    monkeypatch.setenv("NAZAK_API_TOKEN", "s3cret-token")
    assert _guard("/api/system/info", {"host": "127.0.0.1:8899"}).status_code == 401
    assert _guard("/api/system/info", {"host": "127.0.0.1:8899", "x-api-key": "wrong"}).status_code == 401
    assert _guard("/api/system/info", {"host": "127.0.0.1:8899", "x-api-key": "s3cret-token"}).status_code == 200
    # the token only guards /api and /v1.0; docs stay on the Host/Origin perimeter
    assert _guard("/docs", {"host": "127.0.0.1:8899"}).status_code == 200
    assert _guard("/docs", {"host": "evil.example.com"}).status_code == 403


def test_static_prefix_is_not_exempt_from_the_local_only_guard(monkeypatch):
    monkeypatch.setenv("NAZAK_API_TOKEN", "s3cret-token")
    assert _guard("/static/x.js", {"host": "evil.example.com"}).status_code == 403
    assert _guard("/static/../api/system/info", {"host": "evil.example.com"}).status_code == 403


def test_websocket_endpoint_refuses_foreign_origin_cross_site_and_bad_token(monkeypatch):
    manager = _FakeManager()
    monkeypatch.setattr(server, "ws_manager", manager)
    monkeypatch.delenv("NAZAK_API_TOKEN", raising=False)

    for headers in [
        {"host": "evil.example.com"},
        {"host": "127.0.0.1:8899", "origin": "https://evil.example.com"},
        {"host": "127.0.0.1:8899", "sec-fetch-site": "cross-site"},
    ]:
        websocket = _FakeWebSocket(headers)
        asyncio.run(server.websocket_endpoint(websocket))
        assert websocket.closed == [1008], headers
        assert websocket.accepted is False, headers

    monkeypatch.setenv("NAZAK_API_TOKEN", "s3cret-token")
    tokenless = _FakeWebSocket({"host": "127.0.0.1:8899", "origin": "http://127.0.0.1:8899"})
    asyncio.run(server.websocket_endpoint(tokenless))
    assert tokenless.closed == [1008]
    assert tokenless.accepted is False

    accepted = _FakeWebSocket(
        {"host": "127.0.0.1:8899", "origin": "http://127.0.0.1:8899", "x-api-key": "s3cret-token"}
    )
    asyncio.run(server.websocket_endpoint(accepted))
    assert accepted.accepted is True
    assert accepted.closed == []
    assert manager.connected == [accepted]
