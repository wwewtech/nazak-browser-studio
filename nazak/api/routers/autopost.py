"""
Autoposter router (P0 refactor). Moved verbatim from nazak/api/server.py.
"""

import asyncio
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException

from ...config import DATA_DIR
from ...core.spintax import format_video_metadata
from ...core.upload_queue import normalize_upload_platform
from .. import deps
from ..schemas import AutopostBatchRequest, UniquifyRequest
from ..security import resolve_media_source, validate_pid

router = APIRouter()


@router.get(
    "/api/autopost/status", tags=["YouTube Shorts Autoposter"], summary="Get autopost queue and FFmpeg encoder status"
)
async def get_autopost_status():
    upload_queue_mgr = deps.uqm()
    video_uniquifier = deps.vu()
    return {
        "is_running": upload_queue_mgr.is_running,
        "ffmpeg_available": video_uniquifier.is_ffmpeg_available(),
        "ffmpeg_path": video_uniquifier.ffmpeg_path,
        "jobs": upload_queue_mgr.get_jobs_status(),
    }


@router.post("/api/autopost/uniquify", tags=["YouTube Shorts Autoposter"], summary="Batch uniqueize video using FFmpeg")
async def uniquify_videos_endpoint(req: UniquifyRequest):
    video_uniquifier = deps.vu()
    for pid in req.profile_ids:
        validate_pid(pid)
    src = resolve_media_source(req.source_video_path)
    results = await asyncio.to_thread(video_uniquifier.batch_uniquify, src, req.profile_ids)
    formatted = {}
    for pid, (ok, path, err) in results.items():
        formatted[pid] = {"success": ok, "output_path": str(path.resolve()) if path else None, "error": err}
    return {"results": formatted, "count": len(results)}


def _generate_demo_video(path: Path) -> tuple[bool, str | None]:
    from ...core.video_uniquifier import generate_demo_clip

    return generate_demo_clip(path)


@router.post(
    "/api/autopost/launch",
    tags=["YouTube Shorts Autoposter"],
    summary="Launch autonomous YouTube Shorts or Instagram Reels upload queue",
)
async def launch_autopost_batch(req: AutopostBatchRequest, background_tasks: BackgroundTasks):
    for pid in req.profile_ids:
        validate_pid(pid)
    upload_queue_mgr = deps.uqm()
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


@router.post("/api/autopost/cancel", tags=["YouTube Shorts Autoposter"], summary="Cancel running autopost queue")
async def cancel_autopost():
    upload_queue_mgr = deps.uqm()
    upload_queue_mgr.cancel_all()
    return {"success": True, "message": "Autopost cancellation requested"}


@router.post(
    "/api/autopost/preview-spintax",
    tags=["YouTube Shorts Autoposter"],
    summary="Preview Spintax title and description generations",
)
async def preview_spintax_endpoint(req: AutopostBatchRequest):
    profile_manager = deps.pm()
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
