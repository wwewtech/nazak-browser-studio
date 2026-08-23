import pytest
from nazak.core.fingerprint_generator import (
    generate_random_fingerprint,
    GPU_PRESETS,
    SCREEN_RESOLUTIONS,
    TIMEZONES
)

def test_generate_windows_fingerprint():
    fp = generate_random_fingerprint(os_type="windows")
    assert fp.platform == "Win32"
    assert "Windows" in fp.user_agent
    assert fp.hardware_concurrency in (4, 6, 8, 12, 14, 16, 24, 32)
    assert fp.device_memory in (8, 16, 32, 64)
    assert fp.screen_width >= 1366
    assert fp.screen_height >= 768
    assert fp.canvas_noise is True
    assert fp.audio_noise is True
    assert fp.webrtc_policy == "disable_non_proxied_udp"

def test_generate_mac_fingerprint():
    fp = generate_random_fingerprint(os_type="mac")
    assert fp.platform == "MacIntel"
    assert "Macintosh" in fp.user_agent
    assert "Apple" in fp.webgl_vendor

def test_gpu_presets_integrity():
    assert len(GPU_PRESETS) >= 8
    for g in GPU_PRESETS:
        assert "vendor" in g
        assert "renderer" in g
        assert len(g["cores"]) > 0
        assert len(g["ram"]) > 0
