"""Deep bug-hunt suite for the profile storage layer (``nazak/core/profiles``).

Covers the paths the existing suites leave untested:

* ``store_json``  — backup rotation (``MAX_BACKUPS``), corrupt-file recovery byte-for-byte,
  write-failure atomicity and the ``replace`` retry / ``copy2`` fallback, concurrent writers,
  unicode payloads, ``snapshot_for_migration``.
* ``store_sqlite`` — ``vacuum`` / ``close`` lifecycle, WAL sidecars, schema-version marker,
  migration skipped for unusable ``profiles.json``, one-shot migration idempotency,
  ``save_one`` / ``save_all`` / ``delete_one`` consistency, unreadable row blobs,
  and switching ``NAZAK_PROFILE_STORE`` between the two backends.
* ``files`` — cookie save/load (JSON + Netscape fallback, unicode), ``clear_cache`` variants,
  ``disk_size`` boundaries, ``seed_history``.
* ``bundles`` — explicit directory entries, streaming per-entry / cookie limits, unusable
  containers and manifests, export cache filtering.
* ``merge`` — masked proxy/notes values, ``fields_set`` partial updates.

Everything is black-box where possible; the few tests that read the SQLite ``meta`` /
``profiles`` tables or patch module-level helpers say so in their docstring.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import types
import zipfile
from pathlib import Path

import pytest

from nazak.core import profile_manager as pm_mod
from nazak.core.profile_manager import ProfileManager
from nazak.core.profiles import files as profile_files, store_json
from nazak.core.profiles.constants import MASK
from nazak.core.profiles.merge import merge_fingerprint, merge_google, merge_proxy
from nazak.core.profiles.store_json import MAX_BACKUPS, JsonProfileBackend
from nazak.core.profiles.store_sqlite import SQLITE_SCHEMA_VERSION, SqliteProfileBackend
from nazak.core.secrets_store import UNAVAILABLE_PLACEHOLDER, decrypt_notes, sanitize_notes_for_write
from nazak.models.profile import BrowserProfile, FingerprintConfig, GoogleSettings
from nazak.models.proxy import ProxyConfig, ProxyType


def _ids(path: Path) -> list[str]:
    return [item["id"] for item in json.loads(path.read_text(encoding="utf-8"))]


# ---------------------------------------------------------------------------
# store_json.py
# ---------------------------------------------------------------------------


def test_json_backup_rotation_is_bounded_and_newest_first(tmp_path):
    """``_rotate_backups`` keeps exactly MAX_BACKUPS generations and never mixes them up."""
    pfile = tmp_path / "profiles.json"
    backend = JsonProfileBackend(pfile, tmp_path / "profiles")

    for i in range(MAX_BACKUPS + 4):
        backend.save_all({f"p{i}": BrowserProfile(id=f"p{i}", name=f"n{i}")})

    names = {p.name for p in tmp_path.glob("profiles.json*")}
    expected = {"profiles.json"} | {f"profiles.json.bak.{i}" for i in range(1, MAX_BACKUPS + 1)}
    assert names == expected, "rotation must keep the live file plus exactly MAX_BACKUPS generations"
    assert "profiles.json.bak" not in names, "the staging copy must always be renamed away"

    # The live file is the newest write.
    assert _ids(pfile) == [f"p{MAX_BACKUPS + 3}"]
    # Observed (and documented here) rotation order: the staging copy of the *current* file is
    # renamed to .bak.1, so .bak.1 duplicates the live file and the previous generation is .bak.2.
    assert _ids(tmp_path / "profiles.json.bak.1") == [f"p{MAX_BACKUPS + 3}"]
    assert _ids(tmp_path / "profiles.json.bak.2") == [f"p{MAX_BACKUPS + 2}"]


def test_json_load_handles_missing_empty_corrupt_and_unicode(tmp_path):
    """Missing file, zero-byte file, valid empty list, corrupt file and unicode payloads."""
    missing_root = tmp_path / "missing"
    missing = JsonProfileBackend(missing_root / "profiles.json", missing_root / "profiles")
    assert missing.load_all() == {}
    assert list(missing_root.glob("*.bak")) == [], "a missing file is not corruption"

    zero = tmp_path / "zero" / "profiles.json"
    zero.parent.mkdir()
    zero.write_text("", encoding="utf-8")
    assert JsonProfileBackend(zero, zero.parent / "profiles").load_all() == {}

    empty_list = tmp_path / "empty_list" / "profiles.json"
    empty_list.parent.mkdir()
    empty_list.write_text("[]", encoding="utf-8")
    assert JsonProfileBackend(empty_list, empty_list.parent / "profiles").load_all() == {}
    assert list(empty_list.parent.glob("profiles.corrupt.*.bak")) == [], "[] is valid, not corrupt"

    corrupt = tmp_path / "corrupt" / "profiles.json"
    corrupt.parent.mkdir()
    payload = '{"profiles": [{"id": "x"'
    corrupt.write_text(payload, encoding="utf-8")
    assert JsonProfileBackend(corrupt, corrupt.parent / "profiles").load_all() == {}
    backups = list(corrupt.parent.glob("profiles.corrupt.*.bak"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == payload, "recovery must preserve the bytes"

    # Unicode payload: stored readable (ensure_ascii=False) and loaded back unchanged.
    uni_root = tmp_path / "uni"
    uni = JsonProfileBackend(uni_root / "profiles.json", uni_root / "profiles")
    uni.save_all({"uni": BrowserProfile(id="uni", name="Профиль 🚀", group="Тест")})
    raw = (uni_root / "profiles.json").read_text(encoding="utf-8")
    assert "Профиль 🚀" in raw and "\\u" not in raw
    assert uni.load_all()["uni"].name == "Профиль 🚀"


def test_json_save_all_write_failures_never_corrupt_the_previous_file(tmp_path, monkeypatch):
    """A failing dump must leave the previous file intact; a locked target must be retried.

    Internals: patches ``store_json.json`` (module-local alias) and ``Path.replace`` so the
    write path can be made to fail deterministically without touching nazak/ sources.
    """
    pfile = tmp_path / "profiles.json"
    backend = JsonProfileBackend(pfile, tmp_path / "profiles")
    backend.save_all({"keep": BrowserProfile(id="keep", name="Keep")})
    good = pfile.read_text(encoding="utf-8")

    class _PartialJson:
        """json proxy whose dump writes a torn payload and then fails."""

        load = staticmethod(json.load)

        @staticmethod
        def dump(obj, fp, **kwargs):
            """Mirrors ``json.dump``'s signature, writes a torn payload, then fails."""
            fp.write('[{"id": "half')
            raise OSError("no space left on device")

    monkeypatch.setattr(store_json, "json", _PartialJson)
    with pytest.raises(OSError):
        backend.save_all({"new": BrowserProfile(id="new", name="New")})
    monkeypatch.setattr(store_json, "json", json)

    assert pfile.read_text(encoding="utf-8") == good, "a half-written save must not reach the live file"
    assert list(tmp_path.glob("*.tmp")) == [], "the temp file must be cleaned up"

    # Every replace() attempt is denied -> the copy2 fallback must still publish the write.
    real_replace = Path.replace
    calls = {"n": 0}

    def flaky_replace(self, target):
        calls["n"] += 1
        if calls["n"] <= 5:
            raise PermissionError("file is locked by another process")
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", flaky_replace)
    monkeypatch.setattr(store_json, "time", types.SimpleNamespace(sleep=lambda _seconds: None, time=time.time))

    backend.save_all({"after": BrowserProfile(id="after", name="After")})
    assert calls["n"] > 5, "the retry loop must run before the fallback is used"
    assert _ids(pfile) == ["after"]
    assert list(tmp_path.glob("*.tmp")) == []


