"""
FastAPI Server & WebSocket Real-time Hub for Nazak Browser Studio.

P0 refactor: thin composition root. Endpoints live in nazak/api/routers/*,
schemas in nazak/api/schemas.py, security perimeter in nazak/api/security.py,
realtime hub in nazak/api/realtime.py. This module keeps every public name
the old 1792-line server.py exposed (singletons, helpers, endpoint functions)
so the 725-test suite, GUI and CLI keep working unchanged.
"""

import asyncio
import logging
import socket  # re-exported as server.socket: patch target in tests
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..config import (
    DATA_DIR,
    EXTENSIONS_DIR,
    PROFILES_DIR,
    PROFILES_FILE,
    WEB_DIR,
    ensure_data_dirs,
)
from ..core.browser_launcher import BrowserLauncher
from ..core.process_monitor import ProcessMonitor
from ..core.profile_manager import ProfileManager
from ..core.secrets_store import load_mode, set_mode_file
from ..core.synchronizer import SynchronizerManager
from ..core.upload_queue import UploadQueueManager
from ..core.video_uniquifier import VideoUniquifier
from ..core.warmup_engine import ScenarioExecutor
from ..models.profile import ProfileStatus
from .realtime import (
    get_server_loop as _get_rt_loop,
    on_process_state_change as _rt_on_process_state_change,
    set_server_loop as _set_rt_loop,
    ws_manager,
)
from .routers.automation import (
    batch_launch,
    batch_stop,
    dolphin_active_profiles,
    dolphin_list_profiles,
    dolphin_start_profile,
    dolphin_stop_profile,
    get_profile_cdp,
    router as _automation_router,
)
from .routers.autopost import (
    _generate_demo_video,
    cancel_autopost,
    get_autopost_status,
    launch_autopost_batch,
    preview_spintax_endpoint,
    router as _autopost_router,
    uniquify_videos_endpoint,
)
from .routers.cookies import (
    bulk_export_cookies_endpoint,
    bulk_import_cookies_endpoint,
    export_profile_cookies_endpoint,
    import_cookies_endpoint,
    router as _cookies_router,
)
from .routers.profiles import (
    bulk_import_profiles,
    clear_cache,
    clone_profile,
    create_profile,
    delete_profile,
    export_profile_bundle_endpoint,
    get_profile,
    launch_profile,
    list_profiles,
    mass_generate_profiles_endpoint,
    randomize_fingerprint,
    router as _profiles_router,
    seed_profile_history_endpoint,
    stop_profile,
    update_profile,
)
from .routers.proxies import (
    check_all_profiles,
    check_profile_proxy,
    rotate_profile_proxy_endpoint,
    router as _proxies_router,
    test_raw_proxy,
)
from .routers.synchronizer import (
    get_synchronizer_status,
    router as _synchronizer_router,
    start_synchronizer_endpoint,
    stop_synchronizer_endpoint,
    synchronizer_navigate,
    tile_windows_endpoint,
)
from .routers.system import get_secrets_mode, get_system_info, post_secrets_mode, router as _system_router
from .routers.warmup import (
    SCENARIO_ALIASES,
    get_warmup_plan,
    launch_warmup,
    list_scenarios,
    router as _warmup_router,
    run_scenario_endpoint,
)

# Re-export request schemas (backward compat: `from nazak.api.server import AutopostBatchRequest`).
from .schemas import (
    AutopostBatchRequest,
    BatchActionRequest,
    BulkCookieExportRequest,
    BulkCookieImportRequest,
    BulkImportRequest,
    CookieImportRequest,
    LaunchRequest,
    MassGenerateRequest,
    ProxyTestRequest,
    ScenarioRunRequest,
    SecretsModeRequest,
    SynchronizerNavigateRequest,
    SynchronizerStartRequest,
    UniquifyRequest,
    WarmupRequest,
    WindowTileRequest,
)

