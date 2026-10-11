"""Deep coverage for the system / secrets / cdp CLI commands.

`nazak/cli_cmds/system_secrets_cdp.py` was the least-covered non-GUI module
(~59%), and it carries three things agents depend on: the machine-readable
schema, the secrets-mode switch and the Dolphin-parity CDP commands.
"""

from __future__ import annotations

import contextlib
import json
import sys
from io import StringIO

import pytest

from nazak import cli
from nazak.core import secrets_store


def run(argv: list[str]) -> tuple[int, str, str]:
    """Run the CLI in-process; returns (exit_code, stdout, stderr)."""
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
    code, out, _err = run([*argv, "--json"])
    return code, json.loads(out)


@pytest.fixture()
def plain_mode_restored():
    """The secrets mode is process-global; always hand it back as `plain`."""
    before = secrets_store.get_current_mode()
    yield
    secrets_store.set_current_mode("plain")
    assert secrets_store.get_current_mode() == "plain" or before != "plain"


# ---------------------------------------------------------------------------
# system
# ---------------------------------------------------------------------------
def test_system_info_reports_host_and_counters():
    code, payload = run_json(["system", "info"])
    assert code == 0
    assert payload["success"] is True
    assert isinstance(payload["chrome_installed"], bool)
    assert payload["total_profiles"] >= 10, "a fresh store provisions the ten presets"
    assert payload["running_profiles"] == 0
    assert payload["data_directory"]
    assert payload["platform"]


def test_system_version_matches_the_package():
    import nazak

    code, payload = run_json(["system", "version"])
    assert code == 0
    assert payload["nazak"] == nazak.__version__
    assert payload["python"].startswith(str(sys.version_info.major))
    assert payload["platform"]
    assert payload["exe"] is False


def test_system_doctor_lists_every_preflight_check():
    code, payload = run_json(["system", "doctor"])
    assert code in (0, 4)
    assert payload["success"] is True
    checks = {c["name"]: c for c in payload["checks"]}
    assert {"data_dir", "profiles_db", "chrome", "ffmpeg", "secrets_mode", "python"} <= set(checks)
    assert isinstance(payload["overall_ok"], bool)
    assert payload["hint"], "a failing doctor must tell the agent what to fix"


def test_system_doctor_reports_the_active_storage_backend():
    _code, payload = run_json(["system", "doctor"])
    detail = next(c["detail"] for c in payload["checks"] if c["name"] == "profiles_db")
    assert "backend=" in detail, f"doctor must name the live storage backend, got: {detail}"
    assert "json" in detail or "sqlite" in detail


def test_system_doctor_overall_ok_matches_the_red_checks():
    code, payload = run_json(["system", "doctor"])
    red = [c for c in payload["checks"] if not c["ok"]]
    # api_server is informational in direct-core mode and must not fail the run.
    blocking = [c for c in red if c["name"] != "api_server"]
    assert payload["overall_ok"] is (not blocking)
    assert code == (0 if payload["overall_ok"] else 4)


def test_system_schema_is_machine_readable_and_complete():
    code, schema = run_json(["system", "schema"])
    assert code == 0 and schema["schema_version"] == 1
    groups = {g["group"] for g in schema["groups"]}
    assert {
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
    } <= groups
    for group in schema["groups"]:
        assert group["help"], f"{group['group']} has no help"
        for command in group["commands"]:
            assert command["help"], f"{group['group']} {command['name']} has no help"
            for arg in command["args"]:
                assert "flags" in arg and "dest" in arg


def test_system_schema_advertises_the_environment_contract():
    _code, schema = run_json(["system", "schema"])
    for flag in ("--json", "--yes", "--server", "--api-key", "--verbose"):
        assert flag in schema["global_flags"]
    for env in ("NAZAK_JSON", "NAZAK_YES", "NAZAK_API_TOKEN", "NAZAK_DATA_DIR", "NAZAK_PROFILE_STORE"):
        assert env in schema["env"], f"{env} is honoured by the CLI and must be advertised in the schema"
    assert schema["exit_codes"]["2"], "exit codes must stay documented for agents"


def test_system_schema_covers_the_cdp_group():
    _code, schema = run_json(["system", "schema"])
    cdp = next(g for g in schema["groups"] if g["group"] == "cdp")
    assert {c["name"] for c in cdp["commands"]} >= {"start", "stop", "active", "info"}


# ---------------------------------------------------------------------------
# secrets
# ---------------------------------------------------------------------------
def test_secrets_get_reports_the_mode_and_the_alternatives():
    code, payload = run_json(["secrets", "get"])
    assert code == 0
    assert payload["mode"] in secrets_store.SECRETS_MODES
    assert set(payload["available_modes"]) == set(secrets_store.SECRETS_MODES)
    assert payload["platform"]


