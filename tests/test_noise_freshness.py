"""Noise-field freshness: repeated reads must not return identical noise."""

from __future__ import annotations

from pathlib import Path

from nazak.core.extension_generator import generate_profile_extension
from nazak.models.profile import BrowserProfile, FingerprintConfig


def _stealth(tmp_path, **fp_kwargs) -> str:
    fp = FingerprintConfig(**fp_kwargs)
    prof = BrowserProfile(id="p_noise", name="Noise", fingerprint=fp)
    ext_dir = Path(generate_profile_extension(prof, tmp_path))
    assert ext_dir is not None
    return (ext_dir / "stealth.js").read_text(encoding="utf-8")


def test_canvas_noise_reseeds_per_call(tmp_path):
    js = _stealth(tmp_path, canvas_noise=True, canvas_noise_seed=777888)
    assert "mutateCanvasData" in js
    assert "1664525" in js  # LCG constant kept
    assert "777888" in js  # profile seed kept
    # Per-call reseed: a counter mixed into the start state.
    assert "canvasCallCount" in js
    # No fixed single start offset anymore.
    assert "for (let i = (s % 7); i < len; i += 17)" not in js


def test_audio_noise_phase_shifts_per_call(tmp_path):
    js = _stealth(tmp_path, audio_noise=True, audio_noise_seed=0.00002)
    assert "AudioBuffer.prototype.getChannelData" in js
    assert "applyAudioNoise" in js
    assert "audioCallCount" in js
    # The old fixed pattern must be gone from both application sites.
    assert "(((i % 3) - 1) * 0.5)" not in js


def test_rect_and_font_jitter_vary_per_read(tmp_path):
    js = _stealth(tmp_path, client_rects_noise=True, canvas_noise_seed=12345)
    assert "Element.prototype.getBoundingClientRect" in js
    assert "CanvasRenderingContext2D.prototype.measureText" in js
    # Fresh sub-pixel offset per call instead of one session constant.
    assert "rectCallCount" in js
    assert "fontCallCount" in js
    assert "((seed % 7) - 3) * 0.00005" not in js
    assert "((seed % 5) - 2) * 0.0001" not in js


def test_noise_hooks_still_present_after_rework(tmp_path):
    js = _stealth(tmp_path, canvas_noise=True, audio_noise=True, client_rects_noise=True)
    for hook in (
        "CanvasRenderingContext2D.prototype.getImageData",
        "OffscreenCanvasRenderingContext2D.prototype.getImageData",
        "HTMLCanvasElement.prototype.toDataURL",
        "HTMLCanvasElement.prototype.toBlob",
        "OfflineAudioContext.prototype.startRendering",
        "fontJitter",
        "rect.x + jx",
    ):
        assert hook in js, f"hook lost in rework: {hook}"