# Re-export security perimeter names (patch targets for tests).
from .security import (
    _ALLOWED_PORTS,
    _API_TOKEN_ENV,
    _LOCAL_HOSTS,
    _LOCAL_SCHEMES,
    _LOOPBACK_HOSTS,
    _MEDIA_EXTENSIONS,
    _NO_REDIRECT_HANDLER,
    _NO_STORE_PREFIXES,
    CSP_POLICY,
    SECURITY_HEADERS,
    _apply_security_headers,
    _build_pinned_opener,
    _host_name,
    _host_port,
    _is_api_token_valid,
    _is_display_mask_value,
    _is_local_host,
    _is_local_origin,
    _json_safe_error_payload,
    _mask_profile_secrets,
    _mask_proxy_for_api,
    _NoRedirectHandler,
    _origin_matches_request,
    _PinnedHTTPConnection,
    _PinnedHTTPHandler,
    _PinnedHTTPSConnection,
    _PinnedHTTPSHandler,
    _reject_rotation_url,
    _remove_quietly,
    _require_launch_url,
    _resolve_host_ips,
    _rotation_target,
    api_token_configured,
    configure_local_access,
    enforce_exposure_policy,
    resolve_media_source,
    validate_pid,
    validation_error_handler,
)

logger = logging.getLogger(__name__)

# P1: this is a composition root, so it is an explicit place that provisions the
# runtime data tree (importing nazak.config alone no longer touches the disk).
ensure_data_dirs()

# Bootstrap user-selected secrets mode.
set_mode_file(DATA_DIR / "secrets_mode.json")
load_mode()

# Initialize Core Services (singletons shared with the Qt GUI).
profile_manager = ProfileManager(PROFILES_FILE, PROFILES_DIR)
browser_launcher = BrowserLauncher(PROFILES_DIR, EXTENSIONS_DIR)
upload_queue_mgr = UploadQueueManager(profile_manager, browser_launcher, ws_manager.broadcast)
video_uniquifier = VideoUniquifier()
process_monitor = ProcessMonitor(profile_manager, browser_launcher, poll_interval=1.0)
synchronizer_mgr = SynchronizerManager(browser_launcher)
browser_launcher.set_event_sink(synchronizer_mgr.submit_event)
scenario_executor = ScenarioExecutor(browser_launcher, profile_manager)

_server_loop: asyncio.AbstractEventLoop | None = None


def on_process_state_change(profile_id: str, status: ProfileStatus):
    global _server_loop
    _rt_on_process_state_change(profile_id, status)
    try:
        rt_loop = _get_rt_loop()
        if rt_loop is not _server_loop:
            _server_loop = rt_loop
    except Exception:
        pass


process_monitor.register_callback(on_process_state_change)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _server_loop
    _server_loop = asyncio.get_running_loop()
    _set_rt_loop(_server_loop)
    try:
        app.state.loop = _server_loop
    except Exception:
        pass
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
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1):(8899|3000)$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def local_only_guard(request, call_next):
    path = request.url.path
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
    if not _origin_matches_request(origin, request.headers.get("host")):
        return _apply_security_headers(
            JSONResponse(
                status_code=403,
                content={"detail": "Local access only: cross-origin requests are refused"},
            ),
            path,
        )
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


app.exception_handler(RequestValidationError)(validation_error_handler)

# Mount feature routers (objects imported at module top; endpoints moved
# verbatim from the old monolith into nazak/api/routers/*).
for _r in (
    _system_router,
    _profiles_router,
    _automation_router,
    _proxies_router,
    _cookies_router,
    _warmup_router,
    _synchronizer_router,
    _autopost_router,
):
    app.include_router(_r)


@app.websocket("/ws/events")
async def websocket_endpoint(websocket: WebSocket):
    sec_fetch_site = (websocket.headers.get("sec-fetch-site") or "").strip().lower()
    if (
        not _is_local_host(websocket.headers.get("host"))
        or not _origin_matches_request(websocket.headers.get("origin"), websocket.headers.get("host"))
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


if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

    @app.get("/", tags=["System"], summary="Serve Nazak Web Studio Dashboard")
    async def serve_index():
        index_file = WEB_DIR / "index.html"
        if index_file.exists():
            return FileResponse(str(index_file))
        return {"message": "Nazak Browser Studio API Server Running"}


__all__ = [
    "app",
    "browser_launcher",
    "lifespan",
    "local_only_guard",
    "on_process_state_change",
    "process_monitor",
    "profile_manager",
    "scenario_executor",
    "synchronizer_mgr",
    "upload_queue_mgr",
    "video_uniquifier",
    "websocket_endpoint",
    "ws_manager",
]
