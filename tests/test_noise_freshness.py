"""Noise-field contract: deterministic per profile, stable per content.

Hunt A-04 (empirical audit in a real Chrome): the canvas noise used to be
re-seeded from a CALL COUNTER, so drawing the SAME content twice produced two
DIFFERENT canvas hashes. A real browser's canvas hash is STABLE for identical
content — an unstable hash is a one-line automation tell (the classic
BrowserLeaks-style probe draws the same content repeatedly and compares).

So the noise must be a deterministic function of (profile seed, CONTENT):
identical content -> identical pixels and identical hash (as on a real device),
while two different profiles differ (the farm-wide uniqueness the noise exists
for). The old test asserted the opposite ("repeated reads must not return
identical noise"); that premise produced the tell.
"""

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


def test_canvas_noise_is_content_derived_not_call_derived(tmp_path):
    js = _stealth(tmp_path, canvas_noise=True, canvas_noise_seed=777888)
    assert "mutateCanvasData" in js
    assert "1664525" in js  # LCG constant kept
    assert "777888" in js  # profile seed kept
    # Hunt A-04: the noise field is derived from the CONTENT (plus the profile
    # seed), NOT from a call counter — otherwise the same drawing hashes
    # differently on every read, which is the automation tell.
    assert "canvasCallCount" not in js
    assert "contentSeed" in js
    # No fixed single start offset anymore.
    assert "for (let i = (s % 7); i < len; i += 17)" not in js


def test_canvas_hash_is_stable_for_identical_content(tmp_path):
    """The noise must be written into a COPY: the live canvas keeps its clean
    pixels, so a second toDataURL() of the same content hashes identically."""
    js = _stealth(tmp_path, canvas_noise=True, canvas_noise_seed=777888)
    # Hunt A-22: the copy helper moved — the noise is applied ONCE, on the
    # raw pixels, and the copy is encoded from them.
    helper = js[js.find("const noisyCopy") :][:900]
    assert "copyCtx.putImageData" in helper, "the noise must be applied to a copy (A-04)"
    assert "rawImageData(ctx" in helper, "the copy must read the raw pixels (A-22)"
    assert "ctx.putImageData" not in helper, "the noise must not be written back into the live canvas (A-04)"


def test_audio_noise_phase_shifts_per_call(tmp_path):
    js = _stealth(tmp_path, audio_noise=True, audio_noise_seed=0.00002)
    assert "AudioBuffer.prototype.getChannelData" in js
    assert "applyAudioNoise" in js
    assert "audioCallCount" in js
    # The old fixed pattern must be gone from both application sites.
    assert "(((i % 3) - 1) * 0.5)" not in js
    # Hunt A-06: the render helper must not apply the noise a second time
    # (it called the spoofed getter, which applied its own pass on top).
    helper = js[js.find("const applyAudioNoise = function(buffer)") :][:900]
    assert "applyAudioNoiseToChannel" not in helper


def test_rect_and_font_jitter_are_stable_per_element_and_text(tmp_path):
    """Hunt A-07: the rect and font jitters used to be re-derived from a CALL
    COUNTER, so the same element (or the same string) reported different
    values on every read. A real renderer is stable per element, and a real
    font metric is stable per string — the old behaviour was the tell."""
    js = _stealth(tmp_path, client_rects_noise=True, canvas_noise_seed=12345)
    assert "Element.prototype.getBoundingClientRect" in js
    assert "CanvasRenderingContext2D.prototype.measureText" in js
    # Stable per element / per text — not per call.
    assert "rectCallCount" not in js
    assert "fontCallCount" not in js
    assert "rectOffsets" in js, "the rect offset must be cached per element (A-07)"
    assert "textJitter" in js, "the font offset must be derived from the text (A-07)"
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
        "textJitter",
        "rect.x + off.x",
    ):
        assert hook in js, f"hook lost in rework: {hook}"
