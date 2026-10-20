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
        # Hunt C-01: remember the store state we last SAW (mtime+size) so a
        # save can detect that another PROCESS (GUI + CLI, two windows)
        # rewrote profiles.json in the meantime and merge instead of
        # clobbering their work — a classic lost-update.
        self._seen_stat: tuple[float, int] | None = None
        # Ids deleted through THIS instance: the merge must never resurrect
        # them (a foreign process still holding them would otherwise undo our
        # delete on every save).
        self._deleted_ids: set[str] = set()
        # Hunt F-04: True when load_all() found the store FILE (so this is not
        # a fresh install) but zero readable profiles — the operator deleted
        # everything (or every record was corrupt). The service must not seed
        # demo presets over a deliberate delete-all on the next load.
        self._store_file_had_zero_profiles: bool = False
        # Hunt X-02: delete tombstones PERSISTED next to the store (the
        # in-memory set dies with the instance, so a second window / a
        # restarted app resurrected deleted ids through the save_one upsert).
        self._tombstones_file = self.profiles_file.with_name(f"{self.profiles_file.name}.tombstones")
        self._load_tombstones()

    def _load_tombstones(self) -> None:
        try:
            raw = json.loads(self._tombstones_file.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                self._deleted_ids.update(str(x) for x in raw)
        except FileNotFoundError:
            pass
        except Exception:
            logger.debug("tombstones file unreadable: %s", self._tombstones_file, exc_info=True)

    def _save_tombstones(self) -> None:
        try:
            self._tombstones_file.write_text(json.dumps(sorted(self._deleted_ids)), encoding="utf-8")
        except Exception:
            logger.debug("tombstones file write failed: %s", self._tombstones_file, exc_info=True)

    # -- load -----------------------------------------------------------
    def load_all(self) -> dict[str, BrowserProfile]:
        # Hunt X-02: tombstones are persisted; another instance (or a later
        # load in this one) may have recorded deletes since we last looked.
        self._load_tombstones()
        if not self.profiles_file.exists():
            self._seen_stat = None
            self._store_file_had_zero_profiles = False
            return {}
        self._seen_stat = self._stat()
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
                    # A single corrupt record must not lose the whole store,
                    # but the operator has to know the profile was dropped:
                    # a silent skip made "where did my profile go?" undebuggable.
                    logger.warning(
                        "profiles.json: skipping unreadable record id=%r",
                        (item or {}).get("id") if isinstance(item, dict) else "?",
                        exc_info=True,
                    )
                    continue
            # F-04: a parseable file with zero records is a deliberate
            # delete-all, never a first run (a first run has no file).
            self._store_file_had_zero_profiles = not loaded
            return loaded
        except Exception:
            logger.error("profiles.json unreadable — starting empty (backup kept)", exc_info=True)
            try:
                bak_file = self.profiles_file.with_name(f"profiles.corrupt.{int(time.time())}.bak")
                shutil.copy2(self.profiles_file, bak_file)
            except Exception:
                logger.error("corrupt-backup copy failed for %s", self.profiles_file, exc_info=True)
            return {}

    # -- save -----------------------------------------------------------
    # NOTE: on-disk format stays a bare JSON list (compat with 725 tests and
    # existing installs). The versioned envelope is accepted on load only.
    def _stat(self) -> tuple[float, int] | None:
        try:
            st = self.profiles_file.stat()
            return (st.st_mtime, st.st_size)
        except OSError:
            return None

    def note_deleted(self, profile_id: str) -> None:
        """Record a deliberate delete (C-01): the merge must not resurrect it."""
        self._deleted_ids.add(profile_id)
        self._save_tombstones()

    def mark_seen_empty_store(self) -> bool:
        """Hunt F-04: True when the store FILE exists but held zero profiles.

        The service calls this after load_all() returned an empty dict to
        distinguish a fresh install (no file: seed the demo presets) from a
        deliberate delete-all (file present, zero records: never reseed).
        """
        return self._store_file_had_zero_profiles

    def is_deleted(self, profile_id: str) -> bool:
        """Hunt X-02: True when this id was deliberately deleted here.

        The service consults this on every update so a stale in-memory
        snapshot cannot resurrect the row through the save_one upsert path.
        Tombstones are persisted: another instance may have deleted the id
        AFTER this one was constructed, so the file is re-read here — a stale
        in-memory set missed exactly that cross-instance delete.
        """
        self._load_tombstones()
        return profile_id in self._deleted_ids

    def forget_deleted(self, profile_id: str) -> None:
        """An explicit re-create of the same id clears the tombstone."""
        self._deleted_ids.discard(profile_id)
        self._save_tombstones()

    def save_all(self, profiles: dict[str, BrowserProfile]) -> None:
        with self._write_lock:
            # Hunt C-01 (lost update): if another PROCESS rewrote profiles.json
            # after we last read it (GUI open + CLI profile create, two
            # windows, a script...), a plain save would silently erase their
            # work. Reload the foreign state and merge: foreign ids we do not
            # hold are kept; our ids win (we are the newer intent) EXCEPT ids
            # this instance deliberately deleted (a merge must not resurrect
            # our own deletes — the same id recreated later wins normally).
            foreign_wrote = self._seen_stat is not None and self._stat() != self._seen_stat
            if foreign_wrote:
                foreign = self._load_raw_for_merge()
                merged_foreign = 0
                for pid, prof in foreign.items():
                    if pid not in profiles and pid not in self._deleted_ids:
                        profiles = {**profiles, pid: prof}
                        merged_foreign += 1
                if merged_foreign:
                    logger.info(
                        "profiles.json changed on disk by another process; merged %d foreign profile(s)",
                        merged_foreign,
                    )
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
                self._seen_stat = self._stat()
                self._rotate_backups()
            finally:
                if tmp_file.exists():
                    try:
                        tmp_file.unlink(missing_ok=True)
                    except Exception:
                        pass

    def _load_raw_for_merge(self) -> dict[str, BrowserProfile]:
        """Load the on-disk state for merging (no corrupt-backup side effects)."""
        try:
            with open(self.profiles_file, encoding="utf-8") as f:
                data = json.load(f)
            items = data.get("profiles", []) if isinstance(data, dict) else data
            if not isinstance(items, list):
                return {}
            loaded: dict[str, BrowserProfile] = {}
            for item in items:
                if not isinstance(item, dict):
                    continue
                try:
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
            return {}

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
