"""
Automated Google Account & Profile Warmup Engine.
Generates human search paths, natural organic navigation, and history/cookie accumulation.
"""
import random
import asyncio
import time
from typing import List, Dict, Any, Optional

WARMUP_NICHES = {
    "ecommerce": [
        "best wireless noise cancelling headphones 2026",
        "top mechanical keyboards for programming",
        "best ergonomic office chair review",
        "buy macbook air m3 best price",
        "portable power bank 20000mah fast charge",
        "4k gaming monitor 144hz comparison",
        "smart home zigbee motion sensors"
    ],
    "finance": [
        "sp500 etf index performance 2026",
        "best high yield savings accounts interest rates",
        "how to calculate compound interest formula",
        "real estate investment trust dividend yields",
        "term life insurance quotes calculator",
        "credit card reward points strategies"
    ],
    "tech": [
        "python 3.13 new features and performance",
        "docker compose best practices for microservices",
        "fastapi vs django rest framework benchmarks",
        "chrome extensions manifest v3 background workers",
        "webrtc stun turn server configuration",
        "kubernetes cluster monitoring grafana prometheus"
    ],
    "travel": [
        "best places to visit in switzerland summer",
        "flights from new york to london direct",
        "hotel booking tips cancel anytime",
        "travel insurance coverage international trip",
        "scenic train routes in europe alps"
    ],
    "crypto": [
        "bitcoin halving cycle history and price chart",
        "ethereum layer 2 rollup gas fees comparison",
        "hardware wallet security ledger vs trezor",
        "decentralized finance liquidity pool yields"
    ]
}

class WarmupPlan:
    """
    Structured warmup execution plan for a browser profile.
    """
    def __init__(self, profile_id: str, niche: str = "ecommerce", steps_count: int = 5):
        self.profile_id = profile_id
        self.niche = niche if niche in WARMUP_NICHES else "ecommerce"
        self.steps_count = min(max(steps_count, 1), 20)
        self.queries = self._select_queries()

    def _select_queries(self) -> List[str]:
        pool = WARMUP_NICHES[self.niche]
        return random.sample(pool, min(self.steps_count, len(pool)))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "niche": self.niche,
            "steps_count": len(self.queries),
            "search_queries": self.queries,
            "estimated_duration_minutes": len(self.queries) * 1.5
        }

def generate_warmup_urls(queries: List[str]) -> List[str]:
    """Generates direct Google search URLs from query list."""
    urls = []
    for q in queries:
        encoded = q.replace(" ", "+")
        urls.append(f"https://www.google.com/search?q={encoded}&hl=en")
    return urls

from dataclasses import dataclass, field
import uuid

@dataclass
class ScenarioStep:
    action: str  # "open_url", "google_search", "human_scroll", "dwell", "click_internal_link", "watch_youtube", "accept_cookie_dialog"
    params: Dict[str, Any] = field(default_factory=dict)
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "params": self.params,
            "description": self.description
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScenarioStep":
        return cls(
            action=data.get("action", "open_url"),
            params=data.get("params", {}),
            description=data.get("description", "")
        )

@dataclass
class WarmupScenario:
    id: str = field(default_factory=lambda: f"scen_{uuid.uuid4().hex[:8]}")
    name: str = "Custom Scenario"
    description: str = ""
    niche: str = "ecommerce"
    steps: List[ScenarioStep] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "niche": self.niche,
            "steps": [s.to_dict() for s in self.steps],
            "total_steps": len(self.steps)
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WarmupScenario":
        steps_raw = data.get("steps", [])
        steps = [ScenarioStep.from_dict(s) if isinstance(s, dict) else s for s in steps_raw]
        return cls(
            id=data.get("id", f"scen_{uuid.uuid4().hex[:8]}"),
            name=data.get("name", "Custom Scenario"),
            description=data.get("description", ""),
            niche=data.get("niche", "ecommerce"),
            steps=steps
        )

