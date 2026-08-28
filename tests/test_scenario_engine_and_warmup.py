"""
Unit Tests for Scenario Engine and Autonomous Multi-Step Warmup.
"""

from unittest.mock import MagicMock

import pytest

from nazak.core.warmup_engine import BUILTIN_SCENARIOS, ScenarioExecutor, ScenarioStep, WarmupScenario
from nazak.models.profile import BrowserProfile, ProxyConfig


def test_scenario_step_serialization():
    step = ScenarioStep("open_url", {"url": "https://www.google.com"}, "Navigate to Google")
    d = step.to_dict()
    assert d["action"] == "open_url"
    assert d["params"]["url"] == "https://www.google.com"

    recovered = ScenarioStep.from_dict(d)
    assert recovered.action == "open_url"
    assert recovered.description == "Navigate to Google"


def test_warmup_scenario_presets():
    assert len(BUILTIN_SCENARIOS) >= 4
    names = [s.name for s in BUILTIN_SCENARIOS]
    assert any("E-Commerce" in n for n in names)
    assert any("YouTube" in n for n in names)

    scen = BUILTIN_SCENARIOS[0]
    d = scen.to_dict()
    assert "id" in d
    assert "steps" in d
    assert d["total_steps"] == len(scen.steps)

    reconstructed = WarmupScenario.from_dict(d)
    assert reconstructed.id == scen.id
    assert len(reconstructed.steps) == len(scen.steps)


import asyncio


def test_scenario_executor_step_execution():
    async def _run():
        mock_launcher = MagicMock()
        mock_launcher.is_profile_running.return_value = False
        mock_launcher.launch.return_value = (True, 5555, None)

        mock_pm = MagicMock()
        p = BrowserProfile(id="scen_p1", name="Test Profile", proxy=ProxyConfig())
        mock_pm.get_profile.return_value = p

        executor = ScenarioExecutor(mock_launcher, mock_pm)

        # 1. Open URL Step
        step1 = ScenarioStep("open_url", {"url": "https://example.com"})
        ok1 = await executor.execute_step(step1, "scen_p1")
        assert ok1 is True

        # 2. Dwell Step
        step2 = ScenarioStep("dwell", {"min_sec": 0.01, "max_sec": 0.05})
        ok2 = await executor.execute_step(step2, "scen_p1")
        assert ok2 is True

        # 3. Full Scenario run
        custom_scen = WarmupScenario(id="quick_test", name="Quick Test", steps=[step1, step2])
        res = await executor.run_scenario_on_profile(custom_scen, "scen_p1")
        assert res["success"] is True
        assert res["completed_steps"] == 2

    asyncio.run(_run())
