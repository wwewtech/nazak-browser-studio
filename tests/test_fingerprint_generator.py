import pytest

from nazak.core.fingerprint_generator import GPU_PRESETS, SCREEN_RESOLUTIONS, TIMEZONES, generate_random_fingerprint


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


def test_generate_linux_fingerprint_never_uses_direct3d():
    """Audit fix P1-6 (A1): Linux profiles must never produce Direct3D renderer strings."""
    for _ in range(20):
        fp = generate_random_fingerprint(os_type="linux")
        assert fp.platform == "Linux x86_64"
        assert "Linux" in fp.user_agent
        assert "Direct3D" not in fp.webgl_renderer
        assert "D3D11" not in fp.webgl_renderer
        assert any(sig in fp.webgl_renderer for sig in ("OpenGL", "Mesa"))
        assert fp.platform_version != "10.0.0"  # 10.0.0 is Windows-only


def test_gpu_presets_integrity():
    assert len(GPU_PRESETS) >= 8
    for g in GPU_PRESETS:
        assert "vendor" in g
        assert "renderer" in g
        assert len(g["cores"]) > 0
        assert len(g["ram"]) > 0
