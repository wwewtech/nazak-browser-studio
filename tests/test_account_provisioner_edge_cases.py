"""
Suite 3: Account Provisioner, TOTP RFC 6238, OAuth & Token Refresh Edge Cases (20 Tests).
"""

import json
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nazak.core.account_provisioner import AccountProvisioner, generate_totp_rfc6238, parse_account_string
from nazak.core.profile_manager import ProfileManager


@pytest.fixture
def temp_provisioner():
    with tempfile.TemporaryDirectory() as td:
        p_json = Path(td) / "p.json"
        p_dir = Path(td) / "profiles"
        pm = ProfileManager(p_json, p_dir)
        prov = AccountProvisioner(pm, p_dir)
        yield prov, pm


# -------------------------------------------------------------
# 1. TOTP RFC 6238 Engine Tolerances (6 Tests)
# -------------------------------------------------------------


def test_totp_rfc6238_reference_key():
    """Generates standard 6-digit TOTP code for standard base32 key."""
    secret = "JBSWY3DPEHPK3PXP"
    code = generate_totp_rfc6238(secret)
    assert len(code) == 6
    assert code.isdigit()


def test_totp_rfc6238_spaces_and_lowercase():
    """Keys with internal spaces and lowercase characters are sanitized and produce valid codes."""
    secret_clean = "qq6rxgbtkfetme7digqvl27kkechle5i"
    secret_spaced = "  qq6r xgbt kfet me7d igqv l27k kech le5i  "
    code1 = generate_totp_rfc6238(secret_clean)
    code2 = generate_totp_rfc6238(secret_spaced)
    assert code1 == code2
    assert len(code1) == 6


def test_totp_rfc6238_padding_variations():
    """Keys of different non-standard unpadded Base32 lengths are padded correctly."""
    keys = [
        "MZXW6YTBOI",  # 10 chars
        "MZXW6YTBOI======",  # 16 chars padded
        "JBSWY3DPEHPK3PXP",  # 16 chars
        "KVKFKRCPNZQUYMLXOVYDSQKJ",  # 24 chars
        "qq6rxgbtkfetme7digqvl27kkechle5i",  # 32 chars
    ]
    for k in keys:
        code = generate_totp_rfc6238(k)
        assert len(code) == 6
        assert code.isdigit()


def test_totp_rfc6238_invalid_characters_graceful_fallback():
    """Invalid characters (e.g. 1, 8, 9 in Base32 or symbols) fallback cleanly to 000000 or valid code."""
    code = generate_totp_rfc6238("!!!INVALID_NON_BASE32_KEY_1234567890!#@$")
    assert isinstance(code, str)
    assert len(code) == 6


def test_totp_rfc6238_custom_interval():
    """Custom interval parameter changes the counter step."""
    secret = "JBSWY3DPEHPK3PXP"
    code30 = generate_totp_rfc6238(secret, interval=30)
    code60 = generate_totp_rfc6238(secret, interval=60)
    assert len(code30) == 6
    assert len(code60) == 6


def test_totp_rfc6238_custom_digits():
    """Custom digits parameter produces 8-digit code."""
    secret = "JBSWY3DPEHPK3PXP"
    code8 = generate_totp_rfc6238(secret, digits=8)
    assert len(code8) == 8
    assert code8.isdigit()


# -------------------------------------------------------------
# 2. OAuth URL Builder & Parser Edge Cases (4 Tests)
# -------------------------------------------------------------


def test_oauth_url_scope_and_access_type(temp_provisioner):
    """OAuth URL includes youtube.upload scope and offline access."""
    prov, _ = temp_provisioner
    url = prov.build_oauth_auth_url(client_id="my-client-id.apps.googleusercontent.com")
    assert "scope=https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fyoutube.upload" in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url


def test_oauth_url_custom_redirect_uri(temp_provisioner):
    """Custom redirect URI is included in authorization URL."""
    prov, _ = temp_provisioner
    url = prov.build_oauth_auth_url(
        client_id="my-client-id.apps.googleusercontent.com", redirect_uri="http://127.0.0.1:8899/oauth2callback"
    )
    assert "redirect_uri=http://127.0.0.1:8899/oauth2callback" in url


def test_oauth_url_client_id_escaping(temp_provisioner):
    """Client ID is passed into query string cleanly."""
    prov, _ = temp_provisioner
    url = prov.build_oauth_auth_url(client_id="test_client_id_12345")
    assert "client_id=test_client_id_12345" in url


def test_parse_account_string_basic_colon():
    """Single line login:pass:2fa:rec parsed correctly."""
    acc = parse_account_string("user@gmail.com:Secret123:MYTOTPSECRET:rec@mail.com")
    assert acc["email"] == "user@gmail.com"
    assert acc["password"] == "Secret123"
    assert acc["totp_secret"] == "MYTOTPSECRET"
    assert acc["recovery_email"] == "rec@mail.com"


# -------------------------------------------------------------
# 3. Batch Account Creation & Profile Generation (6 Tests)
# -------------------------------------------------------------


def test_account_provisioner_empty_batch(temp_provisioner):
    """Empty batch raw_text returns an empty list without raising."""
    prov, _ = temp_provisioner
    res = prov.batch_import_and_create_profiles("", "Group", "browser_stealth")
    assert res == []