def test_json_concurrent_writers_never_publish_a_partial_file(tmp_path):
    """Several threads saving different collections must never interleave into one file."""
    pfile = tmp_path / "profiles.json"
    backend = JsonProfileBackend(pfile, tmp_path / "profiles")
    errors: list[str] = []

    def writer(idx: int) -> None:
        try:
            for _ in range(5):
                backend.save_all({f"w{idx}_{i}": BrowserProfile(id=f"w{idx}_{i}", name=f"W{idx}") for i in range(8)})
        except Exception as exc:  # pragma: no cover - failure reporting
            errors.append(f"writer {idx}: {exc!r}")

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    data = json.loads(pfile.read_text(encoding="utf-8"))
    assert len(data) == 8, "a torn file would not parse as one complete collection"
    assert len({item["id"].split("_")[0] for item in data}) == 1, "collections must not be mixed"
    assert list(tmp_path.glob("*.tmp")) == []


def test_json_snapshot_for_migration_returns_raw_dicts_only(tmp_path):
    """``snapshot_for_migration`` accepts both layouts, filters junk and never decrypts."""
    pfile = tmp_path / "profiles.json"
    backend = JsonProfileBackend(pfile, tmp_path / "profiles")

    protected = {"id": "a", "proxy": {"password": "nzk1:pwd:salt:token"}}
    pfile.write_text(json.dumps({"version": 1, "profiles": [protected, "junk", 7]}), encoding="utf-8")
    assert backend.snapshot_for_migration() == [protected], "proxy secrets stay protected in the snapshot"

    pfile.write_text(json.dumps([{"id": "b"}, 3]), encoding="utf-8")
    assert backend.snapshot_for_migration() == [{"id": "b"}]

    pfile.write_text("not json at all", encoding="utf-8")
    assert backend.snapshot_for_migration() == []

    absent = JsonProfileBackend(tmp_path / "gone" / "profiles.json", tmp_path / "gone" / "profiles")
    assert absent.snapshot_for_migration() == []


