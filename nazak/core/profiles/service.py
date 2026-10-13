"""Profile business logic: CRUD, clone, mass-generate, batch cookies, reencrypt (P0 refactor)."""

from __future__ import annotations

import json
import logging
import random
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ...models.profile import BrowserProfile, GoogleSettings, ProfileStatus
from ...models.proxy import ProxyConfig, ProxyType
from ..secrets_store import encrypt_notes, sanitize_notes_for_write
from . import files
from .bundles import export_bundle as _export_bundle, import_bundle as _import_bundle
from .constants import MAX_MASS_GENERATE_COUNT
from .merge import merge_fingerprint, merge_google, merge_proxy, sanitize_notes
from .store_json import ProfileBackend

logger = logging.getLogger(__name__)


class ProfileService:
    def __init__(self, backend: ProfileBackend, profiles_dir: Path):
        self.backend = backend
        self.profiles_dir = profiles_dir
        self.profiles: dict[str, BrowserProfile] = {}
        self._lock = threading.RLock()

    # -- lifecycle ------------------------------------------------------
    def load(self, seed_defaults) -> None:
        with self._lock:
            loaded = self.backend.load_all()
            if loaded:
                self.profiles = loaded
                return
            defaults = seed_defaults()
            self.profiles = {p.id: p for p in defaults}
            self.backend.save_all(self.profiles)

    def save(self) -> None:
        with self._lock:
            self.backend.save_all(self.profiles)

    # -- queries --------------------------------------------------------
    def list_all(self) -> list[BrowserProfile]:
        with self._lock:
            return list(self.profiles.values())

    def get(self, profile_id: str) -> BrowserProfile | None:
        try:
            files.validate_id(profile_id)
        except ValueError:
            return None
        with self._lock:
            return self.profiles.get(profile_id)

    # -- mutations ------------------------------------------------------
    def _prepare_for_write(self, profile: BrowserProfile, stored: BrowserProfile | None) -> BrowserProfile:
        if stored is None:
            if profile.google and profile.google.notes:
                from .merge import load_notes_dict

                incoming = load_notes_dict(profile.google.notes)
                if incoming is not None:
                    profile.google.notes = json.dumps(encrypt_notes(sanitize_notes_for_write(incoming, {})))
            return profile
        merged_google = merge_google(profile.google, stored.google)
        if merged_google is not None:
            profile.google = merged_google
        sanitize_notes(profile, stored)
        profile.proxy = merge_proxy(profile.proxy, stored.proxy, set(profile.proxy.model_fields_set))
        if profile.fingerprint is not None and stored.fingerprint is not None:
            profile.fingerprint = merge_fingerprint(profile.fingerprint, stored.fingerprint)
        return profile

    def create(self, profile: BrowserProfile) -> BrowserProfile:
        with self._lock:
            if not profile.id:
                profile.id = f"prof_{uuid.uuid4().hex[:8]}"
            else:
                files.validate_id(profile.id)
                if profile.id in self.profiles:
                    raise ValueError(f"Profile with id '{profile.id}' already exists")
            profile = self._prepare_for_write(profile, None)
            self.profiles[profile.id] = profile
            self.backend.save_all(self.profiles)
            return profile

    def update(self, profile: BrowserProfile) -> BrowserProfile | None:
        files.validate_id(profile.id)
        with self._lock:
            stored = self.profiles.get(profile.id)
            if stored is None:
                return None
            profile = self._prepare_for_write(profile, stored)
            profile.updated_at = datetime.now(timezone.utc).isoformat()
            self.profiles[profile.id] = profile
            backend = self.backend
            save_one = getattr(backend, "save_one", None)
            if callable(save_one):
                save_one(profile)
            else:
                backend.save_all(self.profiles)
            return profile

    def delete(self, profile_id: str, delete_data: bool = True) -> bool:
        files.validate_id(profile_id)
        with self._lock:
            if profile_id not in self.profiles:
                return False
            self.profiles.pop(profile_id, None)
            backend = self.backend
            delete_one = getattr(backend, "delete_one", None)
            if callable(delete_one):
                delete_one(profile_id)
            else:
                backend.save_all(self.profiles)
            if delete_data:
                files.delete_profile_data(self.profiles_dir, profile_id)
            return True

    def clone(self, source_id: str, new_name: str | None = None) -> BrowserProfile | None:
        source = self.get(source_id)
        if not source:
            return None
        cloned_data = source.model_dump()
        new_id = f"prof_{uuid.uuid4().hex[:8]}"
        cloned_data["id"] = new_id
        cloned_data["name"] = new_name or f"{source.name} (Copy)"
        cloned_data["status"] = ProfileStatus.STOPPED
        cloned_data["pid"] = None
        cloned_data["last_launched_at"] = None
        cloned_data["total_runtime_seconds"] = 0
        cloned_data["last_health_check"] = None
        cloned_data["created_at"] = datetime.now(timezone.utc).isoformat()
        cloned_data["updated_at"] = datetime.now(timezone.utc).isoformat()

        if "fingerprint" in cloned_data and isinstance(cloned_data["fingerprint"], dict):
            src_fp = source.fingerprint
            platform = src_fp.platform or "Win32"
            if platform == "MacIntel":
                os_type = "mac"
            elif platform.lower().startswith("linux"):
                os_type = "linux"
            else:
                os_type = "windows"

            from ..fingerprint_generator import generate_random_fingerprint

            fresh = generate_random_fingerprint(os_type=os_type)
            for _ in range(8):
                if fresh.user_agent != src_fp.user_agent:
                    break
                fresh = generate_random_fingerprint(os_type=os_type)
            fp = fresh.model_dump()
            for field in (
                "timezone",
                "timezone_offset",
                "language",
                "languages",
                "canvas_noise",
                "audio_noise",
                "client_rects_noise",
                "block_port_scanning",
                "block_sensors",
                "webrtc_policy",
                "battery",
                "geolocation",
            ):
                fp[field] = (
                    getattr(src_fp, field).model_dump()
                    if field in ("battery", "geolocation")
                    else getattr(src_fp, field)
                )
            cloned_data["fingerprint"] = fp

            orig_canvas = src_fp.canvas_noise_seed
            orig_audio = src_fp.audio_noise_seed

            canvas_seed = random.randint(10000, 999999)
            while orig_canvas is not None and canvas_seed == orig_canvas:
                canvas_seed = random.randint(10000, 999999)
            fp["canvas_noise_seed"] = canvas_seed

            audio_seed = round(random.uniform(0.0000005, 0.000005), 8)
            while orig_audio is not None and audio_seed == orig_audio:
                audio_seed = round(random.uniform(0.0000005, 0.000005), 8)
            fp["audio_noise_seed"] = audio_seed

            if "media_devices" in fp and isinstance(fp["media_devices"], list):
                for dev in fp["media_devices"]:
                    if isinstance(dev, dict):
                        dev["device_id"] = uuid.uuid4().hex
                        dev["group_id"] = uuid.uuid4().hex

        cloned_profile = BrowserProfile(**cloned_data)
        with self._lock:
            self.profiles[new_id] = cloned_profile
            self.backend.save_all(self.profiles)
        return cloned_profile

    # -- disk helpers ---------------------------------------------------
    def disk_size(self, profile_id: str) -> int:
        return files.get_disk_size_bytes(self.profiles_dir, profile_id)

    def clear_cache(self, profile_id: str) -> bool:
        return files.clear_cache(self.profiles_dir, profile_id)

    def seed_history(self, profile_id: str, entries_count: int = 25) -> int:
        files.validate_id(profile_id)
        if self.get(profile_id) is None:
            return 0
        return files.seed_history(self.profiles_dir, profile_id, entries_count)

    # -- cookies --------------------------------------------------------
    def save_cookies(self, profile_id: str, cookies: list[dict[str, Any]]) -> bool:
        files.validate_id(profile_id)
        with self._lock:
            if profile_id not in self.profiles:
                return False
        return files.save_cookies(self.profiles_dir, profile_id, cookies)

    def load_cookies(self, profile_id: str) -> list[dict[str, Any]]:
        return files.load_cookies(self.profiles_dir, profile_id)

    def batch_import_cookies(
        self,
        cookie_map: dict[str, list[dict[str, Any]]],
        auto_create_missing: bool = False,
        group: str = "Imported Cookies",
    ) -> dict[str, Any]:
        matched_count = 0
        created_count = 0
        failed_count = 0
        imported_profile_ids: list[str] = []

        with self._lock:
            all_profiles = list(self.profiles.values())
        id_map = {p.id: p for p in all_profiles}
        name_map = {p.name.strip().lower(): p for p in all_profiles}

        from ..fingerprint_generator import generate_random_fingerprint

        for key, cookies in cookie_map.items():
            if not cookies:
                continue

            target_profile: BrowserProfile | None = None
            key_clean = (key or "").strip()
            if not key_clean:
                # A blank key used to match every profile through the substring
                # fallback below (`"" in p.name.lower()`), so a stray separator
                # line silently wrote cookies into the first stored profile.
                failed_count += 1
                continue
            key_lower = key_clean.lower()

            if key_clean in id_map:
                target_profile = id_map[key_clean]
            elif key_lower in name_map:
                target_profile = name_map[key_lower]
            else:
                for p in all_profiles:
                    if key_lower in p.name.lower() or p.id.lower() in key_lower:
                        target_profile = p
                        break

            if not target_profile and auto_create_missing:
                fp = generate_random_fingerprint(os_type="windows")
                with self._lock:
                    suffix = len(self.profiles) + 1
                p_name = key_clean if key_clean != "default" else f"Cookie Profile {suffix:02d}"
                new_prof = BrowserProfile(
                    name=p_name,
                    group=group,
                    proxy=ProxyConfig(type=ProxyType.DIRECT, raw="direct"),
                    fingerprint=fp,
                    google=GoogleSettings(auto_open_page="google_login", tags=["Cookie Import", group]),
                )
                target_profile = self.create(new_prof)
                id_map[target_profile.id] = target_profile
                name_map[target_profile.name.strip().lower()] = target_profile
                all_profiles.append(target_profile)
                created_count += 1
            elif target_profile:
                matched_count += 1

            if target_profile:
                saved = self.save_cookies(target_profile.id, cookies)
                if saved:
                    imported_profile_ids.append(target_profile.id)
                else:
                    failed_count += 1
            else:
                failed_count += 1

        return {
            "matched": matched_count,
            "created": created_count,
            "failed": failed_count,
            "profile_ids": imported_profile_ids,
        }

    def export_cookies(self, profile_ids: list[str] | None = None) -> dict[str, list[dict[str, Any]]]:
        with self._lock:
            target_ids = profile_ids or list(self.profiles.keys())
        out: dict[str, list[dict[str, Any]]] = {}
        for pid in target_ids:
            try:
                files.validate_id(pid)
            except ValueError:
                continue
            cookies: list[dict[str, Any]] = self.load_cookies(pid)
            if cookies:
                out[pid] = cookies
        return out

    # -- mass generation ------------------------------------------------
    def mass_generate(
        self,
        count: int,
        group: str = "Mass Generated",
        proxy_list: list[str] | None = None,
        os_mix: str = "windows",
        tags: list[str] | None = None,
        auto_open_page: str = "google_login",
        notes: str | None = None,
    ) -> list[BrowserProfile]:
        from ..fingerprint_generator import generate_random_fingerprint

        count = max(1, min(int(count), MAX_MASS_GENERATE_COUNT))

        created_profiles: list[BrowserProfile] = []
        proxies_parsed = [ProxyConfig.parse(p) for p in (proxy_list or []) if p and p.strip()]

        os_types = ["windows"]
        if os_mix == "mac":
            os_types = ["mac"]
        elif os_mix == "linux":
            os_types = ["linux"]
        elif os_mix == "all":
            os_types = ["windows", "mac", "linux"]

        with self._lock:
            base_index = len(self.profiles) + 1
        for i in range(count):
            chosen_os = os_types[i % len(os_types)]
            fp = generate_random_fingerprint(os_type=chosen_os)

            proxy_conf = ProxyConfig(type=ProxyType.DIRECT, raw="direct")
            if proxies_parsed:
                proxy_conf = proxies_parsed[i % len(proxies_parsed)]

            proxy_label = f" ({proxy_conf.host})" if proxy_conf.host else " (Direct)"
            name = f"Profile {base_index + i:02d}{proxy_label}"

            profile_tags = list(tags) if tags else ["Mass Generated", group]
            g_settings = GoogleSettings(
                auto_open_page=auto_open_page, tags=profile_tags, notes=notes or f"Generated in batch of {count}"
            )

            prof = BrowserProfile(name=name, group=group, proxy=proxy_conf, fingerprint=fp, google=g_settings)
            # Audit P2 (CI Windows timeout): create() persists the WHOLE store per
            # profile, so a 200-profile batch rewrote profiles.json 200 times with
            # a growing payload (O(n^2) writes; 30+ s on a slow CI disk and a
            # pytest-timeout kill). Build and register in memory, persist once.
            prof = self._prepare_for_write(prof, None)
            with self._lock:
                self.profiles[prof.id] = prof
            created_profiles.append(prof)

        with self._lock:
            self.backend.save_all(self.profiles)
        return created_profiles

    # -- bundles --------------------------------------------------------
    def export_bundle(self, profile_id: str, output_path: Path | None = None) -> Path | None:
        return _export_bundle(self.profiles_dir, self.get, profile_id, output_path)

    def import_bundle(self, bundle_path: Path, new_name: str | None = None) -> BrowserProfile | None:
        restored = _import_bundle(self.profiles_dir, bundle_path, new_name)
        if restored is None:
            return None
        with self._lock:
            self.profiles[restored.id] = restored
            self.backend.save_all(self.profiles)
        return restored

    # -- secrets --------------------------------------------------------
    def reencrypt_all_secrets(self) -> int:
        import json as _json

        from ..secrets_store import encrypt_notes as _encrypt, reveal_notes

        count = 0
        with self._lock:
            for profile in self.profiles.values():
                notes_raw = profile.google.notes if profile.google else ""
                if not notes_raw:
                    continue
                try:
                    notes = _json.loads(notes_raw)
                except Exception:
                    continue
                try:
                    plain = reveal_notes(notes)
                except Exception:
                    continue
                if any(
                    isinstance(v, str) and v.startswith("<encrypted") for k, v in plain.items() if not k.startswith("_")
                ):
                    continue
                try:
                    new_notes = _encrypt({k: v for k, v in plain.items() if not k.startswith("_")})
                except Exception:
                    continue
                profile.google.notes = _json.dumps(new_notes)
                count += 1
            if count:
                self.backend.save_all(self.profiles)
        return count
