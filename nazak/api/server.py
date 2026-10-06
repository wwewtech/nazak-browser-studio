"""
FastAPI Server & WebSocket Real-time Hub for Nazak Browser Studio.
"""

import asyncio
import http.client
import ipaddress
import json
import logging
import math
import os
import re
import socket
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, Body, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from starlette.background import BackgroundTask

from .. import __version__
from ..config import (
    DATA_DIR,
    DEFAULT_AUTOPOST_DESCRIPTION_TEMPLATE,
    DEFAULT_AUTOPOST_TG_CHANNEL,
    DEFAULT_AUTOPOST_TITLE_TEMPLATE,
    DEFAULT_PORT,
    EXTENSIONS_DIR,
    PROFILES_DIR,
    PROFILES_FILE,
    WEB_DIR,
    find_chrome_executable,
)
from ..core.browser_launcher import BrowserLauncher, sanitize_launch_url
from ..core.cookie_manager import (
    cookies_to_netscape,
    create_cookies_zip_archive,
    parse_any_cookies,
    parse_bulk_cookie_input,
)
from ..core.fingerprint_generator import generate_random_fingerprint
from ..core.process_monitor import ProcessMonitor
from ..core.profile_manager import ProfileManager
from ..core.proxy_checker import check_proxy_health
from ..core.secrets_store import (
    SECRETS_MODES,
    UNAVAILABLE_PLACEHOLDER,
    SecretsError,
    decrypt_notes,
    get_current_mode,
    load_mode,
    set_current_mode,
    set_mode_file,
)
from ..core.spintax import format_video_metadata
from ..core.synchronizer import SynchronizerManager
from ..core.upload_queue import UploadQueueManager, normalize_upload_platform
from ..core.video_uniquifier import VideoUniquifier
from ..core.warmup_engine import (
    BUILTIN_SCENARIOS,
    ScenarioExecutor,
    WarmupPlan,
    WarmupScenario,
    generate_warmup_urls,
)
from ..models.health import HealthCheckResult
from ..models.profile import BrowserProfile, FingerprintConfig, GoogleSettings, ProfileStatus
from ..models.proxy import ProxyConfig

logger = logging.getLogger(__name__)


# Active WebSocket connections
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, event_type: str, data: Any):
        payload = json.dumps({"event": event_type, "data": data})
        for connection in list(self.active_connections):
            try:
                await connection.send_text(payload)
            except Exception as exc:
                logger.debug("WS send failed, dropping connection: %s", exc)
                self.disconnect(connection)


ws_manager = ConnectionManager()

# Bootstrap user-selected secrets mode (plain by default; persisted choice
# survives restarts, the passphrase itself is never written to disk).
set_mode_file(DATA_DIR / "secrets_mode.json")
load_mode()

# Initialize Core Services
profile_manager = ProfileManager(PROFILES_FILE, PROFILES_DIR)
browser_launcher = BrowserLauncher(PROFILES_DIR, EXTENSIONS_DIR)
upload_queue_mgr = UploadQueueManager(profile_manager, browser_launcher, ws_manager.broadcast)
video_uniquifier = VideoUniquifier()
process_monitor = ProcessMonitor(profile_manager, browser_launcher, poll_interval=1.0)
synchronizer_mgr = SynchronizerManager(browser_launcher)
# Audit fix P0-2: route injector binding events (master gestures) into the mirror pump.
browser_launcher.set_event_sink(synchronizer_mgr.submit_event)
scenario_executor = ScenarioExecutor(browser_launcher, profile_manager)


_server_loop: asyncio.AbstractEventLoop | None = None


def on_process_state_change(profile_id: str, status: ProfileStatus):
    global _server_loop
    payload = {"profile_id": profile_id, "status": status.value}
    if _server_loop and _server_loop.is_running():
        try:
            asyncio.run_coroutine_threadsafe(
                ws_manager.broadcast("profile_status_change", payload),
                _server_loop,
            )
            return
        except Exception as exc:
            logger.debug("process-state broadcast failed: %s", exc)
            pass
    try:
        asyncio.get_running_loop()
        asyncio.create_task(ws_manager.broadcast("profile_status_change", payload))
    except RuntimeError:
        logger.debug("no running loop for profile_status_change %s", payload)


process_monitor.register_callback(on_process_state_change)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _server_loop
    _server_loop = asyncio.get_running_loop()
    app.state.loop = _server_loop
    process_monitor.start()
    yield
    process_monitor.stop()


tags_metadata = [
    {
        "name": "Dolphin Automation (v1.0 Parity)",
        "description": "Dolphin{anty}-style REST endpoints for external automation scripts (Playwright, Puppeteer, Selenium). Implements a compatible subset of the Dolphin {anty} v1.0 local API (start/stop/status); full feature parity is not claimed.",
    },
    {
        "name": "Profiles",
        "description": "Anti-detect profile management, hardware fingerprint isolation, mass profile generator, and .nazak portable bundles.",
    },
    {
        "name": "Automation & CDP",
        "description": "Native Chrome DevTools Protocol port allocation, start/stop lifecycle, and active browser queries.",
    },
    {
        "name": "Cookies",
        "description": "Multi-profile bulk cookie import (text blocks, JSON maps, directory scan, ZIP), Netscape format parser, and ZIP archive exporter.",
    },
    {
        "name": "Synchronizer",
        "description": "Real-time action synchronizer (Master to Workers replication with Bezier jitter) and Win32 window tiling grid.",
    },
    {
        "name": "Scenarios & Warmup",
        "description": "Multi-step scenario constructor (E-Commerce, YouTube, Crypto, Banking) and parallel warmup executor.",
    },
    {
        "name": "Proxies",
        "description": "4-stage proxy health diagnostics (Latency, Geolocation, Google Suite, storage/Data Isolation) and mobile IP rotation triggers.",
    },
    {
        "name": "YouTube Shorts Autoposter",
        "description": "Autonomous YouTube Shorts and Instagram Reels upload queue with FFmpeg video uniqueizer and Bezier human motorics.",
    },
    {
        "name": "System",
        "description": "Host diagnostics, Chrome discovery, WebSocket telemetry, and platform information.",
    },
]

app = FastAPI(
    title="Nazak Browser Studio API",
    description="Professional Multi-Profile Anti-Detect Browser Launcher with Strict Proxy & Google Automation Isolation",
    version=__version__,
    openapi_tags=tags_metadata,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)


@app.get("/swagger", include_in_schema=False)
async def redirect_to_swagger_docs():
    return RedirectResponse(url="/docs")


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8899",
        "http://localhost:8899",
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    ],
    # Exact localhost ports only (audit D2-P1-1): a regex that accepted *any*
    # port let every local dev server / Electron app drive the API with cookies.
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1):(8899|3000)$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Local-only request guard (audit D2-P1-1)
# ---------------------------------------------------------------------------
# The API is deliberately unauthenticated for local scripts (documented in
# docs/API_REFERENCE.md), so the trust boundary is "requests that originate
# from this machine's own pages". Cross-site pages are rejected by Origin, and
# DNS-rebinding style access is rejected by the Host check.

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
# Starlette TestClient присылает Host: testserver. Держим его в списке только
# когда это явно разрешено (conftest выставляет NAZAK_ALLOW_TEST_HOST), чтобы в
# проде «testserver» не считался локальным хостом (audit R3).
if os.environ.get("NAZAK_ALLOW_TEST_HOST", "").strip().lower() in ("1", "true", "yes", "y"):
    _LOCAL_HOSTS.add("testserver")
