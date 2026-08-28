"""
Health check models for proxy ping, IP/Geo verification, and Google reachability.
"""

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class HealthStatus(str, Enum):
    IDLE = "idle"
    CHECKING = "checking"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DEAD = "dead"
    ERROR = "error"


class GoogleReachability(BaseModel):
    """
    Reachability status and latencies for key Google services.
    """

    google_main: bool = False
    google_accounts: bool = False
    google_ads: bool = False
    youtube: bool = False
    latencies_ms: dict[str, float] = Field(default_factory=dict)
    all_ok: bool = False


class HealthCheckResult(BaseModel):
    """
    Complete pre-launch diagnostic result with IP, Geo, latencies, and coordinates.
    """

    status: HealthStatus = HealthStatus.IDLE
    ping_ms: float | None = None
    ip: str | None = None
    country: str | None = None
    country_code: str | None = None
    city: str | None = None
    region: str | None = None
    isp: str | None = None
    asn: str | None = None
    timezone_name: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    google: GoogleReachability = Field(default_factory=GoogleReachability)
    data_isolation_ok: bool = True
    webrtc_protected: bool = True
    error_message: str | None = None
    checked_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def is_operational(self) -> bool:
        return self.status in (HealthStatus.HEALTHY, HealthStatus.DEGRADED)