# ---------------------------------------------------------------------------
# store_sqlite.py
# ---------------------------------------------------------------------------


def test_sqlite_vacuum_close_and_wal_lifecycle(tmp_path):
    """vacuum/close are safe and repeatable; WAL sidecars exist and data survives reopen.

    Internals: ``_conn`` is used to read ``PRAGMA journal_mode`` (no public accessor exists).
    """
    root = tmp_path / "db"
    backend = SqliteProfileBackend(root / "profiles.json", root / "profiles")
    backend.save_all({"a": BrowserProfile(id="a", name="A")})

    assert backend._conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    sidecars = {p.name for p in root.glob("profiles.db*")}
    assert "profiles.db" in sidecars
    assert "profiles.db-wal" in sidecars, "WAL mode must keep its sidecar file while open"

    backend.vacuum()
    backend.vacuum()
    assert sorted(backend.load_all()) == ["a"]

    # A second connection sees committed rows and its writes are visible to the first one.
    other = SqliteProfileBackend(root / "profiles.json", root / "profiles")
    assert sorted(other.load_all()) == ["a"]
    other.save_one(BrowserProfile(id="b", name="B"))
    assert sorted(backend.load_all()) == ["a", "b"]

    backend.close()
    backend.close()  # idempotent: closing twice must not raise
    other.delete_one("a")
    other.close()

    reopened = SqliteProfileBackend(root / "profiles.json", root / "profiles")
    assert sorted(reopened.load_all()) == ["b"]
    reopened.close()


def test_sqlite_schema_version_is_recorded_once_and_kept(tmp_path):
    """The schema marker is written on first open, never duplicated and never downgraded.

    Internals: reads the ``meta`` table directly - there is no public schema-version accessor.
    """
    root = tmp_path / "db"
    backend = SqliteProfileBackend(root / "profiles.json", root / "profiles")
    backend.save_one(BrowserProfile(id="a", name="A"))
    assert backend._conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchall() == [
        (str(SQLITE_SCHEMA_VERSION),)
    ]
    backend.close()

    again = SqliteProfileBackend(root / "profiles.json", root / "profiles")
    assert again._conn.execute("SELECT COUNT(*) FROM meta WHERE key='schema_version'").fetchone()[0] == 1
    assert again._conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == str(
        SQLITE_SCHEMA_VERSION
    )

    # A DB written by a *newer* build must not be silently relabelled by this one.
    again._conn.execute("UPDATE meta SET value='999' WHERE key='schema_version'")
    again._conn.commit()
    again.close()

    newer = SqliteProfileBackend(root / "profiles.json", root / "profiles")
    assert newer._conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == "999"
    assert sorted(newer.load_all()) == ["a"], "an unknown future schema version must still be readable"
    newer.close()


