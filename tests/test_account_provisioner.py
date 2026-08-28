"""
Tests for Account Provisioner, TOTP RFC 6238 Generator, and Dual-Mode Posting Engine.
"""

import json
import tempfile
from pathlib import Path

import pytest

from nazak.core.account_provisioner import AccountProvisioner, generate_totp_rfc6238, parse_account_string
from nazak.core.profile_manager import ProfileManager
from nazak.models.profile import BrowserProfile


def test_parse_account_string_colon():
    line = "user_01@gmail.com:SecretPass123:JBSWY3DPEHPK3PXP:recovery@mail.ru"
    res = parse_account_string(line)
    assert res is not None
    assert res["email"] == "user_01@gmail.com"
    assert res["password"] == "SecretPass123"
    assert res["totp_secret"] == "JBSWY3DPEHPK3PXP"
    assert res["recovery_email"] == "recovery@mail.ru"


def test_parse_account_string_semicolon_pipe():
    line_semi = "user_02@gmail.com;Pass2;HXDMVJECJJWSRB3H;rec2@inbox.ru"
    res_semi = parse_account_string(line_semi)
    assert res_semi is not None
    assert res_semi["email"] == "user_02@gmail.com"
    assert res_semi["totp_secret"] == "HXDMVJECJJWSRB3H"

    line_pipe = "user_03@gmail.com|Pass3|HXDMVJECJJWSRB3H|rec3@inbox.ru"
    res_pipe = parse_account_string(line_pipe)
    assert res_pipe is not None
    assert res_pipe["email"] == "user_03@gmail.com"


def test_generate_totp_rfc6238():
    secret = "JBSWY3DPEHPK3PXP"
    code = generate_totp_rfc6238(secret)
    assert isinstance(code, str)
    assert len(code) == 6
    assert code.isdigit()


def test_batch_import_and_create_profiles():
    with tempfile.TemporaryDirectory() as td:
        p_file = Path(td) / "profiles.json"
        p_dir = Path(td) / "browser_profiles"
        pm = ProfileManager(p_file, p_dir)
        provisioner = AccountProvisioner(pm, p_dir)

        raw = (
            "alpha@gmail.com:PassA:JBSWY3DPEHPK3PXP:rec_a@mail.com\n"
            "beta@gmail.com:PassB:HXDMVJECJJWSRB3H:rec_b@mail.com"
        )
        created = provisioner.batch_import_and_create_profiles(
            raw_text=raw,
            group_name="Retriv_2024",
            posting_mode="browser_stealth",
            proxy_list=["http://user:pass@1.2.3.4:8080"],
        )

        assert len(created) == 2
        assert created[0].group == "Retriv_2024"
        assert created[0].proxy.raw == "http://user:pass@1.2.3.4:8080"

        notes = json.loads(created[0].google.notes)
        assert notes["account_email"] == "alpha@gmail.com"
        assert notes["totp_secret"] == "JBSWY3DPEHPK3PXP"
        assert notes["posting_mode"] == "browser_stealth"


def test_build_oauth_auth_url():
    with tempfile.TemporaryDirectory() as td:
        pm = ProfileManager(Path(td) / "p.json", Path(td))
        prov = AccountProvisioner(pm, Path(td))
        url = prov.build_oauth_auth_url(client_id="test-client-id-123.apps.googleusercontent.com")
        assert "accounts.google.com/o/oauth2/v2/auth" in url
        assert "client_id=test-client-id-123.apps.googleusercontent.com" in url
        assert "access_type=offline" in url


def test_data1_file_provisioning():
    data1_path = Path("D:/nazak/data1.txt")
    if not data1_path.exists():
        return

    raw_text = data1_path.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as td:
        pm = ProfileManager(Path(td) / "p.json", Path(td))
        prov = AccountProvisioner(pm, Path(td))

        profiles = prov.batch_import_and_create_profiles(
            raw_text=raw_text, group_name="DarkStore_Batch", posting_mode="browser_stealth"
        )

        assert len(profiles) == 1
        p = profiles[0]
        notes = json.loads(p.google.notes)
        assert notes["account_email"] == "mlikhonkhan78@gmail.com"
        assert notes["account_password"] == "Gomie8383888"
        assert notes["totp_secret"] == "qq6rxgbtkfetme7digqvl27kkechle5i"

        # Test live TOTP generation on real darkstore secret
        code = generate_totp_rfc6238(notes["totp_secret"])
        assert len(code) == 6
        assert code.isdigit()