_ALLOWED_PORTS: set[int] = {DEFAULT_PORT, 3000}
_LOCAL_SCHEMES = ("http", "https")
# Opt-in shared secret for setups that expose the port beyond loopback:
# set NAZAK_API_TOKEN and send it as `X-API-Key` on /api and /v1.0 calls.
_API_TOKEN_ENV = "NAZAK_API_TOKEN"

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def api_token_configured() -> bool:
    return bool((os.environ.get(_API_TOKEN_ENV) or "").strip())


def enforce_exposure_policy(host: str) -> None:
    """Не даём выставить неаутентифицированный API наружу (audit R3).

    Локальный solo-сценарий (127.0.0.1) не меняется вообще: токен не нужен.
    Но если сервер биндится не на loopback (сервер/докер/0.0.0.0), без
    NAZAK_API_TOKEN он больше не поднимется — иначе Host-заголовок `127.0.0.1`
    от любого клиента делает весь guard бессмысленным.
    """
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
    return port in _ALLOWED_PORTS


def _is_api_token_valid(request_headers) -> bool:
    expected = os.environ.get(_API_TOKEN_ENV)
    if not expected:
        return True
    import hmac

    return hmac.compare_digest(str(request_headers.get("x-api-key") or ""), str(expected))


# Audit R3-round2: security-заголовки. Дашборд может запускать браузеры и
# выгружать cookies, поэтому любой инжектированный в него разметкой скрипт
# опасен. script-src вынужденно содержит 'unsafe-inline': UI построен на 58
# inline-обработчиках (см. docs/AUDIT_ROUND3_FINDINGS.md), но даже такой CSP
# запрещает внешние скрипты, object/embed, смену base URI и встраивание в
# iframe, а nosniff/no-referrer закрывают MIME-сниффинг и утечку Referer.
# Полный отказ от 'unsafe-inline' требует перевода обработчиков на
# addEventListener (отдельная задача).
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "geolocation=(), camera=(), microphone=(), usb=(), serial=()",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; "
        "font-src 'self'; "
        "connect-src 'self' ws: wss:; "
        "object-src 'none'; "
        "base-uri 'none'; "
        "form-action 'self'; "
        "frame-ancestors 'none'"
    ),
}
# Ответы API не должны оседать в дисковом кэше браузера (экспорт cookies и т.п.).
_NO_STORE_PREFIXES = ("/api", "/v1.0")


def _apply_security_headers(response, path: str):
    for header, value in SECURITY_HEADERS.items():
        response.headers.setdefault(header, value)
    if path.startswith(_NO_STORE_PREFIXES):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.middleware("http")
async def local_only_guard(request, call_next):
    path = request.url.path
    # Статика нужна локальному дашборду; /docs и /openapi.json больше НЕ
    # исключаются из Host-проверки (audit R3: схема API отдавалась любому Host).
    if path.startswith("/static"):
        return _apply_security_headers(await call_next(request), path)

    if not _is_local_host(request.headers.get("host")):
        return _apply_security_headers(
            JSONResponse(
                status_code=403,
                content={"detail": "Local access only: Host header must be localhost or 127.0.0.1"},
            ),
            path,
        )
    origin = request.headers.get("origin")
    if origin and not _is_local_origin(origin):
        return _apply_security_headers(
            JSONResponse(
                status_code=403,
                content={"detail": "Local access only: cross-origin requests are refused"},
            ),
            path,
        )
    # CSRF-щит для запросов без Origin: современные браузеры помечают чужие
    # подгрузки (img/script) как cross-site (audit R3).
    sec_fetch_site = (request.headers.get("sec-fetch-site") or "").strip().lower()
    if sec_fetch_site == "cross-site":
        return _apply_security_headers(
            JSONResponse(
                status_code=403,
                content={"detail": "Local access only: cross-site requests are refused"},
            ),
            path,
        )
    if path.startswith(("/api", "/v1.0")) and not _is_api_token_valid(request.headers):
        return _apply_security_headers(
            JSONResponse(status_code=401, content={"detail": "Missing or invalid X-API-Key"}), path
        )
    return _apply_security_headers(await call_next(request), path)


def _json_safe_error_payload(value: Any, _depth: int = 0) -> Any:
    """Приводит значение из ошибки валидации к тому, что умеет json.dumps.

    Audit R3-round2: pydantic v2 кладёт в ошибку исходный `input`. Если клиент
    прислал `Infinity`/`NaN` (json.loads их принимает) или строку на 5 МБ,
    стандартный ответ 422 падал на сериализации -> 500 и мусор в логе.
    """
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


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request, exc: RequestValidationError):
    """422 с безопасным телом (без inf/nan и без эха многомегабайтного ввода)."""
    errors = []
    for error in exc.errors():
        safe = {k: v for k, v in error.items() if k not in ("input", "ctx", "url")}
        if "input" in error:
            safe["input"] = _json_safe_error_payload(error["input"])
        if "ctx" in error:
            safe["ctx"] = _json_safe_error_payload(error["ctx"])
        errors.append(safe)
    return JSONResponse(status_code=422, content={"detail": errors})


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
    return profile_id


def _mask_proxy_for_api(proxy: ProxyConfig) -> dict:
    """Proxy dict for API responses with every credential-bearing key masked.

    Audit D2-P0-3: masking only ``password`` still leaked the same credential
    through ``raw`` (``user:pass@host``) and ``rotation_url`` (``?key=...``).
    ``"***"`` communicates "set but hidden"; the write path recognises it and
    keeps the stored value instead of persisting the mask.
    """
    data = proxy.model_dump()
    if data.get("password"):
        data["password"] = "***"
    raw = data.get("raw")
    password = proxy.password
    if isinstance(raw, str) and raw:
        if password and password in raw:
            data["raw"] = raw.replace(password, "***", 1)
        elif "@" in raw:
            data["raw"] = re.sub(r":[^:@/]*@", ":***@", raw, count=1)
    if data.get("rotation_url"):
        data["rotation_url"] = "***"
    return data


def _mask_profile_secrets(profile: BrowserProfile) -> BrowserProfile:
    """Mask sensitive notes *and* proxy credentials for API responses.

    Works on a deep copy: profile_manager returns live references, and
    masked values must never leak back into persisted storage (the write path
    additionally refuses to persist a mask — audit D2-P0-2).
    """
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


class SecretsModeRequest(BaseModel):
    """User-selected secrets storage mode. The choice is always the user's."""

    mode: str
    passphrase: str | None = None


@app.get(
    "/api/security/secrets-mode",
    tags=["System"],
    summary="Get the active secrets storage mode (plain / dpapi / passphrase)",
)
async def get_secrets_mode():
    return {
        "mode": get_current_mode(),
        "available_modes": list(SECRETS_MODES),
        "platform": os.name,
        "notes": (
            "The user selects the mode. 'plain' stores secrets readable; "
            "'dpapi' (Windows-only) encrypts per Windows user; 'passphrase' "
            "encrypts with the user's own passphrase (lost passphrase = lost data). "
            "The passphrase is never persisted."
        ),
    }