def test_secrets_set_to_passphrase_without_a_passphrase_is_refused(plain_mode_restored):
    code, payload = run_json(["secrets", "set", "--mode", "passphrase"])
    assert code == 2, "a strong mode without a passphrase must be a usage error, not a silent switch"
    assert payload["success"] is False
    assert secrets_store.get_current_mode() != "passphrase"


def test_secrets_set_to_plain_succeeds_and_persists(tmp_path):
    from nazak.config import DATA_DIR

    code, payload = run_json(["--yes", "secrets", "set", "--mode", "plain"])
    assert code == 0 and payload["mode"] == "plain"
    mode_file = DATA_DIR / "secrets_mode.json"
    assert mode_file.exists(), "the selected mode must be persisted next to the data"
    assert json.loads(mode_file.read_text(encoding="utf-8"))["mode"] == "plain"


def test_secrets_set_rejects_an_unknown_mode():
    """argparse rejects an unknown mode; run_cli turns it into the usage exit code."""
    code, out, err = run(["secrets", "set", "--mode", "rootkit", "--json"])
    assert code == 2, "an unknown mode must be a usage error"
    assert out == "", "a usage failure must not emit a half-built JSON envelope"
    assert "invalid choice" in err and "rootkit" in err
    assert secrets_store.get_current_mode() != "rootkit"


def test_secrets_set_to_passphrase_with_a_passphrase_reencrypts(plain_mode_restored):
    code, payload = run_json(["--yes", "secrets", "set", "--mode", "passphrase", "--passphrase", "s3cret-phrase"])
    assert code == 0
    assert payload["mode"] == "passphrase"
    assert secrets_store.get_current_mode() == "passphrase"

    again, state = run_json(["secrets", "get"])
    assert again == 0 and state["mode"] == "passphrase"


# ---------------------------------------------------------------------------
# cdp
# ---------------------------------------------------------------------------
def test_cdp_active_returns_a_list():
    code, payload = run_json(["cdp", "active"])
    assert code == 0 and payload["success"] is True
    assert isinstance(payload.get("active") or payload.get("profiles") or [], list)


def test_cdp_info_of_an_unknown_profile_is_not_found():
    code, payload = run_json(["cdp", "info", "does_not_exist"])
    assert code == 1
    assert payload["success"] is False
    assert payload.get("hint") or payload.get("error")


def test_cdp_stop_of_an_unknown_profile_is_not_found():
    code, payload = run_json(["--yes", "cdp", "stop", "does_not_exist"])
    assert code == 1 and payload["success"] is False


def test_cdp_start_of_an_unknown_profile_is_not_found():
    code, payload = run_json(["cdp", "start", "does_not_exist"])
    assert code == 1 and payload["success"] is False


def test_cdp_start_reports_port_and_ws_endpoint(monkeypatch):
    from nazak.cli_cmds import common as cli_common

    created = run_json(["--yes", "profile", "create", "--name", "CDP Probe"])
    profile_id = created[1]["profile_id"]
    try:
        _pm, launcher = cli_common.get_managers()

        def fake_launch(profile, custom_url=None, port=None):
            return True, 4242, 9333, "ws://127.0.0.1:9333/devtools/browser/abc", None

        monkeypatch.setattr(launcher, "launch_with_cdp", fake_launch)
        code, payload = run_json(["cdp", "start", profile_id])
        assert code == 0
        automation = payload["automation"]
        assert automation["port"] == 9333
        assert automation["wsEndpoint"] == "ws://127.0.0.1:9333/devtools/browser/abc"
        assert payload["pid"] == 4242
    finally:
        run(["--yes", "profile", "delete", profile_id, "--json"])


def test_cdp_start_reports_a_launch_failure_as_a_conflict(monkeypatch):
    from nazak.cli_cmds import common as cli_common

    created = run_json(["--yes", "profile", "create", "--name", "CDP Fail Probe"])
    profile_id = created[1]["profile_id"]
    try:
        _pm, launcher = cli_common.get_managers()
        monkeypatch.setattr(
            launcher,
            "launch_with_cdp",
            lambda profile, custom_url=None, port=None: (False, None, None, None, "chrome exploded"),
        )
        code, payload = run_json(["cdp", "start", profile_id])
        assert code == 4
        assert payload["success"] is False
        assert "chrome exploded" in payload["error"]
    finally:
        run(["--yes", "profile", "delete", profile_id, "--json"])


# ---------------------------------------------------------------------------
# --server mode must fail loudly, never silently
# ---------------------------------------------------------------------------
def test_server_mode_without_a_reachable_server_is_a_conflict():
    code, payload = run_json(["--server", "http://127.0.0.1:9", "sync", "status"])
    assert code == 4, "an unreachable API must map to the conflict/transport exit code"
    assert payload["success"] is False
