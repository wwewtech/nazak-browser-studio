"""
Encrypted secrets storage with user-selectable backend.

The user decides how sensitive fields (account password, TOTP secret) are
stored at rest in ``profiles.json``. Three modes:

- **plain**      — no encryption (legacy behavior). Fully readable in GUI/API.
- **dpapi**      — Windows DPAPI (user-scoped, zero management). Windows-only.
- **passphrase** — Fernet (AES-128-CBC + HMAC), key derived from the user's
  own passphrase (PBKDF2-HMAC-SHA256, 600k iterations). Lose the passphrase —
  lose the data.

The choice is always the user's, in three places:
- REST API: ``GET/POST /api/security/secrets-mode`` (see ``nazak/api/server.py``)
- GUI: SettingsView → "Secrets Storage" card (see ``nazak/gui/views/settings_view.py``)
- Docs: ``docs/API_REFERENCE.md`` → "Secrets Storage" section

Envelopes are self-describing (``nzk1:...``), so legacy plaintext notes stay
readable regardless of the current mode.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import sys

logger = logging.getLogger(__name__)

try:  # pragma: no cover - import guard
    from cryptography.fernet import Fernet, InvalidToken
    from cryptography.hazmat.primitives.hashes import SHA256
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    _HAS_CRYPTOGRAPHY = True
except ImportError:  # pragma: no cover
    _HAS_CRYPTOGRAPHY = False

IS_WINDOWS = sys.platform == "win32"

SECRETS_MODES = ("plain", "dpapi", "passphrase")
DEFAULT_SECRETS_MODE = "plain"
PBKDF2_ITERATIONS = 600_000

_ENVELOPE_PREFIX = "nzk1:"
_TAG_DPAPI = "dpapi"
_TAG_PWD = "pwd"
_SALT_BYTES = 16

ENVELOPE_KEY = "_secrets_mode"
SECRET_FIELDS = ("account_password", "totp_secret")

# Where the user-selected mode + (optional) passphrase are persisted.
# Passphrase itself is NEVER persisted to disk; it is held in memory only
# for the current process lifetime (set via API/GUI or env var).
MODE_FILE = None  # set by set_mode_file() during app bootstrap
_in_memory_passphrase: str | None = None
_current_mode: str = DEFAULT_SECRETS_MODE


class SecretsError(Exception):
    """Raised on invalid mode selection or corrupted envelopes."""


class SecretsDecryptError(SecretsError):
    """Raised when an envelope cannot be decrypted (wrong passphrase / corrupt)."""


def mask_secret(value: str | None) -> str:
    """Stable mask for API/GUI display, e.g. ``abc...wxyz`` (8+ chars) or ``***``."""
    if not value:
        return ""
    if len(value) <= 8:
        return "***"
    return f"{value[:3]}...{value[-4:]}"


def is_encrypted_value(value: str | None) -> bool:
    """True when the string is one of our versioned envelopes."""
    return bool(value) and value.startswith(_ENVELOPE_PREFIX)


def normalize_mode(mode: str | None) -> str:
    """Validate a user-selected mode; raises SecretsError with guidance."""
    if not mode:
        return DEFAULT_SECRETS_MODE
    mode = str(mode).strip().lower()
    if mode not in SECRETS_MODES:
        raise SecretsError(
            f"Unknown secrets mode {mode!r}. Available: {', '.join(SECRETS_MODES)}"
        )
    if mode == "dpapi" and not IS_WINDOWS:
        raise SecretsError(
            "Mode 'dpapi' is Windows-only. Choose 'passphrase' or 'plain' on this platform."
        )
    return mode


def set_mode_file(path) -> None:
    """Register where the user-selected mode is persisted (JSON file)."""
    global MODE_FILE
    MODE_FILE = path


def get_current_mode() -> str:
    """Currently active mode (default ``plain`` until user selects otherwise)."""
    return _current_mode


def set_current_mode(mode: str, passphrase: str | None = None) -> str:
    """Switch the active mode at runtime (API/GUI call this)."""
    global _current_mode, _in_memory_passphrase
    _current_mode = normalize_mode(mode)
    _in_memory_passphrase = passphrase
    _persist_mode()
    return _current_mode


def set_passphrase(passphrase: str | None) -> None:
    """Provide/replace the in-memory passphrase (for 'passphrase' mode)."""
    global _in_memory_passphrase
    _in_memory_passphrase = passphrase


def get_passphrase() -> str | None:
    return _in_memory_passphrase


def _persist_mode() -> None:
    """Persist the selected mode so it survives restarts (passphrase never saved)."""
    if MODE_FILE is None:
        return
    try:
        os.makedirs(os.path.dirname(str(MODE_FILE)), exist_ok=True)
        with open(MODE_FILE, "w", encoding="utf-8") as f:
            json.dump({"mode": _current_mode}, f)
    except Exception as exc:
        logger.warning("Failed to persist secrets mode: %s", exc)


def load_mode() -> str:
    """Load persisted mode at bootstrap; falls back to 'plain'."""
    global _current_mode
    if MODE_FILE is not None and os.path.isfile(str(MODE_FILE)):
        try:
            with open(MODE_FILE, encoding="utf-8") as f:
                data = json.load(f)
            _current_mode = normalize_mode(data.get("mode"))
        except Exception as exc:
            logger.warning("Failed to load secrets mode, defaulting to plain: %s", exc)
            _current_mode = DEFAULT_SECRETS_MODE
    return _current_mode


# ---------------------------------------------------------------------------
# Crypto backends
# ---------------------------------------------------------------------------

def _derive_key(passphrase: str, salt: bytes) -> bytes:
    """PBKDF2-HMAC-SHA256 -> Fernet key (600k iterations, OWASP 2023)."""
    kdf = PBKDF2HMAC(
        algorithm=SHA256(),
        length=32,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))


def _fernet_encrypt(raw: bytes, passphrase: str) -> str:
    salt = os.urandom(_SALT_BYTES)
    f = Fernet(_derive_key(passphrase, salt))
    token = f.encrypt(raw)
    salt_b64 = base64.urlsafe_b64encode(salt).decode("ascii")
    return f"{_ENVELOPE_PREFIX}{_TAG_PWD}:{salt_b64}:{token.decode('ascii')}"


def _fernet_decrypt(envelope: str, passphrase: str | None) -> bytes:
    if not passphrase:
        raise SecretsDecryptError(
            "Envelope requires the user passphrase (mode 'passphrase'), "
            "but none was provided."
        )
    try:
        _prefix, _tag, salt_b64, token = envelope.split(":", 3)
        salt = base64.urlsafe_b64decode(salt_b64.encode("ascii"))
        f = Fernet(_derive_key(passphrase, salt))
        return f.decrypt(token.encode("ascii"))
    except InvalidToken as exc:
        raise SecretsDecryptError(
            "Wrong passphrase or corrupted envelope (HMAC verification failed)."
        ) from exc
    except SecretsDecryptError:
        raise
    except Exception as exc:
        raise SecretsDecryptError(f"Malformed passphrase envelope: {exc}") from exc


# -- Windows DPAPI (user scope): no passphrase management needed ------------

def _dpapi_protect(raw: bytes) -> str:
    import ctypes
    import ctypes.wintypes

    class _DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", ctypes.wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        ]

    buf = ctypes.create_string_buffer(raw, len(raw))
    input_blob = _DATA_BLOB(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    output_blob = _DATA_BLOB()
    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(input_blob), None, None, None, None, 0,
        ctypes.byref(output_blob),
    )
    if not ok:
        raise SecretsError(f"DPAPI CryptProtectData failed: {ctypes.GetLastError()}")
    out = ctypes.string_at(output_blob.pbData, output_blob.cbData)
    ctypes.windll.kernel32.LocalFree(output_blob.pbData)
    return f"{_ENVELOPE_PREFIX}{_TAG_DPAPI}:{base64.b64encode(out).decode('ascii')}"


def _dpapi_unprotect(envelope: str) -> bytes:
    import ctypes
    import ctypes.wintypes

    class _DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", ctypes.wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        ]

    try:
        _prefix, _tag, data_b64 = envelope.split(":", 2)
        raw = base64.b64decode(data_b64.encode("ascii"))
    except Exception as exc:
        raise SecretsDecryptError(f"Malformed DPAPI envelope: {exc}") from exc

    buf = ctypes.create_string_buffer(raw, len(raw))
    input_blob = _DATA_BLOB(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    output_blob = _DATA_BLOB()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(input_blob), None, None, None, None, 0,
        ctypes.byref(output_blob),
    )
    if not ok:
        raise SecretsDecryptError(
            f"DPAPI CryptUnprotectData failed: {ctypes.GetLastError()} "
            "(envelope encrypted for a different Windows user?)"
        )
    out = ctypes.string_at(output_blob.pbData, output_blob.cbData)
    ctypes.windll.kernel32.LocalFree(output_blob.pbData)
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def encrypt_secret(value: str, mode: str | None = None, passphrase: str | None = None) -> str:
    """Encrypt one field value into its self-describing envelope string.

    Empty values pass through. ``mode=None`` uses the active runtime mode.
    In ``passphrase`` mode with no passphrase available the value is stored
    as-is and a warning is logged (never blocks the user's workflow).
    """
    if not value:
        return value
    effective_mode = normalize_mode(mode) if mode else _current_mode
    if effective_mode == "plain":
        return value
    if effective_mode == "dpapi":
        return _dpapi_protect(value.encode("utf-8"))
    if effective_mode == "passphrase":
        eff_passphrase = passphrase if passphrase is not None else _in_memory_passphrase
        if not eff_passphrase:
            logger.warning(
                "Secrets: 'passphrase' mode is active but no passphrase is set; "
                "storing value as plaintext."
            )
            return value
        return _fernet_encrypt(value.encode("utf-8"), eff_passphrase)
    raise SecretsError(f"Unsupported mode: {effective_mode!r}")


def decrypt_secret(envelope: str, passphrase: str | None = None) -> str:
    """Decrypt a single envelope back to plaintext.

    Plaintext input passes through unchanged (legacy notes stay readable).
    """
    if not envelope or not is_encrypted_value(envelope):
        return envelope

    body = envelope[len(_ENVELOPE_PREFIX):]
    if body.startswith(_TAG_DPAPI + ":"):
        if not IS_WINDOWS:
            raise SecretsDecryptError("DPAPI envelope found on a non-Windows platform.")
        return _dpapi_unprotect(envelope).decode("utf-8")
    if body.startswith(_TAG_PWD + ":"):
        eff_passphrase = passphrase if passphrase is not None else _in_memory_passphrase
        return _fernet_decrypt(envelope, eff_passphrase).decode("utf-8")
    raise SecretsDecryptError(f"Unknown envelope scheme: {body.split(':', 1)[0]!r}")


# ---------------------------------------------------------------------------
# Notes-level helpers (whole notes-JSON processing)
# ---------------------------------------------------------------------------

def _strip_helper_keys(notes: dict) -> dict:
    """Remove transient helper keys (``_totp_raw`` etc.) before persist/encrypt."""
    return {k: v for k, v in notes.items() if not k.startswith("_")}


def encrypt_notes(notes: dict, mode: str | None = None, passphrase: str | None = None) -> dict:
    """Encrypt ``SECRET_FIELDS`` inside a notes dict; adds the mode envelope key."""
    result = dict(_strip_helper_keys(notes))
    for field in SECRET_FIELDS:
        raw = result.get(field)
        if raw and not is_encrypted_value(raw):
            result[field] = encrypt_secret(str(raw), mode=mode, passphrase=passphrase)
    result[ENVELOPE_KEY] = normalize_mode(mode) if mode else _current_mode
    return result


def decrypt_notes(notes: dict, passphrase: str | None = None, reveal: bool = False) -> dict:
    """Decrypt ``SECRET_FIELDS`` inside a notes dict.

    ``reveal=False`` returns masked values for API/GUI listing;
    ``reveal=True`` returns full plaintext for the actual login flow.
    Additionally injects ``_totp_raw`` (raw TOTP secret) for the GUI ticker.
    """
    result = dict(notes)
    for field in SECRET_FIELDS:
        raw = result.get(field)
        if not raw:
            continue
        raw = str(raw)
        try:
            plain = decrypt_secret(raw, passphrase=passphrase)
        except SecretsDecryptError:
            result[field] = "<encrypted: unavailable passphrase>"
            continue
        if field == "totp_secret":
            result["_totp_raw"] = plain
        result[field] = plain if reveal else mask_secret(plain)
    return result


def reveal_notes(notes: dict, passphrase: str | None = None) -> dict:
    """Full-plaintext variant used by the automated login flow."""
    return decrypt_notes(notes, passphrase=passphrase, reveal=True)
