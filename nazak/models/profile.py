"""
Browser profile definitions, comprehensive hardware fingerprints, and isolation settings.
"""
from enum import Enum
import uuid
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
from pydantic import BaseModel, Field
from .proxy import ProxyConfig, ProxyType
from .health import HealthCheckResult

class ProfileStatus(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"

class MediaDeviceInfo(BaseModel):
    """Spoofed audio/video device."""
    kind: str  # audioinput, audiooutput, videoinput
    label: str
    device_id: str
    group_id: str

class BatterySpoofConfig(BaseModel):
    """Spoofed Battery Status API."""
    charging: bool = True
    charging_time: Optional[float] = 0.0
    discharging_time: Optional[float] = None
    level: float = 1.0

class GeolocationSpoofConfig(BaseModel):
    """Spoofed Geolocation API matching proxy location."""
    enabled: bool = True
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    accuracy: float = 15.0

class FingerprintConfig(BaseModel):
    """
    Complete, deeply isolated hardware, system and browser fingerprint specification.
    Shields 100% of real host PC characteristics.
    """
    # 1. OS & User-Agent
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
    )
    platform: str = "Win32"
    app_version: str = "5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
    vendor: str = "Google Inc."
    
    # 2. Client Hints (User-Agent Data)
    brands: List[Dict[str, str]] = Field(default_factory=lambda: [
        {"brand": "Not(A:Brand", "version": "99"},
        {"brand": "Google Chrome", "version": "133"},
        {"brand": "Chromium", "version": "133"}
    ])
    platform_version: str = "15.0.0"
    architecture: str = "x86"
    bitness: str = "64"
    model: str = ""
    mobile: bool = False

    # 3. Screen & Window Metrics
    screen_width: int = 1920
    screen_height: int = 1080
    screen_avail_width: int = 1920
    screen_avail_height: int = 1040
    color_depth: int = 24
    pixel_depth: int = 24
    device_pixel_ratio: float = 1.0

    # 4. Hardware Resources
    device_memory: int = 16  # GB
    hardware_concurrency: int = 8  # CPU Cores
    max_touch_points: int = 0

    # 5. Locale & Timezone
    language: str = "en-US,en;q=0.9"
    languages: List[str] = Field(default_factory=lambda: ["en-US", "en"])
    timezone: str = "America/New_York"
    timezone_offset: int = 300  # minutes

    # 6. WebGL & GPU Hardware Spoofing
    webgl_vendor: str = "Google Inc. (NVIDIA)"
    webgl_renderer: str = "ANGLE (NVIDIA, NVIDIA GeForce RTX 3080 Direct3D11 vs_5_0 ps_5_0, D3D11)"
    webgl_unmasked_vendor: str = "NVIDIA Corporation"
    webgl_unmasked_renderer: str = "NVIDIA GeForce RTX 3080"
    max_texture_size: int = 16384
    max_renderbuffer_size: int = 16384
    max_viewport_dims: List[int] = Field(default_factory=lambda: [16384, 16384])

    # 7. Hardware Peripherals & Media Devices (Mocks real mics, webcams, speakers)
    media_devices: List[MediaDeviceInfo] = Field(default_factory=lambda: [
        MediaDeviceInfo(kind="audioinput", label="Default - Microphone (High Definition Audio Device)", device_id=uuid.uuid4().hex, group_id=uuid.uuid4().hex),
        MediaDeviceInfo(kind="audiooutput", label="Default - Speakers (Realtek(R) Audio)", device_id=uuid.uuid4().hex, group_id=uuid.uuid4().hex),
        MediaDeviceInfo(kind="videoinput", label="HD Pro Webcam C920", device_id=uuid.uuid4().hex, group_id=uuid.uuid4().hex)
    ])

    # 8. Anti-Fingerprint Noise Injections
    canvas_noise: bool = True
    canvas_noise_seed: int = Field(default_factory=lambda: int(uuid.uuid4().int % 1000000))
    audio_noise: bool = True
    audio_noise_seed: float = Field(default_factory=lambda: 0.000001)
    client_rects_noise: bool = True
    
    # 9. Hardware APIs Shielding
    battery: BatterySpoofConfig = Field(default_factory=BatterySpoofConfig)
    geolocation: GeolocationSpoofConfig = Field(default_factory=GeolocationSpoofConfig)
    webrtc_policy: str = "disable_non_proxied_udp"
    block_port_scanning: bool = True
    block_sensors: bool = True

class GoogleSettings(BaseModel):
    """
    Settings tailored specifically for Google Account Automation & Ads campaigns.
    """
    target_account_email: Optional[str] = None
    auto_open_page: str = "google_login"
    custom_url: Optional[str] = None
    tags: List[str] = Field(default_factory=lambda: ["Google Ads"])
    notes: Optional[str] = None

class BrowserProfile(BaseModel):
    """
    Primary Profile Entity encapsulating isolated storage, proxy, and full digital fingerprint.
    """
    id: str = Field(default_factory=lambda: f"prof_{uuid.uuid4().hex[:8]}")
    name: str = "Profile"
    group: str = "General"
    proxy: ProxyConfig = Field(default_factory=ProxyConfig)
    fingerprint: FingerprintConfig = Field(default_factory=FingerprintConfig)
    google: GoogleSettings = Field(default_factory=GoogleSettings)
    status: ProfileStatus = ProfileStatus.STOPPED
    pid: Optional[int] = None
    last_launched_at: Optional[str] = None
    total_runtime_seconds: int = 0
    last_health_check: Optional[HealthCheckResult] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def get_user_data_path(self, profiles_dir) -> str:
        return str(profiles_dir / self.id)
