import pytest
from pathlib import Path
from nazak.core.video_uniquifier import VideoUniquifier, find_ffmpeg

def test_find_ffmpeg():
    path = find_ffmpeg()
    assert path is not None
    assert "ffmpeg" in path.lower()

def test_video_uniquifier_single_and_batch(tmp_path):
    src_file = tmp_path / "test_source.mp4"
    src_file.write_bytes(b"TEST_MP4_DUMMY_CONTENT_" + b"\x00" * 2000)
    
    out_dir = tmp_path / "out"
    uniq = VideoUniquifier(output_dir=out_dir)
    
    ok, out_path, err = uniq.uniquify_video(src_file, "prof_01")
    assert ok is True
    assert out_path is not None
    assert out_path.exists()
    
    batch_res = uniq.batch_uniquify(src_file, ["prof_01", "prof_02"])
    assert len(batch_res) == 2
    assert batch_res["prof_01"][0] is True
    assert batch_res["prof_02"][0] is True
