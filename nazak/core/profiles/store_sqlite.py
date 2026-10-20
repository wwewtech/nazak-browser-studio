"""SQLite profile backend (P0 refactor). One row per profile, one transaction per save.

Schema (``profiles.db`` next to ``profiles.json``)::

    meta(key TEXT PRIMARY KEY, value TEXT)          -- schema version marker
    profiles(id TEXT PRIMARY KEY, updated_at TEXT, data TEXT)  -- full BrowserProfile JSON

Migration: on first open, if the DB is empty but ``profiles.json`` exists and
parses, all rows are imported in one transaction and ``profiles.json`` is kept
as a ``.pre-sqlite.bak`` copy (never deleted). Runtime statuses (RUNNING/pid)
are normalised to STOPPED on load, exactly like the JSON backend.
"""

from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from ...config import PROFILES_DIR, PROFILES_FILE
from ...models.profile import BrowserProfile, ProfileStatus
from ..secrets_store import protect_proxy_fields, unprotect_proxy_fields
from .store_json import ProfileBackend

logger = logging.getLogger(__name__)

SQLITE_SCHEMA_VERSION = 1


def sqlite_path_for(profiles_file: Path) -> Path:
    return profiles_file.with_name("profiles.db")


class SqliteProfileBackend(ProfileBackend):
    backend_name = "sqlite"

    def __init__(self, profiles_file: Path = PROFILES_FILE, profiles_dir: Path = PROFILES_DIR):
        self.profiles_file = profiles_file
        self.profiles_dir = profiles_dir
        self.db_path = sqlite_path_for(profiles_file)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=30.0)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        # Hunt C-05: ids this instance has LOADED; save_all deletes only
        # those of them that disappeared from the snapshot (never foreign
        # rows another process committed after our load).
        self._loaded_ids: set[str] = set()
        self._ensure_schema()
        self._migrate_from_json_if_needed()

    # -- schema ---------------------------------------------------------
    def _ensure_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.execute("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT)")
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS profiles(id TEXT PRIMARY KEY, updated_at TEXT, data TEXT NOT NULL)"
            )
            row = self._conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            if row is None:
                self._conn.execute(
                    "INSERT INTO meta(key, value) VALUES('schema_version', ?)", (str(SQLITE_SCHEMA_VERSION),)
                )
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_profiles_updated ON profiles(updated_at)")

    def _get_meta(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return None if row is None else str(row[0])

    def _set_meta(self, key: str, value: str) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def _migrate_from_json_if_needed(self) -> None:
        """One-shot JSON -> SQLite import + incremental catch-up.

        The ``json_migration`` marker keeps the initial import one-shot (a
        ``COUNT(*) == 0`` check alone re-imported the fleet after a full
        delete). But the JSON file keeps receiving writes while the operator
        is in json mode, so every open must also catch up profiles that are
        NEW in the JSON file since the last sync — otherwise switching
        json -> sqlite -> json -> create -> sqlite silently hid them.

        Ownership rule: a profile already present in the DB is never
        overwritten by the JSON copy (the DB is authoritative once migrated);
        only ids missing from the DB are imported.
        """
        with self._lock:
            if not self.profiles_file.exists():
                return
            try:
                with open(self.profiles_file, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and isinstance(data.get("profiles"), list):
                    items = data["profiles"]
                elif isinstance(data, list):
                    items = data
                else:
                    items = []
            except Exception as exc:
                logger.debug("SQLite JSON catch-up skipped: %s", exc)
                items = []

            first_sync = self._get_meta("json_migration") != "done"
            if first_sync:
                count = self._conn.execute("SELECT COUNT(*) FROM profiles").fetchone()[0]
                if count:
                    # DB already owns data: mark done without importing.
                    self._set_meta("json_migration", "done")
                    return
            if not items:
                return

            known = {str(row[0]) for row in self._conn.execute("SELECT id FROM profiles")}
            tombstoned = self._tombstoned_ids()
            rows = []
            for item in items:
                if not isinstance(item, dict) or not item.get("id"):
                    continue
                pid = str(item["id"])
                if pid in known:
                    # The DB is authoritative for anything it already holds:
                    # importing would resurrect profiles deleted in sqlite mode.
                    continue
                if pid in tombstoned:
                    # Deleted here while the JSON copy still lists it: a deletion
                    # must survive a store switch, so the id stays dead.
                    continue
                try:
                    BrowserProfile(**{**item, "proxy": unprotect_proxy_fields(item.get("proxy") or {})})
                except Exception:
                    continue
                rows.append(
                    (
                        pid,
                        datetime.now(timezone.utc).isoformat(),
                        json.dumps(item, ensure_ascii=False),
                    )
                )
            if not rows:
                if first_sync:
                    self._set_meta("json_migration", "done")
                return
            with self._conn:
                self._conn.executemany("INSERT INTO profiles(id, updated_at, data) VALUES(?, ?, ?)", rows)
                if first_sync:
                    # Marker written in the same transaction as the rows, so a
                    # crash can never leave imported data behind without the flag.
                    self._conn.execute(
                        "INSERT INTO meta(key, value) VALUES('json_migration', 'done') "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
                    )
            if first_sync:
                bak = self.profiles_file.with_name(f"profiles.pre-sqlite.{int(time.time())}.bak")
                try:
                    shutil.copy2(self.profiles_file, bak)
                except Exception:
                    pass
                logger.info("Migrated %d profiles from JSON to SQLite (%s)", len(rows), self.db_path)
            else:
                logger.info("Caught up %d new JSON profiles into SQLite (%s)", len(rows), self.db_path)

    # -- backend contract -----------------------------------------------
    def load_all(self) -> dict[str, BrowserProfile]:
        with self._lock:
            out: dict[str, BrowserProfile] = {}
            for (blob,) in self._conn.execute("SELECT data FROM profiles"):
                try:
                    item = json.loads(blob)
                    if isinstance(item.get("proxy"), dict):
                        item["proxy"] = unprotect_proxy_fields(item["proxy"])
                    prof = BrowserProfile(**item)
                    prof.status = ProfileStatus.STOPPED
                    prof.pid = None
                    out[prof.id] = prof
                except Exception:
                    continue
            # C-05: remember what WE saw — save_all may delete only these ids.
            self._loaded_ids = set(out)
            # Hunt F-04 (sqlite twin): the database FILE exists with zero rows
            # after this store was EVER populated — the operator deleted
            # everything while on this backend. Seeding demo presets again
            # would resurrect prof_01..prof_10 on every restart. A fresh
            # install has the `ever_populated` marker absent.
            self._db_had_zero_rows = not out and self._get_meta("ever_populated") == "1"
            return out

    def mark_seen_empty_store(self) -> bool:
        """Hunt F-04 (sqlite twin): True when the DB exists, is initialized
        (migration marker present) and holds zero rows — a deliberate
        delete-all, never a fresh install."""
        return getattr(self, "_db_had_zero_rows", False)

    def is_deleted(self, profile_id: str) -> bool:
        """Hunt X-02 (sqlite twin): True while the shared tombstone exists.

        A stale in-memory snapshot must not resurrect the row through the
        save_one upsert (the tombstone only guarded save_all/delete_one).
        """
        with self._lock:
            row = self._conn.execute("SELECT value FROM meta WHERE key=?", (f"deleted:{profile_id}",)).fetchone()
        return row is not None

    def save_all(self, profiles: dict[str, BrowserProfile]) -> None:
        """Upsert the snapshot WITHOUT wiping rows written by other processes.

        Hunt C-05 (the SQLite twin of the JSON lost update): save_all used to
        be `DELETE FROM profiles` + a full re-insert. A second process holding
        its own connection (GUI + CLI, two windows) lost everything it had
        committed since our load — our stale snapshot erased their rows.

        Now: every profile in the snapshot is upserted (except ids tombstoned
        in the SHARED meta table — a delete by another process must win over
        our stale snapshot), and the ids this instance LOADED (and no longer
        holds) are deleted individually. Rows that appeared on disk after our
        load are foreign work and survive. A delete tombstone is still
        written per removed id, matching delete_one, so a later JSON
        catch-up cannot resurrect them.
        """
        rows = []
        now = datetime.now(timezone.utc).isoformat()
        tombstoned = self._tombstoned_ids()
        for p in profiles.values():
            if p.id in tombstoned:
                # Deleted by ANOTHER process (or by us): the tombstone in the
                # shared meta table is the cross-process source of truth —
                # our stale snapshot must not resurrect the row.
                continue
            item = p.model_dump()
            item["proxy"] = protect_proxy_fields(item.get("proxy") or {})
            rows.append((p.id, p.updated_at or now, json.dumps(item, ensure_ascii=False)))
        removed = sorted(self._loaded_ids - set(profiles))
        with self._lock, self._conn:
            if rows:
                # Hunt F-04: remember this store was ever populated so a later
                # delete-all on an EMPTY database is never reseeded.
                self._conn.execute(
                    "INSERT INTO meta(key, value) VALUES('ever_populated', '1') "
                    "ON CONFLICT(key) DO UPDATE SET value='1'"
                )
            self._conn.executemany(
                "INSERT INTO profiles(id, updated_at, data) VALUES(?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at, data=excluded.data",
                rows,
            )
            for pid in removed:
                self._conn.execute("DELETE FROM profiles WHERE id=?", (pid,))
                self._delete_tombstone(pid)
        self._loaded_ids = set(profiles)

    def save_one(self, profile: BrowserProfile) -> None:
        """Single-row upsert (avoids full-table rewrite on every keystroke)."""
        item = profile.model_dump()
        item["proxy"] = protect_proxy_fields(item.get("proxy") or {})
        with self._lock, self._conn:
            # Hunt F-04: same ever-populated marker as save_all.
            self._conn.execute(
                "INSERT INTO meta(key, value) VALUES('ever_populated', '1') ON CONFLICT(key) DO UPDATE SET value='1'"
            )
            self._conn.execute(
                "INSERT INTO profiles(id, updated_at, data) VALUES(?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at, data=excluded.data",
                (
                    profile.id,
                    profile.updated_at or datetime.now(timezone.utc).isoformat(),
                    json.dumps(item, ensure_ascii=False),
                ),
            )
            # An explicit re-create of the same id clears any tombstone: the
            # operator recreated the profile on purpose, so the JSON catch-up
            # must not treat it as deleted.
            self._conn.execute("DELETE FROM meta WHERE key=?", (f"deleted:{profile.id}",))

    def _delete_tombstone(self, profile_id: str) -> None:
        """Record a deletion so the JSON catch-up can never resurrect it.

        Called inside the caller's transaction.
        """
        self._conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, '1') ON CONFLICT(key) DO UPDATE SET value='1'",
            (f"deleted:{profile_id}",),
        )

    def forget_deleted(self, profile_id: str) -> None:
        """An explicit re-create clears the tombstone (cross-process).

        Mirrors the JSON backend contract: service.create calls this so a
        deliberate re-create of a previously deleted id wins over the
        shared tombstone in meta.
        """
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM meta WHERE key=?", (f"deleted:{profile_id}",))

    def _tombstoned_ids(self) -> set[str]:
        prefix = "deleted:"
        return {
            str(row[0])[len(prefix) :]
            for row in self._conn.execute("SELECT key FROM meta WHERE key LIKE ?", (f"{prefix}%",))
        }

    def delete_one(self, profile_id: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM profiles WHERE id=?", (profile_id,))
            self._delete_tombstone(profile_id)

    def vacuum(self) -> None:
        with self._lock:
            self._conn.execute("VACUUM")

    def close(self) -> None:
        try:
            with self._lock:
                self._conn.commit()
                self._conn.close()
        except Exception:
            logger.warning("SQLite backend close failed (uncommitted data may be lost)", exc_info=True)


def backend_for(profiles_file: Path, profiles_dir: Path) -> ProfileBackend:
    """Select backend by ``NAZAK_PROFILE_STORE`` (``json`` default, ``sqlite`` opt-in)."""
    import os

    from .store_json import JsonProfileBackend

    mode = (os.environ.get("NAZAK_PROFILE_STORE") or "json").strip().lower()
    if mode == "sqlite":
        return SqliteProfileBackend(profiles_file, profiles_dir)
    return JsonProfileBackend(profiles_file, profiles_dir)
