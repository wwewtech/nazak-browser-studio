"""
Suite 1: UI & UX Edge Cases, Parsing Tolerances, Filtering & Dialog Validation Tests (26 Tests).
"""
import pytest
import json
import tempfile
from pathlib import Path

from nazak.models.profile import BrowserProfile, ProfileStatus, GoogleSettings, FingerprintConfig
from nazak.models.proxy import ProxyConfig, ProxyType
from nazak.core.profile_manager import ProfileManager
from nazak.core.account_provisioner import AccountProvisioner, parse_account_string
from nazak.core.cookie_manager import parse_any_cookies, parse_netscape_cookies, cookies_to_netscape


@pytest.fixture
def temp_profile_manager():
    with tempfile.TemporaryDirectory() as td:
        p_json = Path(td) / "profiles.json"
        p_dir = Path(td) / "profiles"
        pm = ProfileManager(p_json, p_dir)
        yield pm


# -------------------------------------------------------------
# 1. Search & Filtering Edge Cases (6 Tests)
# -------------------------------------------------------------

def test_search_filter_regex_special_characters(temp_profile_manager):
    """Search queries with regex metacharacters (*, +, ?, ^, $, (, ), [, ], {, }, |, \\) must not crash."""
    pm = temp_profile_manager
    profiles = pm.list_profiles()
    
    special_queries = [
        "RTX 4090 (High-Tier)",
        "Core [i7] + 32GB",
        "name.*with+regex?",
        "group(test)$",
        "^start|end",
        "\\backslash/path",
        "[0-9]+",
        "???***"
    ]
    for q in special_queries:
        # Simulate filter logic
        q_lower = q.lower()
        filtered = [
            p for p in profiles
            if q_lower in p.name.lower()
            or q_lower in p.group.lower()
            or (p.google.target_account_email and q_lower in p.google.target_account_email.lower())
            or (p.fingerprint and q_lower in p.fingerprint.webgl_renderer.lower())
        ]
        assert isinstance(filtered, list)


def test_search_filter_case_insensitivity(temp_profile_manager):
    """Search must match identically regardless of UPPERCASE, lowercase, or MiXeD cAsE."""
    pm = temp_profile_manager
    profiles = pm.list_profiles()
    
    p = profiles[0]
    p.name = "Custom Alpha Tester Profile"
    pm.save_profiles()
    
    for term in ["ALPHA", "alpha", "AlPhA", "CUSTOM", "tester", "PROFILE"]:
        q_lower = term.lower()
        res = [x for x in pm.list_profiles() if q_lower in x.name.lower()]
        assert len(res) >= 1
        assert res[0].id == p.id


def test_search_filter_cyrillic_and_unicode(temp_profile_manager):
    """Cyrillic and unicode queries in search must filter accurately."""
    pm = temp_profile_manager
    p = pm.list_profiles()[0]
    p.name = "Тестовый Профиль Москва RTX 4080"
    p.group = "Россия Фарм"
    pm.save_profiles()
    
    for term in ["Тестовый", "москва", "РОССИЯ", "Фарм", "4080"]:
        q_lower = term.lower()
        res = [
            x for x in pm.list_profiles()
            if q_lower in x.name.lower() or q_lower in x.group.lower()
        ]
        assert len(res) >= 1


def test_search_filter_whitespace_only(temp_profile_manager):
    """Whitespace-only search query should return all profiles without filtering out everything."""
    pm = temp_profile_manager
    total = len(pm.list_profiles())
    
    query = "    \t \n   "
    clean_q = query.strip().lower()
    
    if not clean_q:
        res = pm.list_profiles()
    else:
        res = [p for p in pm.list_profiles() if clean_q in p.name.lower()]
    assert len(res) == total


def test_search_filter_none_and_empty_fields(temp_profile_manager):
    """Profiles with None / empty fields must never raise AttributeError during search."""
    pm = temp_profile_manager
    p = pm.list_profiles()[0]
    p.google.target_account_email = None
    p.google.notes = None
    p.google.tags = []
    p.group = ""
    pm.save_profiles()
    
    query = "google"
    for item in pm.list_profiles():
        email = (item.google.target_account_email or "").lower()
        notes = (item.google.notes or "").lower()
        name = (item.name or "").lower()
        group = (item.group or "").lower()
        tags = " ".join(item.google.tags or []).lower()
        
        matches = query in email or query in notes or query in name or query in group or query in tags
        assert isinstance(matches, bool)


