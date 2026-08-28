import pytest

from nazak.core.warmup_engine import WARMUP_NICHES, WarmupPlan, generate_warmup_urls


def test_warmup_plan_generation():
    plan = WarmupPlan(profile_id="prof_01", niche="ecommerce", steps_count=4)
    assert plan.profile_id == "prof_01"
    assert plan.niche == "ecommerce"
    assert len(plan.queries) == 4

    d = plan.to_dict()
    assert d["steps_count"] == 4
    assert len(d["search_queries"]) == 4


def test_warmup_niches_availability():
    for niche in ("ecommerce", "finance", "tech", "travel", "crypto"):
        assert niche in WARMUP_NICHES
        assert len(WARMUP_NICHES[niche]) >= 4


def test_generate_warmup_urls():
    queries = ["buy macbook m3", "best coffee beans"]
    urls = generate_warmup_urls(queries)
    assert len(urls) == 2
    assert "https://www.google.com/search?q=buy+macbook+m3&hl=en" in urls[0]
    assert "https://www.google.com/search?q=best+coffee+beans&hl=en" in urls[1]
