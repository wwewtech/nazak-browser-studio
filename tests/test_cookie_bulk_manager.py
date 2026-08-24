"""
Unit & Integration Tests for Batch Cookie Importer & Exporter Engine.
"""
import json
import zipfile
from pathlib import Path
import pytest

from nazak.core.cookie_manager import (
    parse_bulk_cookie_input, parse_cookie_files_from_dir, parse_cookie_files_from_zip,
    create_cookies_zip_archive, parse_any_cookies, cookies_to_netscape
)
from nazak.core.profile_manager import ProfileManager
from nazak.models.profile import BrowserProfile, ProxyConfig, FingerprintConfig

def test_parse_bulk_cookie_delimited_text():
    raw = """
=== Profile Alpha ===
[{"name": "SID", "value": "alpha_val", "domain": ".google.com", "path": "/"}]

=== Profile Beta ===
.google.com	TRUE	/	TRUE	0	HSID	beta_val

=== Profile Gamma ===
[{"name": "SSID", "value": "gamma_val", "domain": ".google.com", "path": "/"}]
"""
    parsed = parse_bulk_cookie_input(raw)
    assert len(parsed) == 3
    assert "Profile Alpha" in parsed
    assert parsed["Profile Alpha"][0]["value"] == "alpha_val"
    assert "Profile Beta" in parsed
    assert parsed["Profile Beta"][0]["name"] == "HSID"
    assert "Profile Gamma" in parsed

def test_parse_bulk_cookie_json_map():
    raw_dict = {
        "prof_01": [{"name": "c1", "value": "v1", "domain": ".site.com", "path": "/"}],
        "prof_02": [{"name": "c2", "value": "v2", "domain": ".site.com", "path": "/"}]
    }
    raw_str = json.dumps(raw_dict)
    parsed = parse_bulk_cookie_input(raw_str)
    assert len(parsed) == 2
    assert "prof_01" in parsed
    assert "prof_02" in parsed
    assert parsed["prof_01"][0]["name"] == "c1"

def test_parse_cookie_files_from_dir(tmp_path):
    dir_path = tmp_path / "cookie_folder"
    dir_path.mkdir()

    file1 = dir_path / "Account_USA_01.json"
    file1.write_text(json.dumps([{"name": "SID", "value": "usa_1", "domain": ".google.com", "path": "/"}]), encoding="utf-8")

    file2 = dir_path / "Account_UK_02.txt"
    file2.write_text(".google.com\tTRUE\t/\tTRUE\t0\tHSID\tuk_2\n", encoding="utf-8")

    file3 = dir_path / "ignored.png"
    file3.write_bytes(b"binary_image_data")

    parsed = parse_cookie_files_from_dir(dir_path)
    assert len(parsed) == 2
    assert "Account_USA_01" in parsed
    assert "Account_UK_02" in parsed
    assert parsed["Account_USA_01"][0]["value"] == "usa_1"
    assert parsed["Account_UK_02"][0]["value"] == "uk_2"

def test_parse_cookie_files_from_zip(tmp_path):
    zip_path = tmp_path / "cookies_bundle.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("Farm_01.json", json.dumps([{"name": "token", "value": "t1", "domain": ".farm.com", "path": "/"}]))
        zf.writestr("Farm_02.txt", ".farm.com\tTRUE\t/\tTRUE\t0\ttoken\tt2\n")

    parsed = parse_cookie_files_from_zip(zip_path)
    assert len(parsed) == 2
    assert "Farm_01" in parsed
    assert "Farm_02" in parsed
    assert parsed["Farm_01"][0]["value"] == "t1"
    assert parsed["Farm_02"][0]["value"] == "t2"

def test_create_cookies_zip_archive_roundtrip():
    cookie_map = {
        "profile_1": [{"name": "A", "value": "1", "domain": ".a.com", "path": "/"}],
        "profile_2": [{"name": "B", "value": "2", "domain": ".b.com", "path": "/"}]
    }
    zip_bytes = create_cookies_zip_archive(cookie_map, format_type="json")
    assert len(zip_bytes) > 0

    parsed = parse_cookie_files_from_zip(zip_bytes)
    assert len(parsed) == 2
    assert "profile_1" in parsed
    assert "profile_2" in parsed

def test_batch_import_and_export_cookies_in_profile_manager(tmp_path):
    profiles_file = tmp_path / "profiles.json"
    profiles_dir = tmp_path / "profiles"
    pm = ProfileManager(profiles_file, profiles_dir)

    p1 = BrowserProfile(id="prof_101", name="Target Alpha", proxy=ProxyConfig())
    p2 = BrowserProfile(id="prof_102", name="Target Beta", proxy=ProxyConfig())
    pm.create_profile(p1)
    pm.create_profile(p2)

    cookie_import_map = {
        "Target Alpha": [{"name": "SID", "value": "alpha_secret", "domain": ".google.com", "path": "/"}],
        "Target Beta": [{"name": "SID", "value": "beta_secret", "domain": ".google.com", "path": "/"}],
        "Brand New Auto Profile": [{"name": "SID", "value": "new_secret", "domain": ".google.com", "path": "/"}]
    }

    res = pm.batch_import_cookies(cookie_import_map, auto_create_missing=True, group="Bulk Tests")
    assert res["matched"] == 2
    assert res["created"] == 1

    # Verify cookies loaded
    c1 = pm.load_profile_cookies("prof_101")
    assert len(c1) == 1
    assert c1[0]["value"] == "alpha_secret"

    # Export all cookies
    all_exported = pm.export_all_cookies()
    assert len(all_exported) == 3
    assert "prof_101" in all_exported
    assert "prof_102" in all_exported
