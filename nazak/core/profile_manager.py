"""
Profile Manager facade (P0 refactor): same public API as the old 1195-line
core/profile_manager.py, now delegating to the nazak.core.profiles package
(store backends, service, bundles, files, presets, merge).

Compat notes (load-bearing for the 725-test suite):
- ``profiles`` stays a plain mutable dict attribute; ``_save_lock`` an RLock.
- module-level ``MAX_MASS_GENERATE_COUNT`` / ``MAX_BUNDLE_*`` / ``_BUNDLE_CHUNK``
  / ``_MASK`` / ``_PROXY_SECRET_FIELDS`` are re-exported AND kept live:
  tests do ``monkeypatch.setattr(pm_mod, "MAX_BUNDLE_TOTAL_BYTES", ...)`` and
  expect the bundle import to honour it.
- private helpers ``_load_notes_dict`` / ``_raw_from_proxy`` / ``_merge_*`` /
  ``_sanitize_notes`` keep their names.
- on-disk ``profiles.json`` format is unchanged (bare list).
"""

import logging
import threading
from pathlib import Path
from typing import Any

from ..config import PROFILES_DIR, PROFILES_FILE
from ..models.profile import BrowserProfile
from . import profiles as _pkg
from .profiles import (
    BUNDLE_CHUNK as _BUNDLE_CHUNK,
    MASK as _MASK,
    MAX_BUNDLE_ENTRIES as _MAX_BUNDLE_ENTRIES,
    MAX_BUNDLE_ENTRY_BYTES as _MAX_BUNDLE_ENTRY_BYTES,
    MAX_BUNDLE_TOTAL_BYTES as _MAX_BUNDLE_TOTAL_BYTES,
    MAX_MASS_GENERATE_COUNT as _MAX_MASS_GENERATE_COUNT,
    PROXY_SECRET_FIELDS as _PROXY_SECRET_FIELDS,
    ProfileService,
    backend_for,
    validate_id,
)
from .profiles.merge import (
    load_notes_dict as _load_notes_dict,
    merge_fingerprint as _merge_fingerprint,
    merge_google as _merge_google,
    merge_proxy as _merge_proxy,
    raw_from_proxy as _raw_from_proxy,
    sanitize_notes as _sanitize_notes,
)

__all__ = [
    "MAX_BUNDLE_ENTRIES",
    "MAX_BUNDLE_ENTRY_BYTES",
    "MAX_BUNDLE_TOTAL_BYTES",
    "MAX_MASS_GENERATE_COUNT",
    "_BUNDLE_CHUNK",
    "_MASK",
    "_PROXY_SECRET_FIELDS",
    "ProfileManager",
    "_load_notes_dict",
    "_merge_fingerprint",
    "_merge_google",
    "_merge_proxy",
    "_raw_from_proxy",
    "_sanitize_notes",
]

logger = logging.getLogger(__name__)

# Re-exported bounds (live: bundle code reads them via module getattr).
MAX_MASS_GENERATE_COUNT = _MAX_MASS_GENERATE_COUNT
MAX_BUNDLE_ENTRIES = _MAX_BUNDLE_ENTRIES
MAX_BUNDLE_ENTRY_BYTES = _MAX_BUNDLE_ENTRY_BYTES
MAX_BUNDLE_TOTAL_BYTES = _MAX_BUNDLE_TOTAL_BYTES
_BUNDLE_CHUNK = _BUNDLE_CHUNK


