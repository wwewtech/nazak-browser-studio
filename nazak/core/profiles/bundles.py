"""Portable .nazak bundles: export + import with zip-slip and zip-bomb guards (P0 refactor)."""

import json
import logging
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ...models.profile import BrowserProfile, ProfileStatus
from ..secrets_store import protect_proxy_fields, unprotect_proxy_fields
from . import constants as _limits
from .files import load_cookies, validate_id

logger = logging.getLogger(__name__)


def _limit(name: str) -> int:
    """Live limit lookup honouring monkeypatched facade attributes in tests.

    Tests do ``monkeypatch.setattr(pm_mod, "MAX_BUNDLE_*", ...)`` where pm_mod
    is ``nazak.core.profile_manager``. The constants live in
    ``nazak.core.profiles.constants``, so a direct import would ignore the
    patch. Read the facade module attribute first (deferred import avoids the
    service -> bundles -> profile_manager cycle), fall back to constants.
    """
    try:
        import nazak.core.profile_manager as _pm_mod

        val = _pm_mod.__dict__.get(name)
        if isinstance(val, int):
            return val
    except Exception:
        pass
    return int(getattr(_limits, name))


def export_bundle(
    profiles_dir: Path,
    get_profile,
    profile_id: str,
    output_path: Path | None = None,
) -> Path | None:
    try:
        validate_id(profile_id)
    except ValueError:
        return None
    prof = get_profile(profile_id)
    if not prof:
        return None

    import zipfile

    out_file = output_path or (profiles_dir / f"{profile_id}_bundle.nazak")
    out_file.parent.mkdir(parents=True, exist_ok=True)

    prof_dir = (profiles_dir / profile_id).resolve()
    if not prof_dir.is_relative_to(profiles_dir.resolve()):
        return None

    with zipfile.ZipFile(out_file, "w", zipfile.ZIP_DEFLATED) as zf:
        bundle_meta = prof.model_dump()
        bundle_meta["proxy"] = protect_proxy_fields(bundle_meta.get("proxy") or {})
        zf.writestr("profile.json", json.dumps(bundle_meta, indent=2, ensure_ascii=False))

        cookies = load_cookies(profiles_dir, profile_id)
        if cookies:
            zf.writestr("cookies.json", json.dumps(cookies, indent=2, ensure_ascii=False))

        if prof_dir.exists():
            for root, _, files in os.walk(prof_dir):
                for f in files:
                    full_f = Path(root) / f
                    rel_path = full_f.relative_to(prof_dir)
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


def import_bundle(profiles_dir: Path, bundle_path: Path, new_name: str | None = None) -> BrowserProfile | None:
    if not bundle_path.exists():
        return None

    import zipfile

    target_dir = None
    try:
        with zipfile.ZipFile(bundle_path, "r") as zf:
            infos = zf.infolist()
            max_entries = _limit("MAX_BUNDLE_ENTRIES")
            max_total = _limit("MAX_BUNDLE_TOTAL_BYTES")
            if len(infos) > max_entries:
                logger.warning("Bundle import refused: %d entries > %d", len(infos), max_entries)
                return None
            declared_total = sum(max(0, info.file_size) for info in infos)
            if declared_total > max_total:
                logger.warning(
                    "Bundle import refused: declared %d bytes > %d",
                    declared_total,
                    max_total,
                )
                return None
            names = zf.namelist()
            if "profile.json" not in names:
                return None

            prof_data = json.loads(zf.read("profile.json").decode("utf-8"))
            if isinstance(prof_data.get("proxy"), dict):
                prof_data["proxy"] = unprotect_proxy_fields(prof_data["proxy"])
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

            target_dir = (profiles_dir / new_id).resolve()
            target_dir.mkdir(parents=True, exist_ok=True)
            extracted_total = 0

            for name in zf.namelist():
                if name.startswith("data/"):
                    rel_sub = name[len("data/") :]
                    if not rel_sub:
                        continue
                    rel_path = Path(rel_sub)
                    if rel_path.is_absolute() or rel_path.drive or ".." in rel_path.parts:
                        continue
                    target_file = (target_dir / rel_path).resolve()
                    if not target_file.is_relative_to(target_dir):
                        continue
                    target_file.parent.mkdir(parents=True, exist_ok=True)
                    written = 0
                    max_entry = _limit("MAX_BUNDLE_ENTRY_BYTES")
                    max_total_live = _limit("MAX_BUNDLE_TOTAL_BYTES")
                    chunk_size = _limit("BUNDLE_CHUNK")
                    with zf.open(name) as src, target_file.open("wb") as dst:
                        while True:
                            chunk = src.read(chunk_size)
                            if not chunk:
                                break
                            written += len(chunk)
                            if written > max_entry:
                                raise ValueError(f"bundle entry {name!r} exceeds {max_entry} bytes")
                            extracted_total += len(chunk)
                            if extracted_total > max_total_live:
                                raise ValueError(f"bundle expands beyond {max_total_live} bytes")
                            dst.write(chunk)

            if "cookies.json" in zf.namelist():
                cookie_blob = zf.read("cookies.json")
                if len(cookie_blob) > _limit("MAX_BUNDLE_ENTRY_BYTES"):
                    raise ValueError("cookies.json in bundle is too large")
                cookies = json.loads(cookie_blob.decode("utf-8"))
                from ..cookie_manager import cookies_to_netscape

                (target_dir / "cookies.json").write_text(json.dumps(cookies, indent=2), encoding="utf-8")
                (target_dir / "cookies.txt").write_text(cookies_to_netscape(cookies), encoding="utf-8")

            return BrowserProfile(**prof_data)
    except Exception as exc:
        logger.warning("Bundle import failed: %s", exc)
        if target_dir is not None:
            shutil.rmtree(target_dir, ignore_errors=True)
        return None