def test_sqlite_migration_skips_unusable_json(tmp_path):
    """Missing / empty / corrupt / wrong-shaped JSON must not create a half migration."""
    cases = {
        "missing": None,
        "empty": "",
        "corrupt": "{ not json",
        "root-not-a-container": json.dumps({"version": 1, "other": []}),
        "no-usable-rows": json.dumps([{"name": "no id"}, "junk", 5]),
    }
    for label, payload in cases.items():
        root = tmp_path / label
        root.mkdir()
        pfile = root / "profiles.json"
        if payload is not None:
            pfile.write_text(payload, encoding="utf-8")

        backend = SqliteProfileBackend(pfile, root / "profiles")
        assert backend.load_all() == {}, label
        assert backend._conn.execute("SELECT COUNT(*) FROM profiles").fetchone()[0] == 0, label
        backend.close()
        assert list(root.glob("profiles.pre-sqlite.*.bak")) == [], f"{label}: nothing migrated, no backup"


def test_sqlite_migration_imports_once_and_second_open_does_not_duplicate(tmp_path):
    """First open imports every valid row exactly once and keeps the JSON as a backup."""
    root = tmp_path / "db"
    root.mkdir()
    pfile = root / "profiles.json"
    pfile.write_text(
        json.dumps([{"id": "m1", "name": "M1"}, {"id": "m2", "name": "M2"}, {"name": "no id"}]),
        encoding="utf-8",
    )

    backend = SqliteProfileBackend(pfile, root / "profiles")
    assert sorted(backend.load_all()) == ["m1", "m2"]
    assert backend._conn.execute("SELECT COUNT(*) FROM profiles").fetchone()[0] == 2
    assert len(list(root.glob("profiles.pre-sqlite.*.bak"))) == 1
    assert pfile.exists(), "migration must never delete profiles.json"
    backend.close()

    second = SqliteProfileBackend(pfile, root / "profiles")
    assert second._conn.execute("SELECT COUNT(*) FROM profiles").fetchone()[0] == 2, "no duplicate import"
    assert len(list(root.glob("profiles.pre-sqlite.*.bak"))) == 1, "one-shot: no second backup"
    assert sorted(second.load_all()) == ["m1", "m2"]
    second.close()


def test_sqlite_delete_unknown_save_one_and_save_all_stay_consistent(tmp_path):
    """delete_one on an unknown id is a no-op; save_all replaces the whole collection.

    Internals: raw ``INSERT`` on ``_conn`` seeds the unreadable-blob rows this test needs.
    """
    root = tmp_path / "db"
    backend = SqliteProfileBackend(root / "profiles.json", root / "profiles")

    backend.delete_one("does-not-exist")
    assert backend.load_all() == {}

    backend.save_one(BrowserProfile(id="one", name="One"))
    backend.save_one(BrowserProfile(id="one", name="One Updated"))
    assert backend.load_all()["one"].name == "One Updated"
    backend.save_one(BrowserProfile(id="two", name="Two"))
    assert sorted(backend.load_all()) == ["one", "two"]

    # Rows whose blob is not valid JSON / not an object are skipped, never fatal.
    backend._conn.execute("INSERT OR REPLACE INTO profiles(id, updated_at, data) VALUES('bad', 'now', 'not-json')")
    backend._conn.execute("INSERT OR REPLACE INTO profiles(id, updated_at, data) VALUES('bad2', 'now', '\"str\"')")
    backend._conn.commit()
    assert sorted(backend.load_all()) == ["one", "two"]

    backend.save_all({"three": BrowserProfile(id="three", name="Three")})
    assert sorted(backend.load_all()) == ["three"], "save_all persists the whole collection"
    backend.close()


