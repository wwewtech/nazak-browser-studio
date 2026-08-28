from pathlib import Path

import pytest

from nazak.core.spintax import format_video_metadata, parse_spintax
from nazak.core.video_uniquifier import VideoUniquifier, find_ffmpeg


def test_spintax_deep_3_levels():
    template = "{A|{B|{C|D}}}"
    results = set()
    for _ in range(100):
        results.add(parse_spintax(template))
    assert results == {"A", "B", "C", "D"}


def test_spintax_multiple_blocks():
    template = "{Top|Best} VPN for {Windows|Mac|Android} in {2026|2027}"
    res = parse_spintax(template)
    assert any(w in res for w in ("Top", "Best"))
    assert any(w in res for w in ("Windows", "Mac", "Android"))
    assert any(w in res for w in ("2026", "2027"))


def test_spintax_empty_choice_handling():
    template = "Download {now|} free"
    results = set()
    for _ in range(20):
        results.add(parse_spintax(template))
    assert "Download now free" in results or "Download  free" in results


def test_spintax_preserves_placeholders():
    template = "{Fast|Secure} VPN: {tg} code {promo} {year}"
    res = parse_spintax(template)
    assert "{tg}" in res
    assert "{promo}" in res
    assert "{year}" in res


def test_format_video_metadata_substitutions():
    meta = format_video_metadata(
        title_template="{Watch|Play} in {year}",
        description_template="Contact {tg} Promo {promo}",
        profile_name="Profile Alpha",
        profile_id="p1",
        tg_channel="@my_tg_bot",
        promo_code="SAVE99",
    )
    assert "@my_tg_bot" in meta["description"]
    assert "SAVE99" in meta["description"]
    assert "2026" in meta["title"]


def test_title_length_limit():
    long_title = "A" * 150
    meta = format_video_metadata(
        title_template=long_title, description_template="desc", profile_name="p", profile_id="p1"
    )
    assert len(meta["title"]) <= 95


def test_spintax_unclosed_brace_tolerance():
    malformed = "Normal text {unclosed bracket without pipe"
    res = parse_spintax(malformed)
    assert "Normal text" in res


def test_spintax_unmatched_closing_brace():
    malformed = "Text with } extra closing brace"
    res = parse_spintax(malformed)
    assert "extra closing brace" in res


def test_spintax_special_characters_inside_options():
    template = "{50% OFF!|Special $10 Deal!|#1 Rated}"
    res = parse_spintax(template)
    assert res in ("50% OFF!", "Special $10 Deal!", "#1 Rated")


def test_spintax_cyrillic_text():
    template = "{Лучший|Топ|Рабочий} {Впн|VPN} для {Ютуб|YouTube}"
    results = set()
    for _ in range(50):
        results.add(parse_spintax(template))
    assert len(results) >= 4


def test_find_ffmpeg_returns_valid_string():
    path = find_ffmpeg()
    if path is not None:
        assert isinstance(path, str)
        assert "ffmpeg" in path.lower()
    else:
        assert path is None


def test_video_uniquifier_nonexistent_source(tmp_path):
    uniq = VideoUniquifier(output_dir=tmp_path)
    ok, path, err = uniq.uniquify_video(tmp_path / "nonexistent.mp4", "prof_01")
    assert ok is False
    assert path is None
    assert "not found" in err.lower()


def test_video_uniquifier_batch_empty_list(tmp_path):
    uniq = VideoUniquifier(output_dir=tmp_path)
    src = tmp_path / "src.mp4"
    src.write_bytes(b"DATA" * 50)
    results = uniq.batch_uniquify(src, [])
    assert results == {}


def test_video_uniquifier_batch_multiple_profiles(tmp_path):
    uniq = VideoUniquifier(output_dir=tmp_path / "out")
    src = tmp_path / "source.mp4"
    src.write_bytes(b"MP4_DATA" * 100)
    res = uniq.batch_uniquify(src, ["p1", "p2", "p3"])
    assert len(res) == 3
    assert all(v[0] is True for v in res.values())


def test_video_uniquifier_output_filenames(tmp_path):
    uniq = VideoUniquifier(output_dir=tmp_path)
    src = tmp_path / "my_clip.mp4"
    src.write_bytes(b"VIDEO_CLIP" * 20)
    ok, out_path, err = uniq.uniquify_video(src, "prof_07")
    assert ok is True
    assert "prof_07_unique_my_clip.mp4" in str(out_path)


def test_spintax_empty_string():
    assert parse_spintax("") == ""


def test_spintax_whitespace_string():
    assert parse_spintax("   ") == "   "


def test_format_video_metadata_default_tags():
    meta = format_video_metadata("Title", "Desc", "Prof", "id1")
    assert "#shorts" in meta["tags"]
    assert "#vpn" in meta["tags"]


def test_format_video_metadata_random_promo_code():
    meta1 = format_video_metadata("Title", "Desc {promo}", "Prof", "id1")
    meta2 = format_video_metadata("Title", "Desc {promo}", "Prof", "id2")
    # Both should have valid promo codes
    assert "PROMO" in meta1["description"]
    assert "PROMO" in meta2["description"]


def test_video_uniquifier_is_ffmpeg_available():
    uniq = VideoUniquifier()
    assert isinstance(uniq.is_ffmpeg_available(), bool)
