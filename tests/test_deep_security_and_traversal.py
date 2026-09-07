"""
Deep security, CORS lockdown, path traversal defense, and input sanitization test suite.
Contains 25 comprehensive tests verifying defenses against C3, M3, H11, and injection vectors.
"""

import io
import json
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from starlette.testclient import TestClient

from nazak.api.server import app as fastapi_app, validate_pid
from nazak.core.profile_manager import ProfileManager
from nazak.models.profile import BrowserProfile


# ---------------------------------------------------------------------------
# 1-4: CORS lockdown and origin verification tests
# ---------------------------------------------------------------------------
def test_cors_rejects_arbitrary_https_domains():
    client = TestClient(fastapi_app)
    for bad_origin in ["https://attacker.com", "https://google.com", "https://evil.org"]:
        resp = client.get("/api/system/info", headers={"Origin": bad_origin})
        acao = resp.headers.get("access-control-allow-origin")
        assert acao != bad_origin, f"CORS allowed arbitrary origin: {bad_origin}"


def test_cors_rejects_subdomain_spoofing():
    client = TestClient(fastapi_app)
    for spoofed in ["https://localhost.evil.com", "https://127.0.0.1.attacker.io", "http://evil-localhost"]:
        resp = client.get("/api/system/info", headers={"Origin": spoofed})
        acao = resp.headers.get("access-control-allow-origin")
        assert acao != spoofed, f"CORS allowed spoofed origin: {spoofed}"


def test_cors_rejects_null_origin():
    client = TestClient(fastapi_app)
    resp = client.get("/api/system/info", headers={"Origin": "null"})
    acao = resp.headers.get("access-control-allow-origin")
    assert acao != "null"


def test_cors_allows_localhost_with_arbitrary_ports():
    client = TestClient(fastapi_app)
    for local in ["http://localhost:3000", "http://localhost:8080", "http://127.0.0.1:5173", "http://localhost"]:
        resp = client.get("/api/system/info", headers={"Origin": local})
        assert resp.headers.get("access-control-allow-origin") == local


# ---------------------------------------------------------------------------
# 5-12: validate_pid input validation and rejection of attack payloads
# ---------------------------------------------------------------------------
def test_validate_pid_rejects_windows_drive_letters():
    for bad in ["C:prof", "D:\\prof", "C:/Windows", "E:data"]:
        with pytest.raises(HTTPException) as exc:
            validate_pid(bad)
        assert exc.value.status_code == 400


def test_validate_pid_rejects_relative_traversal_dotdot():
    for bad in ["../prof", "../../etc/passwd", "..\\prof", "prof/../evil", "prof\\..\\evil"]:
        with pytest.raises(HTTPException) as exc:
            validate_pid(bad)
        assert exc.value.status_code == 400


def test_validate_pid_rejects_single_dot_and_double_dot():
    for bad in [".", ".."]:
        with pytest.raises(HTTPException) as exc:
            validate_pid(bad)
        assert exc.value.status_code == 400


def test_validate_pid_rejects_empty_and_whitespace():
    for bad in ["", "   ", "\t", "\n", " \t \n "]:
        with pytest.raises(HTTPException) as exc:
            validate_pid(bad)
        assert exc.value.status_code == 400


def test_validate_pid_rejects_shell_metacharacters():
    for bad in ["prof;rm -rf", "prof&calc", "prof|dir", "prof$HOME", "prof`whoami`", "prof>out"]:
        with pytest.raises(HTTPException) as exc:
            validate_pid(bad)
        assert exc.value.status_code == 400


def test_validate_pid_rejects_null_bytes():
    with pytest.raises(HTTPException) as exc:
        validate_pid("prof\x00_01")
    assert exc.value.status_code == 400


def test_validate_pid_rejects_spaces_and_quotes():
    for bad in ["prof 01", "prof'01", 'prof"01', "prof`01"]:
        with pytest.raises(HTTPException) as exc:
            validate_pid(bad)
        assert exc.value.status_code == 400


def test_validate_pid_allows_standard_slugs():
    for good in ["prof_01", "prof-valid-123", "P12345", "profile_production_99", "a"]:
        assert validate_pid(good) == good


# ---------------------------------------------------------------------------
# 13-19: API endpoint defense against path traversal
# ---------------------------------------------------------------------------
def test_api_profile_endpoints_reject_traversal_ids():
    client = TestClient(fastapi_app)
    bad_pids = ["prof..evil", "prof.dot", "prof$calc", "prof;test"]
    for bad in bad_pids:
        resp = client.get(f"/api/profiles/{bad}")
        assert resp.status_code == 400
        assert "invalid profile_id" in resp.json()["detail"].lower()


def test_api_delete_profile_rejects_traversal():
    client = TestClient(fastapi_app)
    resp = client.delete("/api/profiles/prof..evil")
    assert resp.status_code == 400


def test_api_clear_cache_rejects_traversal():
    client = TestClient(fastapi_app)
    resp = client.post("/api/profiles/prof..evil/clear-cache")
    assert resp.status_code == 400


