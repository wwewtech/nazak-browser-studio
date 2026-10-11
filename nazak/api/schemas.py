"""
Nazak API request schemas (Pydantic models).

Extracted from nazak/api/server.py (P0 refactor): all request bodies live here
so routers stay thin. Bounds are load-bearing (audit R3-round2) — do not relax.
"""

from typing import Any

from pydantic import BaseModel, Field, field_validator

from ..config import (
    DEFAULT_AUTOPOST_DESCRIPTION_TEMPLATE,
    DEFAULT_AUTOPOST_TG_CHANNEL,
    DEFAULT_AUTOPOST_TITLE_TEMPLATE,
)

# Shared bounds (same values as the original server.py).
MAX_PROFILE_IDS = 500
MAX_TEXT = 20_000
MAX_MEDIA_PATH = 4096


class SecretsModeRequest(BaseModel):
    """User-selected secrets storage mode. The choice is always the user's."""

    mode: str
    passphrase: str | None = None


class LaunchRequest(BaseModel):
    custom_url: str | None = Field(default=None, max_length=2048)
    cdp_port: int | None = Field(default=None, ge=1, le=65535)


class ProxyTestRequest(BaseModel):
    raw_proxy: str = Field(max_length=2048)


class BulkImportRequest(BaseModel):
    proxy_lines: str = Field(max_length=1_000_000)
    group: str = Field(default="Google Ads", max_length=120)
    target_page: str = Field(default="google_login", max_length=64)


class MassGenerateRequest(BaseModel):
    # CLI uses the same 1..200 range (cli_cmds/profiles.py: cmd_mass_generate)
    count: int = Field(default=10, ge=1, le=200)
    group: str = Field(default="Mass Generated", max_length=120)
    proxy_lines: str | None = Field(default=None, max_length=1_000_000)
    os_mix: str = Field(default="windows", max_length=16)
    tags: list[str] | None = Field(default=None, max_length=50)
    target_page: str = Field(default="google_login", max_length=64)
    notes: str | None = Field(default=None, max_length=4000)


class BatchActionRequest(BaseModel):
    profile_ids: list[str] = Field(max_length=MAX_PROFILE_IDS)


class AutopostBatchRequest(BaseModel):
    profile_ids: list[str] = Field(max_length=MAX_PROFILE_IDS)
    source_video_path: str | None = Field(default=None, max_length=MAX_MEDIA_PATH)
    platform: str = Field(default="youtube_shorts", max_length=32)
    title_template: str = Field(default=DEFAULT_AUTOPOST_TITLE_TEMPLATE, max_length=500)
    description_template: str = Field(default=DEFAULT_AUTOPOST_DESCRIPTION_TEMPLATE, max_length=5000)
    tg_channel: str = Field(default=DEFAULT_AUTOPOST_TG_CHANNEL, max_length=120)
    delay_seconds: int = Field(default=10, ge=0, le=3600)
    demo: bool = False


class UniquifyRequest(BaseModel):
    source_video_path: str = Field(max_length=MAX_MEDIA_PATH)
    profile_ids: list[str] = Field(max_length=MAX_PROFILE_IDS)


class CookieImportRequest(BaseModel):
    cookies_data: str = Field(max_length=5_000_000)


class BulkCookieImportRequest(BaseModel):
    cookies_data: str = Field(max_length=5_000_000)
    auto_create_missing: bool = True
    group: str = Field(default="Imported Cookies", max_length=120)


class BulkCookieExportRequest(BaseModel):
    profile_ids: list[str] | None = Field(default=None, max_length=MAX_PROFILE_IDS)
    format: str = Field(default="json", pattern="^(json|netscape|zip)$")


class WarmupRequest(BaseModel):
    niche: str = Field(default="ecommerce", max_length=64)
    steps_count: int = Field(default=5, ge=1, le=20)


class ScenarioRunRequest(BaseModel):
    scenario_id: str | None = Field(default=None, max_length=128)
    scenario_data: dict[str, Any] | None = None
    profile_ids: list[str] = Field(max_length=MAX_PROFILE_IDS)
    max_concurrency: int = Field(default=3, ge=1, le=10)


class SynchronizerStartRequest(BaseModel):
    master_profile_id: str = Field(max_length=64)
    worker_profile_ids: list[str] = Field(max_length=MAX_PROFILE_IDS)
    humanize_jitter: bool = True
    min_delay_ms: int = Field(default=20, ge=0, le=60_000)
    max_delay_ms: int = Field(default=80, ge=0, le=60_000)
    coordinate_jitter_px: int = Field(default=2, ge=0, le=50)


class SynchronizerNavigateRequest(BaseModel):
    url: str = Field(max_length=2048)

    @field_validator("url")
    @classmethod
    def _validate_url(cls, value: str) -> str:
        from ..core.browser_launcher import sanitize_launch_url

        sanitized = sanitize_launch_url(value)
        if not sanitized:
            raise ValueError("URL is empty")
        return sanitized


class WindowTileRequest(BaseModel):
    cols: int | None = Field(default=None, ge=1, le=8)