class ProfileManager:
    """
    Manages loading, saving, mutating, cloning, and isolating browser profiles.
    """

    def __init__(self, profiles_file: Path = PROFILES_FILE, profiles_dir: Path = PROFILES_DIR):
        self.profiles_file = profiles_file
        self.profiles_dir = profiles_dir
        self.profiles: dict[str, BrowserProfile] = {}
        self._save_lock = threading.RLock()
        self._backend = backend_for(profiles_file, profiles_dir)
        self._service = ProfileService(self._backend, profiles_dir)
        # Service owns the dict; keep the same object identity both ways.
        self._service.profiles = self.profiles
        self.load_profiles()

    # -- internal plumbing -------------------------------------------
    def _sync_from_service(self) -> None:
        if self._service.profiles is not self.profiles:
            self.profiles.clear()
            self.profiles.update(self._service.profiles)
            self._service.profiles = self.profiles

    def _sync_to_service(self) -> None:
        self._service.profiles = self.profiles

    # -- compat --------------------------------------------------------
    def _validate_id(self, profile_id: str):
        validate_id(profile_id)

    def _generate_default_10_profiles(self) -> list[BrowserProfile]:
        return _pkg.generate_default_10_profiles()

    def _prepare_for_write(self, profile: BrowserProfile, stored: BrowserProfile | None) -> BrowserProfile:
        return self._service._prepare_for_write(profile, stored)

    # -- persistence ---------------------------------------------------
    def load_profiles(self):
        with self._save_lock:
            self._sync_to_service()
            self._service.load(self._generate_default_10_profiles)
            self._sync_from_service()

    def save_profiles(self):
        with self._save_lock:
            self._sync_to_service()
            self._service.save()

    # -- CRUD ----------------------------------------------------------
    def list_profiles(self) -> list[BrowserProfile]:
        with self._save_lock:
            self._sync_to_service()
            # Return live list view semantics (copy of values, same objects).
            return self._service.list_all()

    def get_profile(self, profile_id: str) -> BrowserProfile | None:
        with self._save_lock:
            self._sync_to_service()
            return self._service.get(profile_id)

    def create_profile(self, profile: BrowserProfile) -> BrowserProfile:
        with self._save_lock:
            self._sync_to_service()
            out = self._service.create(profile)
            self._sync_from_service()
            return out

    def update_profile(self, profile: BrowserProfile) -> BrowserProfile | None:
        with self._save_lock:
            self._sync_to_service()
            out = self._service.update(profile)
            self._sync_from_service()
            return out

    def reencrypt_all_profile_secrets(self) -> int:
        with self._save_lock:
            self._sync_to_service()
            out = self._service.reencrypt_all_secrets()
            self._sync_from_service()
            return out

    def delete_profile(self, profile_id: str, delete_data: bool = True) -> bool:
        with self._save_lock:
            self._sync_to_service()
            out = self._service.delete(profile_id, delete_data=delete_data)
            self._sync_from_service()
            return out

    def clone_profile(self, source_id: str, new_name: str | None = None) -> BrowserProfile | None:
        with self._save_lock:
            self._sync_to_service()
            out = self._service.clone(source_id, new_name)
            self._sync_from_service()
            return out

    # -- disk helpers --------------------------------------------------
    def seed_profile_history(self, profile_id: str, entries_count: int = 25) -> int:
        return self._service.seed_history(profile_id, entries_count=entries_count)

    def get_profile_disk_size_bytes(self, profile_id: str) -> int:
        return self._service.disk_size(profile_id)

    def clear_profile_cache(self, profile_id: str) -> bool:
        return self._service.clear_cache(profile_id)

    def save_profile_cookies(self, profile_id: str, cookies: list[dict[str, Any]]) -> bool:
        with self._save_lock:
            self._sync_to_service()
            return self._service.save_cookies(profile_id, cookies)

    def load_profile_cookies(self, profile_id: str) -> list[dict[str, Any]]:
        return self._service.load_cookies(profile_id)

    def batch_import_cookies(
        self,
        cookie_map: dict[str, list[dict[str, Any]]],
        auto_create_missing: bool = False,
        group: str = "Imported Cookies",
    ) -> dict[str, Any]:
        with self._save_lock:
            self._sync_to_service()
            out = self._service.batch_import_cookies(cookie_map, auto_create_missing, group)
            self._sync_from_service()
            return out

    def export_all_cookies(self, profile_ids: list[str] | None = None) -> dict[str, list[dict[str, Any]]]:
        with self._save_lock:
            self._sync_to_service()
            return self._service.export_cookies(profile_ids)

    def mass_generate_profiles(
        self,
        count: int,
        group: str = "Mass Generated",
        proxy_list: list[str] | None = None,
        os_mix: str = "windows",
        tags: list[str] | None = None,
        auto_open_page: str = "google_login",
        notes: str | None = None,
    ) -> list[BrowserProfile]:
        import nazak.core.profiles.constants as _constants

        count = max(1, min(int(count), _constants.MAX_MASS_GENERATE_COUNT))
        with self._save_lock:
            self._sync_to_service()
            out = self._service.mass_generate(
                count=count,
                group=group,
                proxy_list=proxy_list,
                os_mix=os_mix,
                tags=tags,
                auto_open_page=auto_open_page,
                notes=notes,
            )
            self._sync_from_service()
            return out

    def export_profile_bundle(self, profile_id: str, output_path: Path | None = None) -> Path | None:
        with self._save_lock:
            self._sync_to_service()
            return self._service.export_bundle(profile_id, output_path)

    def import_profile_bundle(self, bundle_path: Path, new_name: str | None = None) -> BrowserProfile | None:
        with self._save_lock:
            self._sync_to_service()
            out = self._service.import_bundle(bundle_path, new_name)
            self._sync_from_service()
            return out
