"""P0 refactor regression: API split keeps routes, exports and behaviour."""

from fastapi.testclient import TestClient

import nazak.api.server as server
from nazak.api.server import app

EXPECTED_PATHS = (
    "/api/system/info",
    "/api/profiles",
    "/api/profiles/{profile_id}",
    "/api/profiles/{profile_id}/launch",
    "/api/profiles/{profile_id}/stop",
    "/api/profiles/batch-launch",
    "/api/profiles/batch-stop",
    "/api/profiles/mass-generate",
    "/api/profiles/bulk-import",
    "/api/profiles/{profile_id}/bundle/export",
    "/api/profiles/{profile_id}/rotate-proxy",
    "/api/profiles/{profile_id}/check",
    "/api/profiles/check-all",
    "/api/profiles/test-proxy",
    "/api/cookies/bulk-import",
    "/api/cookies/bulk-export",
    "/api/profiles/{profile_id}/cookies/import",
    "/api/profiles/{profile_id}/cookies/export",
    "/api/scenarios",
    "/api/scenarios/run",
    "/api/profiles/{profile_id}/warmup/plan",
    "/api/profiles/{profile_id}/warmup/launch",
    "/api/synchronizer/start",
    "/api/synchronizer/stop",
    "/api/synchronizer/status",
    "/api/synchronizer/tile-windows",
    "/api/synchronizer/navigate",
    "/api/autopost/status",
    "/api/autopost/launch",
    "/api/autopost/cancel",
    "/api/autopost/uniquify",
    "/api/autopost/preview-spintax",
    "/api/security/secrets-mode",
    "/v1.0/browser_profiles",
    "/v1.0/browser_profiles/active",
    "/v1.0/browser_profiles/{profile_id}/start",
    "/v1.0/browser_profiles/{profile_id}/stop",
    "/api/v1/profiles/{profile_id}/start",
    "/api/v1/profiles/{profile_id}/stop",
    "/api/v1/profiles/{profile_id}/cdp",
)

EXPECTED_EXPORTS = (
    "app",
    "profile_manager",
    "browser_launcher",
    "upload_queue_mgr",
    "video_uniquifier",
    "process_monitor",
    "synchronizer_mgr",
    "scenario_executor",
    "ws_manager",
    "on_process_state_change",
    "SCENARIO_ALIASES",
    "CSP_POLICY",
    "validate_pid",
    "resolve_media_source",
    "_rotation_target",
    "_reject_rotation_url",
    "_resolve_host_ips",
    "_build_pinned_opener",
    "_origin_matches_request",
    "_ALLOWED_PORTS",
    "_LOCAL_HOSTS",
    "configure_local_access",
    "enforce_exposure_policy",
    "AutopostBatchRequest",
    "MassGenerateRequest",
    "SynchronizerStartRequest",
    "uniquify_videos_endpoint",
    "rotate_profile_proxy_endpoint",
)


def test_p0_all_api_paths_still_mounted():
    """Every pre-split endpoint is still mounted on the app.

    The OpenAPI schema is the contract clients actually see, so it is the
    primary source of truth; the app's route objects are checked as well. The
    failure message reports the real state (route count, object identity, route
    classes and a sample), because a bare "routes lost" list said nothing about
    what had actually happened when this diverged in CI.
    """
    schema_paths = set(app.openapi()["paths"])
    route_paths = {getattr(r, "path", "") for r in app.routes}
    missing = [p for p in EXPECTED_PATHS if p not in schema_paths]
    not_mounted = sorted(schema_paths - route_paths)

    diagnostics = (
        f"\n  openapi paths       : {len(schema_paths)}"
        f"\n  app.routes          : {len(app.routes)} ({type(app.routes).__name__})"
        f"\n  route path sample   : {[getattr(r, 'path', None) for r in list(app.routes)[:6]]}"
        f"\n  route classes       : {sorted({type(r).__name__ for r in app.routes})}"
        f"\n  app is server.app   : {app is server.app}"
        f"\n  router identity     : {app.router is server.app.router}"
        f"\n  routes-without-path : {sum(1 for r in app.routes if not getattr(r, 'path', None))}"
    )

    assert not missing, f"routes lost in split: {missing}{diagnostics}"
    assert not not_mounted, f"schema paths not present on app.routes: {not_mounted}{diagnostics}"


def test_p0_server_exports_preserved():
    absent = [n for n in EXPECTED_EXPORTS if not hasattr(server, n)]
    assert not absent, f"server exports lost: {absent}"


def test_p0_routers_are_the_serving_handlers():
    from nazak.api.routers import automation, autopost, cookies, profiles, proxies, synchronizer, system, warmup

    assert server.list_profiles is profiles.list_profiles
    assert server.dolphin_start_profile is automation.dolphin_start_profile
    assert server.rotate_profile_proxy_endpoint is proxies.rotate_profile_proxy_endpoint
    assert server.bulk_import_cookies_endpoint is cookies.bulk_import_cookies_endpoint
    assert server.run_scenario_endpoint is warmup.run_scenario_endpoint
    assert server.start_synchronizer_endpoint is synchronizer.start_synchronizer_endpoint
    assert server.launch_autopost_batch is autopost.launch_autopost_batch
    assert server.get_system_info is system.get_system_info


def test_p0_split_endpoints_serve():
    client = TestClient(app)
    assert client.get("/api/system/info").status_code == 200
    assert client.get("/api/scenarios").status_code == 200
    assert client.get("/api/autopost/status").status_code == 200
    assert client.get("/api/synchronizer/status").status_code == 200
