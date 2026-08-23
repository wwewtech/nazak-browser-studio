"""
Health check models for proxy ping, IP/Geo verification, and Google reachability.
"""
from enum import Enum
from typing import Dict, Optional
from pydantic import BaseModel, Field
from datetime import datetime, timezone

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
    latencies_ms: Dict[str, float] = Field(default_factory=dict)
    all_ok: bool = False

class HealthCheckResult(BaseModel):
    """
    Complete pre-launch diagnostic result with IP, Geo, latencies, and coordinates.
    """
    status: HealthStatus = HealthStatus.IDLE
    ping_ms: Optional[float] = None
    ip: Optional[str] = None
    country: Optional[str] = None
    country_code: Optional[str] = None
    city: Optional[str] = None
    region: Optional[str] = None
    isp: Optional[str] = None
    asn: Optional[str] = None
    timezone_name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    google: GoogleReachability = Field(default_factory=GoogleReachability)
    data_isolation_ok: bool = True
    webrtc_protected: bool = True
    error_message: Optional[str] = None
    checked_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def is_operational(self) -> bool:
        return self.status in (HealthStatus.HEALTHY, HealthStatus.DEGRADED)