@app.post(
    "/api/security/secrets-mode",
    tags=["System"],
    summary="Switch the secrets storage mode (user decision)",
)
async def post_secrets_mode(req: SecretsModeRequest):
    try:
        effective = set_current_mode(req.mode, passphrase=req.passphrase)
    except SecretsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await ws_manager.broadcast("secrets_mode_changed", {"mode": effective})
    return {
        "success": True,
        "mode": effective,
        "message": (
            f"Secrets mode switched to '{effective}'. New imports will use it. Existing envelopes stay decodable."
        ),
    }


# Schemas for requests
#
# Audit R3-round2: ни одна из моделей не имела границ, поэтому один запрос мог
# повесить сервер (mass-generate на десятки тысяч профилей, пауза в батче на
# годы, отрицательная задержка синхронизатора, нулевой/огромный cols). Границы
# заданы здесь и продублированы клампами в сервисном слое.
_MAX_PROFILE_IDS = 500
_MAX_TEXT = 20_000
_MAX_MEDIA_PATH = 4096


class LaunchRequest(BaseModel):
    custom_url: str | None = Field(default=None, max_length=2048)
    cdp_port: int | None = Field(default=None, ge=1, le=65535)


class ProxyTestRequest(BaseModel):
    raw_proxy: str = Field(max_length=2048)


class BulkImportRequest(BaseModel):
    proxy_lines: str = Field(max_length=1_000_000)
    group: str = Field(default="Google Ads", max_length=120)
    target_page: str = Field(default="google_login", max_length=64)


class MassGenerateRequest(BaseModel):
    # CLI использует тот же диапазон 1..200 (cli_cmds/profiles.py: cmd_mass_generate)
    count: int = Field(default=10, ge=1, le=200)
    group: str = Field(default="Mass Generated", max_length=120)
    proxy_lines: str | None = Field(default=None, max_length=1_000_000)
    os_mix: str = Field(default="windows", max_length=16)
    tags: list[str] | None = Field(default=None, max_length=50)
    target_page: str = Field(default="google_login", max_length=64)
    notes: str | None = Field(default=None, max_length=4000)


class BatchActionRequest(BaseModel):
    # Верхняя граница — защита от заваливания сервера списком; нижнюю проверяет
    # сам эндпоинт и отвечает 400 (контракт не меняем).
    profile_ids: list[str] = Field(max_length=_MAX_PROFILE_IDS)


class AutopostBatchRequest(BaseModel):
    profile_ids: list[str] = Field(max_length=_MAX_PROFILE_IDS)
    source_video_path: str | None = Field(default=None, max_length=_MAX_MEDIA_PATH)
    platform: str = Field(default="youtube_shorts", max_length=32)
    title_template: str = Field(default=DEFAULT_AUTOPOST_TITLE_TEMPLATE, max_length=500)
    description_template: str = Field(default=DEFAULT_AUTOPOST_DESCRIPTION_TEMPLATE, max_length=5000)
    tg_channel: str = Field(default=DEFAULT_AUTOPOST_TG_CHANNEL, max_length=120)
    # Верхняя граница = 1 час: больше не бывает осмысленной паузой, а раньше
    # значение вроде 10**9 усыпляло батч на годы, блокируя очередь (is_running).
    delay_seconds: int = Field(default=10, ge=0, le=3600)
    # Audit fix P0-4: demo clips are generated ONLY on explicit request — the
    # old code silently wrote a fake "DEMO_MP4_HEADER" blob and uploaded it.
    demo: bool = False


class UniquifyRequest(BaseModel):
    source_video_path: str = Field(max_length=_MAX_MEDIA_PATH)
    profile_ids: list[str] = Field(max_length=_MAX_PROFILE_IDS)


class CookieImportRequest(BaseModel):
    cookies_data: str = Field(max_length=5_000_000)


class BulkCookieImportRequest(BaseModel):
    cookies_data: str = Field(max_length=5_000_000)
    auto_create_missing: bool = True
    group: str = Field(default="Imported Cookies", max_length=120)


class BulkCookieExportRequest(BaseModel):
    profile_ids: list[str] | None = Field(default=None, max_length=_MAX_PROFILE_IDS)
    format: str = Field(default="json", pattern="^(json|netscape|zip)$")


class WarmupRequest(BaseModel):
    niche: str = Field(default="ecommerce", max_length=64)
    steps_count: int = Field(default=5, ge=1, le=20)


class ScenarioRunRequest(BaseModel):
    scenario_id: str | None = Field(default=None, max_length=128)
    scenario_data: dict[str, Any] | None = None
    profile_ids: list[str] = Field(max_length=_MAX_PROFILE_IDS)
    max_concurrency: int = Field(default=3, ge=1, le=10)


class SynchronizerStartRequest(BaseModel):
    master_profile_id: str = Field(max_length=64)
    worker_profile_ids: list[str] = Field(max_length=_MAX_PROFILE_IDS)
    humanize_jitter: bool = True
    # 0..60 c на событие: отрицательное значение раньше убивало поток-насос
    # (time.sleep с отрицательным аргументом -> ValueError вне try).
    min_delay_ms: int = Field(default=20, ge=0, le=60_000)
    max_delay_ms: int = Field(default=80, ge=0, le=60_000)
    coordinate_jitter_px: int = Field(default=2, ge=0, le=50)


class SynchronizerNavigateRequest(BaseModel):
    url: str = Field(max_length=2048)

    @field_validator("url")
    @classmethod
    def _validate_url(cls, value: str) -> str:
        """Только http(s): file://, data: и javascript: в воркеры не уходят.

        Audit R3-round2: раньше URL доходил до page.goto() как есть (в warmup и
        launch такая же проверка уже была).
        """
        from ..core.browser_launcher import sanitize_launch_url

        sanitized = sanitize_launch_url(value)
        if not sanitized:
            raise ValueError("URL is empty")
        return sanitized


class WindowTileRequest(BaseModel):
    cols: int | None = Field(default=None, ge=1, le=8)


# API Routes
@app.get("/api/system/info", tags=["System"], summary="Get system diagnostics and host telemetry")
async def get_system_info():
    chrome_exe = find_chrome_executable()
    profiles = profile_manager.list_profiles()
    running_count = sum(1 for p in profiles if browser_launcher.is_profile_running(p.id))
    return {
        "status": "online",
        "chrome_installed": bool(chrome_exe),
        "chrome_executable": chrome_exe,
        "total_profiles": len(profiles),
        "running_profiles": running_count,
        "data_directory": str(PROFILES_DIR.resolve()),
        "platform": os.name,
    }


@app.get(
    "/api/profiles",
    response_model=list[BrowserProfile],
    tags=["Profiles"],
    summary="List all browser profiles with live statuses",
)
async def list_profiles():
    profiles = profile_manager.list_profiles()
    result = []
    for p in profiles:
        if browser_launcher.is_profile_running(p.id):
            p.status = ProfileStatus.RUNNING
            p.pid = browser_launcher.profile_pids.get(p.id)
        else:
            p.status = ProfileStatus.STOPPED
            p.pid = None
        result.append(_mask_profile_secrets(p))
    return result


@app.get(
    "/api/profiles/{profile_id}", response_model=BrowserProfile, tags=["Profiles"], summary="Get single profile details"
)
async def get_profile(profile_id: str):
    validate_pid(profile_id)
    profile = profile_manager.get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    if browser_launcher.is_profile_running(profile.id):
        profile.status = ProfileStatus.RUNNING
        profile.pid = browser_launcher.profile_pids.get(profile.id)
    return _mask_profile_secrets(profile)