def test_profile_store_switching_between_json_and_sqlite_loses_nothing(tmp_path, monkeypatch):
    """Rolling back to JSON and forward to SQLite again must never drop a profile."""
    pfile = tmp_path / "profiles.json"
    pdir = tmp_path / "profiles"

    monkeypatch.setenv("NAZAK_PROFILE_STORE", "json")
    pm = ProfileManager(pfile, pdir)
    pm.create_profile(BrowserProfile(id="json_first", name="Json First"))

    monkeypatch.setenv("NAZAK_PROFILE_STORE", "sqlite")
    pm = ProfileManager(pfile, pdir)
    assert pm.get_profile("json_first") is not None
    pm.create_profile(BrowserProfile(id="sqlite_second", name="Sqlite Second"))

    monkeypatch.setenv("NAZAK_PROFILE_STORE", "json")
    pm = ProfileManager(pfile, pdir)
    pm.create_profile(BrowserProfile(id="json_third", name="Json Third"))

    monkeypatch.setenv("NAZAK_PROFILE_STORE", "sqlite")
    pm = ProfileManager(pfile, pdir)
    visible = {profile.id for profile in pm.list_profiles()}
    assert "json_third" in visible, "profiles saved while JSON was active must reach the SQLite store"


# ---------------------------------------------------------------------------
# files.py
# ---------------------------------------------------------------------------


def test_files_cookie_round_trip_and_netscape_fallback(tmp_path):
    """save_cookies/load_cookies, the cookies.txt fallback and clean failure reporting."""
    root = tmp_path / "profiles"
    root.mkdir()
    cookies = [{"name": "sid", "value": "Профиль 🚀", "domain": ".example.com", "path": "/"}]

    assert profile_files.save_cookies(root, "c1", cookies) is True
    for rel in ("cookies.json", "Default/cookies.json", "cookies.txt", "Default/cookies.txt"):
        assert (root / "c1" / rel).exists(), rel
    assert profile_files.load_cookies(root, "c1") == cookies

    # Corrupt JSON must fall back to the Netscape file (which keeps the unicode value).
    (root / "c1" / "cookies.json").write_text("{ truncated", encoding="utf-8")
    fallback = profile_files.load_cookies(root, "c1")
    assert len(fallback) == 1
    assert fallback[0]["value"] == "Профиль 🚀"

    assert profile_files.load_cookies(root, "ghost_profile") == []

    assert profile_files.save_cookies(root, "c2", [{"value": object()}]) is False
    assert not (root / "c2" / "cookies.json").exists(), "a refused save leaves no half-written cookie file"


def test_files_clear_cache_removes_every_cache_variant_and_keeps_cookies(tmp_path):
    """Every cache directory name the helper knows about is purged; cookies survive."""
    root = tmp_path / "profiles"
    profile_dir = root / "c1"
    caches = [
        "Default/Cache",
        "Default/Code Cache",
        "Default/GPUCache",
        "Default/DawnCache",
        "Default/Service Worker/CacheStorage",
        "Cache",
        "GPUCache",
    ]
    for rel in caches:
        (profile_dir / rel).mkdir(parents=True, exist_ok=True)
        (profile_dir / rel / "blob.bin").write_bytes(b"junk")
    keep = profile_dir / "Default" / "Cookies"
    keep.write_bytes(b"session")

    assert profile_files.clear_cache(root, "c1") is True
    for rel in caches:
        assert not (profile_dir / rel).exists(), rel
    assert keep.read_bytes() == b"session"

    assert profile_files.clear_cache(root, "unknown_profile") is False, (
        "an unknown profile must report a miss so callers can answer 404"
    )


