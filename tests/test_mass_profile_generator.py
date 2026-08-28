"""
Unit Tests for Mass Profile Generator Engine.
"""

import pytest

from nazak.core.profile_manager import ProfileManager


def test_mass_generate_profiles_basic(tmp_path):
    pm = ProfileManager(tmp_path / "profiles.json", tmp_path / "profiles")

    proxies = ["192.168.1.1:8080:user1:pass1", "192.168.1.2:8080:user2:pass2"]

    created = pm.mass_generate_profiles(
        count=6, group="Farm Alpha", proxy_list=proxies, os_mix="windows", tags=["Mass", "Alpha"]
    )

    assert len(created) == 6
    # Verify proxy round-robin distribution
    assert created[0].proxy.host == "192.168.1.1"
    assert created[1].proxy.host == "192.168.1.2"
    assert created[2].proxy.host == "192.168.1.1"

    # Verify unique hardware fingerprints
    canvas_noises = [p.fingerprint.canvas_noise_seed for p in created]
    assert len(set(canvas_noises)) == 6
    audio_noises = [p.fingerprint.audio_noise_seed for p in created]
    assert len(set(audio_noises)) == 6


def test_mass_generate_profiles_os_mix(tmp_path):
    pm = ProfileManager(tmp_path / "profiles.json", tmp_path / "profiles")

    created = pm.mass_generate_profiles(count=9, group="OS Mix Farm", os_mix="all")
    assert len(created) == 9
    user_agents = [p.fingerprint.user_agent for p in created]
    # Verify presence of multiple OS platforms in user agent
    assert any("Windows" in ua for ua in user_agents)
    assert any("Macintosh" in ua for ua in user_agents) or any("Linux" in ua for ua in user_agents)
