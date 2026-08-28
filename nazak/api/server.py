"""
FastAPI Server & WebSocket Real-time Hub for Nazak Browser Studio.
"""

import asyncio
import json
import os
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, Body, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..config import DATA_DIR, EXTENSIONS_DIR, PROFILES_DIR, PROFILES_FILE, WEB_DIR, find_chrome_executable
from ..core.browser_launcher import BrowserLauncher
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
from ..core.spintax import format_video_metadata
from ..core.synchronizer import SynchronizerManager
from ..core.upload_queue import UploadQueueManager
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
            except Exception:
                self.disconnect(connection)


ws_manager = ConnectionManager()

# Initialize Core Services
profile_manager = ProfileManager(PROFILES_FILE, PROFILES_DIR)
browser_launcher = BrowserLauncher(PROFILES_DIR, EXTENSIONS_DIR)
upload_queue_mgr = UploadQueueManager(profile_manager, browser_launcher, ws_manager.broadcast)
video_uniquifier = VideoUniquifier()
process_monitor = ProcessMonitor(profile_manager, browser_launcher, poll_interval=1.0)
synchronizer_mgr = SynchronizerManager(browser_launcher)
scenario_executor = ScenarioExecutor(browser_launcher, profile_manager)


def on_process_state_change(profile_id: str, status: ProfileStatus):
    try:
        asyncio.get_running_loop()
        _task = asyncio.create_task(
            ws_manager.broadcast("profile_status_change", {"profile_id": profile_id, "status": status.value})
        )
    except RuntimeError:
        pass


process_monitor.register_callback(on_process_state_change)


@asynccontextmanager
async def lifespan(app: FastAPI):
    process_monitor.start()
    yield
    process_monitor.stop()


tags_metadata = [
    {
        "name": "Dolphin Automation (v1.0 Parity)",
        "description": "100% Dolphin{anty}-compatible REST endpoints for external automation scripts (Playwright, Puppeteer, Selenium).",
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
        "description": "5-stage proxy health diagnostics (Latency, Geolocation, Google Suite, WebRTC) and mobile IP rotation triggers.",
    },
    {
        "name": "YouTube Shorts Autoposter",
        "description": "Autonomous YouTube Shorts upload queue with FFmpeg video uniqueizer and Bezier human motorics.",
    },
    {
        "name": "System",
        "description": "Host diagnostics, Chrome discovery, WebSocket telemetry, and platform information.",
    },
]