@app.post("/api/profiles", response_model=BrowserProfile, tags=["Profiles"], summary="Create new isolated profile")
async def create_profile(profile_data: BrowserProfile):
    if profile_data.id:
        validate_pid(profile_data.id)
        if profile_manager.get_profile(profile_data.id):
            raise HTTPException(status_code=409, detail=f"Profile with id '{profile_data.id}' already exists")
    # Audit D2-P2-1: clients that omit the WebGL fields (the old web modal
    # hard-coded one GPU for every profile) would all land on the same
    # stock GPU string. Fill whatever was not sent from a fresh generator.
    fp = profile_data.fingerprint
    if fp is not None and "webgl_renderer" not in fp.model_fields_set:
        ref = generate_random_fingerprint().model_copy()
        for field in ("webgl_vendor", "webgl_renderer", "webgl_unmasked_vendor", "webgl_unmasked_renderer"):
            setattr(fp, field, getattr(ref, field))
    created = profile_manager.create_profile(profile_data)
    await ws_manager.broadcast("profile_created", _mask_profile_secrets(created).model_dump())
    return _mask_profile_secrets(created)


@app.put(
    "/api/profiles/{profile_id}", response_model=BrowserProfile, tags=["Profiles"], summary="Update profile settings"
)
async def update_profile(profile_id: str, profile_data: BrowserProfile):
    validate_pid(profile_id)
    profile_data.id = profile_id
    updated = profile_manager.update_profile(profile_data)
    if not updated:
        raise HTTPException(status_code=404, detail="Profile not found")
    await ws_manager.broadcast("profile_updated", _mask_profile_secrets(updated).model_dump())
    return _mask_profile_secrets(updated)


@app.delete("/api/profiles/{profile_id}", tags=["Profiles"], summary="Delete profile and local storage data")
async def delete_profile(profile_id: str):
    validate_pid(profile_id)
    if browser_launcher.is_profile_running(profile_id):
        browser_launcher.stop(profile_id)
    deleted = profile_manager.delete_profile(profile_id, delete_data=True)
    if not deleted:
        raise HTTPException(status_code=404, detail="Profile not found")
    await ws_manager.broadcast("profile_deleted", {"profile_id": profile_id})
    return {"success": True, "message": "Profile deleted successfully"}


@app.post(
    "/api/profiles/{profile_id}/clone",
    response_model=BrowserProfile,
    tags=["Profiles"],
    summary="Clone profile with randomized hardware fingerprint",
)
async def clone_profile(profile_id: str, new_name: str | None = Query(None)):
    validate_pid(profile_id)
    cloned = profile_manager.clone_profile(profile_id, new_name)
    if not cloned:
        raise HTTPException(status_code=404, detail="Source profile not found")
    await ws_manager.broadcast("profile_created", _mask_profile_secrets(cloned).model_dump())
    return _mask_profile_secrets(cloned)


@app.post("/api/profiles/{profile_id}/launch", tags=["Profiles"], summary="Launch browser profile")
async def launch_profile(profile_id: str, req: LaunchRequest | None = None):
    validate_pid(profile_id)
    profile = profile_manager.get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    custom_url = req.custom_url if req else None
    cdp_port = req.cdp_port if req else None
    custom_url = _require_launch_url(custom_url)

    if cdp_port:
        success, pid, port, ws_url, err = browser_launcher.launch_with_cdp(
            profile, custom_url=custom_url, port=cdp_port
        )
    else:
        success, pid, err = browser_launcher.launch(profile, custom_url=custom_url)
        port, ws_url = None, None

    if not success:
        profile.status = ProfileStatus.ERROR
        profile_manager.update_profile(profile)
        await ws_manager.broadcast("profile_status_change", {"profile_id": profile_id, "status": "error", "error": err})
        raise HTTPException(status_code=400, detail=err or "Failed to launch browser")

    profile.status = ProfileStatus.RUNNING
    profile.pid = pid
    profile_manager.update_profile(profile)
    await ws_manager.broadcast("profile_status_change", {"profile_id": profile_id, "status": "running", "pid": pid})
    res = {"success": True, "pid": pid, "profile_id": profile_id}
    if port:
        res["port"] = port
        res["wsEndpoint"] = ws_url
    return res


@app.post("/api/profiles/{profile_id}/stop", tags=["Profiles"], summary="Stop running browser profile")
async def stop_profile(profile_id: str):
    validate_pid(profile_id)
    profile = profile_manager.get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    browser_launcher.stop(profile_id)
    profile.status = ProfileStatus.STOPPED
    profile.pid = None
    profile_manager.update_profile(profile)
    await ws_manager.broadcast("profile_status_change", {"profile_id": profile_id, "status": "stopped"})
    return {"success": True, "profile_id": profile_id}


# ----------------------------------------------------
# Dolphin{anty} Local Automation API v1.0 Parity
# ----------------------------------------------------
@app.get(
    "/v1.0/browser_profiles", tags=["Dolphin Automation (v1.0 Parity)"], summary="Dolphin v1.0 - List all profiles"
)
async def dolphin_list_profiles():
    profiles = profile_manager.list_profiles()
    data = []
    for p in profiles:
        is_run = browser_launcher.is_profile_running(p.id)
        cdp_info = browser_launcher.get_cdp_info(p.id) if is_run else None
        data.append(
            {
                "id": p.id,
                "name": p.name,
                "status": "running" if is_run else "stopped",
                "proxy": _mask_proxy_for_api(p.proxy),
                "automation": cdp_info,
                "tags": p.google.tags,
            }
        )
    return {"success": True, "data": data}


@app.get(
    "/v1.0/browser_profiles/{profile_id}/start",
    tags=["Dolphin Automation (v1.0 Parity)", "Automation & CDP"],
    summary="Dolphin v1.0 - Start profile and get CDP WebSocket URL",
)
@app.post(
    "/api/v1/profiles/{profile_id}/start",
    tags=["Automation & CDP"],
    summary="Nazak v1 - Start profile with CDP automation",
)
async def dolphin_start_profile(profile_id: str, custom_url: str | None = Query(None), port: int | None = Query(None)):
    validate_pid(profile_id)
    custom_url = _require_launch_url(custom_url)
    profile = profile_manager.get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    ok, pid, cdp_port, ws_endpoint, err = browser_launcher.launch_with_cdp(profile, custom_url=custom_url, port=port)
    if not ok:
        profile.status = ProfileStatus.ERROR
        profile_manager.update_profile(profile)
        raise HTTPException(status_code=400, detail=err or "Failed to start profile with automation")

    profile.status = ProfileStatus.RUNNING
    profile.pid = pid
    profile_manager.update_profile(profile)
    await ws_manager.broadcast("profile_status_change", {"profile_id": profile_id, "status": "running", "pid": pid})
    return {
        "success": True,
        "automation": {"port": cdp_port, "wsEndpoint": ws_endpoint},
        "pid": pid,
        "profile_id": profile_id,
    }


