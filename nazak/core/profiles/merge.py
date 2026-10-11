"""Field-set aware merge helpers (P0 refactor). Verbatim from core/profile_manager.py."""

import json
from typing import Any

from ...models.profile import BrowserProfile, FingerprintConfig, GoogleSettings
from ...models.proxy import ProxyConfig, ProxyType
from ..secrets_store import encrypt_notes, sanitize_notes_for_write
from .constants import MASK


def load_notes_dict(raw: Any) -> dict | None:
    """Parse a notes value into a dict; returns None for free-text notes."""
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str) and raw.lstrip().startswith("{"):
        try:
            data = json.loads(raw)
        except Exception:
            return None
        return data if isinstance(data, dict) else None
    return None


def raw_from_proxy(proxy: ProxyConfig) -> str | None:
    """Rebuild the human-readable proxy string from structured fields."""
    if proxy.is_direct():
        return proxy.raw
    proto = proxy.type.value
    if proxy.has_auth():
        return f"{proto}://{proxy.username}:{proxy.password}@{proxy.host}:{proxy.port}"
    return f"{proto}://{proxy.host}:{proxy.port}"


def merge_proxy(incoming: ProxyConfig, stored: ProxyConfig, fields_set: set[str]) -> ProxyConfig:
    merged = stored.model_copy(deep=True)

    if "raw" in fields_set:
        raw = (incoming.raw or "").strip()
        if not raw or raw.lower() in ("direct", "none", "null"):
            return ProxyConfig(type=ProxyType.DIRECT, raw=raw or None)
        if MASK in raw:
            parsed = ProxyConfig.parse(raw)
            merged.host = parsed.host if parsed.host is not None else stored.host
            merged.port = parsed.port if parsed.port is not None else stored.port
            merged.username = parsed.username if parsed.username not in (None, "", MASK) else stored.username
            merged.password = stored.password if parsed.password in (None, "", MASK) else parsed.password
            merged.type = parsed.type
            merged.rotation_url = stored.rotation_url if parsed.rotation_url is None else parsed.rotation_url
            merged.raw = raw_from_proxy(merged)
        else:
            parsed = ProxyConfig.parse(raw)
            if parsed.rotation_url is None and "rotation_url" not in fields_set:
                parsed.rotation_url = stored.rotation_url
            merged = parsed

    for field in fields_set - {"raw"}:
        if field not in ProxyConfig.model_fields:
            continue
        value = getattr(incoming, field, None)
        if value == MASK:
            value = getattr(stored, field, None)
        setattr(merged, field, value)

    if "raw" not in fields_set and fields_set & {"host", "port", "username", "password"}:
        merged.raw = raw_from_proxy(merged)
    if "active" not in fields_set and "raw" in fields_set:
        merged.active = stored.active
    return merged


def sanitize_notes(new_profile: BrowserProfile, stored_profile: BrowserProfile | None) -> None:
    if not new_profile.google:
        return
    incoming = load_notes_dict(new_profile.google.notes)
    if incoming is None:
        return
    stored = None
    if stored_profile is not None and stored_profile.google:
        stored = load_notes_dict(stored_profile.google.notes)
    cleaned = sanitize_notes_for_write(incoming, stored or {})
    new_profile.google.notes = json.dumps(encrypt_notes(cleaned))


def merge_fingerprint(incoming: FingerprintConfig, stored: FingerprintConfig) -> FingerprintConfig:
    merged = stored.model_copy(deep=True)
    for field in incoming.model_fields_set:
        if field in FingerprintConfig.model_fields:
            setattr(merged, field, getattr(incoming, field))
    return merged


def merge_google(incoming: GoogleSettings | None, stored: GoogleSettings | None) -> GoogleSettings | None:
    if stored is None:
        return incoming
    if incoming is None:
        return stored.model_copy(deep=True)
    merged = stored.model_copy(deep=True)
    for field in incoming.model_fields_set:
        if field in GoogleSettings.model_fields:
            setattr(merged, field, getattr(incoming, field))
    return merged
