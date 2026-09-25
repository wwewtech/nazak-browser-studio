"""
Unit Tests for Scenario Engine and Autonomous Multi-Step Warmup.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from nazak.core.warmup_engine import BUILTIN_SCENARIOS, ScenarioExecutor, ScenarioStep, WarmupScenario
from nazak.models.profile import BrowserProfile, ProxyConfig


class _FakePage:
    """Minimal Playwright-page double for CDP action tests."""

    def __init__(self) -> None:
        self.scrolls: list[tuple[int, int]] = []
        self.evals: list[tuple] = []
        self.gotos: list[str] = []
        self.mouse = SimpleNamespace(wheel=self._wheel)

    async def _wheel(self, dx: int, dy: int):
        self.scrolls.append((dx, dy))

    async def evaluate(self, expr, *args):
        self.evals.append((expr, args))
        return ""

    async def goto(self, url, **kwargs):
        self.gotos.append(url)
        return None


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


# ---------------------------------------------------------------------------
# Audit C1 fixes: steps must execute real CDP actions, not just sleep
# ---------------------------------------------------------------------------


def test_human_scroll_executes_real_wheel_events():
    async def _run():
        launcher = MagicMock()
        pm = MagicMock()
        pm.get_profile.return_value = BrowserProfile(id="p", name="P", proxy=ProxyConfig())
        executor = ScenarioExecutor(launcher, pm)
        page = _FakePage()

        step = ScenarioStep("human_scroll", {"duration_sec": 0.6, "direction": "down"})
        ok = await executor.execute_step(step, "p", page=page)
        assert ok is True
        assert len(page.scrolls) >= 1
        assert all(dy > 0 for _, dy in page.scrolls)

    asyncio.run(_run())


def test_scroll_and_cookie_steps_require_page():
    async def _run():
        launcher = MagicMock()
        launcher.is_profile_running.return_value = False
        pm = MagicMock()
        pm.get_profile.return_value = BrowserProfile(id="p", name="P", proxy=ProxyConfig())
        executor = ScenarioExecutor(launcher, pm)

        assert await executor.execute_step(ScenarioStep("human_scroll", {"duration_sec": 0.5}), "p") is False
        assert await executor.execute_step(ScenarioStep("accept_cookie_dialog", {}), "p") is False

    asyncio.run(_run())


def test_navigation_with_running_browser_executes_goto():
    async def _run():
        launcher = MagicMock()
        launcher.is_profile_running.return_value = True
        pm = MagicMock()
        pm.get_profile.return_value = BrowserProfile(id="p", name="P", proxy=ProxyConfig())
        executor = ScenarioExecutor(launcher, pm)
        page = _FakePage()

        ok = await executor.execute_step(
            ScenarioStep("open_url", {"url": "https://www.amazon.com/s?k=test"}), "p", page=page
        )
        assert ok is True
        assert page.gotos == ["https://www.amazon.com/s?k=test"]
        launcher.launch.assert_not_called()  # no relaunch — real navigation happened

    asyncio.run(_run())


def test_navigation_with_running_browser_without_page_fails_loudly():
    async def _run():
        launcher = MagicMock()
        launcher.is_profile_running.return_value = True
        pm = MagicMock()
        pm.get_profile.return_value = BrowserProfile(id="p", name="P", proxy=ProxyConfig())
        executor = ScenarioExecutor(launcher, pm)

        ok = await executor.execute_step(ScenarioStep("open_url", {"url": "https://x.test"}), "p")
        assert ok is False  # old code returned True here, silently skipping the step

    asyncio.run(_run())


def test_cookie_dialog_step_calls_page_script():
    async def _run():
        launcher = MagicMock()
        pm = MagicMock()
        pm.get_profile.return_value = BrowserProfile(id="p", name="P", proxy=ProxyConfig())
        executor = ScenarioExecutor(launcher, pm)
        page = _FakePage()

        ok = await executor.execute_step(ScenarioStep("accept_cookie_dialog", {}), "p", page=page)
        assert ok is True
        assert page.evals and "onetrust-accept-btn-handler" in page.evals[0][0]

    asyncio.run(_run())


def test_run_scenario_stops_browser_it_started():
    async def _run():
        launcher = MagicMock()
        # 1st call (was_running) -> False; the run then launches the browser.
        launcher.is_profile_running.side_effect = [False] + [True] * 10
        pm = MagicMock()
        pm.get_profile.return_value = BrowserProfile(id="p", name="P", proxy=ProxyConfig())
        executor = ScenarioExecutor(launcher, pm)
        scenario = WarmupScenario(
            id="noop", name="Dwell only", steps=[ScenarioStep("dwell", {"min_sec": 0.01, "max_sec": 0.02})]
        )

        res = await executor.run_scenario_on_profile(scenario, "p")
        assert res["success"] is True
        launcher.stop.assert_called_once_with("p")

    asyncio.run(_run())


def test_run_scenario_keeps_user_opened_browser():
    async def _run():
        launcher = MagicMock()
        launcher.is_profile_running.return_value = True  # user had it open already
        pm = MagicMock()
        pm.get_profile.return_value = BrowserProfile(id="p", name="P", proxy=ProxyConfig())
        executor = ScenarioExecutor(launcher, pm)
        scenario = WarmupScenario(
            id="noop2", name="Dwell only", steps=[ScenarioStep("dwell", {"min_sec": 0.01, "max_sec": 0.02})]
        )

        res = await executor.run_scenario_on_profile(scenario, "p")
        assert res["success"] is True
        launcher.stop.assert_not_called()

    asyncio.run(_run())
