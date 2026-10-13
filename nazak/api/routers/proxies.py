"""
Proxies router (P0 refactor). Moved verbatim from nazak/api/server.py,
with patch-compatible resolver/opener lookups for the rotation endpoint.
"""

import asyncio
import urllib.error
import urllib.request
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from ...core.proxy_checker import check_proxy_health
from ...models.health import HealthCheckResult
from ...models.profile import BrowserProfile
from ...models.proxy import ProxyConfig
from .. import deps
from ..schemas import ProxyTestRequest
from ..security import (
    _build_pinned_opener,
    _is_display_mask_value,
    _resolve_resolver,
    _rotation_target,
    validate_pid,
)

router = APIRouter()


@router.post(
    "/api/profiles/{profile_id}/check",
    response_model=HealthCheckResult,
    tags=["Proxies"],
    summary="Perform 5-stage health check for profile proxy",
)
async def check_profile_proxy(profile_id: str):
    from ...config import PROFILES_DIR

    validate_pid(profile_id)
    profile_manager = deps.pm()
    profile = profile_manager.get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    user_data_path = PROFILES_DIR / profile.id
    result = await check_proxy_health(profile.proxy, profile_dir=user_data_path)
    profile.last_health_check = result

    if result.latitude is not None and result.longitude is not None:
        profile.fingerprint.geolocation.latitude = result.latitude
        profile.fingerprint.geolocation.longitude = result.longitude
    if result.timezone_name:
        profile.fingerprint.timezone = result.timezone_name

    profile_manager.update_profile(profile)

    await deps.broadcast_coro("profile_health_update", {"profile_id": profile_id, "health": result.model_dump()})
    return result


@router.post("/api/profiles/check-all", tags=["Proxies"], summary="Run proxy health checks across all profiles")
async def check_all_profiles():
    from ...config import PROFILES_DIR

    profile_manager = deps.pm()

    async def _check(p: BrowserProfile):
        res = await check_proxy_health(p.proxy, profile_dir=PROFILES_DIR / p.id)
        p.last_health_check = res
        p.updated_at = datetime.now(timezone.utc).isoformat()
        profile_manager.profiles[p.id] = p
        await deps.broadcast_coro("profile_health_update", {"profile_id": p.id, "health": res.model_dump()})
        return p.id, res

    profiles = profile_manager.list_profiles()
    await asyncio.gather(*[_check(p) for p in profiles], return_exceptions=True)
    profile_manager.save_profiles()
    return {"total_checked": len(profiles)}


@router.post(
    "/api/profiles/test-proxy",
    response_model=HealthCheckResult,
    tags=["Proxies"],
    summary="Test standalone raw proxy string",
)
async def test_raw_proxy(req: ProxyTestRequest):
    proxy_config = ProxyConfig.parse(req.raw_proxy)
    # Anti-detect invariant: a malformed string silently parsing into a DIRECT
    # connection made /test-proxy report a "healthy" local link — the operator
    # believes traffic goes through a proxy while the real IP is exposed.
    # DIRECT is an explicit choice (the string "direct"), never a fallback.
    if proxy_config.is_direct() and (req.raw_proxy or "").strip().lower() not in ("direct", "none", "null", ""):
        raise HTTPException(
            status_code=400,
            detail="Invalid proxy string: it does not contain a usable host:port and would silently degrade to a DIRECT (no-proxy) connection",
        )
    result = await check_proxy_health(proxy_config, profile_dir=None)
    return result


@router.post(
    "/api/profiles/{profile_id}/rotate-proxy", tags=["Proxies"], summary="Trigger mobile proxy IP rotation URL"
)
async def rotate_profile_proxy_endpoint(profile_id: str):
    validate_pid(profile_id)
    profile_manager = deps.pm()
    try:
        server_mod = __import__("nazak.api.server", fromlist=["_resolve_host_ips", "_build_pinned_opener"])
        resolve = getattr(server_mod, "_resolve_host_ips", None) or _resolve_resolver()
        build_opener = getattr(server_mod, "_build_pinned_opener", None) or _build_pinned_opener
    except Exception:
        resolve = _resolve_resolver()
        build_opener = _build_pinned_opener
    prof = profile_manager.get_profile(profile_id)
    if not prof:
        raise HTTPException(status_code=404, detail="Profile not found")
    if not prof.proxy.rotation_url:
        raise HTTPException(status_code=400, detail="Profile does not have a proxy rotation URL configured")
    url = prof.proxy.rotation_url
    if _is_display_mask_value(url):
        raise HTTPException(status_code=400, detail="Proxy rotation URL is masked; send the real URL to update it")
    import nazak.api.security as sec

    orig_resolver = sec._resolve_host_ips
    try:
        if resolve is not orig_resolver:
            sec._resolve_host_ips = resolve
        target = _rotation_target(url)
    finally:
        sec._resolve_host_ips = orig_resolver
    if isinstance(target, str):
        raise HTTPException(status_code=400, detail=f"Proxy rotation URL refused: {target}")
    _host, _port, pinned_ip = target
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Nazak-Studio"})
        opener = build_opener(pinned_ip)
        with opener.open(req, timeout=10.0) as resp:
            resp_body = resp.read().decode("utf-8", errors="ignore")
            return {"success": True, "status_code": resp.status, "response": resp_body[:200]}
    except urllib.error.HTTPError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Proxy rotation URL refused: unexpected HTTP status {exc.code}",
        ) from exc
    except Exception:
        raise HTTPException(status_code=502, detail="Proxy rotation request failed") from None


__all__ = ["router"]