@app.get(
    "/v1.0/browser_profiles/{profile_id}/stop",
    tags=["Dolphin Automation (v1.0 Parity)", "Automation & CDP"],
    summary="Dolphin v1.0 - Stop running profile",
)
@app.post("/api/v1/profiles/{profile_id}/stop", tags=["Automation & CDP"], summary="Nazak v1 - Stop running profile")
async def dolphin_stop_profile(profile_id: str):
    validate_pid(profile_id)
    profile = profile_manager.get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    browser_launcher.stop(profile_id)
    profile.status = ProfileStatus.STOPPED
    profile.pid = None
    profile_manager.update_profile(profile)
    await ws_manager.broadcast("profile_status_change", {"profile_id": profile_id, "status": "stopped"})
    return {"success": True, "profile_id": profile_id}


@app.get(
    "/v1.0/browser_profiles/active",
    tags=["Dolphin Automation (v1.0 Parity)", "Automation & CDP"],
    summary="Dolphin v1.0 - List all active browser profiles with CDP endpoints",
)
async def dolphin_active_profiles():
    profiles = profile_manager.list_profiles()
    active = []
    for p in profiles:
        if browser_launcher.is_profile_running(p.id):
            cdp_info = browser_launcher.get_cdp_info(p.id)
            active.append(
                {
                    "profile_id": p.id,
                    "name": p.name,
                    "pid": browser_launcher.profile_pids.get(p.id),
                    "automation": cdp_info,
                }
            )
    return {"success": True, "active_count": len(active), "profiles": active}


@app.get(
    "/api/v1/profiles/{profile_id}/cdp",
    tags=["Automation & CDP"],
    summary="Query active CDP port and WebSocket URL for profile",
)
async def get_profile_cdp(profile_id: str):
    validate_pid(profile_id)
    cdp_info = browser_launcher.get_cdp_info(profile_id)
    if not cdp_info:
        raise HTTPException(status_code=400, detail="Profile is not running or CDP is not active")
    return {"success": True, "cdp": cdp_info}


@app.post("/api/profiles/batch-launch", tags=["Profiles"], summary="Launch multiple profiles simultaneously")
async def batch_launch(req: BatchActionRequest):
    results: dict[str, Any] = {}
    any_changed = False
    for pid in req.profile_ids:
        try:
            validate_pid(pid)
        except HTTPException:
            results[pid] = {"success": False, "error": f"Invalid profile ID: {pid}"}
            continue
        prof = profile_manager.get_profile(pid)
        if prof:
            ok, p_id, err = browser_launcher.launch(prof)
            if ok:
                prof.status = ProfileStatus.RUNNING
                prof.pid = p_id
                prof.updated_at = datetime.now(timezone.utc).isoformat()
                profile_manager.profiles[pid] = prof
                any_changed = True
                results[pid] = {"success": True, "pid": p_id}
            else:
                prof.status = ProfileStatus.ERROR
                prof.pid = None
                prof.updated_at = datetime.now(timezone.utc).isoformat()
                profile_manager.profiles[pid] = prof
                any_changed = True
                results[pid] = {"success": False, "error": err}
    if any_changed:
        profile_manager.save_profiles()
    return results


@app.post("/api/profiles/batch-stop", tags=["Profiles"], summary="Stop multiple running profiles simultaneously")
async def batch_stop(req: BatchActionRequest):
    any_changed = False
    for pid in req.profile_ids:
        try:
            validate_pid(pid)
        except HTTPException:
            continue
        browser_launcher.stop(pid)
        prof = profile_manager.get_profile(pid)
        if prof:
            prof.status = ProfileStatus.STOPPED
            prof.pid = None
            prof.updated_at = datetime.now(timezone.utc).isoformat()
            profile_manager.profiles[pid] = prof
            any_changed = True
    if any_changed:
        profile_manager.save_profiles()
    return {"success": True, "stopped_count": len(req.profile_ids)}


@app.post(
    "/api/profiles/{profile_id}/check",
    response_model=HealthCheckResult,
    tags=["Proxies"],
    summary="Perform 5-stage health check for profile proxy",
)
async def check_profile_proxy(profile_id: str):
    validate_pid(profile_id)
    profile = profile_manager.get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    user_data_path = PROFILES_DIR / profile.id
    result = await check_proxy_health(profile.proxy, profile_dir=user_data_path)
    profile.last_health_check = result

    # Auto-align fingerprint geolocation and timezone with real proxy exit node
    if result.latitude is not None and result.longitude is not None:
        profile.fingerprint.geolocation.latitude = result.latitude
        profile.fingerprint.geolocation.longitude = result.longitude
    if result.timezone_name:
        profile.fingerprint.timezone = result.timezone_name

    profile_manager.update_profile(profile)

    await ws_manager.broadcast("profile_health_update", {"profile_id": profile_id, "health": result.model_dump()})
    return result


@app.post("/api/profiles/check-all", tags=["Proxies"], summary="Run proxy health checks across all profiles")
async def check_all_profiles():
    profiles = profile_manager.list_profiles()

    async def _check(p: BrowserProfile):
        res = await check_proxy_health(p.proxy, profile_dir=PROFILES_DIR / p.id)
        p.last_health_check = res
        p.updated_at = datetime.now(timezone.utc).isoformat()
        profile_manager.profiles[p.id] = p
        await ws_manager.broadcast("profile_health_update", {"profile_id": p.id, "health": res.model_dump()})
        return p.id, res

    await asyncio.gather(*[_check(p) for p in profiles], return_exceptions=True)
    profile_manager.save_profiles()
    return {"total_checked": len(profiles)}


@app.post("/api/profiles/{profile_id}/clear-cache", tags=["Profiles"], summary="Purge browser cache for profile")
async def clear_cache(profile_id: str):
    validate_pid(profile_id)
    if browser_launcher.is_profile_running(profile_id):
        raise HTTPException(
            status_code=400, detail="Cannot clear cache while browser is running. Please stop it first."
        )
    ok = profile_manager.clear_profile_cache(profile_id)
    return {"success": ok, "message": "Cache cleared successfully"}


@app.post(
    "/api/profiles/{profile_id}/seed-history",
    tags=["Profiles"],
    summary="Seed authentic Chromium browsing history records into profile",
)
async def seed_profile_history_endpoint(profile_id: str, entries_count: int = Query(25, ge=5, le=100)):
    validate_pid(profile_id)
    prof = profile_manager.get_profile(profile_id)
    if not prof:
        raise HTTPException(status_code=404, detail="Profile not found")
    inserted = profile_manager.seed_profile_history(profile_id, entries_count=entries_count)
    return {"success": True, "profile_id": profile_id, "seeded_entries": inserted}


@app.post(
    "/api/profiles/randomize-fingerprint",
    response_model=FingerprintConfig,
    tags=["Profiles"],
    summary="Generate random isolated hardware fingerprint",
)
async def randomize_fingerprint(os_type: str = Query("windows")):
    return generate_random_fingerprint(os_type=os_type)


@app.post("/api/profiles/bulk-import", tags=["Profiles"], summary="Bulk import profiles from proxy strings")
async def bulk_import_profiles(req: BulkImportRequest):
    lines = [line.strip() for line in req.proxy_lines.splitlines() if line.strip()]
    if not lines:
        raise HTTPException(status_code=400, detail="No valid proxy lines provided")
    created_list = []

    for idx, line in enumerate(lines, start=len(profile_manager.list_profiles()) + 1):
        proxy_conf = ProxyConfig.parse(line)
        fp = generate_random_fingerprint(os_type="windows")
        google_set = GoogleSettings(auto_open_page=req.target_page, tags=["Bulk Import", req.group])
        prof = BrowserProfile(
            name=f"Profile {idx:02d} ({proxy_conf.host or 'Direct'})",
            group=req.group,
            proxy=proxy_conf,
            fingerprint=fp,
            google=google_set,
        )
        saved = profile_manager.create_profile(prof)
        created_list.append(saved)

    await ws_manager.broadcast("profiles_bulk_created", {"count": len(created_list)})
    return {"created_count": len(created_list)}