def test_files_disk_size_for_nested_unknown_and_unsafe_profiles(tmp_path):
    """disk_size sums nested files exactly and refuses unknown / traversal ids."""
    root = tmp_path / "profiles"
    profile_dir = root / "c1"
    (profile_dir / "nested" / "deep").mkdir(parents=True)
    (profile_dir / "a.bin").write_bytes(b"a" * 100)
    (profile_dir / "nested" / "b.bin").write_bytes(b"b" * 250)
    (profile_dir / "nested" / "deep" / "c.bin").write_bytes(b"c" * 7)

    assert profile_files.get_disk_size_bytes(root, "c1") == 357
    assert profile_files.get_disk_size_bytes(root, "ghost") == 0
    assert profile_files.get_disk_size_bytes(root, "../outside") == 0
    assert profile_files.get_disk_size_bytes(root, "c1/../c1") == 0
    assert profile_files.resolve_profile_dir(root, "ghost") == (root / "ghost").resolve()


def test_files_seed_history_creates_chromium_history_db(tmp_path):
    """seed_history writes a Chromium-shaped History DB with the requested entry count."""
    root = tmp_path / "profiles"
    root.mkdir()
    assert profile_files.seed_history(root, "c1", entries_count=7) == 7

    history = root / "c1" / "Default" / "History"
    assert history.exists()
    conn = sqlite3.connect(str(history))
    try:
        assert conn.execute("SELECT COUNT(*) FROM urls").fetchone()[0] == 7
        assert conn.execute("SELECT COUNT(*) FROM visits").fetchone()[0] >= 7
        assert conn.execute("SELECT value FROM meta WHERE key='version'").fetchone()[0] == "65"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# bundles.py
# ---------------------------------------------------------------------------


def test_bundle_import_accepts_explicit_directory_entries(tmp_path):
    """Directory entries inside a bundle must be skipped, not turned into files."""
    bundle = tmp_path / "with_dirs.nazak"
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("profile.json", json.dumps({"name": "With Dirs"}))
        zf.writestr("data/sub/", "")
        zf.writestr("data/sub/file.txt", "payload")

    work = tmp_path / "work"
    pm = ProfileManager(work / "profiles.json", work / "profiles")
    imported = pm.import_profile_bundle(bundle)

    assert imported is not None
    assert (work / "profiles" / imported.id / "sub" / "file.txt").read_text(encoding="utf-8") == "payload"


