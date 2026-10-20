"""
Automation & CDP router (P0 refactor). Moved verbatim from nazak/api/server.py.
All service singletons are resolved lazily via deps so tests can replace
``nazak.api.server.profile_manager`` / ``browser_launcher`` per-test.
"""

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ...models.profile import ProfileStatus
from .. import deps
from ..schemas import BatchActionRequest
from ..security import _mask_proxy_for_api, _require_launch_url, validate_pid

router = APIRouter()


@router.get(
    "/v1.0/browser_profiles", tags=["Dolphin Automation (v1.0 Parity)"], summary="Dolphin v1.0 - List all profiles"
)
async def dolphin_list_profiles():
    profile_manager = deps.pm()
    browser_launcher = deps.bl()
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


@router.get(
    "/v1.0/browser_profiles/{profile_id}/start",
    tags=["Dolphin Automation (v1.0 Parity)", "Automation & CDP"],
    summary="Dolphin v1.0 - Start profile and get CDP WebSocket URL",
)
@router.post(
    "/api/v1/profiles/{profile_id}/start",
    tags=["Automation & CDP"],
    summary="Nazak v1 - Start profile with CDP automation",
)
async def dolphin_start_profile(profile_id: str, custom_url: str | None = Query(None), port: int | None = Query(None)):
    validate_pid(profile_id)
    custom_url = _require_launch_url(custom_url)
    profile_manager = deps.pm()
    browser_launcher = deps.bl()
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
    await deps.broadcast_coro("profile_status_change", {"profile_id": profile_id, "status": "running", "pid": pid})
    return {
        "success": True,
        "automation": {"port": cdp_port, "wsEndpoint": ws_endpoint},
        "pid": pid,
        "profile_id": profile_id,
    }


@router.get(
    "/v1.0/browser_profiles/{profile_id}/stop",
    tags=["Dolphin Automation (v1.0 Parity)", "Automation & CDP"],
    summary="Dolphin v1.0 - Stop running profile",
)
@router.post("/api/v1/profiles/{profile_id}/stop", tags=["Automation & CDP"], summary="Nazak v1 - Stop running profile")
async def dolphin_stop_profile(profile_id: str):
    validate_pid(profile_id)
    profile_manager = deps.pm()
    browser_launcher = deps.bl()
    profile = profile_manager.get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    browser_launcher.stop(profile_id)
    profile.status = ProfileStatus.STOPPED
    profile.pid = None
    profile_manager.update_profile(profile)
    await deps.broadcast_coro("profile_status_change", {"profile_id": profile_id, "status": "stopped"})
    return {"success": True, "profile_id": profile_id}


@router.get(
    "/v1.0/browser_profiles/active",
    tags=["Dolphin Automation (v1.0 Parity)", "Automation & CDP"],
    summary="Dolphin v1.0 - List all active browser profiles with CDP endpoints",
)
async def dolphin_active_profiles():
    profile_manager = deps.pm()
    browser_launcher = deps.bl()
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


@router.get(
    "/api/v1/profiles/{profile_id}/cdp",
    tags=["Automation & CDP"],
    summary="Query active CDP port and WebSocket URL for profile",
)
async def get_profile_cdp(profile_id: str):
    validate_pid(profile_id)
    browser_launcher = deps.bl()
    cdp_info = browser_launcher.get_cdp_info(profile_id)
    if not cdp_info:
        raise HTTPException(status_code=400, detail="Profile is not running or CDP is not active")
    return {"success": True, "cdp": cdp_info}


@router.post("/api/profiles/batch-launch", tags=["Profiles"], summary="Launch multiple profiles simultaneously")
async def batch_launch(req: BatchActionRequest):
    profile_manager = deps.pm()
    browser_launcher = deps.bl()
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
            prof.updated_at = datetime.now(timezone.utc).isoformat()
            if ok:
                prof.status = ProfileStatus.RUNNING
                prof.pid = p_id
                # Hunt X-22: profile_manager.profiles[pid] = prof wrote the
                # shared dict OUTSIDE the service lock — concurrent save_all
                # raised "dictionary changed size during iteration". update()
                # does the write under the service lock.
                profile_manager.update_profile(prof)
                any_changed = True
                results[pid] = {"success": True, "pid": p_id}
            else:
                prof.status = ProfileStatus.ERROR
                prof.pid = None
                profile_manager.update_profile(prof)
                any_changed = True
                results[pid] = {"success": False, "error": err}
    if any_changed:
        profile_manager.save_profiles()
    return results


@router.post("/api/profiles/batch-stop", tags=["Profiles"], summary="Stop multiple running profiles simultaneously")
async def batch_stop(req: BatchActionRequest):
    profile_manager = deps.pm()
    browser_launcher = deps.bl()
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
            # Hunt X-22 (twin of batch-launch): no unlocked dict writes.
            profile_manager.update_profile(prof)
            any_changed = True
    if any_changed:
        profile_manager.save_profiles()
    return {"success": True, "stopped_count": len(req.profile_ids)}
