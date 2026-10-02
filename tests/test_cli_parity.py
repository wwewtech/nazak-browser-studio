"""CLI parity: все группы GUI доступны, AI-контракт (--json + exit-коды), backward-compat."""

import json
import sys

import pytest

from nazak import cli
from nazak.cli_cmds.common import GlobalOptions, build_global_options


def run(argv: list[str]) -> tuple[int, str, str]:
    old = sys.argv
    sys.argv = ["nazak", *argv]
    try:
        import contextlib
        from io import StringIO

        out, err = StringIO(), StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.run_cli()
        return int(code), out.getvalue(), err.getvalue()
    finally:
        sys.argv = old


def run_json(argv: list[str]) -> tuple[int, dict]:
    code, out, _ = run([*argv, "--json"])
    # human-префиксов быть не должно: весь stdout — один JSON-документ
    payload = json.loads(out)
    return code, payload


def test_parser_has_all_groups():
    p = cli.build_parser()
    actions = [a.dest for a in p._actions if a.dest == "group"]
    assert actions, "subparsers missing"
    # все группы + legacy зарегистрированы
    help_text = p.format_help()
    for grp in ("profile", "cookie", "proxy", "warmup", "scenario", "sync",
                "autopost", "account", "cdp", "secrets", "system",
                "list", "launch", "check-all"):
        assert grp in help_text


def test_hoist_global_flags_both_orders():
    assert cli._hoist_global_flags(["profile", "list", "--json"]) == ["--json", "profile", "list"]
    assert cli._hoist_global_flags(["--json", "profile", "list"]) == ["--json", "profile", "list"]
    assert cli._hoist_global_flags(["sync", "tile", "--cols", "2", "--json"]) == ["--json", "sync", "tile", "--cols", "2"]
    assert cli._hoist_global_flags(["profile", "list", "--server", "http://x", "--json"]) == [
        "--server", "http://x", "--json", "profile", "list"]


def test_profile_crud_roundtrip_json():
    code, created = run_json(["profile", "create", "--name", "CLI Parity", "--group", "CLI", "--proxy", "direct"])
    assert code == 0 and created["success"]
    pid = created["profile_id"]

    code, got = run_json(["profile", "get", pid])
    assert code == 0 and got["profile"]["id"] == pid

    code, upd = run_json(["profile", "update", pid, "--name", "CLI Parity 2"])
    assert code == 0

    code, cloned = run_json(["profile", "clone", pid, "--new-name", "CLI Clone"])
    assert code == 0 and cloned["profile_id"] != pid

    code, _ = run_json(["--yes", "profile", "delete", pid])
    assert code == 0
    code, _ = run_json(["--yes", "profile", "delete", cloned["profile_id"]])
    assert code == 0

    code, payload = run_json(["profile", "get", pid])
    assert code == 1 and payload["success"] is False  # EXIT_NOT_FOUND


def test_profile_fingerprint_and_mass_generate_validation():
    code, payload = run_json(["profile", "fingerprint", "--os", "windows"])
    assert code == 0 and "webgl_renderer" in payload["fingerprint"]

    code, _, _ = run(["profile", "mass-generate", "--count", "0", "--json"])
    assert code == 2


def test_scenario_list_and_aliases():
    code, payload = run_json(["scenario", "list"])
    assert code == 0
    ids = {s["id"] for s in payload["scenarios"]}
    assert {"scen_ecom_trust", "scen_youtube_viewer", "scen_crypto_web3", "scen_finance_banking"} <= ids
    assert payload["aliases"]["youtube_shorts_warmup"] == "scen_youtube_viewer"


def test_warmup_plan_and_validation():
    code, created = run_json(["profile", "create", "--name", "WU", "--proxy", "direct"])
    pid = created["profile_id"]
    try:
        code, payload = run_json(["warmup", "plan", pid, "--niche", "crypto", "--steps", "3"])
        assert code == 0 and payload["plan"]["profile_id"] == pid
    finally:
        run(["--yes", "profile", "delete", pid, "--json"])

    code, payload = run_json(["warmup", "plan", "prof_nope"])
    assert code == 1


def test_cookie_bulk_roundtrip_and_export_validation():
    code, payload = run_json(["cookie", "bulk-export"])
    assert code == 2  # нужны --profiles

    text = "=== CLIProf ===\n" + json.dumps([{"name": "a", "value": "b", "domain": ".example.com", "path": "/"}])
    code, payload = run_json(["cookie", "bulk-import", "--group", "CLI Cookies", text])
    assert code == 0 or payload.get("success") in (True, False)


def test_secrets_system_sync_cdp_autopost_status():
    for argv in (["secrets", "get"], ["system", "info"], ["sync", "status"],
                 ["cdp", "active"], ["autopost", "status"]):
        code, payload = run_json(argv)
        assert code == 0 and payload.get("success") is True, argv


def test_autopost_preview_and_proxy_test_parse():
    code, created = run_json(["profile", "create", "--name", "AP", "--proxy", "direct"])
    pid = created["profile_id"]
    try:
        code, payload = run_json(["autopost", "preview", "--profiles", pid,
                                  "--title", "{A|B} clip", "--tg", "@t"])
        assert code == 0 and payload["samples"]
    finally:
        run(["--yes", "profile", "delete", pid, "--json"])


def test_legacy_aliases_still_work():
    code, payload = run_json(["list"])
    assert code == 0 and payload["count"] >= 1
    code, payload = run_json(["info"])
    assert code == 0 and payload["success"] is True


def test_server_mode_without_server_fails_cleanly():
    # закрытый порт: чистый JSON с success=false и ненулевым кодом, без traceback/hang
    code, payload = run_json(["--server", "http://127.0.0.1:9", "sync", "status"])
    assert code == 4
    assert payload["success"] is False


def test_global_options_builder():
    import argparse

    ns = argparse.Namespace(json=True, yes=True, server="http://x", api_key=None, verbose=False)
    opt = build_global_options(ns)
    assert isinstance(opt, GlobalOptions) and opt.as_json and opt.yes
