"""
Profile Manager: Persistence, Deep 10-Profile Auto-Provisioning, Total Disk Isolation & Cookie Tools.
"""

import json
import os
import random
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import PROFILES_DIR, PROFILES_FILE
from ..models.profile import (
    BatterySpoofConfig,
    BrowserProfile,
    FingerprintConfig,
    GeolocationSpoofConfig,
    GoogleSettings,
    MediaDeviceInfo,
    ProfileStatus,
)
from ..models.proxy import ProxyConfig, ProxyType


class ProfileManager:
    """
    Manages loading, saving, mutating, cloning, and isolating browser profiles.
    """

    def __init__(self, profiles_file: Path = PROFILES_FILE, profiles_dir: Path = PROFILES_DIR):
        self.profiles_file = profiles_file
        self.profiles_dir = profiles_dir
        self.profiles: dict[str, BrowserProfile] = {}
        self.load_profiles()

    def _generate_default_10_profiles(self) -> list[BrowserProfile]:
        """
        Creates 10 deeply distinct, ultra-realistic browser profiles with complete system isolation.
        """
        presets = [
            {
                "name": "01 - Google Ads USA (High-Tier Desktop RTX 4090)",
                "group": "Google Ads",
                "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
                "platform": "Win32",
                "width": 2560,
                "height": 1440,
                "ram": 64,
                "cores": 24,
                "lang": "en-US,en;q=0.9",
                "langs": ["en-US", "en"],
                "tz": "America/New_York",
                "tz_off": 300,
                "gpu_v": "Google Inc. (NVIDIA)",
                "gpu_r": "ANGLE (NVIDIA, NVIDIA GeForce RTX 4090 Direct3D11 vs_5_0 ps_5_0, D3D11)",
                "gpu_uv": "NVIDIA Corporation",
                "gpu_ur": "NVIDIA GeForce RTX 4090",
                "target": "google_login",
                "tags": ["Google Ads", "USA", "Tier 1", "Flagship"],
                "notes": "Primary Google Ads Flagship Desktop.",
            },
            {
                "name": "02 - Google Ads USA (Ryzen 7 Laptop)",
                "group": "Google Ads",
                "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
                "platform": "Win32",
                "width": 1920,
                "height": 1080,
                "ram": 32,
                "cores": 16,
                "lang": "en-US,en;q=0.9",
                "langs": ["en-US", "en"],
                "tz": "America/Los_Angeles",
                "tz_off": 480,
                "gpu_v": "Google Inc. (AMD)",
                "gpu_r": "ANGLE (AMD, AMD Radeon 780M Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)",
                "gpu_uv": "Advanced Micro Devices, Inc.",
                "gpu_ur": "AMD Radeon 780M Graphics",
                "target": "google_ads",
                "tags": ["Google Ads", "USA", "Laptop"],
                "notes": "Targeted ad spend manager.",
            },
            {
                "name": "03 - Google Ads UK (Ryzen 9 4K Workstation)",
                "group": "Google Ads",
                "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
                "platform": "Win32",
                "width": 3840,
                "height": 2160,
                "ram": 32,
                "cores": 32,
                "lang": "en-GB,en;q=0.9",
                "langs": ["en-GB", "en"],
                "tz": "Europe/London",
                "tz_off": 0,
                "gpu_v": "Google Inc. (AMD)",
                "gpu_r": "ANGLE (AMD, AMD Radeon RX 7900 XTX Direct3D11 vs_5_0 ps_5_0, D3D11)",
                "gpu_uv": "Advanced Micro Devices, Inc.",
                "gpu_ur": "AMD Radeon RX 7900 XTX",
                "target": "google_ads",
                "tags": ["Google Ads", "UK", "Tier 1", "4K"],
                "notes": "UK campaigns and billing master.",
            },
            {
                "name": "04 - Google Ads Germany (Core i7 RTX 4070 Ti)",
                "group": "Google Ads",
                "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                "platform": "Win32",
                "width": 1920,
                "height": 1080,
                "ram": 32,
                "cores": 16,
                "lang": "de-DE,de;q=0.9,en;q=0.8",
                "langs": ["de-DE", "de", "en"],
                "tz": "Europe/Berlin",
                "tz_off": -60,
                "gpu_v": "Google Inc. (NVIDIA)",
                "gpu_r": "ANGLE (NVIDIA, NVIDIA GeForce RTX 4070 Ti Direct3D11 vs_5_0 ps_5_0, D3D11)",
                "gpu_uv": "NVIDIA Corporation",
                "gpu_ur": "NVIDIA GeForce RTX 4070 Ti",
                "target": "google_login",
                "tags": ["Google Ads", "DE", "Europe"],
                "notes": "DACH region ad campaigns.",
            },
            {
                "name": "05 - Google Warmup (Office PC Intel UHD 770)",
                "group": "Warmup",
                "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
                "platform": "Win32",
                "width": 1536,
                "height": 864,
                "ram": 16,
                "cores": 12,
                "lang": "en-US,en;q=0.9",
                "langs": ["en-US", "en"],
                "tz": "America/Chicago",
                "tz_off": 360,
                "gpu_v": "Google Inc. (Intel)",
                "gpu_r": "ANGLE (Intel, Intel(R) UHD Graphics 770 Direct3D11 vs_5_0 ps_5_0, D3D11)",
                "gpu_uv": "Intel Inc.",
                "gpu_ur": "Intel(R) UHD Graphics 770",
                "target": "google_search",
                "tags": ["Warmup", "Organic", "Farming"],
                "notes": "Search history & cookie accumulation.",
            },
            {
                "name": "06 - Google Warmup (Ultrabook Intel Arc)",
                "group": "Warmup",
                "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
                "platform": "Win32",
                "width": 1920,
                "height": 1200,
                "ram": 16,
                "cores": 16,
                "lang": "en-CA,en;q=0.9",
                "langs": ["en-CA", "en"],
                "tz": "America/Toronto",
                "tz_off": 300,
                "gpu_v": "Google Inc. (Intel)",
                "gpu_r": "ANGLE (Intel, Intel(R) Arc(TM) Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)",
                "gpu_uv": "Intel Inc.",
                "gpu_ur": "Intel(R) Arc(TM) Graphics",
                "target": "google_search",
                "tags": ["Warmup", "Organic", "Farming"],
                "notes": "Search history & trust score building.",
            },
            {
                "name": "07 - YouTube Studio (MacBook Pro M3 Max)",
                "group": "YouTube",
                "ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
                "platform": "MacIntel",
                "width": 3024,
                "height": 1964,
                "ram": 64,
                "cores": 16,
                "lang": "en-US,en;q=0.9",
                "langs": ["en-US", "en"],
                "tz": "America/Chicago",
                "tz_off": 360,
                "gpu_v": "Google Inc. (Apple)",
                "gpu_r": "ANGLE (Apple, ANGLE Metal Renderer: Apple M3 Max, Version 15.0)",
                "gpu_uv": "Apple Inc.",
                "gpu_ur": "Apple M3 Max GPU",
                "target": "youtube_studio",
                "tags": ["YouTube", "Studio", "MacBook"],
                "notes": "YouTube channel management master.",
            },
            {
                "name": "08 - YouTube Studio (Mac Studio M2 Pro)",
                "group": "YouTube",
                "ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
                "platform": "MacIntel",
                "width": 2560,
                "height": 1600,
                "ram": 32,
                "cores": 12,
                "lang": "en-AU,en;q=0.9",
                "langs": ["en-AU", "en"],
                "tz": "Australia/Sydney",
                "tz_off": -600,
                "gpu_v": "Google Inc. (Apple)",
                "gpu_r": "ANGLE (Apple, ANGLE Metal Renderer: Apple M2 Pro, Version 14.5)",
                "gpu_uv": "Apple Inc.",
                "gpu_ur": "Apple M2 Pro GPU",
                "target": "youtube_studio",
                "tags": ["YouTube", "Studio", "Creator"],
                "notes": "Secondary creator channel.",
            },
            {
                "name": "09 - Organic Search Traffic (Gaming Rig RTX 3080)",
                "group": "Organic",
                "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
                "platform": "Win32",
                "width": 1920,
                "height": 1080,
                "ram": 32,
                "cores": 16,
                "lang": "fr-FR,fr;q=0.9,en;q=0.8",
                "langs": ["fr-FR", "fr", "en"],
                "tz": "Europe/Paris",
                "tz_off": -60,
                "gpu_v": "Google Inc. (NVIDIA)",
                "gpu_r": "ANGLE (NVIDIA, NVIDIA GeForce RTX 3080 Direct3D11 vs_5_0 ps_5_0, D3D11)",
                "gpu_uv": "NVIDIA Corporation",
                "gpu_ur": "NVIDIA GeForce RTX 3080",
                "target": "google_search",
                "tags": ["Organic", "Search", "SEO"],
                "notes": "Organic traffic & CTR automation.",
            },
            {
                "name": "10 - Arbitrage & Backup Node (Compact PC)",
                "group": "Arbitrage",
                "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
                "platform": "Win32",
                "width": 1366,
                "height": 768,
                "ram": 8,
                "cores": 8,
                "lang": "en-US,en;q=0.9",
                "langs": ["en-US", "en"],
                "tz": "America/New_York",
                "tz_off": 300,
                "gpu_v": "Google Inc. (Intel)",
                "gpu_r": "ANGLE (Intel, Intel(R) UHD Graphics 730 Direct3D11 vs_5_0 ps_5_0, D3D11)",
                "gpu_uv": "Intel Inc.",
                "gpu_ur": "Intel(R) UHD Graphics 730",
                "target": "google_login",
                "tags": ["Arbitrage", "Backup", "Multi-Acc"],
                "notes": "Backup node for quick launch.",
            },
        ]

        result = []
        for idx, item in enumerate(presets, start=1):
            pid = f"prof_{idx:02d}"

            # Unique persistent media devices for each profile
            devs = [
                MediaDeviceInfo(
                    kind="audioinput",
                    label=f"Microphone (Realtek Audio HD {idx})",
                    device_id=uuid.uuid4().hex,
                    group_id=uuid.uuid4().hex,
                ),
                MediaDeviceInfo(
                    kind="audiooutput",
                    label=f"Speakers (Realtek Audio HD {idx})",
                    device_id=uuid.uuid4().hex,
                    group_id=uuid.uuid4().hex,
                ),
                MediaDeviceInfo(
                    kind="videoinput",
                    label=f"Integrated HD Camera {idx}",
                    device_id=uuid.uuid4().hex,
                    group_id=uuid.uuid4().hex,
                ),
            ]

            fp = FingerprintConfig(
                user_agent=str(item["ua"]),
                platform=str(item["platform"]),
                screen_width=int(item["width"]),
                screen_height=int(item["height"]),
                screen_avail_width=int(item["width"]),
                screen_avail_height=int(item["height"]) - 40,
                color_depth=24,
                pixel_depth=24,
                device_pixel_ratio=1.0 if int(item["width"]) <= 2560 else 2.0,
                device_memory=int(item["ram"]),
                hardware_concurrency=int(item["cores"]),
                language=str(item["lang"]),
                languages=list(item["langs"]),
                timezone=str(item["tz"]),
                timezone_offset=int(item["tz_off"]),
                webgl_vendor=str(item["gpu_v"]),
                webgl_renderer=str(item["gpu_r"]),
                webgl_unmasked_vendor=str(item["gpu_uv"]),
                webgl_unmasked_renderer=str(item["gpu_ur"]),
                media_devices=devs,
                canvas_noise=True,
                canvas_noise_seed=100000 + idx * 7777,
                audio_noise=True,
                audio_noise_seed=0.000001 * idx,
                client_rects_noise=True,
                battery=BatterySpoofConfig(
                    charging=True,
                    level=0.98 if "Laptop" in str(item["name"]) or "MacBook" in str(item["name"]) else 1.0,
                ),
                geolocation=GeolocationSpoofConfig(enabled=True),
                webrtc_policy="disable_non_proxied_udp",
                block_port_scanning=True,
            )

            google = GoogleSettings(auto_open_page=item["target"], tags=item["tags"], notes=item["notes"])

            prof = BrowserProfile(
                id=pid,
                name=item["name"],
                group=item["group"],
                proxy=ProxyConfig(type=ProxyType.DIRECT, raw="direct"),
                fingerprint=fp,
                google=google,
                status=ProfileStatus.STOPPED,
            )
            result.append(prof)
        return result

    def load_profiles(self):
        """Loads profiles from JSON or initializes 10 default profiles with robust recovery."""
        if not self.profiles_file.exists():
            default_profiles = self._generate_default_10_profiles()
            self.profiles = {p.id: p for p in default_profiles}
            self.save_profiles()
            return

        try:
            with open(self.profiles_file, encoding="utf-8") as f:
                data = json.load(f)

            if not isinstance(data, list):
                raise ValueError("profiles.json root must be a list")

            loaded = {}
            for item in data:
                try:
                    if isinstance(item, dict):
                        prof = BrowserProfile(**item)
                        prof.status = ProfileStatus.STOPPED
                        prof.pid = None
                        loaded[prof.id] = prof
                except Exception:
                    continue

            if loaded:
                self.profiles = loaded
            else:
                default_profiles = self._generate_default_10_profiles()
                self.profiles = {p.id: p for p in default_profiles}
                self.save_profiles()

        except Exception:
            # Backup corrupted file to prevent data loss
            try:
                bak_file = self.profiles_file.with_name(f"profiles.corrupt.{int(time.time())}.bak")
                shutil.copy2(self.profiles_file, bak_file)
            except Exception:
                pass

            default_profiles = self._generate_default_10_profiles()
            self.profiles = {p.id: p for p in default_profiles}
            self.save_profiles()

    def save_profiles(self):
        """Atomically saves profiles to JSON file with Windows retry resilience."""
        self.profiles_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_file = self.profiles_file.with_suffix(".tmp")
        data = [p.model_dump() for p in self.profiles.values()]
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        for attempt in range(5):
            try:
                tmp_file.replace(self.profiles_file)
                break
            except (PermissionError, OSError):
                time.sleep(0.05 * (attempt + 1))
                if attempt == 4:
                    shutil.copy2(tmp_file, self.profiles_file)
                    try:
                        tmp_file.unlink(missing_ok=True)
                    except Exception:
                        pass

    def list_profiles(self) -> list[BrowserProfile]:
        return list(self.profiles.values())

    def get_profile(self, profile_id: str) -> BrowserProfile | None:
        return self.profiles.get(profile_id)

    def create_profile(self, profile: BrowserProfile) -> BrowserProfile:
        if not profile.id:
            profile.id = f"prof_{uuid.uuid4().hex[:8]}"
        self.profiles[profile.id] = profile
        self.save_profiles()
        return profile

    def update_profile(self, profile: BrowserProfile) -> BrowserProfile | None:
        if profile.id not in self.profiles:
            return None
        profile.updated_at = datetime.now(timezone.utc).isoformat()
        self.profiles[profile.id] = profile
        self.save_profiles()
        return profile

    def delete_profile(self, profile_id: str, delete_data: bool = True) -> bool:
        if profile_id not in self.profiles:
            return False
        self.profiles.pop(profile_id, None)
        self.save_profiles()

        if delete_data:
            data_path = self.profiles_dir / profile_id
            if data_path.exists():
                shutil.rmtree(data_path, ignore_errors=True)
        return True

    def clone_profile(self, source_id: str, new_name: str | None = None) -> BrowserProfile | None:
        source = self.get_profile(source_id)
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

        # Regenerate hardware seeds and UUIDs to ensure zero linkage with source profile
        if "fingerprint" in cloned_data and isinstance(cloned_data["fingerprint"], dict):
            fp = cloned_data["fingerprint"]
            fp["canvas_noise_seed"] = random.randint(10000, 999999)
            fp["audio_noise_seed"] = round(random.uniform(0.0000005, 0.000005), 8)
            if "media_devices" in fp and isinstance(fp["media_devices"], list):
                for dev in fp["media_devices"]:
                    if isinstance(dev, dict):
                        dev["device_id"] = uuid.uuid4().hex
                        dev["group_id"] = uuid.uuid4().hex

        cloned_profile = BrowserProfile(**cloned_data)
        self.profiles[new_id] = cloned_profile
        self.save_profiles()
        return cloned_profile

    def get_profile_disk_size_bytes(self, profile_id: str) -> int:
        path = self.profiles_dir / profile_id
        if not path.exists():
            return 0
        total = 0
        try:
            entries = list(os.scandir(path))
        except Exception:
            return 0
        for entry in entries:
            try:
                if entry.is_file():
                    total += entry.stat().st_size
                elif entry.is_dir():
                    for root, _, files in os.walk(entry.path):
                        for f in files:
                            try:
                                total += os.path.getsize(os.path.join(root, f))
                            except Exception:
                                pass
            except Exception:
                pass
        return total

    def clear_profile_cache(self, profile_id: str) -> bool:
        path = self.profiles_dir / profile_id
        if not path.exists():
            return True
        cache_dirs = ["Cache", "Code Cache", "GPUCache", "DawnCache", "Service Worker/CacheStorage"]
        for cdir in cache_dirs:
            target = path / "Default" / cdir
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            top_target = path / cdir
            if top_target.exists():
                shutil.rmtree(top_target, ignore_errors=True)
        return True

    def save_profile_cookies(self, profile_id: str, cookies: list[dict[str, Any]]) -> bool:
        """Persists imported cookies to both JSON and Netscape formats in profile directory."""
        path = self.profiles_dir / profile_id
        path.mkdir(parents=True, exist_ok=True)
        default_dir = path / "Default"
        default_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Save JSON cookies
            json_str = json.dumps(cookies, indent=2, ensure_ascii=False)
            (path / "cookies.json").write_text(json_str, encoding="utf-8")
            (default_dir / "cookies.json").write_text(json_str, encoding="utf-8")

            # Save Netscape cookies
            from .cookie_manager import cookies_to_netscape

            netscape_str = cookies_to_netscape(cookies)
            (path / "cookies.txt").write_text(netscape_str, encoding="utf-8")
            (default_dir / "cookies.txt").write_text(netscape_str, encoding="utf-8")
            return True
        except Exception:
            return False

    def load_profile_cookies(self, profile_id: str) -> list[dict[str, Any]]:
        """Loads saved cookies from JSON or Netscape formats in profile directory."""
        path = self.profiles_dir / profile_id
        json_file = path / "cookies.json"
        if json_file.exists():
            try:
                return json.loads(json_file.read_text(encoding="utf-8"))
            except Exception:
                pass

        txt_file = path / "cookies.txt"
        if txt_file.exists():
            try:
                from .cookie_manager import parse_netscape_cookies

                return parse_netscape_cookies(txt_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        return []

    def batch_import_cookies(
        self,
        cookie_map: dict[str, list[dict[str, Any]]],
        auto_create_missing: bool = False,
        group: str = "Imported Cookies",
    ) -> dict[str, Any]:
        """
        Batch imports cookies across multiple profiles.
        Matches by profile ID, exact profile Name, or case-insensitive substring.
        If no matching profile is found and auto_create_missing is True, creates a new isolated profile.
        """
        matched_count = 0
        created_count = 0
        failed_count = 0
        imported_profile_ids: list[str] = []

        all_profiles = list(self.profiles.values())
        id_map = {p.id: p for p in all_profiles}
        name_map = {p.name.strip().lower(): p for p in all_profiles}

        from .fingerprint_generator import generate_random_fingerprint

        for key, cookies in cookie_map.items():
            if not cookies:
                continue

            target_profile: BrowserProfile | None = None
            key_clean = key.strip()
            key_lower = key_clean.lower()

            # 1. Direct ID match
            if key_clean in id_map:
                target_profile = id_map[key_clean]
            # 2. Exact Name match
            elif key_lower in name_map:
                target_profile = name_map[key_lower]
            # 3. Substring Name match
            else:
                for p in all_profiles:
                    if key_lower in p.name.lower() or p.id.lower() in key_lower:
                        target_profile = p
                        break

            # 4. Auto-create if not matched
            if not target_profile and auto_create_missing:
                fp = generate_random_fingerprint(os_type="windows")
                p_name = key_clean if key_clean != "default" else f"Cookie Profile {len(self.profiles) + 1:02d}"
                new_prof = BrowserProfile(
                    name=p_name,
                    group=group,
                    proxy=ProxyConfig(type=ProxyType.DIRECT, raw="direct"),
                    fingerprint=fp,
                    google=GoogleSettings(auto_open_page="google_login", tags=["Cookie Import", group]),
                )
                target_profile = self.create_profile(new_prof)
                id_map[target_profile.id] = target_profile
                name_map[target_profile.name.strip().lower()] = target_profile
                created_count += 1
            elif target_profile:
                matched_count += 1

            if target_profile:
                saved = self.save_profile_cookies(target_profile.id, cookies)
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

    def export_all_cookies(self, profile_ids: list[str] | None = None) -> dict[str, list[dict[str, Any]]]:
        """Exports loaded cookies for specified or all profiles indexed by profile ID."""
        target_ids = profile_ids or list(self.profiles.keys())
        out = {}
        for pid in target_ids:
            cookies = self.load_profile_cookies(pid)
            if cookies:
                out[pid] = cookies
        return out

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
        """
        Mass generates N fully isolated, high-tier browser profiles with distinct hardware fingerprints
        and proxy round-robin allocation.
        """
        from .fingerprint_generator import generate_random_fingerprint

        created_profiles: list[BrowserProfile] = []
        proxies_parsed = [ProxyConfig.parse(p) for p in (proxy_list or []) if p and p.strip()]

        os_types = ["windows"]
        if os_mix == "mac":
            os_types = ["mac"]
        elif os_mix == "linux":
            os_types = ["linux"]
        elif os_mix == "all":
            os_types = ["windows", "mac", "linux"]

        base_index = len(self.profiles) + 1
        for i in range(count):
            chosen_os = random.choice(os_types)
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

            saved = self.create_profile(prof)
            created_profiles.append(saved)

        return created_profiles

    def export_profile_bundle(self, profile_id: str, output_path: Path | None = None) -> Path | None:
        """
        Exports a complete portable .nazak / zip bundle containing profile metadata,
        fingerprint, cookies, and local session files.
        """
        prof = self.get_profile(profile_id)
        if not prof:
            return None

        import zipfile

        out_file = output_path or (self.profiles_dir / f"{profile_id}_bundle.nazak")
        out_file.parent.mkdir(parents=True, exist_ok=True)

        prof_dir = self.profiles_dir / profile_id

        with zipfile.ZipFile(out_file, "w", zipfile.ZIP_DEFLATED) as zf:
            # 1. Profile metadata JSON
            zf.writestr("profile.json", json.dumps(prof.model_dump(), indent=2, ensure_ascii=False))

            # 2. Profile cookies
            cookies = self.load_profile_cookies(profile_id)
            if cookies:
                zf.writestr("cookies.json", json.dumps(cookies, indent=2, ensure_ascii=False))

            # 3. Include local session files if exist (Default/Network, Default/Local Storage, Default/IndexedDB)
            if prof_dir.exists():
                for root, _, files in os.walk(prof_dir):
                    for f in files:
                        full_f = Path(root) / f
                        rel_path = full_f.relative_to(prof_dir)
                        # Skip huge caches, locks, and logs
                        if any(
                            c in str(rel_path)
                            for c in ["Cache", "Code Cache", "DawnCache", "GPUCache", "Singleton", "lock"]
                        ):
                            continue
                        try:
                            zf.write(full_f, arcname=f"data/{rel_path}")
                        except Exception:
                            pass

        return out_file

    def import_profile_bundle(self, bundle_path: Path, new_name: str | None = None) -> BrowserProfile | None:
        """
        Imports and restores a portable .nazak / zip bundle into the workspace.
        """
        if not bundle_path.exists():
            return None

        import zipfile

        try:
            with zipfile.ZipFile(bundle_path, "r") as zf:
                if "profile.json" not in zf.namelist():
                    return None

                prof_data = json.loads(zf.read("profile.json").decode("utf-8"))
                new_id = f"prof_{uuid.uuid4().hex[:8]}"
                prof_data["id"] = new_id
                if new_name:
                    prof_data["name"] = new_name
                else:
                    prof_data["name"] = f"{prof_data.get('name', 'Imported Profile')} (Imported)"

                prof_data["status"] = ProfileStatus.STOPPED
                prof_data["pid"] = None
                prof_data["last_launched_at"] = None
                prof_data["total_runtime_seconds"] = 0
                prof_data["last_health_check"] = None
                prof_data["created_at"] = datetime.now(timezone.utc).isoformat()
                prof_data["updated_at"] = datetime.now(timezone.utc).isoformat()

                # Restore session files
                target_dir = self.profiles_dir / new_id
                target_dir.mkdir(parents=True, exist_ok=True)

                for name in zf.namelist():
                    if name.startswith("data/"):
                        rel_sub = name[len("data/") :]
                        if rel_sub:
                            target_file = target_dir / rel_sub
                            target_file.parent.mkdir(parents=True, exist_ok=True)
                            target_file.write_bytes(zf.read(name))

                # Restore cookies
                if "cookies.json" in zf.namelist():
                    cookies = json.loads(zf.read("cookies.json").decode("utf-8"))
                    from .cookie_manager import cookies_to_netscape

                    (target_dir / "cookies.json").write_text(json.dumps(cookies, indent=2), encoding="utf-8")
                    (target_dir / "cookies.txt").write_text(cookies_to_netscape(cookies), encoding="utf-8")

                restored_profile = BrowserProfile(**prof_data)
                self.profiles[new_id] = restored_profile
                self.save_profiles()
                return restored_profile
        except Exception:
            return None
