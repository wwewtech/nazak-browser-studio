"""
Cookies router (P0 refactor). Moved verbatim from nazak/api/server.py.
"""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from ...core.cookie_manager import (
    cookies_to_netscape,
    create_cookies_zip_archive,
    parse_any_cookies,
    parse_bulk_cookie_input,
)
from .. import deps
from ..schemas import BulkCookieExportRequest, BulkCookieImportRequest, CookieImportRequest
from ..security import validate_pid

router = APIRouter()


@router.post(
    "/api/cookies/bulk-import",
    tags=["Cookies"],
    summary="Bulk import multi-profile cookies (text blocks, JSON maps, ZIP)",
)
async def bulk_import_cookies_endpoint(req: BulkCookieImportRequest):
    profile_manager = deps.pm()
    cookie_map = parse_bulk_cookie_input(req.cookies_data)
    if not cookie_map:
        raise HTTPException(status_code=400, detail="No valid cookies parsed from input")
    res = profile_manager.batch_import_cookies(cookie_map, auto_create_missing=req.auto_create_missing, group=req.group)
    await deps.broadcast_coro("cookies_bulk_imported", res)
    return {"success": True, "results": res}


@router.post("/api/cookies/bulk-export", tags=["Cookies"], summary="Export cookies for the listed profiles")
async def bulk_export_cookies_endpoint(req: BulkCookieExportRequest):
    profile_manager = deps.pm()
    if not req.profile_ids:
        raise HTTPException(
            status_code=400,
            detail="profile_ids must be a non-empty list of profile ids",
        )
    for pid in req.profile_ids:
        validate_pid(pid)
    cookie_dict = profile_manager.export_all_cookies(req.profile_ids)
    export_format = req.format.lower()
    if export_format == "zip":
        zip_bytes = create_cookies_zip_archive(cookie_dict, format_type="json")
        return Response(
            content=zip_bytes,
            media_type="application/zip",
            headers={"Content-Disposition": "attachment; filename=nazak_cookies.zip"},
        )
    if export_format == "netscape":
        # The schema pattern accepts 'netscape', but the branch used to be missing:
        # the parameter was silently ignored and the JSON payload came back.
        # Mirrors the per-profile export contract (cookies_to_netscape content).
        combined = "".join(cookies_to_netscape(cookies) for cookies in cookie_dict.values())
        return {"format": "netscape", "content": combined, "profiles_count": len(cookie_dict)}
    return {"success": True, "cookies": cookie_dict, "profiles_count": len(cookie_dict)}


@router.get(
    "/api/profiles/{profile_id}/cookies/export",
    tags=["Cookies"],
    summary="Export profile cookies as JSON or Netscape format",
)
async def export_profile_cookies_endpoint(profile_id: str, format: str = Query("json")):
    validate_pid(profile_id)
    profile_manager = deps.pm()
    prof = profile_manager.get_profile(profile_id)
    if not prof:
        raise HTTPException(status_code=404, detail="Profile not found")
    cookies = profile_manager.load_profile_cookies(profile_id)
    if format.lower() == "netscape":
        return {"format": "netscape", "content": cookies_to_netscape(cookies), "cookies_count": len(cookies)}
    return {"format": "json", "cookies": cookies, "cookies_count": len(cookies)}


@router.post(
    "/api/profiles/{profile_id}/cookies/import",
    tags=["Cookies"],
    summary="Import cookies into profile (JSON or Netscape format)",
)
async def import_cookies_endpoint(profile_id: str, req: CookieImportRequest):
    validate_pid(profile_id)
    profile_manager = deps.pm()
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
