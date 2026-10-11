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
        """One-shot JSON -> SQLite import, decided by a persisted marker.

        The marker is the point: deciding by ``COUNT(*) == 0`` alone made the
        import run again every time the table happened to be empty, so deleting
        every profile under the SQLite backend resurrected the whole fleet from
        the (deliberately kept) ``profiles.json`` on the next start.
        """
        with self._lock:
            if self._get_meta("json_migration") == "done":
                return
            count = self._conn.execute("SELECT COUNT(*) FROM profiles").fetchone()[0]
            if count:
                # The DB already owns data, so it must never import the JSON file.
                self._set_meta("json_migration", "done")
                return
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
                    return
                rows = []
                for item in items:
                    if not isinstance(item, dict) or not item.get("id"):
                        continue
                    try:
                        BrowserProfile(**{**item, "proxy": unprotect_proxy_fields(item.get("proxy") or {})})
                    except Exception:
                        continue
                    rows.append(
                        (
                            str(item["id"]),
                            datetime.now(timezone.utc).isoformat(),
                            json.dumps(item, ensure_ascii=False),
                        )
                    )
                if not rows:
                    return
                with self._conn:
                    self._conn.executemany(
                        "INSERT OR REPLACE INTO profiles(id, updated_at, data) VALUES(?, ?, ?)", rows
                    )
                    # Marker written in the same transaction as the rows, so a
                    # crash can never leave imported data behind without the flag.
                    self._conn.execute(
                        "INSERT INTO meta(key, value) VALUES('json_migration', 'done') "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
                    )
                bak = self.profiles_file.with_name(f"profiles.pre-sqlite.{int(time.time())}.bak")
                try:
                    shutil.copy2(self.profiles_file, bak)
                except Exception:
                    pass
                logger.info("Migrated %d profiles from JSON to SQLite (%s)", len(rows), self.db_path)
            except Exception as exc:
                logger.warning("SQLite migration skipped: %s", exc)

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
            return out

    def save_all(self, profiles: dict[str, BrowserProfile]) -> None:
        rows = []
        now = datetime.now(timezone.utc).isoformat()
        for p in profiles.values():
            item = p.model_dump()
            item["proxy"] = protect_proxy_fields(item.get("proxy") or {})
            rows.append((p.id, p.updated_at or now, json.dumps(item, ensure_ascii=False)))
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM profiles")
            self._conn.executemany("INSERT INTO profiles(id, updated_at, data) VALUES(?, ?, ?)", rows)

    def save_one(self, profile: BrowserProfile) -> None:
        """Single-row upsert (avoids full-table rewrite on every keystroke)."""
        item = profile.model_dump()
        item["proxy"] = protect_proxy_fields(item.get("proxy") or {})
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO profiles(id, updated_at, data) VALUES(?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at, data=excluded.data",
                (
                    profile.id,
                    profile.updated_at or datetime.now(timezone.utc).isoformat(),
                    json.dumps(item, ensure_ascii=False),
                ),
            )

    def delete_one(self, profile_id: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM profiles WHERE id=?", (profile_id,))

    def vacuum(self) -> None:
        with self._lock:
            self._conn.execute("VACUUM")

    def close(self) -> None:
        try:
            with self._lock:
                self._conn.commit()
                self._conn.close()
        except Exception:
            pass


def backend_for(profiles_file: Path, profiles_dir: Path) -> ProfileBackend:
    """Select backend by ``NAZAK_PROFILE_STORE`` (``json`` default, ``sqlite`` opt-in)."""
    import os

    from .store_json import JsonProfileBackend

    mode = (os.environ.get("NAZAK_PROFILE_STORE") or "json").strip().lower()
    if mode == "sqlite":
        return SqliteProfileBackend(profiles_file, profiles_dir)
    return JsonProfileBackend(profiles_file, profiles_dir)
