"""
Scenarios & Warmup router (P0 refactor). Moved verbatim from nazak/api/server.py.
"""

from fastapi import APIRouter, BackgroundTasks, HTTPException

from ...core.warmup_engine import (
    BUILTIN_SCENARIOS,
    WarmupPlan,
    WarmupScenario,
    generate_warmup_urls,
)
from ...models.profile import ProfileStatus
from .. import deps
from ..schemas import ScenarioRunRequest, WarmupRequest
from ..security import _require_launch_url, validate_pid

router = APIRouter()

SCENARIO_ALIASES: dict[str, str] = {
    "ecommerce_trust_booster": "scen_ecom_trust",
    "youtube_shorts_warmup": "scen_youtube_viewer",
    "crypto_web3_farming": "scen_crypto_web3",
    "finance_high_cpc_banking": "scen_finance_banking",
}


@router.get("/api/scenarios", tags=["Scenarios & Warmup"], summary="List built-in warmup scenarios")
async def list_scenarios():
    return [s.to_dict() for s in BUILTIN_SCENARIOS]


@router.post(
    "/api/scenarios/run", tags=["Scenarios & Warmup"], summary="Run scenario across profile pool with concurrency limit"
)
async def run_scenario_endpoint(req: ScenarioRunRequest, background_tasks: BackgroundTasks):
    scenario_executor = deps.scen_exec()
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


@router.post(
    "/api/profiles/{profile_id}/warmup/plan", tags=["Scenarios & Warmup"], summary="Generate organic warmup search plan"
)
async def get_warmup_plan(profile_id: str, req: WarmupRequest):
    validate_pid(profile_id)
    plan = WarmupPlan(profile_id=profile_id, niche=req.niche, steps_count=req.steps_count)
    return plan.to_dict()


@router.post(
    "/api/profiles/{profile_id}/warmup/launch",
    tags=["Scenarios & Warmup"],
    summary="Launch profile on warmup start URL",
)
async def launch_warmup(profile_id: str, req: WarmupRequest):
    validate_pid(profile_id)
    profile_manager = deps.pm()
    browser_launcher = deps.bl()
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