app = FastAPI(
    title="Nazak Browser Studio API",
    description="Professional Multi-Profile Anti-Detect Browser Launcher with Strict Proxy & Google Automation Isolation",
    version="1.4.1",
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
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Schemas for requests
class LaunchRequest(BaseModel):
    custom_url: str | None = None
    cdp_port: int | None = None


class ProxyTestRequest(BaseModel):
    raw_proxy: str


class BulkImportRequest(BaseModel):
    proxy_lines: str
    group: str = "Google Ads"
    target_page: str = "google_login"


class MassGenerateRequest(BaseModel):
    count: int = 10
    group: str = "Mass Generated"
    proxy_lines: str | None = None
    os_mix: str = "windows"
    tags: list[str] | None = None
    target_page: str = "google_login"
    notes: str | None = None


class BatchActionRequest(BaseModel):
    profile_ids: list[str]


class AutopostBatchRequest(BaseModel):
    profile_ids: list[str]
    source_video_path: str | None = None
    title_template: str = "{Лучший|Топ|Рабочий} {VPN|Впн} для {РФ|России} 2026 ⚡ #shorts"
    description_template: str = (
        "⚡ Скачать быстрый VPN без ограничений: {tg}\n🎁 Промокод на скидку: {promo}\n\n#shorts #vpn #впн"
    )
    tg_channel: str = "@your_vpn_bot"
    delay_seconds: int = 10


class UniquifyRequest(BaseModel):
    source_video_path: str
    profile_ids: list[str]


class CookieImportRequest(BaseModel):
    cookies_data: str


class BulkCookieImportRequest(BaseModel):
    cookies_data: str
    auto_create_missing: bool = True
    group: str = "Imported Cookies"


class BulkCookieExportRequest(BaseModel):
    profile_ids: list[str] | None = None
    format: str = "json"


class WarmupRequest(BaseModel):
    niche: str = "ecommerce"
    steps_count: int = 5


class ScenarioRunRequest(BaseModel):
    scenario_id: str | None = None
    scenario_data: dict[str, Any] | None = None
    profile_ids: list[str]
    max_concurrency: int = 3


class SynchronizerStartRequest(BaseModel):
    master_profile_id: str
    worker_profile_ids: list[str]
    humanize_jitter: bool = True
    min_delay_ms: int = 20
    max_delay_ms: int = 80
    coordinate_jitter_px: int = 2


class SynchronizerNavigateRequest(BaseModel):
    url: str


class WindowTileRequest(BaseModel):
    cols: int | None = None


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
    for p in profiles:
        if browser_launcher.is_profile_running(p.id):
            p.status = ProfileStatus.RUNNING
            p.pid = browser_launcher.profile_pids.get(p.id)
        else:
            p.status = ProfileStatus.STOPPED
            p.pid = None
    return profiles


@app.get(
    "/api/profiles/{profile_id}", response_model=BrowserProfile, tags=["Profiles"], summary="Get single profile details"
)
async def get_profile(profile_id: str):
    profile = profile_manager.get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    if browser_launcher.is_profile_running(profile.id):
        profile.status = ProfileStatus.RUNNING
        profile.pid = browser_launcher.profile_pids.get(profile.id)
    return profile


@app.post("/api/profiles", response_model=BrowserProfile, tags=["Profiles"], summary="Create new isolated profile")
async def create_profile(profile_data: BrowserProfile):
    created = profile_manager.create_profile(profile_data)
    await ws_manager.broadcast("profile_created", created.model_dump())
    return created


@app.put(
    "/api/profiles/{profile_id}", response_model=BrowserProfile, tags=["Profiles"], summary="Update profile settings"
)
async def update_profile(profile_id: str, profile_data: BrowserProfile):
    profile_data.id = profile_id
    updated = profile_manager.update_profile(profile_data)
    if not updated:
        raise HTTPException(status_code=404, detail="Profile not found")
    await ws_manager.broadcast("profile_updated", updated.model_dump())
    return updated


@app.delete("/api/profiles/{profile_id}", tags=["Profiles"], summary="Delete profile and local storage data")
async def delete_profile(profile_id: str):
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
    cloned = profile_manager.clone_profile(profile_id, new_name)
    if not cloned:
        raise HTTPException(status_code=404, detail="Source profile not found")
    await ws_manager.broadcast("profile_created", cloned.model_dump())
    return cloned


@app.post("/api/profiles/{profile_id}/launch", tags=["Profiles"], summary="Launch browser profile")
async def launch_profile(profile_id: str, req: LaunchRequest | None = None):
    profile = profile_manager.get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    custom_url = req.custom_url if req else None
    cdp_port = req.cdp_port if req else None

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
                "proxy": p.proxy.model_dump(),
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
    cdp_info = browser_launcher.get_cdp_info(profile_id)
    if not cdp_info:
        raise HTTPException(status_code=400, detail="Profile is not running or CDP is not active")
    return {"success": True, "cdp": cdp_info}


@app.post("/api/profiles/batch-launch", tags=["Profiles"], summary="Launch multiple profiles simultaneously")
async def batch_launch(req: BatchActionRequest):
    results = {}
    for pid in req.profile_ids:
        prof = profile_manager.get_profile(pid)
        if prof:
            ok, p_id, err = browser_launcher.launch(prof)
            if ok:
                prof.status = ProfileStatus.RUNNING
                prof.pid = p_id
                profile_manager.update_profile(prof)
                results[pid] = {"success": True, "pid": p_id}
            else:
                results[pid] = {"success": False, "error": err}
    return results


@app.post("/api/profiles/batch-stop", tags=["Profiles"], summary="Stop multiple running profiles simultaneously")
async def batch_stop(req: BatchActionRequest):
    for pid in req.profile_ids:
        browser_launcher.stop(pid)
        prof = profile_manager.get_profile(pid)
        if prof:
            prof.status = ProfileStatus.STOPPED
            prof.pid = None
            profile_manager.update_profile(prof)
    return {"success": True, "stopped_count": len(req.profile_ids)}


@app.post(
    "/api/profiles/{profile_id}/check",
    response_model=HealthCheckResult,
    tags=["Proxies"],
    summary="Perform 5-stage health check for profile proxy",
)
async def check_profile_proxy(profile_id: str):
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
        profile_manager.update_profile(p)
        await ws_manager.broadcast("profile_health_update", {"profile_id": p.id, "health": res.model_dump()})
        return p.id, res

    await asyncio.gather(*[_check(p) for p in profiles], return_exceptions=True)
    return {"total_checked": len(profiles)}


@app.post("/api/profiles/{profile_id}/clear-cache", tags=["Profiles"], summary="Purge browser cache for profile")
async def clear_cache(profile_id: str):
    if browser_launcher.is_profile_running(profile_id):
        raise HTTPException(
            status_code=400, detail="Cannot clear cache while browser is running. Please stop it first."
        )
    ok = profile_manager.clear_profile_cache(profile_id)
    return {"success": ok, "message": "Cache cleared successfully"}


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
    return {"success": True, "created_count": len(created), "profiles": [p.model_dump() for p in created]}


@app.get(
    "/api/profiles/{profile_id}/bundle/export",
    tags=["Profiles"],
    summary="Export complete profile as portable .nazak archive",
)
async def export_profile_bundle_endpoint(profile_id: str):
    prof = profile_manager.get_profile(profile_id)
    if not prof:
        raise HTTPException(status_code=404, detail="Profile not found")
    bundle_path = profile_manager.export_profile_bundle(profile_id)
    if not bundle_path or not bundle_path.exists():
        raise HTTPException(status_code=500, detail="Failed to create profile bundle")
    return FileResponse(path=str(bundle_path), filename=f"{profile_id}_bundle.nazak", media_type="application/zip")


@app.post("/api/profiles/{profile_id}/rotate-proxy", tags=["Proxies"], summary="Trigger mobile proxy IP rotation URL")
async def rotate_profile_proxy_endpoint(profile_id: str):
    prof = profile_manager.get_profile(profile_id)
    if not prof:
        raise HTTPException(status_code=404, detail="Profile not found")
    if not prof.proxy.rotation_url:
        raise HTTPException(status_code=400, detail="Profile does not have a proxy rotation URL configured")
    try:
        req = urllib.request.Request(prof.proxy.rotation_url, headers={"User-Agent": "Nazak-Studio"})
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            resp_body = resp.read().decode("utf-8", errors="ignore")
            return {"success": True, "status_code": resp.status, "response": resp_body[:200]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to trigger proxy rotation: {e!s}") from e


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


@app.post("/api/cookies/bulk-export", tags=["Cookies"], summary="Export all cookies as JSON or structured ZIP archive")
async def bulk_export_cookies_endpoint(req: BulkCookieExportRequest):
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


@app.post(
    "/api/scenarios/run", tags=["Scenarios & Warmup"], summary="Run scenario across profile pool with concurrency limit"
)
async def run_scenario_endpoint(req: ScenarioRunRequest, background_tasks: BackgroundTasks):
    scenario = None
    if req.scenario_id:
        for s in BUILTIN_SCENARIOS:
            if s.id == req.scenario_id:
                scenario = s
                break
    elif req.scenario_data:
        scenario = WarmupScenario.from_dict(req.scenario_data)

    if not scenario:
        scenario = BUILTIN_SCENARIOS[0]

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
    plan = WarmupPlan(profile_id=profile_id, niche=req.niche, steps_count=req.steps_count)
    return plan.to_dict()


@app.post(
    "/api/profiles/{profile_id}/warmup/launch",
    tags=["Scenarios & Warmup"],
    summary="Launch profile on warmup start URL",
)
async def launch_warmup(profile_id: str, req: WarmupRequest):
    plan = WarmupPlan(profile_id=profile_id, niche=req.niche, steps_count=req.steps_count)
    urls = generate_warmup_urls(plan.queries)
    start_url = urls[0] if urls else "https://www.google.com"

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
    src = Path(req.source_video_path)
    if not src.exists():
        raise HTTPException(status_code=400, detail=f"Source video not found: {req.source_video_path}")
    results = video_uniquifier.batch_uniquify(src, req.profile_ids)
    formatted = {}
    for pid, (ok, path, err) in results.items():
        formatted[pid] = {"success": ok, "output_path": str(path.resolve()) if path else None, "error": err}
    return {"results": formatted, "count": len(results)}


@app.post(
    "/api/autopost/launch", tags=["YouTube Shorts Autoposter"], summary="Launch autonomous YouTube Shorts upload queue"
)
async def launch_autopost_batch(req: AutopostBatchRequest, background_tasks: BackgroundTasks):
    if upload_queue_mgr.is_running:
        raise HTTPException(
            status_code=400, detail="An upload batch is already running. Please wait or cancel it first."
        )

    src_path = Path(req.source_video_path) if req.source_video_path else (DATA_DIR / "videos" / "source.mp4")
    if not src_path.exists():
        # Create a dummy demo video if none exists so user can test immediately
        src_path.parent.mkdir(parents=True, exist_ok=True)
        src_path.write_bytes(b"DEMO_MP4_HEADER" + b"0" * 1024)

    background_tasks.add_task(
        upload_queue_mgr.run_batch_upload,
        profile_ids=req.profile_ids,
        source_video_path=src_path,
        title_template=req.title_template,
        description_template=req.description_template,
        tg_channel=req.tg_channel,
        delay_between_accounts_sec=req.delay_seconds,
    )
    return {"success": True, "message": f"Autopost started for {len(req.profile_ids)} profiles in background"}


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
