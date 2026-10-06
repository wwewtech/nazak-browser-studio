"""Round-3b regression tests: честный фон `scenario run` (R3b-01)."""

from __future__ import annotations

import os
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from nazak.core import synchronizer as sync


def test_r3b_background_scenario_spawns_detached_process(tmp_path, monkeypatch):
    from nazak import config as nazak_config
    from nazak.cli_cmds import automation

    monkeypatch.setattr(nazak_config, "LOGS_DIR", tmp_path, raising=False)
    args = SimpleNamespace(
        profiles=["p1", "p2"],
        scenario="scen_ecom_trust",
        scenario_file=None,
        concurrency=2,
        **{"all": False},
    )
    cmd = automation._background_scenario_command(args)
    assert cmd[1:4] == ["-m", "nazak.cli", "scenario"]
    assert "--wait" in cmd and "--profiles" in cmd and "p1,p2" in cmd
    assert "--concurrency" in cmd

    captured: dict = {}

    class _FakePopen:
        def __init__(self, argv, **kwargs):
            captured["argv"] = argv
            captured["kwargs"] = kwargs
            self.pid = 4242

        def wait(self, timeout=None):  # pragma: no cover - не вызывается
            return 0

    with patch("subprocess.Popen", _FakePopen):
        launched = automation._spawn_background_scenario(args, ["p1", "p2"])
    assert launched is not None
    pid, log_path = launched
    assert pid == 4242
    assert Path(log_path).parent == tmp_path
    assert captured["kwargs"]["stdin"] is not None
    assert captured["kwargs"].get("stdout") is not None
    if os.name == "nt":
        assert captured["kwargs"]["creationflags"] & 0x00000008  # DETACHED_PROCESS
    else:
        assert captured["kwargs"]["start_new_session"] is True


def test_r3b_background_scenario_reports_spawn_failure(tmp_path, monkeypatch):
    from nazak import config as nazak_config
    from nazak.cli_cmds import automation

    monkeypatch.setattr(nazak_config, "LOGS_DIR", tmp_path, raising=False)
    args = SimpleNamespace(profiles=["p1"], scenario="s", scenario_file=None, concurrency=None, **{"all": False})
    with patch("subprocess.Popen", side_effect=OSError("no exec")):
        assert automation._spawn_background_scenario(args, ["p1"]) is None


def test_r3b_automation_has_no_daemon_thread_for_scenario_run():
    source = (
        Path(sync.__file__).parent.joinpath("..", "cli_cmds", "automation.py").resolve().read_text(encoding="utf-8")
    )
    assert "threading.Thread(target=_bg, daemon=True" not in source
    assert "_spawn_background_scenario" in source


def test_r3b_scenario_run_background_log_dir_is_under_data(tmp_path, monkeypatch):
    from nazak.config import LOGS_DIR

    assert str(LOGS_DIR).endswith("logs")
    assert re.search(r"scenario_\d{8}_\d{6}\.log", "scenario_20260101_120000.log")
