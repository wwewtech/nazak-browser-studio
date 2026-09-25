"""Video uniquifier tests.

Audit fix P0-4: the old suite asserted ``success=True`` for a *dummy* (invalid
MP4) file — possible only because a failed encode silently fell back to a plain
byte copy, so the upload queue published non-uniquified videos as "unique".
The rewritten suite checks the honest contract: missing ffmpeg fails loudly,
invalid media fails loudly with no leftover artifact, and a real clip is fully
re-encoded into a byte-distinct output.
"""

import subprocess

import pytest

from nazak.core.video_uniquifier import VideoUniquifier, find_ffmpeg


def test_find_ffmpeg():
    path = find_ffmpeg()
    if path is not None:
        assert "ffmpeg" in path.lower()
    else:
        assert path is None


def test_uniquify_fails_loudly_without_ffmpeg(tmp_path, monkeypatch):
    src_file = tmp_path / "source.mp4"
    src_file.write_bytes(b"TEST_MP4_DUMMY_CONTENT_" + b"\x00" * 2000)
    uniq = VideoUniquifier(output_dir=tmp_path / "out")
    monkeypatch.setattr(uniq, "ffmpeg_path", None)

    ok, out_path, err = uniq.uniquify_video(src_file, "prof_01")
    assert ok is False
    assert out_path is None
    assert "ffmpeg" in (err or "").lower()
    # must NOT leave a copied file pretending to be a unique render
    assert not (tmp_path / "out" / "prof_01_unique_source.mp4").exists()


def test_uniquify_invalid_media_does_not_fake_success(tmp_path):
    src_file = tmp_path / "bogus.mp4"
    src_file.write_bytes(b"NOT_A_REAL_MP4" + b"\x01" * 4000)
    uniq = VideoUniquifier(output_dir=tmp_path / "out")
    if not uniq.is_ffmpeg_available():
        pytest.skip("ffmpeg not installed on this machine")

    ok, out_path, err = uniq.uniquify_video(src_file, "prof_01")
    assert ok is False
    assert out_path is None
    assert err and "FFmpeg" in err
    assert not (tmp_path / "out" / "prof_01_unique_bogus.mp4").exists()


def test_uniquify_real_clip_produces_reencoded_output(tmp_path):
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        pytest.skip("ffmpeg not installed on this machine")
    src = tmp_path / "real.mp4"
    gen = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x240:rate=15:duration=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(src),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if gen.returncode != 0 or not src.exists():
        pytest.skip("ffmpeg build cannot generate the test clip")

    source_bytes = src.read_bytes()
    uniq = VideoUniquifier(output_dir=tmp_path / "out")

    ok, out_path, err = uniq.uniquify_video(src, "prof_01")
    assert ok is True, err
    assert out_path is not None and out_path.exists()
    assert out_path.stat().st_size > 1000
    # re-encoded output must NOT be a byte copy of the source
    assert out_path.read_bytes() != source_bytes

    batch_res = uniq.batch_uniquify(src, ["prof_01", "prof_02"])
    assert len(batch_res) == 2
    assert batch_res["prof_01"][0] is True
    assert batch_res["prof_02"][0] is True
