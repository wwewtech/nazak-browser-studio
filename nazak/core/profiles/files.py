"""Profile disk helpers: cookies, cache, history, sizes (P0 refactor). Verbatim logic."""

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def validate_id(profile_id: str):
    import re

    if not profile_id or not isinstance(profile_id, str):
        raise ValueError("Invalid profile ID: must be a non-empty string")
    p = Path(profile_id)
    if (
        p.name != profile_id
        or p.is_absolute()
        or profile_id in ("", ".", "..")
        or "/" in profile_id
        or "\\" in profile_id
        or ":" in profile_id
    ):
        raise ValueError(f"Invalid profile ID: path traversal detected ({profile_id})")
    if not re.match(r"^[a-zA-Z0-9_\-]+$", profile_id):
        raise ValueError(f"Invalid profile ID: unsafe characters ({profile_id})")


def resolve_profile_dir(profiles_dir: Path, profile_id: str) -> Path | None:
    """Resolved profile dir, or None when it escapes the root."""
    validate_id(profile_id)
    raw_path = profiles_dir / profile_id
    if raw_path.is_symlink():
        return None
    data_path = raw_path.resolve()
    if not data_path.is_relative_to(profiles_dir.resolve()) or data_path == profiles_dir.resolve():
        return None
    return data_path


def get_disk_size_bytes(profiles_dir: Path, profile_id: str) -> int:
    try:
        validate_id(profile_id)
    except ValueError:
        return 0
    path = (profiles_dir / profile_id).resolve()
    try:
        if not path.is_relative_to(profiles_dir.resolve()) or not path.exists():
            return 0
    except Exception:
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


def clear_cache(profiles_dir: Path, profile_id: str) -> bool:
    validate_id(profile_id)
    path = (profiles_dir / profile_id).resolve()
    if not path.is_relative_to(profiles_dir.resolve()) or not path.exists():
        # A missing profile directory is "nothing to clear" for a fresh profile,
        # but callers use this to report success — returning True made
        # `clear-cache <unknown-id>` answer "cleared" for a profile that does
        # not exist. Report the miss instead and let the caller map it to 404.
        return False
    cache_dirs = ["Cache", "Code Cache", "GPUCache", "DawnCache", "Service Worker/CacheStorage"]
    for cdir in cache_dirs:
        target = path / "Default" / cdir
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        top_target = path / cdir
        if top_target.exists():
            shutil.rmtree(top_target, ignore_errors=True)
    return True


def delete_profile_data(profiles_dir: Path, profile_id: str) -> None:
    validate_id(profile_id)
    raw_path = profiles_dir / profile_id
    if raw_path.is_symlink():
        try:
            raw_path.unlink()
        except Exception as exc:
            logger.warning("Failed to unlink symlink profile dir %s: %s", raw_path, exc)
        return
    data_path = raw_path.resolve()
    if data_path.is_relative_to(profiles_dir.resolve()) and data_path != profiles_dir.resolve() and data_path.exists():
        try:
            shutil.rmtree(data_path)
        except Exception as exc:
            logger.warning("Error deleting profile directory %s: %s; retrying with ignore_errors", data_path, exc)
            shutil.rmtree(data_path, ignore_errors=True)


def save_cookies(profiles_dir: Path, profile_id: str, cookies: list[dict[str, Any]]) -> bool:
    validate_id(profile_id)
    path = resolve_profile_dir(profiles_dir, profile_id)
    if path is None:
        return False
    path.mkdir(parents=True, exist_ok=True)
    default_dir = path / "Default"
    default_dir.mkdir(parents=True, exist_ok=True)
    try:
        json_str = json.dumps(cookies, indent=2, ensure_ascii=False)
        (path / "cookies.json").write_text(json_str, encoding="utf-8")
        (default_dir / "cookies.json").write_text(json_str, encoding="utf-8")

        from ..cookie_manager import cookies_to_netscape

        netscape_str = cookies_to_netscape(cookies)
        (path / "cookies.txt").write_text(netscape_str, encoding="utf-8")
        (default_dir / "cookies.txt").write_text(netscape_str, encoding="utf-8")
        return True
    except Exception:
        return False


def load_cookies(profiles_dir: Path, profile_id: str) -> list[dict[str, Any]]:
    validate_id(profile_id)
    path = (profiles_dir / profile_id).resolve()
    if not path.is_relative_to(profiles_dir.resolve()) or not path.exists():
        return []
    json_file = path / "cookies.json"
    if json_file.exists():
        try:
            return json.loads(json_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    txt_file = path / "cookies.txt"
    if txt_file.exists():
        try:
            from ..cookie_manager import parse_netscape_cookies

            return parse_netscape_cookies(txt_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def seed_history(profiles_dir: Path, profile_id: str, entries_count: int = 25) -> int:
    validate_id(profile_id)
    user_data_path = profiles_dir / profile_id
    user_data_path.mkdir(parents=True, exist_ok=True)
    from ..history_seeder import seed_chrome_history

    return seed_chrome_history(user_data_path, entries_count=entries_count)
