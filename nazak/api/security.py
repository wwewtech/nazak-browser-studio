"""
Nazak API security perimeter (P0 refactor).

Extracted verbatim from nazak/api/server.py: local-only Host/Origin/
Sec-Fetch-Site guard, API-token policy, CSP + security headers, validation
helpers, masking helpers, media-source gate and SSRF-pinned rotation fetch.
Behaviour is unchanged — only the home moved so routers stay thin.
"""

import http.client
import ipaddress
import json
import math
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from ..config import DEFAULT_PORT
from ..core.browser_launcher import sanitize_launch_url
from ..core.secrets_store import UNAVAILABLE_PLACEHOLDER, decrypt_notes
from ..models.profile import BrowserProfile
from ..models.proxy import ProxyConfig

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
if os.environ.get("NAZAK_ALLOW_TEST_HOST", "").strip().lower() in ("1", "true", "yes", "y"):
    _LOCAL_HOSTS.add("testserver")
_ALLOWED_PORTS: set[int] = {DEFAULT_PORT, 3000}
_LOCAL_SCHEMES = ("http", "https")
_API_TOKEN_ENV = "NAZAK_API_TOKEN"

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def api_token_configured() -> bool:
    return bool((os.environ.get(_API_TOKEN_ENV) or "").strip())


def enforce_exposure_policy(host: str) -> None:
    if not host or host in _LOOPBACK_HOSTS:
        return
    if api_token_configured():
        return
    raise SystemExit(
        f"Отказ запуска: --host {host} выставляет API за пределы loopback, "
        f"а {_API_TOKEN_ENV} не задан. Варианты:\n"
        f"  1) слушать только локально: --host 127.0.0.1 (по умолчанию);\n"
        f"  2) осознанно выставить наружу: задайте {_API_TOKEN_ENV}=<секрет> "
        f"и передавайте заголовок X-API-Key (CLI: --api-key)."
    )


def configure_local_access(port: int) -> None:
    """Trust the port the server actually binds to (call from startup)."""
    if port:
        _ALLOWED_PORTS.add(int(port))


def _host_name(host: str) -> str:
    host = (host or "").strip().lower()
    if host.startswith("["):
        return host[1 : host.find("]")] if "]" in host else host
    name, sep, tail = host.rpartition(":")
    return name if sep and tail.isdigit() else host


def _is_local_host(host: str | None) -> bool:
    return _host_name(host or "") in _LOCAL_HOSTS


def _is_local_origin(origin: str | None) -> bool:
    if not origin:
        return True
    match = re.match(r"^(https?)://([^/]+)$", origin.rstrip("/"))
    if not match or match.group(1) not in _LOCAL_SCHEMES:
        return False
    name = _host_name(match.group(2))
    if name not in _LOCAL_HOSTS:
        return False
    raw = match.group(2)
    port_part = raw.rpartition(":")[2]
    if port_part.isdigit():
        port = int(port_part)
    else:
        port = 443 if match.group(1) == "https" else 80
    return port in _get_allowed_ports()


def _host_port(value: str | None) -> int | None:
    raw = (value or "").strip()
    if not raw:
        return None
    candidate = raw.rpartition("]:")[2] if raw.startswith("[") else raw.rpartition(":")[2]
    return int(candidate) if candidate.isdigit() else None


def _origin_matches_request(origin: str | None, host_header: str | None) -> bool:
    if not origin:
        return True
    if _is_local_origin(origin):
        return True
    match = re.match(r"^(https?)://([^/]+)$", origin.rstrip("/"))
    if not match or match.group(1) not in _LOCAL_SCHEMES:
        return False
    if _host_name(match.group(2)) not in _LOCAL_HOSTS:
        return False
    origin_port = _host_port(match.group(2)) or (443 if match.group(1) == "https" else 80)
    request_port = _host_port(host_header) or 80
    return origin_port == request_port


def _is_api_token_valid(request_headers) -> bool:
    expected = os.environ.get(_API_TOKEN_ENV)
    if not expected:
        return True
    import hmac

    provided = str(request_headers.get("x-api-key") or "")
    # Compare bytes, not str: hmac.compare_digest() raises TypeError on non-ASCII
    # str input, so a client sending "X-API-Key: sécret" (or an operator setting a
    # non-ASCII token) turned a 401 into an unhandled 500 — a self-inflicted outage
    # and a free error channel for anyone who can reach the port.
    return hmac.compare_digest(provided.encode("utf-8"), str(expected).encode("utf-8"))


CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "font-src 'self'; "
    "connect-src 'self' ws: wss:; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "geolocation=(), camera=(), microphone=(), usb=(), serial=()",
    "Content-Security-Policy": CSP_POLICY,
}
_NO_STORE_PREFIXES = ("/api", "/v1.0")