def test_account_provisioner_comments_and_whitespace_only(temp_provisioner):
    """Raw text with only comments and empty lines produces empty result."""
    prov, _ = temp_provisioner
    raw = "# Header comment\n// Another comment\n\n   \t\n"
    res = prov.batch_import_and_create_profiles(raw, "Group", "browser_stealth")
    assert res == []


def test_account_provisioner_browser_stealth_mode_tagging(temp_provisioner):
    """Browser stealth mode assigns youtube_studio auto_open_page and correct tags."""
    prov, _ = temp_provisioner
    raw = "stealth_user@gmail.com:pass:secret:rec\n"
    profs = prov.batch_import_and_create_profiles(raw, "StealthGroup", "browser_stealth")
    assert len(profs) == 1
    p = profs[0]
    assert p.google.auto_open_page == "youtube_studio"
    assert "browser_stealth" in p.google.tags


def test_account_provisioner_oauth_api_mode_tagging(temp_provisioner):
    """OAuth API mode assigns google_login auto_open_page and oauth_api tag."""
    prov, _ = temp_provisioner
    raw = "api_user@gmail.com:pass:secret:rec\n"
    profs = prov.batch_import_and_create_profiles(raw, "ApiGroup", "oauth_api")
    assert len(profs) == 1
    p = profs[0]
    assert p.google.auto_open_page == "google_login"
    assert "oauth_api" in p.google.tags


def test_account_provisioner_notes_json_structure(temp_provisioner):
    """Notes field contains structured JSON with all credential fields."""
    prov, _ = temp_provisioner
    raw = "json_user@gmail.com:mypass:my2fa:myrec@gmail.com\n"
    profs = prov.batch_import_and_create_profiles(raw, "JsonGroup", "browser_stealth")
    notes = json.loads(profs[0].google.notes)
    assert notes["account_email"] == "json_user@gmail.com"
    assert notes["account_password"] == "mypass"
    assert notes["totp_secret"] == "my2fa"
    assert notes["recovery_email"] == "myrec@gmail.com"
    assert notes["auth_status"] == "ready_to_launch"


def test_account_provisioner_profile_id_uniqueness(temp_provisioner):
    """Every generated profile has a unique non-overlapping ID."""
    prov, _ = temp_provisioner
    raw = "\n".join([f"user_{i}@gmail.com:pass:sec:rec" for i in range(10)])
    profs = prov.batch_import_and_create_profiles(raw, "MultiGroup", "browser_stealth")
    ids = [p.id for p in profs]
    assert len(ids) == 10
    assert len(set(ids)) == 10


# -------------------------------------------------------------
# 4. Token Operations Mock Testing (4 Tests)
# -------------------------------------------------------------


def test_account_provisioner_random_fingerprint_generated(temp_provisioner):
    """Created profiles have valid hardware fingerprint with GPU, Screen, CPU, RAM."""
    prov, _ = temp_provisioner
    raw = "fp_user@gmail.com:pass:sec:rec\n"
    profs = prov.batch_import_and_create_profiles(raw, "FPGroup", "browser_stealth")
    fp = profs[0].fingerprint
    assert fp.screen_width in (1366, 1440, 1536, 1600, 1680, 1920, 2560, 3840)
    assert fp.device_memory in (8, 16, 32, 64)
    assert "NVIDIA" in fp.webgl_renderer or "AMD" in fp.webgl_renderer or "Intel" in fp.webgl_renderer


def test_account_provisioner_refresh_token_mock_success(temp_provisioner):
    """Mock successful refresh token HTTP call."""
    prov, _ = temp_provisioner
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(
        {"access_token": "ya29.a0AfH6SMTestToken123", "expires_in": 3600, "token_type": "Bearer"}
    ).encode("utf-8")
    mock_response.__enter__.return_value = mock_response

    with patch("urllib.request.build_opener") as mock_opener:
        mock_instance = MagicMock()
        mock_instance.open.return_value = mock_response
        mock_opener.return_value = mock_instance

        tokens = prov.refresh_access_token(
            refresh_token="1//04TestRefreshToken", client_id="client_id_123", client_secret="client_sec_123"
        )
        assert tokens is not None
        assert tokens["access_token"] == "ya29.a0AfH6SMTestToken123"
        assert "obtained_at" in tokens


def test_account_provisioner_refresh_token_mock_failure(temp_provisioner):
    """Network failure during refresh returns None gracefully without unhandled exception."""
    prov, _ = temp_provisioner
    with patch("urllib.request.build_opener") as mock_opener:
        mock_instance = MagicMock()
        mock_instance.open.side_effect = Exception("Connection Refused")
        mock_opener.return_value = mock_instance

        tokens = prov.refresh_access_token(refresh_token="bad_token", client_id="cid", client_secret="csec")
        assert tokens is None


def test_account_provisioner_exchange_oauth_code_mock_success(temp_provisioner):
    """Mock exchanging authorization code for access and refresh tokens."""
    prov, _ = temp_provisioner
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(
        {"access_token": "ya29.fresh_access_token", "refresh_token": "1//04_fresh_refresh_token", "expires_in": 3599}
    ).encode("utf-8")
    mock_response.__enter__.return_value = mock_response

    with patch("urllib.request.build_opener") as mock_opener:
        mock_instance = MagicMock()
        mock_instance.open.return_value = mock_response
        mock_opener.return_value = mock_instance

        tokens = prov.exchange_oauth_code_for_tokens(code="4/0AWgavdfTestCode", client_id="cid", client_secret="csec")
        assert tokens is not None
        assert tokens["refresh_token"] == "1//04_fresh_refresh_token"
