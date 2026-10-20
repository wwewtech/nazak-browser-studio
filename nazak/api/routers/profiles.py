"""
Profiles router (P0 refactor). Moved verbatim from nazak/api/server.py.
"""

import logging
import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from ...core.fingerprint_generator import generate_random_fingerprint
from ...models.profile import BrowserProfile, FingerprintConfig, GoogleSettings, ProfileStatus
from ...models.proxy import ProxyConfig
from .. import deps
from ..schemas import BulkImportRequest, LaunchRequest, MassGenerateRequest
from ..security import (
    _mask_profile_secrets,
    _mask_proxy_for_api,
    _remove_quietly,
    _require_launch_url,
    validate_pid,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Profiles"])

# Parity with schemas.MAX_PROFILE_IDS (500): one request must not be able to
# create an unbounded farm. Before this bound a 1 MB body (~100k proxy lines)
# created 100k profiles, each with a directory and a generated fingerprint.
MAX_BULK_IMPORT_LINES = 500


@router.get(
    "/api/profiles", response_model=list[BrowserProfile], summary="List all browser profiles with live statuses"
)
async def list_profiles():
    profile_manager = deps.pm()
    browser_launcher = deps.bl()
    profiles = profile_manager.list_profiles()
    result = []
    for p in profiles:
        # Hunt X-13: p is the SHARED stored object. Setting p.status/p.pid on
        # it made the transient RUNNING overlay leak into the store through
        # any concurrent save of a different profile (the next save_all
        # serializes the polluted object). The overlay must live on a copy.
        p = p.model_copy(deep=True)
        if browser_launcher.is_profile_running(p.id):
            p.status = ProfileStatus.RUNNING
            p.pid = browser_launcher.profile_pids.get(p.id)
        else:
            p.status = ProfileStatus.STOPPED
            p.pid = None
        result.append(_mask_profile_secrets(p))
    return result


@router.get("/api/profiles/{profile_id}", response_model=BrowserProfile, summary="Get single profile details")
async def get_profile(profile_id: str):
    validate_pid(profile_id)
    profile_manager = deps.pm()
    browser_launcher = deps.bl()
    profile = profile_manager.get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    # Hunt X-13 (twin of the list endpoint): the overlay must not be written
    # onto the shared stored object.
    profile = profile.model_copy(deep=True)
    if browser_launcher.is_profile_running(profile.id):
        profile.status = ProfileStatus.RUNNING
        profile.pid = browser_launcher.profile_pids.get(profile.id)
    return _mask_profile_secrets(profile)


@router.post("/api/profiles", response_model=BrowserProfile, summary="Create new isolated profile")
async def create_profile(profile_data: BrowserProfile):
    profile_manager = deps.pm()
    if profile_data.id:
        validate_pid(profile_data.id)
        if profile_manager.get_profile(profile_data.id):
            raise HTTPException(status_code=409, detail=f"Profile with id '{profile_data.id}' already exists")
    fp = profile_data.fingerprint
    if fp is not None and "webgl_renderer" not in fp.model_fields_set:
        ref = generate_random_fingerprint().model_copy()
        for field in ("webgl_vendor", "webgl_renderer", "webgl_unmasked_vendor", "webgl_unmasked_renderer"):
            setattr(fp, field, getattr(ref, field))
    created = profile_manager.create_profile(profile_data)
    await deps.broadcast_coro("profile_created", _mask_profile_secrets(created).model_dump())
    return _mask_profile_secrets(created)


@router.put("/api/profiles/{profile_id}", response_model=BrowserProfile, summary="Update profile settings")
async def update_profile(profile_id: str, profile_data: BrowserProfile):
    validate_pid(profile_id)
    profile_manager = deps.pm()
    profile_data.id = profile_id
    updated = profile_manager.update_profile(profile_data)
    if not updated:
        raise HTTPException(status_code=404, detail="Profile not found")
    await deps.broadcast_coro("profile_updated", _mask_profile_secrets(updated).model_dump())
    return _mask_profile_secrets(updated)


@router.delete("/api/profiles/{profile_id}", summary="Delete profile and local storage data")
async def delete_profile(profile_id: str):
    validate_pid(profile_id)
    profile_manager = deps.pm()
    browser_launcher = deps.bl()
    if browser_launcher.is_profile_running(profile_id):
        browser_launcher.stop(profile_id)
    deleted = profile_manager.delete_profile(profile_id, delete_data=True)
    if not deleted:
        raise HTTPException(status_code=404, detail="Profile not found")
    await deps.broadcast_coro("profile_deleted", {"profile_id": profile_id})
    return {"success": True, "message": "Profile deleted successfully"}


@router.post(
    "/api/profiles/{profile_id}/clone",
    response_model=BrowserProfile,
    summary="Clone profile with randomized hardware fingerprint",
)
async def clone_profile(profile_id: str, new_name: str | None = Query(None)):
    validate_pid(profile_id)
    profile_manager = deps.pm()
    cloned = profile_manager.clone_profile(profile_id, new_name)
    if not cloned:
        raise HTTPException(status_code=404, detail="Source profile not found")
    await deps.broadcast_coro("profile_created", _mask_profile_secrets(cloned).model_dump())
    return _mask_profile_secrets(cloned)


@router.post("/api/profiles/{profile_id}/launch", summary="Launch browser profile")
async def launch_profile(profile_id: str, req: LaunchRequest | None = None):
    validate_pid(profile_id)
    profile_manager = deps.pm()
    browser_launcher = deps.bl()
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
        await deps.broadcast_coro("profile_status_change", {"profile_id": profile_id, "status": "error", "error": err})
        raise HTTPException(status_code=400, detail=err or "Failed to launch browser")

    profile.status = ProfileStatus.RUNNING
    profile.pid = pid
    profile_manager.update_profile(profile)
    await deps.broadcast_coro("profile_status_change", {"profile_id": profile_id, "status": "running", "pid": pid})
    res = {"success": True, "pid": pid, "profile_id": profile_id}
    if port:
        res["port"] = port
        res["wsEndpoint"] = ws_url
    return res


@router.post("/api/profiles/{profile_id}/stop", summary="Stop running browser profile")
async def stop_profile(profile_id: str):
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


@router.post("/api/profiles/{profile_id}/clear-cache", summary="Purge browser cache for profile")
async def clear_cache(profile_id: str):
    validate_pid(profile_id)
    profile_manager = deps.pm()
    browser_launcher = deps.bl()
    if browser_launcher.is_profile_running(profile_id):
        raise HTTPException(
            status_code=400, detail="Cannot clear cache while browser is running. Please stop it first."
        )
    ok = profile_manager.clear_profile_cache(profile_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Profile '{profile_id}' not found")
    return {"success": True, "message": "Cache cleared successfully"}


@router.post(
    "/api/profiles/{profile_id}/seed-history",
    summary="Seed authentic Chromium browsing history records into profile",
)
async def seed_profile_history_endpoint(profile_id: str, entries_count: int = Query(25, ge=5, le=100)):
    validate_pid(profile_id)
    profile_manager = deps.pm()
    prof = profile_manager.get_profile(profile_id)
    if not prof:
        raise HTTPException(status_code=404, detail="Profile not found")
    inserted = profile_manager.seed_profile_history(profile_id, entries_count=entries_count)
    return {"success": True, "profile_id": profile_id, "seeded_entries": inserted}


@router.post(
    "/api/profiles/randomize-fingerprint",
    response_model=FingerprintConfig,
    summary="Generate random isolated hardware fingerprint",
)
async def randomize_fingerprint(os_type: str = Query("windows")):
    return generate_random_fingerprint(os_type=os_type)


@router.post("/api/profiles/bulk-import", summary="Bulk import profiles from proxy strings")
async def bulk_import_profiles(req: BulkImportRequest):
    profile_manager = deps.pm()
    lines = [line.strip() for line in req.proxy_lines.splitlines() if line.strip()]
    if not lines:
        raise HTTPException(status_code=400, detail="No valid proxy lines provided")
    if len(lines) > MAX_BULK_IMPORT_LINES:
        # 422: the request body violates the endpoint's documented bound
        # (500 lines, same cap as schemas.MAX_PROFILE_IDS), not the input
        # syntax — that keeps '400 = malformed content, 422 = request out of
        # contract' distinguishable for API consumers.
        raise HTTPException(
            status_code=422,
            detail=f"Too many proxy lines: {len(lines)} (max {MAX_BULK_IMPORT_LINES})",
        )
    created_list = []
    skipped: list[dict] = []

    for idx, line in enumerate(lines, start=len(profile_manager.list_profiles()) + 1):
        try:
            proxy_conf = ProxyConfig.parse(line)
        except ValueError as exc:
            # P-03: an explicit invalid port must fail LOUDLY for this line —
            # the operator sees exactly which entry is broken — but not kill
            # the rest of the batch.
            skipped.append({"line": line[:80], "error": str(exc)})
            continue
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

    await deps.broadcast_coro("profiles_bulk_created", {"count": len(created_list)})
    result: dict = {"created_count": len(created_list)}
    if skipped:
        result["skipped"] = skipped
        logger.warning("bulk-import skipped %d malformed proxy line(s)", len(skipped))
    return result


@router.post("/api/profiles/mass-generate", summary="1-Click mass profile generator (1-100+ farm)")
async def mass_generate_profiles_endpoint(req: MassGenerateRequest):
    profile_manager = deps.pm()
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
    await deps.broadcast_coro("profiles_bulk_created", {"count": len(created)})
    masked = []
    for p in created:
        item = _mask_profile_secrets(p).model_dump()
        item["proxy"] = _mask_proxy_for_api(p.proxy)
        masked.append(item)
    return {"success": True, "created_count": len(created), "profiles": masked}


@router.get(
    "/api/profiles/{profile_id}/bundle/export",
    summary="Export complete profile as portable .nazak archive",
)
async def export_profile_bundle_endpoint(profile_id: str):
    validate_pid(profile_id)
    profile_manager = deps.pm()
    prof = profile_manager.get_profile(profile_id)
    if not prof:
        raise HTTPException(status_code=404, detail="Profile not found")
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