@app.post("/api/profiles/mass-generate", tags=["Profiles"], summary="1-Click mass profile generator (1-100+ farm)")
async def mass_generate_profiles_endpoint(req: MassGenerateRequest):
    proxy_list = [p.strip() for p in req.proxy_lines.splitlines() if p.strip()] if req.proxy_lines else None
    created = profile_manager.mass_generate_profiles(
        count=req.count,
        group=req.group,
        proxy_list=proxy_list,
        os_mix=req.os_mix,
        tags=req.tags,
        auto_open_page=req.target_page,
        notes=req.notes,
    )
    await ws_manager.broadcast("profiles_bulk_created", {"count": len(created)})
    masked = []
    for p in created:
        item = _mask_profile_secrets(p).model_dump()
        item["proxy"] = _mask_proxy_for_api(p.proxy)
        masked.append(item)
    return {"success": True, "created_count": len(created), "profiles": masked}


@app.get(
    "/api/profiles/{profile_id}/bundle/export",
    tags=["Profiles"],
    summary="Export complete profile as portable .nazak archive",
)
async def export_profile_bundle_endpoint(profile_id: str):
    validate_pid(profile_id)
    prof = profile_manager.get_profile(profile_id)
    if not prof:
        raise HTTPException(status_code=404, detail="Profile not found")
    # Audit D2-P1-5: bundles used to accumulate in profiles/ forever (cookies,
    # session files and proxy data copied in the clear). Build it in a temp
    # file and remove it once the response has been sent.
    fd, tmp_name = tempfile.mkstemp(prefix=f"{profile_id}_", suffix=".nazak")
    os.close(fd)
    bundle_path = profile_manager.export_profile_bundle(profile_id, output_path=Path(tmp_name))
    if not bundle_path or not bundle_path.exists():
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise HTTPException(status_code=500, detail="Failed to create profile bundle")
    return FileResponse(
        path=str(bundle_path),
        filename=f"{profile_id}_bundle.nazak",
        media_type="application/zip",
        background=BackgroundTask(_remove_quietly, bundle_path),
    )


def _remove_quietly(path) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def _is_display_mask_value(value) -> bool:
    """True when a rotation URL field only echoes a mask, not a real target."""
    if not isinstance(value, str):
        return True
    stripped = value.strip()
    return stripped in ("", "***", UNAVAILABLE_PLACEHOLDER) or stripped.startswith("<encrypted")


def _require_launch_url(url: str | None) -> str | None:
    """HTTP-facing wrapper for :func:`sanitize_launch_url` (audit D2-P1-3)."""
    if not url:
        return None
    try:
        return sanitize_launch_url(url)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid launch URL: only http(s) and about: targets are allowed",
        ) from None


# Расширения, которые вообще имеет смысл отдавать ffmpeg'у (audit R3): эндпоинт
# принимает путь из запроса, поэтому это ещё и фильтр «не даём скормить
# уникализатору произвольный файл системы».
_MEDIA_EXTENSIONS = (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mpg", ".mpeg", ".wmv", ".flv")


def resolve_media_source(raw_path: str) -> Path:
    """Проверяет source_video_path до передачи в ffmpeg (audit R3)."""
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


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse redirects outright: a rotation URL must not bounce us anywhere."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirects are not followed", headers, fp)


_NO_REDIRECT_HANDLER = _NoRedirectHandler()


def _resolve_host_ips(hostname: str, port: int) -> list[str]:
    """DNS lookup seam (patched in tests) — returns every address for the host.

    IP literals skip DNS entirely, so a numeric loopback/private address can
    never be argued away by a wildcard DNS record.
    """
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


def _rotation_target(url: str) -> tuple[str, int, str] | str:
    """(host, port, validated_ip) для ротации или строка-причина отказа.

    Audit R3: проверка адреса и сам запрос раньше резолвили имя дважды, поэтому
    DNS-ответ «сначала публичный, потом приватный» обходил фильтр (TOCTOU).
    Теперь соединение пиннится к проверенному IP.
    """
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
    addresses = _resolve_host_ips(parts.hostname, port)
    if not addresses:
        return "host cannot be resolved"
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return "host cannot be resolved"
        if not ip.is_global:
            return "host must be a public address"
    return parts.hostname, port, addresses[0]


def _reject_rotation_url(url: str) -> str | None:
    """Return a reason string when the rotation URL must not be fetched.

    Audit D2-P1-2: the endpoint used to fetch whatever was stored, so a
    ``file:///C:/Windows/win.ini`` or ``http://169.254.169.254/...`` URL turned
    the server into a local/SSRF reader. Policy: public http(s) hosts only,
    no redirects, no detail leaking back to the caller.
    """
    target = _rotation_target(url)
    return target if isinstance(target, str) else None


