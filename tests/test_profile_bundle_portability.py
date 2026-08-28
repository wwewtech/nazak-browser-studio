"""
Unit Tests for Portable .nazak Profile Bundles Export & Import.
"""

import pytest

from nazak.core.profile_manager import ProfileManager
from nazak.models.profile import BrowserProfile, ProxyConfig


def test_profile_bundle_roundtrip(tmp_path):
    pm1 = ProfileManager(tmp_path / "pm1" / "profiles.json", tmp_path / "pm1" / "profiles")
    pm2 = ProfileManager(tmp_path / "pm2" / "profiles.json", tmp_path / "pm2" / "profiles")

    # Create profile in pm1 with session cookies
    p = BrowserProfile(id="portable_p1", name="Original Farm Profile", group="Portable", proxy=ProxyConfig())
    pm1.create_profile(p)
    pm1.save_profile_cookies(
        "portable_p1", [{"name": "SSID", "value": "portable_val", "domain": ".site.com", "path": "/"}]
    )

    # Export bundle
    bundle_path = tmp_path / "export_target.nazak"
    res_path = pm1.export_profile_bundle("portable_p1", bundle_path)
    assert res_path is not None
    assert res_path.exists()

    # Import bundle into fresh pm2 workspace
    imported = pm2.import_profile_bundle(bundle_path, new_name="Restored Farm Profile")
    assert imported is not None
    assert imported.name == "Restored Farm Profile"
    assert imported.group == "Portable"

    # Verify cookies preserved
    cookies = pm2.load_profile_cookies(imported.id)
    assert len(cookies) == 1
    assert cookies[0]["value"] == "portable_val"
