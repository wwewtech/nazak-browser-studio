"""
Nazak Browser Studio - Professional Multi-Profile Browser Management Suite.
"""

__version__ = "1.4.1"
__author__ = "Nazak Digital"

from .core import BrowserLauncher, ProcessMonitor, ProfileManager, check_proxy_health
from .models import BrowserProfile, HealthCheckResult, ProfileStatus, ProxyConfig, ProxyType

__all__ = [
    "BrowserLauncher",
    "BrowserProfile",
    "HealthCheckResult",
    "ProcessMonitor",
    "ProfileManager",
    "ProfileStatus",
    "ProxyConfig",
    "ProxyType",
    "check_proxy_health",
]