class _PinnedHTTPConnection(http.client.HTTPConnection):
    """HTTP-соединение строго с проверенным IP (без повторного DNS)."""

    def __init__(self, host: str, *args, pinned_ip: str, **kwargs):
        self._pinned_ip = pinned_ip
        super().__init__(host, *args, **kwargs)

    def connect(self) -> None:
        self.sock = socket.create_connection((self._pinned_ip, self.port), self.timeout)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS к проверенному IP с SNI/проверкой сертификата по имени хоста."""

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
    """Opener без редиректов, но с соединением строго на проверенный IP."""
    return urllib.request.build_opener(
        _NoRedirectHandler(), _PinnedHTTPHandler(pinned_ip), _PinnedHTTPSHandler(pinned_ip)
    )


@app.post("/api/profiles/{profile_id}/rotate-proxy", tags=["Proxies"], summary="Trigger mobile proxy IP rotation URL")
async def rotate_profile_proxy_endpoint(profile_id: str):
    validate_pid(profile_id)
    prof = profile_manager.get_profile(profile_id)
    if not prof:
        raise HTTPException(status_code=404, detail="Profile not found")
    if not prof.proxy.rotation_url:
        raise HTTPException(status_code=400, detail="Profile does not have a proxy rotation URL configured")
    url = prof.proxy.rotation_url
    if _is_display_mask_value(url):
        raise HTTPException(status_code=400, detail="Proxy rotation URL is masked; send the real URL to update it")
    target = _rotation_target(url)
    if isinstance(target, str):
        raise HTTPException(status_code=400, detail=f"Proxy rotation URL refused: {target}")
    _host, _port, pinned_ip = target
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Nazak-Studio"})
        opener = _build_pinned_opener(pinned_ip)
        with opener.open(req, timeout=10.0) as resp:
            resp_body = resp.read().decode("utf-8", errors="ignore")
            return {"success": True, "status_code": resp.status, "response": resp_body[:200]}
    except urllib.error.HTTPError as exc:
        # Redirects and HTTP status problems are policy, not infrastructure.
        raise HTTPException(
            status_code=400,
            detail=f"Proxy rotation URL refused: unexpected HTTP status {exc.code}",
        ) from exc
    except Exception:
        # Never echo resolution/connect details (host scanning oracle, D2-P1-2).
        raise HTTPException(status_code=502, detail="Proxy rotation request failed") from None


# Cookie Management Endpoints
@app.post(
    "/api/cookies/bulk-import",
    tags=["Cookies"],
    summary="Bulk import multi-profile cookies (text blocks, JSON maps, ZIP)",
)
async def bulk_import_cookies_endpoint(req: BulkCookieImportRequest):
    cookie_map = parse_bulk_cookie_input(req.cookies_data)
    if not cookie_map:
        raise HTTPException(status_code=400, detail="No valid cookies parsed from input")
    res = profile_manager.batch_import_cookies(cookie_map, auto_create_missing=req.auto_create_missing, group=req.group)
    await ws_manager.broadcast("cookies_bulk_imported", res)
    return {"success": True, "results": res}


@app.post("/api/cookies/bulk-export", tags=["Cookies"], summary="Export cookies for the listed profiles")
async def bulk_export_cookies_endpoint(req: BulkCookieExportRequest):
    # Audit D2-P1-5: an empty / omitted profile_ids silently exported every
    # profile in the park. Require an explicit list.
    if not req.profile_ids:
        raise HTTPException(
            status_code=400,
            detail="profile_ids must be a non-empty list of profile ids",
        )
    for pid in req.profile_ids:
        validate_pid(pid)
    cookie_dict = profile_manager.export_all_cookies(req.profile_ids)
    if req.format.lower() == "zip":
        zip_bytes = create_cookies_zip_archive(cookie_dict, format_type="json")
        from fastapi.responses import Response

        return Response(
            content=zip_bytes,
            media_type="application/zip",
            headers={"Content-Disposition": "attachment; filename=nazak_cookies.zip"},
        )
    return {"success": True, "cookies": cookie_dict, "profiles_count": len(cookie_dict)}


@app.get(
    "/api/profiles/{profile_id}/cookies/export",
    tags=["Cookies"],
    summary="Export profile cookies as JSON or Netscape format",
)
async def export_profile_cookies_endpoint(profile_id: str, format: str = Query("json")):
    validate_pid(profile_id)
    prof = profile_manager.get_profile(profile_id)
    if not prof:
        raise HTTPException(status_code=404, detail="Profile not found")
    cookies = profile_manager.load_profile_cookies(profile_id)
    if format.lower() == "netscape":
        return {"format": "netscape", "content": cookies_to_netscape(cookies), "cookies_count": len(cookies)}
    return {"format": "json", "cookies": cookies, "cookies_count": len(cookies)}


@app.post(
    "/api/profiles/{profile_id}/cookies/import",
    tags=["Cookies"],
    summary="Import cookies into profile (JSON or Netscape format)",
)
async def import_cookies_endpoint(profile_id: str, req: CookieImportRequest):
    validate_pid(profile_id)
    prof = profile_manager.get_profile(profile_id)
    if not prof:
        raise HTTPException(status_code=404, detail="Profile not found")
    cookies = parse_any_cookies(req.cookies_data)
    if not cookies:
        raise HTTPException(
            status_code=400, detail="Invalid or empty cookies format. Supported: JSON or Netscape format."
        )
    saved = profile_manager.save_profile_cookies(profile_id, cookies)
    return {"success": saved, "parsed_cookies_count": len(cookies)}


# Scenario & Autonomous Warmup Endpoints
@app.get("/api/scenarios", tags=["Scenarios & Warmup"], summary="List built-in warmup scenarios")
async def list_scenarios():
    return [s.to_dict() for s in BUILTIN_SCENARIOS]


SCENARIO_ALIASES: dict[str, str] = {
    "ecommerce_trust_booster": "scen_ecom_trust",
    "youtube_shorts_warmup": "scen_youtube_viewer",
    "crypto_web3_farming": "scen_crypto_web3",
    "finance_high_cpc_banking": "scen_finance_banking",
}


@app.post(
    "/api/scenarios/run", tags=["Scenarios & Warmup"], summary="Run scenario across profile pool with concurrency limit"
)
async def run_scenario_endpoint(req: ScenarioRunRequest, background_tasks: BackgroundTasks):
    for pid in req.profile_ids:
        validate_pid(pid)

    scenario = None
    if req.scenario_id:
        target_id = SCENARIO_ALIASES.get(req.scenario_id, req.scenario_id)
        for s in BUILTIN_SCENARIOS:
            if s.id == target_id:
                scenario = s
                break
        if not scenario:
            valid_ids = [s.id for s in BUILTIN_SCENARIOS] + list(SCENARIO_ALIASES.keys())
            raise HTTPException(
                status_code=400,
                detail=f"Unknown scenario_id '{req.scenario_id}'. Valid IDs: {valid_ids}",
            )
    elif req.scenario_data:
        scenario = WarmupScenario.from_dict(req.scenario_data)
    else:
        raise HTTPException(
            status_code=400,
            detail="Either scenario_id or scenario_data must be provided",
        )

    background_tasks.add_task(
        scenario_executor.run_batch_warmup,
        scenario=scenario,
        profile_ids=req.profile_ids,
        max_concurrency=req.max_concurrency,
    )
    return {"success": True, "message": f"Scenario '{scenario.name}' started for {len(req.profile_ids)} profiles"}


# Synchronizer Endpoints
@app.post(
    "/api/synchronizer/start", tags=["Synchronizer"], summary="Start Master-to-Workers action synchronizer session"
)
async def start_synchronizer_endpoint(req: SynchronizerStartRequest):
    try:
        validate_pid(req.master_profile_id)
    except HTTPException as exc:
        raise HTTPException(status_code=400, detail=f"Invalid master_profile_id: {exc.detail}") from exc
    for pid in req.worker_profile_ids:
        try:
            validate_pid(pid)
        except HTTPException as exc:
            raise HTTPException(status_code=400, detail=f"Invalid worker_profile_id '{pid}': {exc.detail}") from exc
    session = synchronizer_mgr.start_session(
        master_profile_id=req.master_profile_id,
        worker_profile_ids=req.worker_profile_ids,
        humanize_jitter=req.humanize_jitter,
        delay_range_ms=(req.min_delay_ms, req.max_delay_ms),
        coordinate_jitter_px=req.coordinate_jitter_px,
    )
    await ws_manager.broadcast("synchronizer_started", session.to_dict())
    return {"success": True, "session": session.to_dict()}


@app.post("/api/synchronizer/stop", tags=["Synchronizer"], summary="Stop active synchronizer session")
async def stop_synchronizer_endpoint():
    synchronizer_mgr.stop_session()
    await ws_manager.broadcast("synchronizer_stopped", {})
    return {"success": True, "message": "Synchronizer stopped"}


@app.get("/api/synchronizer/status", tags=["Synchronizer"], summary="Get synchronizer session status")
async def get_synchronizer_status():
    return synchronizer_mgr.get_status()


@app.post(
    "/api/synchronizer/tile-windows",
    tags=["Synchronizer"],
    summary="Arrange active browser windows into Win32 grid layout",
)
async def tile_windows_endpoint(req: WindowTileRequest = Body(default=WindowTileRequest())):
    ok = synchronizer_mgr.tile_active_windows(cols=req.cols)
    return {"success": ok}


@app.post(
    "/api/synchronizer/navigate", tags=["Synchronizer"], summary="Broadcast URL navigation to all worker browsers"
)
async def synchronizer_navigate(req: SynchronizerNavigateRequest):
    results = await synchronizer_mgr.mirror_navigation(req.url)
    return {"success": True, "results": results}


@app.post(
    "/api/profiles/{profile_id}/warmup/plan", tags=["Scenarios & Warmup"], summary="Generate organic warmup search plan"
)
async def get_warmup_plan(profile_id: str, req: WarmupRequest):
    validate_pid(profile_id)
    plan = WarmupPlan(profile_id=profile_id, niche=req.niche, steps_count=req.steps_count)
    return plan.to_dict()


@app.post(
    "/api/profiles/{profile_id}/warmup/launch",
    tags=["Scenarios & Warmup"],
    summary="Launch profile on warmup start URL",
)
async def launch_warmup(profile_id: str, req: WarmupRequest):
    validate_pid(profile_id)
    plan = WarmupPlan(profile_id=profile_id, niche=req.niche, steps_count=req.steps_count)
    urls = generate_warmup_urls(plan.queries)
    start_url = _require_launch_url(urls[0] if urls else "https://www.google.com")

    profile = profile_manager.get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    ok, pid, err = browser_launcher.launch(profile, custom_url=start_url)
    if not ok:
        raise HTTPException(status_code=400, detail=err or "Failed to start browser for warmup")

    profile.status = ProfileStatus.RUNNING
    profile.pid = pid
    profile_manager.update_profile(profile)
    return {"success": True, "pid": pid, "plan": plan.to_dict(), "start_url": start_url}


@app.post(
    "/api/profiles/test-proxy",
    response_model=HealthCheckResult,
    tags=["Proxies"],
    summary="Test standalone raw proxy string",
)
async def test_raw_proxy(req: ProxyTestRequest):
    proxy_config = ProxyConfig.parse(req.raw_proxy)
    result = await check_proxy_health(proxy_config, profile_dir=None)
    return result


# Auto-Posting & Video Uniqueization Endpoints
@app.get(
    "/api/autopost/status", tags=["YouTube Shorts Autoposter"], summary="Get autopost queue and FFmpeg encoder status"
)
async def get_autopost_status():
    return {
        "is_running": upload_queue_mgr.is_running,
        "ffmpeg_available": video_uniquifier.is_ffmpeg_available(),
        "ffmpeg_path": video_uniquifier.ffmpeg_path,
        "jobs": upload_queue_mgr.get_jobs_status(),
    }


@app.post("/api/autopost/uniquify", tags=["YouTube Shorts Autoposter"], summary="Batch uniqueize video using FFmpeg")
async def uniquify_videos_endpoint(req: UniquifyRequest):
    for pid in req.profile_ids:
        validate_pid(pid)
    src = resolve_media_source(req.source_video_path)
    results = await asyncio.to_thread(video_uniquifier.batch_uniquify, src, req.profile_ids)
    formatted = {}
    for pid, (ok, path, err) in results.items():
        formatted[pid] = {"success": ok, "output_path": str(path.resolve()) if path else None, "error": err}
    return {"results": formatted, "count": len(results)}


def _generate_demo_video(path: Path) -> tuple[bool, str | None]:
    """Create a REAL, playable demo clip via ffmpeg (audit fix P0-4 / R3).

    The old flow wrote ``b"DEMO_MP4_HEADER" + b"0" * 1024`` — garbage bytes that
    no player (and no uniqueizer) can process — yet the autopost would happily
    try to upload it. The generator now lives in ``core.video_uniquifier`` so the
    API and the legacy CLI login flow share one honest implementation.
    """
    from ..core.video_uniquifier import generate_demo_clip

    return generate_demo_clip(path)


@app.post(
    "/api/autopost/launch",
    tags=["YouTube Shorts Autoposter"],
    summary="Launch autonomous YouTube Shorts or Instagram Reels upload queue",
)
async def launch_autopost_batch(req: AutopostBatchRequest, background_tasks: BackgroundTasks):
    for pid in req.profile_ids:
        validate_pid(pid)
    if upload_queue_mgr.is_running:
        raise HTTPException(
            status_code=400, detail="An upload batch is already running. Please wait or cancel it first."
        )

    normalized_platform = normalize_upload_platform(req.platform)
    if req.source_video_path:
        src_path = resolve_media_source(req.source_video_path)
    else:
        src_path = DATA_DIR / "videos" / "source.mp4"
        if not src_path.exists():
            if not req.demo:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "No source video: provide source_video_path with a real video file, "
                        "or pass demo=true to generate a short ffmpeg test clip."
                    ),
                )
            ok, demo_err = _generate_demo_video(src_path)
            if not ok:
                raise HTTPException(status_code=400, detail=demo_err)

    background_tasks.add_task(
        upload_queue_mgr.run_batch_upload,
        profile_ids=req.profile_ids,
        source_video_path=src_path,
        title_template=req.title_template,
        description_template=req.description_template,
        tg_channel=req.tg_channel,
        delay_between_accounts_sec=req.delay_seconds,
        platform=normalized_platform,
    )
    return {
        "success": True,
        "platform": normalized_platform,
        "message": f"Autopost started for {len(req.profile_ids)} profiles in background",
    }


@app.post("/api/autopost/cancel", tags=["YouTube Shorts Autoposter"], summary="Cancel running autopost queue")
async def cancel_autopost():
    upload_queue_mgr.cancel_all()
    return {"success": True, "message": "Autopost cancellation requested"}


@app.post(
    "/api/autopost/preview-spintax",
    tags=["YouTube Shorts Autoposter"],
    summary="Preview Spintax title and description generations",
)
async def preview_spintax_endpoint(req: AutopostBatchRequest):
    for pid in req.profile_ids:
        validate_pid(pid)
    samples = []
    for pid in req.profile_ids[:5]:
        prof = profile_manager.get_profile(pid)
        pname = prof.name if prof else pid
        meta = format_video_metadata(
            title_template=req.title_template,
            description_template=req.description_template,
            profile_name=pname,
            profile_id=pid,
            tg_channel=req.tg_channel,
        )
        samples.append(
            {"profile_id": pid, "profile_name": pname, "title": meta["title"], "description": meta["description"]}
        )
    return {"samples": samples}


# WebSocket Real-time Feed
@app.websocket("/ws/events")
async def websocket_endpoint(websocket: WebSocket):
    # Audit D2-P1-1 / R3: тот же Origin/Host/Sec-Fetch-Site-политика, что и для HTTP.
    sec_fetch_site = (websocket.headers.get("sec-fetch-site") or "").strip().lower()
    if (
        not _is_local_host(websocket.headers.get("host"))
        or (websocket.headers.get("origin") and not _is_local_origin(websocket.headers.get("origin")))
        or sec_fetch_site == "cross-site"
        or not _is_api_token_valid(websocket.headers)
    ):
        await websocket.close(code=1008)
        return
    await ws_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception:
        ws_manager.disconnect(websocket)


# Mount Static Web App
if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

    @app.get("/", tags=["System"], summary="Serve Nazak Web Studio Dashboard")
    async def serve_index():
        index_file = WEB_DIR / "index.html"
        if index_file.exists():
            return FileResponse(str(index_file))
        return {"message": "Nazak Browser Studio API Server Running"}
