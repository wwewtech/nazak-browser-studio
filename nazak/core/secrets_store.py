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
from typing import Any

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
# Shown instead of a value whose envelope cannot be opened right now. It is a
# *display* value: it must never be written back over the real secret.
UNAVAILABLE_PLACEHOLDER = "<encrypted: unavailable passphrase>"

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
    return value is not None and value.startswith(_ENVELOPE_PREFIX)


def normalize_mode(mode: str | None) -> str:
    """Validate a user-selected mode; raises SecretsError with guidance."""
    if not mode:
        return DEFAULT_SECRETS_MODE
    mode = str(mode).strip().lower()
    if mode not in SECRETS_MODES:
        raise SecretsError(f"Unknown secrets mode {mode!r}. Available: {', '.join(SECRETS_MODES)}")
    if mode == "dpapi" and not IS_WINDOWS:
        raise SecretsError("Mode 'dpapi' is Windows-only. Choose 'passphrase' or 'plain' on this platform.")
    if mode == "passphrase" and not _HAS_CRYPTOGRAPHY:
        # Audit R3: раньше флаг _HAS_CRYPTOGRAPHY вычислялся и нигде не читался,
        # поэтому без пакета cryptography режим падал с NameError в недрах KDF.
        raise SecretsError(
            "Mode 'passphrase' requires the 'cryptography' package (pip install cryptography). "
            "Choose 'dpapi' on Windows or 'plain'."
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
    """Switch the active mode at runtime (API/GUI call this).

    Selecting ``passphrase`` without supplying one is rejected up front, so the
    GUI/API can never advertise a strong mode while values land in plaintext.
    """
    global _current_mode, _in_memory_passphrase
    effective = normalize_mode(mode)
    if effective == "passphrase":
        if passphrase:
            _in_memory_passphrase = passphrase
        elif not _in_memory_passphrase:
            raise SecretsError("Passphrase mode requires a passphrase. Enter one to continue.")
    else:
        _in_memory_passphrase = None
    _current_mode = effective
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
        raise SecretsDecryptError("Envelope requires the user passphrase (mode 'passphrase'), but none was provided.")
    try:
        _prefix, _tag, salt_b64, token = envelope.split(":", 3)
        salt = base64.urlsafe_b64decode(salt_b64.encode("ascii"))
        f = Fernet(_derive_key(passphrase, salt))
        return f.decrypt(token.encode("ascii"))
    except InvalidToken as exc:
        raise SecretsDecryptError("Wrong passphrase or corrupted envelope (HMAC verification failed).") from exc
    except SecretsDecryptError:
        raise
    except Exception as exc:
        raise SecretsDecryptError(f"Malformed passphrase envelope: {exc}") from exc


# -- Windows DPAPI (user scope): no passphrase management needed ------------


def _windows_dpapi_api() -> tuple[Any, Any]:
    """Windows-only вход в crypt32/kernel32 через ctypes.

    Audit R3-round2: обращаемся через getattr, потому что на Linux typeshed не
    знает ``ctypes.windll``/``GetLastError`` — прямой доступ валил mypy
    (attr-defined) на CI-раннере, хотя код всё равно работает только на Windows.
    """
    import ctypes

    windll = getattr(ctypes, "windll", None)
    if windll is None:  # pragma: no cover - выполняется только вне Windows
        raise SecretsError("DPAPI is only available on Windows")
    get_last_error = getattr(ctypes, "GetLastError", None)
    return windll, get_last_error


def _dpapi_protect(raw: bytes) -> str:
    import ctypes
    import ctypes.wintypes

    windll, get_last_error = _windows_dpapi_api()

    class _DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", ctypes.wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        ]

    buf = ctypes.create_string_buffer(raw, len(raw))
    input_blob = _DATA_BLOB(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    output_blob = _DATA_BLOB()
    ok = windll.crypt32.CryptProtectData(
        ctypes.byref(input_blob),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(output_blob),
    )
    if not ok:
        code = get_last_error() if get_last_error else "unknown"
        raise SecretsError(f"DPAPI CryptProtectData failed: {code}")
    out = ctypes.string_at(output_blob.pbData, output_blob.cbData)
    windll.kernel32.LocalFree(output_blob.pbData)
    return f"{_ENVELOPE_PREFIX}{_TAG_DPAPI}:{base64.b64encode(out).decode('ascii')}"


def _dpapi_unprotect(envelope: str) -> bytes:
    import ctypes
    import ctypes.wintypes

    windll, get_last_error = _windows_dpapi_api()

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
    ok = windll.crypt32.CryptUnprotectData(
        ctypes.byref(input_blob),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(output_blob),
    )
    if not ok:
        code = get_last_error() if get_last_error else "unknown"
        raise SecretsDecryptError(
            f"DPAPI CryptUnprotectData failed: {code} (envelope encrypted for a different Windows user?)"
        )
    out = ctypes.string_at(output_blob.pbData, output_blob.cbData)
    windll.kernel32.LocalFree(output_blob.pbData)
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def encrypt_secret(value: str, mode: str | None = None, passphrase: str | None = None) -> str:
    """Encrypt one field value into its self-describing envelope string.

    Empty values pass through. ``mode=None`` uses the active runtime mode.
    ``passphrase`` mode without a passphrase raises :class:`SecretsError` —
    silently degrading to plaintext would make the mode selector a lie.
    """
    if not value:
        return value
    effective_mode = normalize_mode(mode) if mode else _current_mode
    if effective_mode == "plain":
        return value
    if effective_mode == "dpapi":
        return _dpapi_protect(value.encode("utf-8"))
    if effective_mode == "passphrase":
        if not _HAS_CRYPTOGRAPHY:
            raise SecretsError("Passphrase mode needs the 'cryptography' package (pip install cryptography).")
        eff_passphrase = passphrase if passphrase is not None else _in_memory_passphrase
        if not eff_passphrase:
            raise SecretsError(
                "Passphrase mode is active but no passphrase is available. "
                "Provide the passphrase (Settings -> Secrets Storage) instead of storing the value unprotected."
            )
        return _fernet_encrypt(value.encode("utf-8"), eff_passphrase)
    raise SecretsError(f"Unsupported mode: {effective_mode!r}")


def decrypt_secret(envelope: str, passphrase: str | None = None) -> str:
    """Decrypt a single envelope back to plaintext.

    Plaintext input passes through unchanged (legacy notes stay readable).
    """
    if not envelope or not is_encrypted_value(envelope):
        return envelope

    body = envelope[len(_ENVELOPE_PREFIX) :]
    if body.startswith(_TAG_DPAPI + ":"):
        if not IS_WINDOWS:
            raise SecretsDecryptError("DPAPI envelope found on a non-Windows platform.")
        return _dpapi_unprotect(envelope).decode("utf-8")
    if body.startswith(_TAG_PWD + ":"):
        if not _HAS_CRYPTOGRAPHY:
            raise SecretsDecryptError("Passphrase envelope found, but the 'cryptography' package is not installed.")
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
    """Encrypt ``SECRET_FIELDS`` inside a notes dict; adds the mode envelope key.

    Like the proxy protection below, a mode that cannot encrypt right now
    (``passphrase`` selected but not supplied) must not block the write — the
    value stays readable and a warning is logged so the gap is visible.
    """
    result = dict(_strip_helper_keys(notes))
    incoming_label = notes.get(ENVELOPE_KEY)
    encrypted_any = False
    for field in SECRET_FIELDS:
        raw = result.get(field)
        if raw and not is_encrypted_value(raw):
            try:
                result[field] = encrypt_secret(str(raw), mode=mode, passphrase=passphrase)
                encrypted_any = True
            except SecretsError as exc:
                # Значение остаётся читаемым намеренно (не блокируем запись), но
                # это ошибка уровня ERROR, а не тихое предупреждение (audit R3).
                logger.error("Secrets: notes %s left unprotected for this save: %s", field, exc)
    # Label the record with the mode the values actually live in: keep the
    # incoming label when nothing was (re)encrypted, so a mixed store never
    # claims "plain" while envelopes are still present.
    if encrypted_any:
        result[ENVELOPE_KEY] = normalize_mode(mode) if mode else _current_mode
    elif isinstance(incoming_label, str) and incoming_label:
        try:
            result[ENVELOPE_KEY] = normalize_mode(incoming_label)
        except SecretsError:
            result[ENVELOPE_KEY] = normalize_mode(mode) if mode else _current_mode
    else:
        result[ENVELOPE_KEY] = normalize_mode(mode) if mode else _current_mode
    return result


def decrypt_notes(notes: dict, passphrase: str | None = None, reveal: bool = False) -> dict:
    """Decrypt ``SECRET_FIELDS`` inside a notes dict.

    ``reveal=False`` returns masked values for API/GUI listing and never
    exposes plaintext: ``_totp_raw`` is injected **only** on the ``reveal=True``
    path (audit D2-P0-1 — a display listing must not hand out a live 2FA seed).
    ``reveal=True`` returns full plaintext for the actual login flow.
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
            result[field] = UNAVAILABLE_PLACEHOLDER
            continue
        if field == "totp_secret" and reveal:
            result["_totp_raw"] = plain
        result[field] = plain if reveal else mask_secret(plain)
    return result


def reveal_notes(notes: dict, passphrase: str | None = None) -> dict:
    """Full-plaintext variant used by the automated login flow."""
    return decrypt_notes(notes, passphrase=passphrase, reveal=True)


def is_display_value(value: str | None, stored_value: str | None) -> bool:
    """True when ``value`` is only a rendering of ``stored_value``, not new input.

    Covers the three shapes a client can echo back to us: the mask produced by
    :func:`mask_secret`, the unavailable-passphrase placeholder, and the stored
    envelope itself (pass-through).
    """
    if not isinstance(value, str) or not isinstance(stored_value, str):
        return False
    if value in (stored_value, UNAVAILABLE_PLACEHOLDER):
        return True
    if value.startswith("<encrypted"):
        return True
    try:
        stored_plain = decrypt_secret(stored_value)
    except SecretsDecryptError:
        # Cannot tell display from intent — never let a non-envelope win.
        return not is_encrypted_value(value)
    return value == mask_secret(stored_plain)


def sanitize_notes_for_write(new_notes: dict, stored_notes: dict | None = None) -> dict:
    """Prepare client-supplied notes for persistence (audit D2-P0-2).

    Rules: helper keys (``_*``) are always dropped, an existing envelope is
    never replaced by its display mask / placeholder, and a genuinely new
    plaintext value is passed through so the write path can encrypt it.
    """
    stored = dict(stored_notes or {})
    # Helper keys are dropped, except the record's own mode label: losing it
    # would make the write path re-label old envelopes with the current mode.
    result = {k: v for k, v in new_notes.items() if not k.startswith("_") or k == ENVELOPE_KEY}
    for field in SECRET_FIELDS:
        if field not in result:
            continue
        stored_value = stored.get(field)
        if stored_value and is_display_value(result[field], stored_value):
            result[field] = stored_value
    return result


# --- Proxy credentials at rest (audit D2-P0-3) -----------------------------
#
# ``proxy.password`` / ``proxy.raw`` / ``proxy.rotation_url`` carry live
# credentials in every storage mode; they are protected on the way to disk and
# opened on the way back, so the rest of the codebase always sees plaintext.

PROXY_SECRET_FIELDS = ("password", "raw", "rotation_url")


def protect_proxy_fields(proxy: dict) -> dict:
    """Encrypt the credential-bearing proxy keys for storage."""
    if _current_mode == "plain":
        return proxy
    out = dict(proxy)
    for field in PROXY_SECRET_FIELDS:
        value = out.get(field)
        if not value or not isinstance(value, str) or is_encrypted_value(value):
            continue
        try:
            out[field] = encrypt_secret(value, mode=_current_mode)
        except SecretsError as exc:
            # Never block persistence: keep the value readable and say so loudly.
            logger.error("Secrets: proxy %s left unprotected for this save: %s", field, exc)
    return out


def unprotect_proxy_fields(proxy: dict) -> dict:
    """Best-effort decryption of proxy credentials read from storage."""
    out = dict(proxy)
    for field in PROXY_SECRET_FIELDS:
        value = out.get(field)
        if not value or not isinstance(value, str) or not is_encrypted_value(value):
            continue
        try:
            out[field] = decrypt_secret(value)
        except SecretsDecryptError as exc:
            logger.warning("Secrets: cannot open stored proxy %s: %s", field, exc)
    return out
