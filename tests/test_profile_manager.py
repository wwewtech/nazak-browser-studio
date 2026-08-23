import pytest
from pathlib import Path
from nazak.core.profile_manager import ProfileManager
from nazak.models.profile import BrowserProfile, ProfileStatus

def test_default_10_profiles_provisioning(tmp_path):
    pfile = tmp_path / "profiles.json"
    pdir = tmp_path / "profiles"

    pm = ProfileManager(profiles_file=pfile, profiles_dir=pdir)
    profiles = pm.list_profiles()

    assert len(profiles) == 10
    assert pfile.exists()

    # Verify distinct profile attributes
    names = [p.name for p in profiles]
    assert len(set(names)) == 10
    assert "01 - Google Ads USA" in names[0]

def test_profile_crud_and_clone(tmp_path):
    pfile = tmp_path / "profiles.json"
    pdir = tmp_path / "profiles"
    pm = ProfileManager(profiles_file=pfile, profiles_dir=pdir)

    # 1. Create
    new_prof = BrowserProfile(id="custom_01", name="Custom SEO Profile", group="Organic")
    pm.create_profile(new_prof)
    assert pm.get_profile("custom_01") is not None

    # 2. Update
    new_prof.name = "Custom SEO Profile (Updated)"
    pm.update_profile(new_prof)
    assert pm.get_profile("custom_01").name == "Custom SEO Profile (Updated)"

    # 3. Clone
    cloned = pm.clone_profile("custom_01", new_name="Cloned SEO Profile")
    assert cloned is not None
    assert cloned.id != "custom_01"
    assert cloned.name == "Cloned SEO Profile"

    # 4. Delete
    deleted = pm.delete_profile("custom_01")
    assert deleted is True
    assert pm.get_profile("custom_01") is None