BUILTIN_SCENARIOS: List[WarmupScenario] = [
    WarmupScenario(
        id="scen_ecom_trust",
        name="E-Commerce & Google Ads Trust Booster",
        description="Organic Google searches, product pages visits, and natural dwell times to maximize Cookie Trust Score",
        niche="ecommerce",
        steps=[
            ScenarioStep("google_search", {"query": "best noise cancelling headphones 2026 review"}, "Search Google for top retail electronics"),
            ScenarioStep("human_scroll", {"duration_sec": 4, "direction": "down"}, "Natural scroll through SERP results"),
            ScenarioStep("dwell", {"min_sec": 3, "max_sec": 7}, "Simulate reading organic search results"),
            ScenarioStep("open_url", {"url": "https://www.amazon.com/s?k=wireless+headphones"}, "Visit Amazon product catalog"),
            ScenarioStep("human_scroll", {"duration_sec": 6, "direction": "down"}, "Browse product listings"),
            ScenarioStep("accept_cookie_dialog", {}, "Accept cookie consent dialog"),
            ScenarioStep("dwell", {"min_sec": 5, "max_sec": 10}, "Dwell on marketplace page")
        ]
    ),
    WarmupScenario(
        id="scen_youtube_viewer",
        name="YouTube & Shorts Audience Warmup",
        description="Searches YouTube, watches video previews, scrolls recommendations to build real viewer footprint",
        niche="tech",
        steps=[
            ScenarioStep("open_url", {"url": "https://www.youtube.com"}, "Navigate to YouTube homepage"),
            ScenarioStep("human_scroll", {"duration_sec": 5, "direction": "down"}, "Scroll YouTube homepage recommendations"),
            ScenarioStep("google_search", {"query": "site:youtube.com tech review 2026"}, "Search top tech review videos"),
            ScenarioStep("watch_youtube", {"watch_seconds": 15, "topic": "technology"}, "Watch video session with natural pauses"),
            ScenarioStep("dwell", {"min_sec": 4, "max_sec": 8}, "Finish session and persist cookies")
        ]
    ),
    WarmupScenario(
        id="scen_crypto_web3",
        name="Crypto & Web3 Investor Farming",
        description="Searches DeFi protocols, market prices on CoinMarketCap, and tech whitepapers",
        niche="crypto",
        steps=[
            ScenarioStep("open_url", {"url": "https://coinmarketcap.com"}, "Open CoinMarketCap crypto rankings"),
            ScenarioStep("human_scroll", {"duration_sec": 8, "direction": "down"}, "Inspect top 100 cryptocurrencies table"),
            ScenarioStep("google_search", {"query": "bitcoin halving historical price cycle 2026"}, "Search deep crypto analysis"),
            ScenarioStep("dwell", {"min_sec": 6, "max_sec": 12}, "Read analytics article")
        ]
    ),
    WarmupScenario(
        id="scen_finance_banking",
        name="Finance & High-CPC Banking Footprint",
        description="Accumulates highest Tier-1 advertising cookies in banking, credit, and ETF investments",
        niche="finance",
        steps=[
            ScenarioStep("google_search", {"query": "best high yield savings accounts rates 2026"}, "Google search for banking rates"),
            ScenarioStep("human_scroll", {"duration_sec": 5, "direction": "down"}, "Scroll organic financial comparisons"),
            ScenarioStep("open_url", {"url": "https://www.investopedia.com"}, "Read Investopedia financial guides"),
            ScenarioStep("dwell", {"min_sec": 8, "max_sec": 15}, "Accumulate high-CPC finance tracking cookies")
        ]
    )
]

class ScenarioExecutor:
    """
    Executes warmup scenarios across isolated browser profiles with concurrency control.
    """
    def __init__(self, browser_launcher, profile_manager):
        self.browser_launcher = browser_launcher
        self.profile_manager = profile_manager
        self.is_running = False

    async def execute_step(self, step: ScenarioStep, profile_id: str) -> bool:
        """Executes an individual scenario step for a profile."""
        prof = self.profile_manager.get_profile(profile_id)
        if not prof:
            return False

        if step.action == "open_url":
            url = step.params.get("url", "https://www.google.com")
            if not self.browser_launcher.is_profile_running(profile_id):
                ok, _, _ = self.browser_launcher.launch(prof, custom_url=url)
                return ok
            return True

        elif step.action == "google_search":
            query = step.params.get("query", "tech news 2026")
            url = f"https://www.google.com/search?q={query.replace(' ', '+')}&hl=en"
            if not self.browser_launcher.is_profile_running(profile_id):
                ok, _, _ = self.browser_launcher.launch(prof, custom_url=url)
                return ok
            return True

        elif step.action == "dwell":
            min_s = step.params.get("min_sec", 2)
            max_s = step.params.get("max_sec", 5)
            await asyncio.sleep(random.uniform(min_s, max_s))
            return True

        elif step.action == "human_scroll":
            dur = step.params.get("duration_sec", 3)
            await asyncio.sleep(dur)
            return True

        elif step.action == "accept_cookie_dialog":
            await asyncio.sleep(1.0)
            return True

        elif step.action == "watch_youtube":
            watch_s = step.params.get("watch_seconds", 10)
            await asyncio.sleep(min(watch_s, 30))
            return True

        return True

    async def run_scenario_on_profile(
        self,
        scenario: WarmupScenario,
        profile_id: str,
        progress_callback: Optional[Any] = None
    ) -> Dict[str, Any]:
        """Runs all steps in a scenario on a single profile."""
        prof = self.profile_manager.get_profile(profile_id)
        if not prof:
            return {"profile_id": profile_id, "success": False, "error": "Profile not found"}

        results = []
        for idx, step in enumerate(scenario.steps, start=1):
            if progress_callback:
                progress_callback(profile_id, idx, len(scenario.steps), step.description or step.action)
            ok = await self.execute_step(step, profile_id)
            results.append({"step": idx, "action": step.action, "success": ok})
            await asyncio.sleep(0.5)

        return {
            "profile_id": profile_id,
            "profile_name": prof.name,
            "scenario_name": scenario.name,
            "total_steps": len(scenario.steps),
            "completed_steps": len(results),
            "success": all(r["success"] for r in results)
        }

    async def run_batch_warmup(
        self,
        scenario: WarmupScenario,
        profile_ids: List[str],
        max_concurrency: int = 3,
        progress_callback: Optional[Any] = None
    ) -> Dict[str, Any]:
        """Executes a scenario across multiple profiles with concurrency throttling."""
        self.is_running = True
        sem = asyncio.Semaphore(max(1, min(max_concurrency, 10)))

        async def _worker(pid: str):
            async with sem:
                return await self.run_scenario_on_profile(scenario, pid, progress_callback=progress_callback)

        try:
            tasks = [_worker(pid) for pid in profile_ids]
            outcomes = await asyncio.gather(*tasks, return_exceptions=True)
            formatted = []
            for item in outcomes:
                if isinstance(item, dict):
                    formatted.append(item)
                else:
                    formatted.append({"success": False, "error": str(item)})
            return {
                "scenario": scenario.name,
                "total_profiles": len(profile_ids),
                "successful": sum(1 for o in formatted if o.get("success")),
                "results": formatted
            }
        finally:
            self.is_running = False

