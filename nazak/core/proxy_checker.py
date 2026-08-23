"""
Comprehensive Proxy Diagnostics & Health Checker Engine.
Performs:
1. TCP Ping / Socket Latency
2. External IP, Country, City, ASN, Timezone, Coordinates (Lat/Lon) resolution
3. Google Reachability Suite (Search, Accounts Login, Ads, YouTube)
4. Profile Data Isolation & Disk Integrity check
"""
import asyncio
import socket
import time
from pathlib import Path
from typing import Optional, Dict, Tuple
import httpx
from datetime import datetime, timezone

from ..models.proxy import ProxyConfig, ProxyType
from ..models.health import HealthCheckResult, HealthStatus, GoogleReachability

GOOGLE_ENDPOINTS = {
    "google_main": "https://www.google.com/generate_204",
    "google_accounts": "https://accounts.google.com/ServiceLogin",
    "google_ads": "https://ads.google.com",
    "youtube": "https://www.youtube.com/generate_204",
}

async def measure_tcp_ping(host: str, port: int, timeout_sec: float = 3.0) -> Optional[float]:
    """Measures raw TCP handshake latency in milliseconds."""
    t0 = time.perf_counter()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout_sec
        )
        writer.close()
        await writer.wait_closed()
        latency = (time.perf_counter() - t0) * 1000.0
        return round(latency, 2)
    except Exception:
        return None

def check_profile_data_isolation(profile_dir: Optional[Path]) -> Tuple[bool, Optional[str]]:
    """Validates that profile directory exists, is writable, and is not corrupted/locked."""
    if not profile_dir:
        return True, None
    try:
        profile_dir.mkdir(parents=True, exist_ok=True)
        test_file = profile_dir / ".isolation_check.tmp"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink(missing_ok=True)
        return True, None
    except Exception as e:
        return False, f"Profile directory error: {str(e)}"

async def check_proxy_health(
    proxy: ProxyConfig,
    profile_dir: Optional[Path] = None,
    timeout_sec: float = 8.0
) -> HealthCheckResult:
    """
    Executes the full diagnostic suite for a proxy configuration.
    """
    result = HealthCheckResult(
        status=HealthStatus.CHECKING,
        checked_at=datetime.now(timezone.utc).isoformat()
    )

    # 1. Check Profile Data Isolation
    isolation_ok, isolation_err = check_profile_data_isolation(profile_dir)
    result.data_isolation_ok = isolation_ok
    if not isolation_ok:
        result.status = HealthStatus.ERROR
        result.error_message = isolation_err
        return result

    # Direct connection handling
    if proxy.is_direct():
        proxy_url = None
        result.ping_ms = 1.0
    else:
        # Measure TCP Ping
        if proxy.host and proxy.port:
            ping_ms = await measure_tcp_ping(proxy.host, proxy.port, timeout_sec=3.0)
            result.ping_ms = ping_ms
            if ping_ms is None:
                result.status = HealthStatus.DEAD
                result.error_message = f"Failed to connect to proxy {proxy.host}:{proxy.port} (TCP Connection timed out)"
                return result

        proxy_url = proxy.to_httpx_url()

    # Create HTTPX client with proxy settings
    transport = httpx.AsyncHTTPTransport(retries=1)
    client_kwargs = {
        "timeout": httpx.Timeout(timeout_sec, connect=5.0),
        "follow_redirects": True,
        "headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
    }
    if proxy_url:
        client_kwargs["proxy"] = proxy_url

    async with httpx.AsyncClient(**client_kwargs) as client:
        # 2. IP & Geo Location Check
        try:
            geo_resp = await client.get("http://ip-api.com/json/?fields=status,message,country,countryCode,regionName,city,isp,as,query,timezone,lat,lon")
            if geo_resp.status_code == 200:
                geo_data = geo_resp.json()
                if geo_data.get("status") == "success":
                    result.ip = geo_data.get("query")
                    result.country = geo_data.get("country")
                    result.country_code = geo_data.get("countryCode")
                    result.city = geo_data.get("city")
                    result.region = geo_data.get("regionName")
                    result.isp = geo_data.get("isp")
                    result.asn = geo_data.get("as")
                    result.timezone_name = geo_data.get("timezone")
                    result.latitude = geo_data.get("lat")
                    result.longitude = geo_data.get("lon")
                else:
                    result.error_message = geo_data.get("message", "Geo lookup returned fail status")
        except Exception as e:
            # Fallback to ipify if ip-api is throttled
            try:
                ip_resp = await client.get("https://api.ipify.org?format=json")
                if ip_resp.status_code == 200:
                    result.ip = ip_resp.json().get("ip")
            except Exception:
                result.error_message = f"Proxy routing error: {str(e)}"

        if not result.ip and not proxy.is_direct():
            result.status = HealthStatus.DEAD
            if not result.error_message:
                result.error_message = "Proxy failed to route HTTP traffic"
            return result

        # 3. Google Reachability Suite
        google_reach = GoogleReachability()
        latencies: Dict[str, float] = {}

        async def check_endpoint(key: str, url: str):
            t0 = time.perf_counter()
            try:
                r = await client.get(url)
                lat = round((time.perf_counter() - t0) * 1000.0, 1)
                latencies[key] = lat
                if r.status_code in (200, 204, 301, 302):
                    return key, True, lat
                return key, False, lat
            except Exception:
                return key, False, 0.0

        tasks = [check_endpoint(k, u) for k, u in GOOGLE_ENDPOINTS.items()]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for res in results:
            if isinstance(res, tuple):
                key, ok, lat = res
                setattr(google_reach, key, ok)
                if lat > 0:
                    latencies[key] = lat

        google_reach.latencies_ms = latencies
        google_reach.all_ok = bool(
            google_reach.google_main and 
            google_reach.google_accounts and 
            google_reach.google_ads and 
            google_reach.youtube
        )
        result.google = google_reach

    # Final status determination
    if google_reach.all_ok:
        result.status = HealthStatus.HEALTHY
    elif google_reach.google_main or google_reach.google_accounts:
        result.status = HealthStatus.DEGRADED
    else:
        result.status = HealthStatus.DEAD if not proxy.is_direct() else HealthStatus.ERROR
        result.error_message = "Google services unreachable through this connection"

    return result
