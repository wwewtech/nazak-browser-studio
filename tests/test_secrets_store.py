"""Phase 3: secrets storage (plain / dpapi / passphrase) — user-selectable mode."""

import json

import pytest

from nazak.core import secrets_store as ss


@pytest.fixture(autouse=True)
def _clean_state():
    """Reset module globals around each test."""
    old_mode, old_pass, old_file = ss._current_mode, ss._in_memory_passphrase, ss.MODE_FILE
    yield
    ss._current_mode = old_mode
    ss._in_memory_passphrase = old_pass
    ss.MODE_FILE = old_file


def test_mask_secret():
    assert ss.mask_secret(None) == ""
    assert ss.mask_secret("") == ""
    assert ss.mask_secret("short") == "***"
    assert ss.mask_secret("abcdefghij") == "abc...ghij"


def test_normalize_mode_rejects_unknown():
    with pytest.raises(ss.SecretsError):
        ss.normalize_mode("rot13")
    assert ss.normalize_mode(None) == "plain"
    assert ss.normalize_mode(" PASSPHRASE ") == "passphrase"


def test_plain_mode_passthrough():
    assert ss.encrypt_secret("secret", mode="plain") == "secret"
    assert ss.decrypt_secret("secret") == "secret"


def test_passphrase_roundtrip_and_wrong_key():
    enc = ss.encrypt_secret("S3cret!+", mode="passphrase", passphrase="right")
    assert enc.startswith("nzk1:pwd:")
    assert ss.decrypt_secret(enc, passphrase="right") == "S3cret!+"
    with pytest.raises(ss.SecretsDecryptError):
        ss.decrypt_secret(enc, passphrase="wrong")
    with pytest.raises(ss.SecretsDecryptError):
        ss.decrypt_secret(enc)  # no passphrase at all


def test_passphrase_mode_without_passphrase_stores_plaintext():
    out = ss.encrypt_secret("visible", mode="passphrase", passphrase=None)
    assert out == "visible"


def test_dpapi_roundtrip_windows_only():
    if not ss.IS_WINDOWS:
        with pytest.raises(ss.SecretsError):
            ss.encrypt_secret("x", mode="dpapi")
        return
    enc = ss.encrypt_secret("dpdata", mode="dpapi")
    assert enc.startswith("nzk1:dpapi:")
    assert ss.decrypt_secret(enc) == "dpdata"


def test_encrypt_notes_and_masking():
    notes = {
        "account_email": "a@b.c",
        "account_password": "pw123456789",
        "totp_secret": "TOPSECRET",
        "recovery_email": "r@x.y",
    }
    enc = ss.encrypt_notes(notes, mode="passphrase", passphrase="p1")
    assert enc["_secrets_mode"] == "passphrase"
    assert enc["account_email"] == "a@b.c"  # non-secret untouched
    assert ss.is_encrypted_value(enc["account_password"])
    masked = ss.decrypt_notes(enc, passphrase="p1")
    assert masked["account_password"] == "pw1...6789"
    assert masked["totp_secret"] == "TOP...CRET"
    revealed = ss.reveal_notes(enc, passphrase="p1")
    assert revealed["account_password"] == "pw123456789"
    assert revealed["totp_secret"] == "TOPSECRET"


def test_decrypt_notes_without_passphrase_shows_placeholder():
    enc = ss.encrypt_notes({"account_password": "pw123456789"}, mode="passphrase", passphrase="p")
    out = ss.decrypt_notes(enc)
    assert out["account_password"] == "<encrypted: unavailable passphrase>"


def test_legacy_plaintext_notes_stay_readable():
    out = ss.decrypt_notes({"account_password": "legacypw12345"})
    assert out["account_password"] == "leg...2345"
    assert ss.decrypt_secret("legacypw12345") == "legacypw12345"


def test_mode_persistence_roundtrip(tmp_path):
    ss.set_mode_file(tmp_path / "mode.json")
    ss.set_current_mode("passphrase", passphrase="tmp")
    assert ss.get_current_mode() == "passphrase"
    assert ss.load_mode() == "passphrase"
    # passphrase must never reach the disk
    content = (tmp_path / "mode.json").read_text(encoding="utf-8")
    assert "tmp" not in content
    ss.set_current_mode("plain")
    assert ss.load_mode() == "plain"


def test_encrypt_notes_idempotent():
    enc1 = ss.encrypt_notes({"account_password": "x12345678"}, mode="plain")
    enc2 = ss.encrypt_notes(enc1, mode="plain")
    assert enc1["account_password"] == enc2["account_password"] == "x12345678"


def test_reencrypt_never_persists_masked_or_helper_values(tmp_path):
    """Critical: masked display values must never be re-encrypted to disk."""
    from nazak.core.profile_manager import ProfileManager
    from nazak.models.profile import BrowserProfile, GoogleSettings

    pm = ProfileManager(tmp_path / "profiles.json", tmp_path / "data")
    secret = "RealSecretValue99"
    created = pm.create_profile(
        BrowserProfile(
            name="reenc",
            google=GoogleSettings(
                notes=json.dumps(
                    ss.encrypt_notes({"account_password": secret}, mode="passphrase", passphrase="k1")
                )
            ),
        )
    )

    # Switch to the SAME passphrase explicitly and re-encrypt (user decision).
    # (Re-encrypting with the current in-memory passphrase works; switching
    # the passphrase requires reveal with the OLD one first — the GUI collects
    # both and the API keeps envelopes decodable either way.)
    ss.set_current_mode("passphrase", passphrase="k1")
    assert pm.reencrypt_all_profile_secrets() == 1

    stored = json.loads(pm.get_profile(created.id).google.notes)
    assert secret not in json.dumps(stored)  # still an envelope
    revealed = ss.reveal_notes(stored, passphrase="k1")
    assert revealed["account_password"] == secret
    assert "_totp_raw" not in stored  # helper keys never leak to disk


def test_reencrypt_skips_undecryptable_profiles(tmp_path):
    """Missing passphrase -> profile left untouched, never clobbered."""
    from nazak.core.profile_manager import ProfileManager
    from nazak.models.profile import BrowserProfile, GoogleSettings

    pm = ProfileManager(tmp_path / "profiles.json", tmp_path / "data")
    before = json.dumps(ss.encrypt_notes({"account_password": "KeepMe01"}, mode="passphrase", passphrase="k"))
    locked = pm.create_profile(BrowserProfile(name="locked", google=GoogleSettings(notes=before)))

    ss._in_memory_passphrase = None  # simulate restart without passphrase
    ss._current_mode = "plain"
    assert pm.reencrypt_all_profile_secrets() == 0
    assert json.loads(pm.get_profile(locked.id).google.notes) == json.loads(before)
