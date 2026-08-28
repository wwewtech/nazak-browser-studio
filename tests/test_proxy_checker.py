import asyncio
from pathlib import Path

import pytest

from nazak.core.proxy_checker import check_profile_data_isolation, check_proxy_health
from nazak.models.proxy import ProxyConfig, ProxyType


def test_data_isolation_checker(tmp_path):
    prof_dir = tmp_path / "test_iso_prof"
    ok, err = check_profile_data_isolation(prof_dir)
    assert ok is True
    assert err is None
    assert prof_dir.exists()


def test_direct_connection_health_check(tmp_path):
    prof_dir = tmp_path / "test_direct_prof"
    direct_proxy = ProxyConfig(type=ProxyType.DIRECT)

    res = asyncio.run(check_proxy_health(direct_proxy, profile_dir=prof_dir))
    assert res.data_isolation_ok is True
    assert res.status in ("healthy", "degraded", "idle", "checking")
    assert res.google is not None
