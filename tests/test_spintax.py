import pytest

from nazak.core.spintax import format_video_metadata, parse_spintax


def test_parse_spintax_simple():
    template = "Buy {cheap|fast|secure} VPN"
    for _ in range(20):
        res = parse_spintax(template)
        assert res in ("Buy cheap VPN", "Buy fast VPN", "Buy secure VPN")


def test_parse_spintax_nested():
    template = "{Top|Best {fast|reliable}} VPN"
    res_set = set()
    for _ in range(50):
        res_set.add(parse_spintax(template))
    assert "Top VPN" in res_set
    assert "Best fast VPN" in res_set
    assert "Best reliable VPN" in res_set


def test_format_video_metadata():
    meta = format_video_metadata(
        title_template="{Watch|Stream} YouTube {fast|in 4K} in {year}",
        description_template="Get VPN: {tg} with code {promo}",
        profile_name="Profile 01",
        profile_id="prof_01",
        tg_channel="@vpn_test_bot",
        promo_code="DISCOUNT50",
    )
    assert "YouTube" in meta["title"]
    assert "2026" in meta["title"]
    assert "@vpn_test_bot" in meta["description"]
    assert "DISCOUNT50" in meta["description"]
    assert len(meta["tags"]) >= 4
