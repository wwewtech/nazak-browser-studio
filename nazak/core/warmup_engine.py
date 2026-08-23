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
