"""API routers package (P0 refactor)."""

from .automation import router as automation_router
from .autopost import router as autopost_router
from .cookies import router as cookies_router
from .profiles import router as profiles_router
from .proxies import router as proxies_router
from .synchronizer import router as synchronizer_router
from .system import router as system_router
from .warmup import router as warmup_router

__all__ = [
    "automation_router",
    "autopost_router",
    "cookies_router",
    "profiles_router",
    "proxies_router",
    "synchronizer_router",
    "system_router",
    "warmup_router",
]