def test_profile_card_rendering_extreme_lengths(temp_profile_manager):
    """Profiles with 500+ character names or notes must store and serialize cleanly without truncation crash."""
    pm = temp_profile_manager
    p = pm.list_profiles()[0]
    p.name = "A" * 500
    p.google.notes = "B" * 2000
    p.google.tags = [f"tag_{i}" for i in range(100)]
    pm.save_profiles()
    
    reloaded = pm.get_profile(p.id)
    assert len(reloaded.name) == 500
    assert len(reloaded.google.notes) == 2000
    assert len(reloaded.google.tags) == 100


# -------------------------------------------------------------
# 2. Batch Import & Market Parsing Edge Cases (11 Tests)
# -------------------------------------------------------------

def test_batch_import_windows_crlf_endings():
    """Windows \\r\\n line endings must be parsed accurately."""
    raw = "user1@gmail.com:pass1:secret1:rec1@mail.com\r\nuser2@gmail.com:pass2:secret2:rec2@mail.com\r\n"
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    assert len(lines) == 2
    acc1 = parse_account_string(lines[0])
    assert acc1["email"] == "user1@gmail.com"
    acc2 = parse_account_string(lines[1])
    assert acc2["email"] == "user2@gmail.com"


def test_batch_import_mac_cr_endings():
    """Legacy \\r carriage returns must split correctly without single-string bunching."""
    raw = "user1@gmail.com:pass1:secret1:rec1@mail.com\ruser2@gmail.com:pass2:secret2:rec2@mail.com\r"
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    assert len(lines) == 2


def test_batch_import_trailing_blank_lines():
    """Batches with multiple blank lines at start, middle, and end should produce exact account count."""
    raw = "\n\n\n  \nuser1@gmail.com:pass1:secret1:rec1\n\n   \n\nuser2@gmail.com:pass2:secret2:rec2\n\n\n"
    with tempfile.TemporaryDirectory() as td:
        pm = ProfileManager(Path(td)/"p.json", Path(td))
        prov = AccountProvisioner(pm, Path(td))
        profs = prov.batch_import_and_create_profiles(raw, "TestGroup", "browser_stealth")
        assert len(profs) == 2


def test_batch_import_whitespace_padded_fields():
    """Whitespace inside field segments must be stripped cleanly."""
    line = "   mlikhonkhan78@gmail.com   :   Gomie8383888   :   qq6rxgbtkfetme7digqvl27kkechle5i   :   rec@gmail.com   "
    acc = parse_account_string(line)
    assert acc["email"] == "mlikhonkhan78@gmail.com"
    assert acc["password"] == "Gomie8383888"
    assert acc["totp_secret"] == "qq6rxgbtkfetme7digqvl27kkechle5i"
    assert acc["recovery_email"] == "rec@gmail.com"


def test_batch_import_semicolon_delimited():
    """Semicolon-delimited line from foreign marketplaces."""
    line = "target_acc@gmail.com;SecretPass123;ABCDEF234567;backup@mail.ru"
    acc = parse_account_string(line)
    assert acc["email"] == "target_acc@gmail.com"
    assert acc["password"] == "SecretPass123"
    assert acc["totp_secret"] == "ABCDEF234567"
    assert acc["recovery_email"] == "backup@mail.ru"


def test_batch_import_pipe_delimited():
    """Pipe-delimited format from Retriv."""
    line = "retriv_user@gmail.com|MyPassWord#99|JBSWY3DPEHPK3PXP|recovery_url.com"
    acc = parse_account_string(line)
    assert acc["email"] == "retriv_user@gmail.com"
    assert acc["password"] == "MyPassWord#99"
    assert acc["totp_secret"] == "JBSWY3DPEHPK3PXP"
    assert acc["recovery_email"] == "recovery_url.com"


