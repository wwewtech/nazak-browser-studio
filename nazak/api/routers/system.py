"""
System router (P0 refactor). Moved verbatim from nazak/api/server.py.
"""

import os

from fastapi import APIRouter

from ...config import PROFILES_DIR, find_chrome_executable
from ...core.secrets_store import SECRETS_MODES, SecretsError, get_current_mode, set_current_mode
from .. import deps
from ..realtime import ws_manager
from ..schemas import SecretsModeRequest

router = APIRouter(tags=["System"])


@router.get("/api/system/info", summary="Get system diagnostics and host telemetry")
async def get_system_info():
    chrome_exe = find_chrome_executable()
    profile_manager = deps.pm()
    browser_launcher = deps.bl()
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


@router.get(
    "/api/security/secrets-mode",
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


@router.post(
    "/api/security/secrets-mode",
    summary="Switch the secrets storage mode (user decision)",
)
async def post_secrets_mode(req: SecretsModeRequest):
    try:
        effective = set_current_mode(req.mode, passphrase=req.passphrase)
    except SecretsError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await ws_manager.broadcast("secrets_mode_changed", {"mode": effective})
    return {
        "success": True,
        "mode": effective,
        "message": (
            f"Secrets mode switched to '{effective}'. New imports will use it. Existing envelopes stay decodable."
        ),
    }
