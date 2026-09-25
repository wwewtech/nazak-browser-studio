"""
Automated Google Account & Profile Warmup Engine.
Generates human search paths, natural organic navigation, and history/cookie accumulation.
"""

import asyncio
import logging
import random
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Consent-button selectors shared by the cookie step (audit fix C1).
COOKIE_CONSENT_JS = """
() => {
  const selectors = [
    '#onetrust-accept-btn-handler',
    '#sp-cc-accept',
    'button#L2AGLb',
    'button[jsname="b3VHJd"]',
    'button[aria-label*="accept" i]',
    'button[aria-label*="agree" i]',
    '[data-testid="cookie-accept"]',
    '[data-cy="cookieAccept"]'
  ];
  for (const s of selectors) {
    const el = document.querySelector(s);
    if (el) { el.click(); return 'selector:' + s; }
  }
  const words = ['accept all', 'accept cookies', 'accept', 'i agree', 'agree', 'allow all', 'got it'];
  const candidates = document.querySelectorAll('button, a[role="button"], div[role="button"]');
  for (const b of Array.from(candidates)) {
    const t = (b.textContent || '').trim().toLowerCase();
    if (t && t.length < 40 && words.some((w) => t === w || t.startsWith(w))) {
      b.click();
      return 'text:' + t;
    }
  }
  return '';
}
"""


class _PageSession:
    """Playwright page attached to a running profile over CDP (shared per scenario)."""

    def __init__(self) -> None:
        self._pw: Any = None
        self._browser: Any = None
        self.page: Any = None

    async def open(self, http_endpoint: str) -> bool:
        if self.page is not None:
            return True
        try:
            from playwright.async_api import async_playwright

            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.connect_over_cdp(http_endpoint)
            context = self._browser.contexts[0] if self._browser.contexts else await self._browser.new_context()
            self.page = context.pages[0] if context.pages else await context.new_page()
            return True
        except Exception as exc:
            logger.warning("warmup: CDP page attach failed (%s): %s", http_endpoint, exc)
            await self.close()
            return False

    async def close(self) -> None:
        for closer in (self._browser, self._pw):
            if closer is not None:
                try:
                    await (closer.close() if closer is self._browser else closer.stop())
                except Exception:
                    pass
        self._browser = None
        self._pw = None
        self.page = None


