"""
Nazak Browser Studio - Professional Multi-Profile Browser Management Suite.
"""
__version__ = "1.4.0"
__author__ = "Nazak Digital"

from .models import BrowserProfile, ProxyConfig, ProxyType, HealthCheckResult, ProfileStatus
from .core import ProfileManager, BrowserLauncher, ProcessMonitor, check_proxy_health

__all__ = [
    "BrowserProfile",
    "ProxyConfig",
    "ProxyType",
    "HealthCheckResult",
    "ProfileStatus",
    "ProfileManager",
    "BrowserLauncher",
    "ProcessMonitor",
    "check_proxy_health",
]