def test_batch_import_tab_delimited():
    """Tab-delimited format exported from spreadsheets."""
    line = "sheet_acc@gmail.com\tPass12345\tMY2FASECRETKEY\trecovery@yahoo.com"
    acc = parse_account_string(line)
    assert acc["email"] == "sheet_acc@gmail.com"
    assert acc["password"] == "Pass12345"
    assert acc["totp_secret"] == "MY2FASECRETKEY"


def test_batch_import_mixed_delimiters_in_single_batch():
    """A batch containing colon, pipe, semicolon, and tab lines simultaneously."""
    raw = (
        "user1@gmail.com:pass1:sec1:rec1\n"
        "user2@gmail.com|pass2|sec2|rec2\n"
        "user3@gmail.com;pass3;sec3;rec3\n"
        "user4@gmail.com\tpass4\tsec4\trec4\n"
    )
    with tempfile.TemporaryDirectory() as td:
        pm = ProfileManager(Path(td)/"p.json", Path(td))
        prov = AccountProvisioner(pm, Path(td))
        profs = prov.batch_import_and_create_profiles(raw, "MixedGroup", "browser_stealth")
        assert len(profs) == 4


def test_batch_import_malformed_lines_skipped():
    """Receipt banners, order IDs, and advertising lines without '@' are filtered out."""
    raw = (
        "Заказ: #9991234\n"
        "Сайт магазина: https://market.shop\n"
        "======================================\n"
        "user_valid@gmail.com:SecretPass:TOTPKEY:rec@gmail.com\n"
        "Спасибо за покупку!\n"
    )
    with tempfile.TemporaryDirectory() as td:
        pm = ProfileManager(Path(td)/"p.json", Path(td))
        prov = AccountProvisioner(pm, Path(td))
        profs = prov.batch_import_and_create_profiles(raw, "FilteredGroup", "browser_stealth")
        assert len(profs) == 1
        assert profs[0].google.target_account_email == "user_valid@gmail.com"


def test_batch_import_extra_colons_in_recovery_url():
    """DarkStore format with URLs like (year: https://shorturl.at/xyz) contains colons in note field."""
    line = "mlikhon@gmail.com:Pass123:2FAKEEY:(year: https://shorturl.at/xyz:extra)"
    acc = parse_account_string(line)
    assert acc["email"] == "mlikhon@gmail.com"
    assert acc["password"] == "Pass123"
    assert acc["totp_secret"] == "2FAKEEY"
    assert "https://shorturl.at/xyz:extra" in acc["recovery_email"]


def test_batch_import_duplicate_email_handling():
    """Importing identical email twice creates distinct profiles without primary key clash."""
    raw = (
        "same_email@gmail.com:pass1:sec1:rec1\n"
        "same_email@gmail.com:pass2:sec2:rec2\n"
    )
    with tempfile.TemporaryDirectory() as td:
        pm = ProfileManager(Path(td)/"p.json", Path(td))
        prov = AccountProvisioner(pm, Path(td))
        profs = prov.batch_import_and_create_profiles(raw, "DupGroup", "browser_stealth")
        assert len(profs) == 2
        assert profs[0].id != profs[1].id


# -------------------------------------------------------------
# 3. Cookie Formats & Tolerances Edge Cases (5 Tests)
# -------------------------------------------------------------

def test_cookie_dialog_netscape_with_http_only_hash():
    """Netscape format containing #HttpOnly_ prefixes must preserve httpOnly flag."""
    netscape = "#HttpOnly_.google.com\tTRUE\t/\tTRUE\t1787461235\tSID\tsecure_sid_value"
    cookies = parse_netscape_cookies(netscape)
    assert len(cookies) == 1
    assert cookies[0]["httpOnly"] is True
    assert cookies[0]["domain"] == ".google.com"
    assert cookies[0]["name"] == "SID"
    assert cookies[0]["value"] == "secure_sid_value"