def _apply_security_headers(response, path: str):
    for header, value in SECURITY_HEADERS.items():
        response.headers.setdefault(header, value)
    if path.startswith(_NO_STORE_PREFIXES):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


def _json_safe_error_payload(value: Any, _depth: int = 0) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, dict) and _depth < 3:
        return {str(k): _json_safe_error_payload(v, _depth + 1) for k, v in list(value.items())[:20]}
    if isinstance(value, (list, tuple)) and _depth < 3:
        return [_json_safe_error_payload(v, _depth + 1) for v in list(value)[:20]]
    if isinstance(value, str) and len(value) > 200:
        return value[:200] + f"…(+{len(value) - 200} chars)"
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    return str(value)


async def validation_error_handler(request, exc):
    """422 with a safe body (no inf/nan, no multi-megabyte input echo)."""
    errors = []
    for error in exc.errors():
        safe = {k: v for k, v in error.items() if k not in ("input", "ctx", "url")}
        if "input" in error:
            safe["input"] = _json_safe_error_payload(error["input"])
        if "ctx" in error:
            safe["ctx"] = _json_safe_error_payload(error["ctx"])
        errors.append(safe)
    return JSONResponse(status_code=422, content={"detail": errors})


_RESERVED_WINDOWS_DEVICE_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
)


def validate_pid(profile_id: str) -> str:
    if not profile_id or not isinstance(profile_id, str):
        raise HTTPException(status_code=400, detail="Invalid profile_id: must be a non-empty string")
    p = Path(profile_id)
    if (
        p.name != profile_id
        or p.is_absolute()
        or profile_id in ("", ".", "..")
        or "/" in profile_id
        or "\\" in profile_id
        or ":" in profile_id
    ):
        raise HTTPException(status_code=400, detail="Invalid profile_id: path traversal detected")
    if not re.match(r"^[a-zA-Z0-9_\-]+$", profile_id):
        raise HTTPException(status_code=400, detail="Invalid profile_id: unsafe characters")
    # Windows resolves these names to devices (NUL, CON, COM1, ...) regardless of
    # the directory, so a profile id of "NUL" or "COM1" would write to a device
    # instead of a file — silently discarding data. "NUL.mp4" is the same device.
    if profile_id.split(".")[0].upper() in _RESERVED_WINDOWS_DEVICE_NAMES:
        raise HTTPException(status_code=400, detail="Invalid profile_id: reserved Windows device name")
    return profile_id


def _mask_raw_proxy_credentials(raw: str) -> str:
    """Mask the password inside a proxy URL, wherever it sits in the userinfo.

    Delegates to the shared masker (:mod:`nazak.core.secret_masking`), which
    also understands the CLI's ``host:port:user:pass`` colon form — the two
    surfaces used to implement masking twice and each had a gap the other
    had closed.
    """
    from ..core.secret_masking import mask_raw_proxy_string

    return mask_raw_proxy_string(raw)


def _mask_proxy_for_api(proxy: ProxyConfig) -> dict:
    """Mask proxy credentials for API payloads (shared implementation)."""
    from ..core.secret_masking import mask_proxy_fields

    return mask_proxy_fields(proxy.model_dump())


def _mask_profile_secrets(profile: BrowserProfile) -> BrowserProfile:
    safe = profile.model_copy(deep=True)
    if safe.proxy:
        safe.proxy = ProxyConfig(**_mask_proxy_for_api(safe.proxy))
    if safe.google and safe.google.notes:
        try:
            notes = json.loads(safe.google.notes)
        except Exception:
            return safe
        masked = decrypt_notes(notes)
        safe.google.notes = json.dumps(masked)
    return safe


def _is_display_mask_value(value) -> bool:
    if not isinstance(value, str):
        return True
    stripped = value.strip()
    return stripped in ("", "***", UNAVAILABLE_PLACEHOLDER) or stripped.startswith("<encrypted")


def _require_launch_url(url: str | None) -> str | None:
    if not url:
        return None
    try:
        return sanitize_launch_url(url)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid launch URL: only http(s) and about: targets are allowed",
        ) from None


_MEDIA_EXTENSIONS = (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mpg", ".mpeg", ".wmv", ".flv")


def resolve_media_source(raw_path: str) -> Path:
    if not raw_path or not str(raw_path).strip():
        raise HTTPException(status_code=400, detail="source_video_path must be a non-empty path")
    src = Path(str(raw_path)).expanduser()
    if not src.exists():
        raise HTTPException(status_code=400, detail=f"Source video not found: {raw_path}")
    if not src.is_file():
        raise HTTPException(status_code=400, detail=f"Source path is not a regular file: {raw_path}")
    if src.suffix.lower() not in _MEDIA_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported media extension {src.suffix!r}: expected one of {', '.join(_MEDIA_EXTENSIONS)}",
        )
    return src


def _remove_quietly(path) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse redirects outright: a rotation URL must not bounce us anywhere."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirects are not followed", headers, fp)