def test_bundle_import_enforces_per_entry_and_cookie_limits(tmp_path, monkeypatch):
    """The streaming per-entry guard and the cookies.json guard trip when declared size is fine."""
    monkeypatch.setattr(pm_mod, "MAX_BUNDLE_ENTRY_BYTES", 64)
    monkeypatch.setattr(pm_mod, "MAX_BUNDLE_TOTAL_BYTES", 10 * 1024 * 1024)

    entry_bundle = tmp_path / "entry.nazak"
    with zipfile.ZipFile(entry_bundle, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("profile.json", json.dumps({"name": "Entry"}))
        zf.writestr("data/big.bin", b"x" * 4096)
    entry_work = tmp_path / "entry_work"
    entry_pm = ProfileManager(entry_work / "profiles.json", entry_work / "profiles")
    assert entry_pm.import_profile_bundle(entry_bundle) is None
    assert list((entry_work / "profiles").iterdir()) == [], "a refused import leaves no partial profile dir"

    cookie_bundle = tmp_path / "cookies.nazak"
    with zipfile.ZipFile(cookie_bundle, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("profile.json", json.dumps({"name": "Cookies"}))
        zf.writestr("cookies.json", json.dumps([{"name": "c", "value": "v" * 256}]))
    cookie_work = tmp_path / "cookie_work"
    cookie_pm = ProfileManager(cookie_work / "profiles.json", cookie_work / "profiles")
    assert cookie_pm.import_profile_bundle(cookie_bundle) is None
    assert list((cookie_work / "profiles").iterdir()) == []


def test_bundle_import_refuses_unusable_container_or_manifest(tmp_path):
    """Empty zips, garbage, directories and broken/missing manifests are refused cleanly."""
    empty_zip = tmp_path / "empty.nazak"
    with zipfile.ZipFile(empty_zip, "w"):
        pass

    data_only = tmp_path / "data_only.nazak"
    with zipfile.ZipFile(data_only, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("data/a.txt", "a")

    list_manifest = tmp_path / "list_manifest.nazak"
    with zipfile.ZipFile(list_manifest, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("profile.json", "[1, 2, 3]")
        zf.writestr("data/a.txt", "a")

    broken_manifest = tmp_path / "broken_manifest.nazak"
    with zipfile.ZipFile(broken_manifest, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("profile.json", "{ truncated")
        zf.writestr("data/a.txt", "a")

    garbage = tmp_path / "garbage.nazak"
    garbage.write_bytes(b"definitely not a zip archive")

    a_directory = tmp_path / "directory.nazak"
    a_directory.mkdir()

    work = tmp_path / "work"
    pm = ProfileManager(work / "profiles.json", work / "profiles")
    for candidate in (
        empty_zip,
        data_only,
        list_manifest,
        broken_manifest,
        garbage,
        a_directory,
        tmp_path / "missing.nazak",
    ):
        assert pm.import_profile_bundle(candidate) is None, candidate.name

    assert not (work / "profiles").exists(), "refused imports must not create the profiles root"


def test_bundle_export_excludes_caches_and_locks_but_keeps_profile_data(tmp_path):
    """Export ships the manifest and real profile data, never caches or lock files."""
    work = tmp_path / "work"
    pm = ProfileManager(work / "profiles.json", work / "profiles")
    pm.create_profile(BrowserProfile(id="exp1", name="Export Me"))

    data_dir = work / "profiles" / "exp1"
    for rel in ("Default/Cache/blob.bin", "Default/Code Cache/x.bin", "GPUCache/y.bin", "DawnCache/z.bin"):
        (data_dir / rel).parent.mkdir(parents=True, exist_ok=True)
        (data_dir / rel).write_bytes(b"cache")
    (data_dir / "SingletonLock").write_bytes(b"lock")
    (data_dir / "Default" / "Preferences").write_text("{}", encoding="utf-8")

    bundle = pm.export_profile_bundle("exp1")
    assert bundle is not None and bundle.exists()

    with zipfile.ZipFile(bundle) as zf:
        names = set(zf.namelist())
        manifest = json.loads(zf.read("profile.json"))

    assert manifest["id"] == "exp1"
    assert "data/Default/Preferences" in names
    assert not [name for name in names if "Cache" in name or "Singleton" in name]


# ---------------------------------------------------------------------------
# merge.py
# ---------------------------------------------------------------------------


def test_merge_proxy_masked_values_never_clobber_stored_credentials():
    """``***`` from a GET response (raw, password, rotation_url) must keep the stored secret."""
    stored = ProxyConfig(
        type=ProxyType.HTTP,
        host="1.2.3.4",
        port=8080,
        username="user",
        password="stored-pw",
        raw="http://user:stored-pw@1.2.3.4:8080",
        rotation_url="https://rotate.example/new-ip",
    )

    merged = merge_proxy(ProxyConfig(raw="http://user:***@1.2.3.4:8080"), stored, {"raw"})
    assert merged.password == "stored-pw"
    assert (merged.host, merged.port, merged.username) == ("1.2.3.4", 8080, "user")
    assert merged.raw == "http://user:stored-pw@1.2.3.4:8080"
    assert merged.active is True
    assert merged.rotation_url == "https://rotate.example/new-ip"

    masked = stored.model_copy(deep=True)
    masked.password = MASK
    masked.rotation_url = MASK
    merged_fields = merge_proxy(masked, stored, {"password", "rotation_url"})
    assert merged_fields.password == "stored-pw"
    assert merged_fields.rotation_url == "https://rotate.example/new-ip"


def test_merge_partial_updates_only_touch_supplied_fields():
    """``fields_set`` drives proxy/fingerprint/google merges; everything else is preserved."""
    stored_proxy = ProxyConfig(
        type=ProxyType.SOCKS5,
        host="5.5.5.5",
        port=1080,
        username="u",
        password="pw",
        rotation_url="https://rotate.example",
        active=False,
        raw="socks5://u:pw@5.5.5.5:1080",
    )
    incoming = stored_proxy.model_copy(deep=True)
    incoming.host = "9.9.9.9"
    merged = merge_proxy(incoming, stored_proxy, {"host"})
    assert merged.host == "9.9.9.9"
    assert (merged.port, merged.username, merged.password) == (1080, "u", "pw")
    assert merged.rotation_url == "https://rotate.example"
    assert merged.active is False
    assert merged.raw == "socks5://u:pw@9.9.9.9:1080"

    direct = merge_proxy(ProxyConfig(raw="direct"), stored_proxy, {"raw"})
    assert direct.type == ProxyType.DIRECT
    assert (direct.host, direct.port, direct.password, direct.rotation_url) == (None, None, None, None)

    stored_fp = FingerprintConfig(timezone="Europe/Berlin", hardware_concurrency=8, screen_width=1920)
    merged_fp = merge_fingerprint(FingerprintConfig(timezone="Asia/Tokyo"), stored_fp)
    assert merged_fp.timezone == "Asia/Tokyo"
    assert (merged_fp.hardware_concurrency, merged_fp.screen_width) == (8, 1920)

    stored_google = GoogleSettings(target_account_email="a@b.c", tags=["Ads"], notes="kept")
    merged_google = merge_google(GoogleSettings(tags=["New"]), stored_google)
    assert merged_google.tags == ["New"]
    assert (merged_google.target_account_email, merged_google.notes) == ("a@b.c", "kept")


def test_sanitize_notes_protects_stored_secret_from_masked_echo(tmp_path, monkeypatch):
    """The masked notes body the API returns may be PUT back without destroying the secret."""
    monkeypatch.delenv("NAZAK_PROFILE_STORE", raising=False)
    pm = ProfileManager(tmp_path / "profiles.json", tmp_path / "profiles")
    secret = "SuperSecret123"
    notes = {"account_password": secret, "totp_secret": "JBSWY3DPEHPK3PXP", "target_account_email": "a@b.c"}
    pm.create_profile(BrowserProfile(id="n1", name="N1", google=GoogleSettings(notes=json.dumps(notes))))

    stored = pm.get_profile("n1")
    masked = decrypt_notes(json.loads(stored.google.notes))
    assert masked["account_password"] == "Sup...t123", "the API mask shape for a long secret"
    assert masked["account_password"] != secret

    echo = stored.model_copy(deep=True)
    echo.google.notes = json.dumps(masked)
    pm.update_profile(echo)

    after = json.loads(pm.get_profile("n1").google.notes)
    assert after["account_password"] == secret, "a masked echo must never become the stored password"
    assert after["totp_secret"] == "JBSWY3DPEHPK3PXP"

    # Helper keys are dropped; the unavailable-passphrase placeholder is a display value.
    cleaned = sanitize_notes_for_write(
        {"account_password": UNAVAILABLE_PLACEHOLDER, "_totp_raw": "leak-me"},
        {"account_password": secret},
    )
    assert cleaned == {"account_password": secret}


def test_sanitize_notes_literal_mask_never_overwrites_long_secret(tmp_path, monkeypatch):
    """The canonical ``***`` display mask must never be persisted over a real secret."""
    secret = "SuperSecret123"  # longer than 8 chars, so its own mask is 'Sup...t123'
    assert sanitize_notes_for_write({"account_password": MASK}, {"account_password": secret}) == {
        "account_password": secret
    }

    monkeypatch.delenv("NAZAK_PROFILE_STORE", raising=False)
    pm = ProfileManager(tmp_path / "profiles.json", tmp_path / "profiles")
    pm.create_profile(
        BrowserProfile(id="n2", name="N2", google=GoogleSettings(notes=json.dumps({"account_password": secret})))
    )
    incoming = pm.get_profile("n2").model_copy(deep=True)
    incoming.google.notes = json.dumps({"account_password": MASK})
    pm.update_profile(incoming)

    assert json.loads(pm.get_profile("n2").google.notes)["account_password"] == secret
