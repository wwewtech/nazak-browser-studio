"""JSON profile backend (P0 refactor). Atomic writes + corrupt recovery + backup rotation.

This is the current on-disk format (``profiles.json`` list of BrowserProfile
dicts). The backend interface (:class:`ProfileBackend`) is shared with the new
SQLite backend so ``ProfileManager`` can switch formats without callers noticing.
"""

from __future__ import annotations

import json
import logging
import shutil
import threading
import time
import uuid
from abc import ABC, abstractmethod
from pathlib import Path

from ...config import PROFILES_DIR, PROFILES_FILE
from ...models.profile import BrowserProfile, ProfileStatus
from ..secrets_store import protect_proxy_fields, unprotect_proxy_fields

logger = logging.getLogger(__name__)

STORE_SCHEMA_VERSION = 1
MAX_BACKUPS = 5


class ProfileBackend(ABC):
    """Minimal storage contract used by ProfileManager."""

    backend_name: str = "base"

    @abstractmethod
    def load_all(self) -> dict[str, BrowserProfile]: ...

    @abstractmethod
    def save_all(self, profiles: dict[str, BrowserProfile]) -> None:
        """Persist the whole collection."""

        ...


class JsonProfileBackend(ProfileBackend):
    backend_name = "json"

    def __init__(self, profiles_file: Path = PROFILES_FILE, profiles_dir: Path = PROFILES_DIR):
        self.profiles_file = profiles_file
        self.profiles_dir = profiles_dir
        self._write_lock = threading.RLock()

    # -- load -----------------------------------------------------------
    def load_all(self) -> dict[str, BrowserProfile]:
        if not self.profiles_file.exists():
            return {}
        try:
            with open(self.profiles_file, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "profiles" in data and "version" in data:
                items = data.get("profiles", [])
            elif isinstance(data, list):
                items = data
            else:
                raise ValueError("profiles.json root must be a list")
            loaded: dict[str, BrowserProfile] = {}
            for item in items:
                try:
                    if isinstance(item, dict):
                        if isinstance(item.get("proxy"), dict):
                            item["proxy"] = unprotect_proxy_fields(item["proxy"])
                        prof = BrowserProfile(**item)
                        prof.status = ProfileStatus.STOPPED
                        prof.pid = None
                        loaded[prof.id] = prof
                except Exception:
                    continue
            return loaded
        except Exception:
            try:
                bak_file = self.profiles_file.with_name(f"profiles.corrupt.{int(time.time())}.bak")
                shutil.copy2(self.profiles_file, bak_file)
            except Exception:
                pass
            return {}

    # -- save -----------------------------------------------------------
    # NOTE: on-disk format stays a bare JSON list (compat with 725 tests and
    # existing installs). The versioned envelope is accepted on load only.
    def save_all(self, profiles: dict[str, BrowserProfile]) -> None:
        with self._write_lock:
            self.profiles_file.parent.mkdir(parents=True, exist_ok=True)
            tmp_file = self.profiles_file.with_name(f"{self.profiles_file.name}.{uuid.uuid4().hex}.tmp")
            try:
                data = []
                for p in profiles.values():
                    item = p.model_dump()
                    item["proxy"] = protect_proxy_fields(item.get("proxy") or {})
                    data.append(item)
                payload = data
                with open(tmp_file, "w", encoding="utf-8") as f:
                    json.dump(payload, f, indent=2, ensure_ascii=False)
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
                self._rotate_backups()
            finally:
                if tmp_file.exists():
                    try:
                        tmp_file.unlink(missing_ok=True)
                    except Exception:
                        pass

    def _rotate_backups(self) -> None:
        try:
            backup = self.profiles_file.with_suffix(self.profiles_file.suffix + ".bak")
            shutil.copy2(self.profiles_file, backup)
            for i in range(MAX_BACKUPS - 1, 0, -1):
                older = self.profiles_file.with_suffix(f"{self.profiles_file.suffix}.bak.{i}")
                newer = self.profiles_file.with_suffix(f"{self.profiles_file.suffix}.bak.{i + 1}")
                if older.exists():
                    if i + 1 > MAX_BACKUPS:
                        older.unlink(missing_ok=True)
                    else:
                        older.replace(newer)
            if backup.exists():
                backup.replace(self.profiles_file.with_suffix(f"{self.profiles_file.suffix}.bak.1"))
        except Exception as exc:
            logger.debug("backup rotation skipped: %s", exc)

    def snapshot_for_migration(self) -> list[dict]:
        """Raw dict list for SQLite migration (proxy fields still protected)."""
        try:
            with open(self.profiles_file, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("profiles"), list):
                return [x for x in data["profiles"] if isinstance(x, dict)]
            if isinstance(data, list):
                return [x for x in data if isinstance(x, dict)]
        except Exception:
            pass
        return []