def test_api_cookies_export_rejects_traversal():
    client = TestClient(fastapi_app)
    resp = client.get("/api/profiles/prof..evil/cookies/export")
    assert resp.status_code == 400


def test_api_cookies_import_rejects_traversal():
    client = TestClient(fastapi_app)
    resp = client.post("/api/profiles/prof..evil/cookies/import", json={"cookies_data": "[]"})
    assert resp.status_code == 400


def test_api_warmup_plan_rejects_traversal():
    client = TestClient(fastapi_app)
    resp = client.post("/api/profiles/prof..evil/warmup/plan", json={"niche": "tech", "steps_count": 5})
    assert resp.status_code == 400


def test_api_warmup_launch_rejects_traversal():
    client = TestClient(fastapi_app)
    resp = client.post("/api/profiles/prof..evil/warmup/launch", json={"niche": "tech", "steps_count": 5})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# 20-22: ProfileManager boundary checks on filesystem operations
# ---------------------------------------------------------------------------
def test_profile_manager_delete_profile_boundary_check(tmp_path):
    pfile = tmp_path / "profiles.json"
    pdir = tmp_path / "profiles"
    pm = ProfileManager(pfile, pdir)
    with pytest.raises(ValueError, match="Invalid profile ID"):
        pm.delete_profile("../outside")


def test_profile_manager_clear_cache_boundary_check(tmp_path):
    pfile = tmp_path / "profiles.json"
    pdir = tmp_path / "profiles"
    pm = ProfileManager(pfile, pdir)
    with pytest.raises(ValueError, match="Invalid profile ID"):
        pm.clear_profile_cache("../../bad_id")


def test_profile_manager_disk_size_boundary_check(tmp_path):
    pfile = tmp_path / "profiles.json"
    pdir = tmp_path / "profiles"
    pm = ProfileManager(pfile, pdir)
    # Traversal ID must safely return 0 without accessing outside directories
    assert pm.get_profile_disk_size_bytes("../bad_id") == 0


# ---------------------------------------------------------------------------
# 23-24: Zip-slip archive evasion attacks during bundle import
# ---------------------------------------------------------------------------
def test_zip_slip_absolute_paths_ignored(tmp_path):
    pfile = tmp_path / "profiles.json"
    pdir = tmp_path / "profiles"
    pm = ProfileManager(pfile, pdir)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("profile.json", json.dumps({"name": "Slip Abs"}))
        # Absolute path on Windows or Unix
        zf.writestr("data/C:/Windows/system32/cmd.exe", "MALICIOUS")
        zf.writestr("data//etc/passwd", "MALICIOUS")
        zf.writestr("data/valid.txt", "VALID")
    buf.seek(0)

    bundle_path = tmp_path / "slip_abs.nazak"
    bundle_path.write_bytes(buf.getvalue())

    imported = pm.import_profile_bundle(bundle_path)
    assert imported is not None
    assert (pdir / imported.id / "valid.txt").exists()
    assert not Path("C:/Windows/system32/cmd.exe.tmp").exists()


def test_zip_slip_unc_and_dotdot_parts_ignored(tmp_path):
    pfile = tmp_path / "profiles.json"
    pdir = tmp_path / "profiles"
    pm = ProfileManager(pfile, pdir)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("profile.json", json.dumps({"name": "Slip UNC"}))
        zf.writestr("data/..\\..\\root.txt", "MALICIOUS")
        zf.writestr("data/nested/../../escaped.txt", "MALICIOUS")
        zf.writestr("data/ok/file.dat", "OK")
    buf.seek(0)

    bundle_path = tmp_path / "slip_unc.nazak"
    bundle_path.write_bytes(buf.getvalue())

    imported = pm.import_profile_bundle(bundle_path)
    assert imported is not None
    assert not (tmp_path / "root.txt").exists()
    assert not (tmp_path / "escaped.txt").exists()
    assert (pdir / imported.id / "ok" / "file.dat").exists()


# ---------------------------------------------------------------------------
# 25: CLI credentials masking in stdout
# ---------------------------------------------------------------------------
def test_cli_env_credentials_masked_in_stdout(capsys):
    from nazak.cli_auto_login_and_upload import run_live_flow

    with (
        patch.dict(
            "os.environ", {"GOOGLE_PASSWORD": "SecretSuperPassword123!", "GOOGLE_TOTP_SECRET": "JBSWY3DPEHPK3PXP"}
        ),
        patch("nazak.cli_auto_login_and_upload.async_playwright") as mock_pw,
    ):
        # Let run_live_flow exit early or mock playwright context
        mock_pw.side_effect = RuntimeError("Abort flow for test")
        try:
            import asyncio

            asyncio.run(run_live_flow())
        except Exception:
            pass
    captured = capsys.readouterr().out
    assert "SecretSuperPassword123!" not in captured
    assert "**********************" in captured or "******" in captured
