"""Agent-comfort: schema/doctor/version/ensure, неинтерактивные confirm, env-флаги, ApiError-коды."""

import contextlib
import json
import sys
from io import StringIO

import pytest

from nazak import cli
from nazak.cli_cmds.common import ApiError, api_error_code


def run(argv: list[str]) -> tuple[int, str, str]:
    old = sys.argv
    sys.argv = ["nazak", *argv]
    try:
        out, err = StringIO(), StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.run_cli()
        return int(code), out.getvalue(), err.getvalue()
    finally:
        sys.argv = old


def run_json(argv: list[str]) -> tuple[int, dict]:
    code, out, _ = run([*argv, "--json"])
    return code, json.loads(out)


def test_system_schema_covers_all_gui_groups():
    code, schema = run_json(["system", "schema"])
    assert code == 0 and schema["schema_version"] == 1
    groups = {g["group"]: g for g in schema["groups"]}
    for grp in (
        "profile",
        "cookie",
        "proxy",
        "warmup",
        "scenario",
        "sync",
        "autopost",
        "account",
        "system",
        "secrets",
        "cdp",
        "legacy",
    ):
        assert grp in groups, f"missing group {grp}"
    profile_cmds = {c["name"] for c in groups["profile"]["commands"]}
    assert {
        "list",
        "get",
        "create",
        "update",
        "delete",
        "clone",
        "ensure",
        "launch",
        "stop",
        "batch-launch",
        "mass-generate",
        "bundle-export",
        "bundle-import",
        "seed-history",
        "clear-cache",
    } <= profile_cmds
    # у каждой команды есть help и типизированные аргументы
    for g in schema["groups"]:
        for cmd in g["commands"]:
            assert cmd["help"], f"{g['group']} {cmd['name']} без help"
            for arg in cmd["args"]:
                assert "flags" in arg and "dest" in arg
    assert "NAZAK_JSON" in schema["env"]


def test_system_doctor_reports_checks():
    code, payload = run_json(["system", "doctor"])
    assert code in (0, 4)
    assert payload["success"] is True
    names = {c["name"] for c in payload["checks"]}
    assert {"data_dir", "profiles_db", "chrome", "ffmpeg", "secrets_mode", "python"} <= names
    assert isinstance(payload["overall_ok"], bool)


def test_system_version():
    code, payload = run_json(["system", "version"])
    assert code == 0 and payload["nazak"] and payload["python"]


def test_profile_ensure_is_idempotent():
    code, first = run_json(["profile", "ensure", "--name", "Agent Ensure Probe"])
    assert code == 0 and first["created"] is True
    pid = first["profile_id"]
    code, second = run_json(["profile", "ensure", "--name", "Agent Ensure Probe"])
    assert code == 0 and second["created"] is False and second["profile_id"] == pid
    run(["--yes", "profile", "delete", pid, "--json"])


def test_delete_without_yes_in_json_gives_hint_not_hang():
    code, created = run_json(["profile", "create", "--name", "Agent Del Probe"])
    pid = created["profile_id"]
    try:
        code, payload = run_json(["profile", "delete", pid])
        assert code == 4  # не висит на input(), не молча отменяется с 0
        assert payload["success"] is False
        assert "--yes" in payload.get("hint", "")
    finally:
        run(["--yes", "profile", "delete", pid, "--json"])


def test_env_flags_replace_cli_flags(monkeypatch):
    monkeypatch.setenv("NAZAK_JSON", "1")
    code, out, _ = run(["system", "version"])  # без --json во argv
    assert code == 0
    assert json.loads(out)["success"] is True


def test_api_error_code_mapping():
    assert api_error_code(404) == 1
    assert api_error_code(400) == 2
    assert api_error_code(409) == 2
    assert api_error_code(422) == 2
    assert api_error_code(500) == 4
    err = ApiError(404, "Profile not found")
    assert err.status == 404 and "Profile not found" in str(err.detail)