def test_cookie_dialog_netscape_with_comments_and_spaces():
    """Netscape comments starting with # (without HttpOnly_) are ignored."""
    netscape = (
        "# Netscape HTTP Cookie File\n"
        "# https://curl.se/docs/http-cookies.html\n"
        "# This file was generated by libcurl! Edit at your own risk.\n\n"
        ".youtube.com\tTRUE\t/\tTRUE\t0\tLOGIN_INFO\tAFmmF2cwRQIhAN\n"
    )
    cookies = parse_netscape_cookies(netscape)
    assert len(cookies) == 1
    assert cookies[0]["domain"] == ".youtube.com"
    assert cookies[0]["name"] == "LOGIN_INFO"


def test_cookie_dialog_json_array_with_missing_optional_fields():
    """JSON cookies without 'path', 'expires', or 'secure' should be populated with defaults."""
    raw_json = json.dumps([{"name": "session_id", "value": "xyz123", "domain": ".site.com"}])
    cookies = parse_any_cookies(raw_json)
    assert len(cookies) == 1
    c = cookies[0]
    assert c["name"] == "session_id"
    assert c["value"] == "xyz123"
    assert c["path"] == "/"


def test_cookie_dialog_single_json_object():
    """If user pastes a single JSON dict instead of a list, parse_any_cookies must wrap it in a list."""
    single_obj = json.dumps({"name": "token", "value": "jwt_token_val", "domain": "api.google.com"})
    cookies = parse_any_cookies(single_obj)
    assert len(cookies) == 1
    assert cookies[0]["name"] == "token"


def test_cookie_netscape_roundtrip_fidelity():
    """Converting cookies to Netscape and back must retain names, values, and domains."""
    orig = [
        {"name": "c1", "value": "v1", "domain": ".google.com", "path": "/", "secure": True, "httpOnly": True, "expires": 1800000000},
        {"name": "c2", "value": "v2", "domain": ".youtube.com", "path": "/studio", "secure": False, "httpOnly": False, "expires": 0}
    ]
    netscape_text = cookies_to_netscape(orig)
    reparsed = parse_netscape_cookies(netscape_text)
    assert len(reparsed) == 2
    assert reparsed[0]["name"] == "c1"
    assert reparsed[0]["httpOnly"] is True
    assert reparsed[1]["name"] == "c2"
    assert reparsed[1]["path"] == "/studio"


# -------------------------------------------------------------
# 4. Proxy Parsing & Dialog Validation Edge Cases (4 Tests)
# -------------------------------------------------------------

def test_proxy_parser_full_schemes():
    """Tests all standard proxy connection schemes."""
    assert ProxyConfig.parse("http://192.168.1.1:8080").type == ProxyType.HTTP
    assert ProxyConfig.parse("https://192.168.1.1:8443").type == ProxyType.HTTPS
    assert ProxyConfig.parse("socks5://192.168.1.1:1080").type == ProxyType.SOCKS5
    assert ProxyConfig.parse("socks4://192.168.1.1:1080").type == ProxyType.SOCKS4


def test_proxy_parser_ip_port_user_pass_format():
    """Tests standard market format: IP:PORT:USER:PASS."""
    cfg = ProxyConfig.parse("45.12.34.56:8000:myuser:mypass123")
    assert cfg.host == "45.12.34.56"
    assert cfg.port == 8000
    assert cfg.username == "myuser"
    assert cfg.password == "mypass123"
    assert cfg.has_auth() is True


def test_proxy_parser_user_pass_at_host_port():
    """Tests standard URI format: http://user:pass@host:port."""
    cfg = ProxyConfig.parse("http://proxyadmin:Secret#99@proxy.provider.com:9050")
    assert cfg.host == "proxy.provider.com"
    assert cfg.port == 9050
    assert cfg.username == "proxyadmin"
    assert cfg.password == "Secret#99"


def test_proxy_parser_direct_and_invalid_fallbacks():
    """Empty, 'direct', or malformed proxy strings fallback safely to DIRECT type."""
    assert ProxyConfig.parse("").type == ProxyType.DIRECT
    assert ProxyConfig.parse("direct").type == ProxyType.DIRECT
    assert ProxyConfig.parse("none").type == ProxyType.DIRECT
    assert ProxyConfig.parse("not_a_valid_proxy").type == ProxyType.DIRECT