WARMUP_NICHES = {
    "ecommerce": [
        "best wireless noise cancelling headphones 2026",
        "top mechanical keyboards for programming",
        "best ergonomic office chair review",
        "buy macbook air m3 best price",
        "portable power bank 20000mah fast charge",
        "4k gaming monitor 144hz comparison",
        "smart home zigbee motion sensors",
    ],
    "finance": [
        "sp500 etf index performance 2026",
        "best high yield savings accounts interest rates",
        "how to calculate compound interest formula",
        "real estate investment trust dividend yields",
        "term life insurance quotes calculator",
        "credit card reward points strategies",
    ],
    "tech": [
        "python 3.13 new features and performance",
        "docker compose best practices for microservices",
        "fastapi vs django rest framework benchmarks",
        "chrome extensions manifest v3 background workers",
        "webrtc stun turn server configuration",
        "kubernetes cluster monitoring grafana prometheus",
    ],
    "travel": [
        "best places to visit in switzerland summer",
        "flights from new york to london direct",
        "hotel booking tips cancel anytime",
        "travel insurance coverage international trip",
        "scenic train routes in europe alps",
    ],
    "crypto": [
        "bitcoin halving cycle history and price chart",
        "ethereum layer 2 rollup gas fees comparison",
        "hardware wallet security ledger vs trezor",
        "decentralized finance liquidity pool yields",
    ],
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

    def _select_queries(self) -> list[str]:
        pool = WARMUP_NICHES[self.niche]
        return random.sample(pool, min(self.steps_count, len(pool)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "niche": self.niche,
            "steps_count": len(self.queries),
            "search_queries": self.queries,
            "estimated_duration_minutes": len(self.queries) * 1.5,
        }


def generate_warmup_urls(queries: list[str]) -> list[str]:
    """Generates direct Google search URLs from query list."""
    urls = []
    for q in queries:
        encoded = q.replace(" ", "+")
        urls.append(f"https://www.google.com/search?q={encoded}&hl=en")
    return urls


@dataclass
class ScenarioStep:
    action: str  # "open_url", "google_search", "human_scroll", "dwell", "click_internal_link", "watch_youtube", "accept_cookie_dialog"
    params: dict[str, Any] = field(default_factory=dict)
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"action": self.action, "params": self.params, "description": self.description}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScenarioStep":
        return cls(
            action=data.get("action", "open_url"),
            params=data.get("params", {}),
            description=data.get("description", ""),
        )


@dataclass
class WarmupScenario:
    id: str = field(default_factory=lambda: f"scen_{uuid.uuid4().hex[:8]}")
    name: str = "Custom Scenario"
    description: str = ""
    niche: str = "ecommerce"
    steps: list[ScenarioStep] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "niche": self.niche,
            "steps": [s.to_dict() for s in self.steps],
            "total_steps": len(self.steps),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WarmupScenario":
        steps_raw = data.get("steps", [])
        steps = [ScenarioStep.from_dict(s) if isinstance(s, dict) else s for s in steps_raw]
        return cls(
            id=data.get("id", f"scen_{uuid.uuid4().hex[:8]}"),
            name=data.get("name", "Custom Scenario"),
            description=data.get("description", ""),
            niche=data.get("niche", "ecommerce"),
            steps=steps,
        )


BUILTIN_SCENARIOS: list[WarmupScenario] = [
    WarmupScenario(
        id="scen_ecom_trust",
        name="E-Commerce & Google Ads Trust Booster",
        description="Organic Google searches, product pages visits, and natural dwell times to maximize Cookie Trust Score",
        niche="ecommerce",
        steps=[
            ScenarioStep(
                "google_search",
                {"query": "best noise cancelling headphones 2026 review"},
                "Search Google for top retail electronics",
            ),
            ScenarioStep(
                "human_scroll", {"duration_sec": 4, "direction": "down"}, "Natural scroll through SERP results"
            ),
            ScenarioStep("dwell", {"min_sec": 3, "max_sec": 7}, "Simulate reading organic search results"),
            ScenarioStep(
                "open_url", {"url": "https://www.amazon.com/s?k=wireless+headphones"}, "Visit Amazon product catalog"
            ),
            ScenarioStep("human_scroll", {"duration_sec": 6, "direction": "down"}, "Browse product listings"),
            ScenarioStep("accept_cookie_dialog", {}, "Accept cookie consent dialog"),
            ScenarioStep("dwell", {"min_sec": 5, "max_sec": 10}, "Dwell on marketplace page"),
        ],
    ),
    WarmupScenario(
        id="scen_youtube_viewer",
        name="YouTube & Shorts Audience Warmup",
        description="Searches YouTube, watches video previews, scrolls recommendations to build real viewer footprint",
        niche="tech",
        steps=[
            ScenarioStep("open_url", {"url": "https://www.youtube.com"}, "Navigate to YouTube homepage"),
            ScenarioStep(
                "human_scroll", {"duration_sec": 5, "direction": "down"}, "Scroll YouTube homepage recommendations"
            ),
            ScenarioStep(
                "google_search", {"query": "site:youtube.com tech review 2026"}, "Search top tech review videos"
            ),
            ScenarioStep(
                "watch_youtube", {"watch_seconds": 15, "topic": "technology"}, "Watch video session with natural pauses"
            ),
            ScenarioStep("dwell", {"min_sec": 4, "max_sec": 8}, "Finish session and persist cookies"),
        ],
    ),
    WarmupScenario(
        id="scen_crypto_web3",
        name="Crypto & Web3 Investor Farming",
        description="Searches DeFi protocols, market prices on CoinMarketCap, and tech whitepapers",
        niche="crypto",
        steps=[
            ScenarioStep("open_url", {"url": "https://coinmarketcap.com"}, "Open CoinMarketCap crypto rankings"),
            ScenarioStep(
                "human_scroll", {"duration_sec": 8, "direction": "down"}, "Inspect top 100 cryptocurrencies table"
            ),
            ScenarioStep(
                "google_search", {"query": "bitcoin halving historical price cycle 2026"}, "Search deep crypto analysis"
            ),
            ScenarioStep("dwell", {"min_sec": 6, "max_sec": 12}, "Read analytics article"),
        ],
    ),
    WarmupScenario(
        id="scen_finance_banking",
        name="Finance & High-CPC Banking Footprint",
        description="Accumulates highest Tier-1 advertising cookies in banking, credit, and ETF investments",
        niche="finance",
        steps=[
            ScenarioStep(
                "google_search",
                {"query": "best high yield savings accounts rates 2026"},
                "Google search for banking rates",
            ),
            ScenarioStep(
                "human_scroll", {"duration_sec": 5, "direction": "down"}, "Scroll organic financial comparisons"
            ),
            ScenarioStep("open_url", {"url": "https://www.investopedia.com"}, "Read Investopedia financial guides"),
            ScenarioStep("dwell", {"min_sec": 8, "max_sec": 15}, "Accumulate high-CPC finance tracking cookies"),
        ],
    ),
]


class ScenarioExecutor:
    """
    Executes warmup scenarios across isolated browser profiles with concurrency control.
    """

    def __init__(self, browser_launcher, profile_manager):
        self.browser_launcher = browser_launcher
        self.profile_manager = profile_manager
        self.is_running = False

    async def execute_step(self, step: ScenarioStep, profile_id: str, page: Any | None = None) -> bool:
        """Executes an individual scenario step for a profile.

        ``page`` is a Playwright page (or test double) supplied by the runner.
        Navigation/scroll/consent steps really execute over CDP now — the old
        implementation silently skipped every step once the browser was up
        (audit finding C1).
        """
        prof = self.profile_manager.get_profile(profile_id)
        if not prof:
            return False

        if step.action in ("open_url", "google_search"):
            if step.action == "open_url":
                url = step.params.get("url", "https://www.google.com")
            else:
                query = str(step.params.get("query", "tech news 2026"))
                url = f"https://www.google.com/search?q={query.replace(' ', '+')}&hl=en"
            if not self.browser_launcher.is_profile_running(profile_id):
                ok, _, _ = self.browser_launcher.launch(prof, custom_url=url)
                return ok
            if page is None:
                logger.warning("warmup: no CDP page for navigation step on %s", profile_id)
                return False
            return await self._navigate(page, url)

        if step.action == "human_scroll":
            if page is None:
                return False
            return await self._human_scroll(
                page,
                float(step.params.get("duration_sec", 3)),
                str(step.params.get("direction", "down")),
            )

        if step.action == "dwell":
            min_s = step.params.get("min_sec", 2)
            max_s = step.params.get("max_sec", 5)
            await asyncio.sleep(random.uniform(min_s, max_s))
            return True

        if step.action == "accept_cookie_dialog":
            if page is None:
                return False
            return await self._accept_cookie_dialog(page)

        if step.action == "watch_youtube":
            watch_s = min(float(step.params.get("watch_seconds", 10)), 120.0)
            if page is not None and step.params.get("url"):
                await self._navigate(page, str(step.params["url"]))
            await asyncio.sleep(watch_s)
            return True

        return True

    # ------------------------------------------------------------ CDP page actions
    async def _navigate(self, page: Any, url: str) -> bool:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(random.uniform(0.6, 1.6))
            return True
        except Exception as exc:
            logger.warning("warmup navigation failed for %s: %s", url, exc)
            return False

    async def _human_scroll(self, page: Any, duration_sec: float, direction: str = "down") -> bool:
        """Real viewport scrolling with human-like steps (audit C1 fix)."""
        sign = -1 if direction == "up" else 1
        try:
            loop = asyncio.get_running_loop()
            deadline = loop.time() + max(0.5, duration_sec)
            while loop.time() < deadline:
                distance = random.randint(160, 480) * sign
                try:
                    await page.mouse.wheel(0, distance)
                except Exception:
                    await page.evaluate("(dy) => window.scrollBy(0, dy)", distance)
                await asyncio.sleep(random.uniform(0.25, 0.7))
                if random.random() < 0.15:  # occasional reader micro-pause
                    await asyncio.sleep(random.uniform(0.4, 1.1))
            return True
        except Exception as exc:
            logger.warning("warmup scroll failed: %s", exc)
            return False

    async def _accept_cookie_dialog(self, page: Any) -> bool:
        """Click common consent buttons; harmless when no dialog is present."""
        try:
            clicked = await page.evaluate(COOKIE_CONSENT_JS)
            await asyncio.sleep(random.uniform(0.5, 1.2))
            logger.debug("cookie dialog click result: %s", clicked)
            return True
        except Exception as exc:
            logger.warning("cookie dialog handling failed: %s", exc)
            return False

    async def run_scenario_on_profile(
        self, scenario: WarmupScenario, profile_id: str, progress_callback: Any | None = None
    ) -> dict[str, Any]:
        """Runs all steps in a scenario on a single profile with a shared CDP page."""
        prof = self.profile_manager.get_profile(profile_id)
        if not prof:
            return {"profile_id": profile_id, "success": False, "error": "Profile not found"}

        was_running = self.browser_launcher.is_profile_running(profile_id)
        session = _PageSession()
        results: list[dict[str, Any]] = []
        try:
            for idx, step in enumerate(scenario.steps, start=1):
                if progress_callback:
                    progress_callback(profile_id, idx, len(scenario.steps), step.description or step.action)
                session.page = await self._ensure_page(session, profile_id)
                ok = await self.execute_step(step, profile_id, page=session.page)
                results.append({"step": idx, "action": step.action, "success": ok})
                await asyncio.sleep(0.5)
        finally:
            await session.close()
            # Stop the browser we started for this scenario (audit C1: it used to leak).
            if not was_running and self.browser_launcher.is_profile_running(profile_id):
                try:
                    self.browser_launcher.stop(profile_id)
                except Exception:
                    logger.debug("warmup: failed to stop profile %s", profile_id, exc_info=True)

        return {
            "profile_id": profile_id,
            "profile_name": prof.name,
            "scenario_name": scenario.name,
            "total_steps": len(scenario.steps),
            "completed_steps": len(results),
            "results": results,
            "success": all(r["success"] for r in results),
        }

    async def _ensure_page(self, session: _PageSession, profile_id: str) -> Any | None:
        """Return an attached page when the browser exposes a CDP endpoint."""
        if session.page is not None:
            return session.page
        if not self.browser_launcher.is_profile_running(profile_id):
            return None
        info = None
        try:
            info = self.browser_launcher.get_cdp_info(profile_id)
        except Exception:
            info = None
        endpoint = (info or {}).get("http_endpoint")
        if not endpoint or not isinstance(endpoint, str):
            return None
        if await session.open(endpoint):
            return session.page
        return None

    async def run_batch_warmup(
        self,
        scenario: WarmupScenario,
        profile_ids: list[str],
        max_concurrency: int = 3,
        progress_callback: Any | None = None,
    ) -> dict[str, Any]:
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
                "results": formatted,
            }
        finally:
            self.is_running = False