_NO_REDIRECT_HANDLER = _NoRedirectHandler()


def _get_allowed_ports() -> set[int]:
    """Ports trusted by the Origin guard (P0: monkeypatch-compatible).

    Tests do ``monkeypatch.setattr(server, "_ALLOWED_PORTS", ...)``; the guard
    must honour the *server* attribute, not a stale copy captured at import.
    """
    try:
        import nazak.api.server as _srv

        ports = _srv.__dict__.get("_ALLOWED_PORTS")
        if isinstance(ports, set):
            return ports
    except Exception:
        pass
    return _ALLOWED_PORTS


def _resolve_resolver():
    """Patch-compatible resolver lookup (P0).

    Tests patch ``nazak.api.server._resolve_host_ips``; internal callers must
    honour the server attribute instead of the import-time global.
    """
    try:
        import nazak.api.server as _srv

        resolver = _srv.__dict__.get("_resolve_host_ips")
        if callable(resolver):
            return resolver
    except Exception:
        pass
    return _resolve_host_ips


def _resolve_host_ips(hostname: str, port: int) -> list[str]:
    try:
        ipaddress.ip_address(hostname)
        return [hostname]
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError, OSError):
        return []
    return [str(info[4][0]) for info in infos]


_IPV4_EMBEDDING_NETS = (
    ipaddress.ip_network("::/96"),  # IPv4-compatible (deprecated), e.g. ::7f00:1
    ipaddress.ip_network("::ffff:0:0/96"),  # IPv4-mapped
    ipaddress.ip_network("64:ff9b::/96"),  # NAT64 well-known prefix
    ipaddress.ip_network("64:ff9b:1::/48"),  # NAT64 local-use prefix
    ipaddress.ip_network("2002::/16"),  # 6to4
    ipaddress.ip_network("2001::/32"),  # Teredo
)


def _embeds_ipv4(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True for IPv6 forms that carry an IPv4 address inside them."""
    if ip.version != 6:
        return False
    return any(ip in net for net in _IPV4_EMBEDDING_NETS)


def _rotation_target(url: str) -> tuple[str, int, str] | str:
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port
    except ValueError:
        return "malformed URL"
    if parts.scheme not in ("http", "https"):
        return "only http(s) URLs are allowed"
    if not parts.hostname:
        return "URL has no host"
    if port is None:
        port = 443 if parts.scheme == "https" else 80
    addresses = _resolve_resolver()(parts.hostname, port)
    if not addresses:
        return "host cannot be resolved"
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return "host cannot be resolved"
        # is_global alone is not enough: IPv4-embedded IPv6 forms of loopback and
        # link-local (NAT64 64:ff9b::a9fe:a9fe == 169.254.169.254, IPv4-compatible
        # ::7f00:1) are reported as global, so a rotation URL could pin the fetch
        # to cloud metadata or loopback on a NAT64/CLAT host.
        if not ip.is_global or ip.is_reserved or _embeds_ipv4(ip):
            return "host must be a public address"
    return parts.hostname, port, addresses[0]


def _reject_rotation_url(url: str) -> str | None:
    target = _rotation_target(url)
    return target if isinstance(target, str) else None


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host: str, *args, pinned_ip: str, **kwargs):
        self._pinned_ip = pinned_ip
        super().__init__(host, *args, **kwargs)

    def connect(self) -> None:
        self.sock = socket.create_connection((self._pinned_ip, self.port), self.timeout)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, *args, pinned_ip: str, context=None, **kwargs):
        self._pinned_ip = pinned_ip
        self._tls_context = context
        super().__init__(host, *args, context=context, **kwargs)

    def connect(self) -> None:
        import ssl

        raw = socket.create_connection((self._pinned_ip, self.port), self.timeout)
        ctx = self._tls_context or ssl.create_default_context()
        self.sock = ctx.wrap_socket(raw, server_hostname=self.host)


class _PinnedHTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, pinned_ip: str):
        super().__init__()
        self._pinned_ip = pinned_ip

    def http_open(self, req):
        return self.do_open(lambda host, **kw: _PinnedHTTPConnection(host, pinned_ip=self._pinned_ip, **kw), req)


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, pinned_ip: str):
        super().__init__()
        self._pinned_ip = pinned_ip

    def https_open(self, req):
        return self.do_open(lambda host, **kw: _PinnedHTTPSConnection(host, pinned_ip=self._pinned_ip, **kw), req)


def _build_pinned_opener(pinned_ip: str):
    # ProxyHandler({}) disables env/system proxies: the rotation fetch must go
    # straight to the validated IP, never via a middlebox that defeats pinning.
    return urllib.request.build_opener(
        _NoRedirectHandler(),
        urllib.request.ProxyHandler({}),
        _PinnedHTTPHandler(pinned_ip),
        _PinnedHTTPSHandler(pinned_ip),
    )
