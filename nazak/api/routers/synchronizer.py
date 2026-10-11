"""
Synchronizer router (P0 refactor). Moved verbatim from nazak/api/server.py.
"""

from fastapi import APIRouter, Body, HTTPException

from .. import deps
from ..schemas import SynchronizerNavigateRequest, SynchronizerStartRequest, WindowTileRequest
from ..security import validate_pid

router = APIRouter()


@router.post(
    "/api/synchronizer/start", tags=["Synchronizer"], summary="Start Master-to-Workers action synchronizer session"
)
async def start_synchronizer_endpoint(req: SynchronizerStartRequest):
    synchronizer_mgr = deps.sync_mgr()
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
    await deps.broadcast_coro("synchronizer_started", session.to_dict())
    return {"success": True, "session": session.to_dict()}


@router.post("/api/synchronizer/stop", tags=["Synchronizer"], summary="Stop active synchronizer session")
async def stop_synchronizer_endpoint():
    synchronizer_mgr = deps.sync_mgr()
    synchronizer_mgr.stop_session()
    await deps.broadcast_coro("synchronizer_stopped", {})
    return {"success": True, "message": "Synchronizer stopped"}


@router.get("/api/synchronizer/status", tags=["Synchronizer"], summary="Get synchronizer session status")
async def get_synchronizer_status():
    synchronizer_mgr = deps.sync_mgr()
    return synchronizer_mgr.get_status()


@router.post(
    "/api/synchronizer/tile-windows",
    tags=["Synchronizer"],
    summary="Arrange active browser windows into Win32 grid layout",
)
async def tile_windows_endpoint(req: WindowTileRequest = Body(default=WindowTileRequest())):
    synchronizer_mgr = deps.sync_mgr()
    ok = synchronizer_mgr.tile_active_windows(cols=req.cols)
    return {"success": ok}


@router.post(
    "/api/synchronizer/navigate", tags=["Synchronizer"], summary="Broadcast URL navigation to all worker browsers"
)
async def synchronizer_navigate(req: SynchronizerNavigateRequest):
    synchronizer_mgr = deps.sync_mgr()
    results = await synchronizer_mgr.mirror_navigation(req.url)
    return {"success": True, "results": results}
