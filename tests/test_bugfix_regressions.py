"""Regression tests for real defects found by the deep coverage pass.

Each test here documents a bug that was observed in the product, not a
hypothetical: the docstring states the wrong behaviour and the assertion pins
the correct one.
"""

from __future__ import annotations

import json
import sqlite3

from nazak.core.profile_manager import ProfileManager
from nazak.core.profiles.store_sqlite import SqliteProfileBackend, sqlite_path_for
from nazak.models.profile import BrowserProfile

JSON_MODE = "json"
SQLITE_MODE = "sqlite"


def _stores(tmp_path):
    return tmp_path / "profiles.json", tmp_path / "profiles"


def _meta_value(db_path, key):
    with sqlite3.connect(str(db_path)) as conn:
        row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return None if row is None else row[0]


# ---------------------------------------------------------------------------
# BUG (fixed): one-shot JSON->SQLite migration re-ran whenever the table was
# empty, so deleting every profile resurrected the whole fleet from the stale
# profiles.json that the migration deliberately keeps on disk.
# ---------------------------------------------------------------------------
def test_deleting_every_profile_does_not_resurrect_them_from_json(tmp_path, monkeypatch):
    pfile, pdir = _stores(tmp_path)

    monkeypatch.setenv("NAZAK_PROFILE_STORE", JSON_MODE)
    pm_json = ProfileManager(pfile, pdir)
    pm_json.create_profile(BrowserProfile(id="ghost_one", name="Ghost One"))
    pm_json.create_profile(BrowserProfile(id="ghost_two", name="Ghost Two"))
    assert pfile.exists(), "the JSON backend must own profiles.json"

    monkeypatch.setenv("NAZAK_PROFILE_STORE", SQLITE_MODE)
    pm_sqlite = ProfileManager(pfile, pdir)
    assert pm_sqlite.get_profile("ghost_one") is not None, "first open must migrate"

    for profile in list(pm_sqlite.list_profiles()):
        assert pm_sqlite.delete_profile(profile.id) is True
    assert pm_sqlite.list_profiles() == []

    # Reopen the store. The JSON file is still on disk (kept for rollback), but
    # the migration already happened and must never run a second time.
    reopened = ProfileManager(pfile, pdir)
    assert reopened.get_profile("ghost_one") is None, "deleted profile came back from profiles.json"
    assert reopened.get_profile("ghost_two") is None, "deleted profile came back from profiles.json"
    assert pfile.exists(), "the JSON original must be kept on disk for rollback"

    # Only the built-in seed presets may appear again (the long-standing
    # "seed defaults when the store is empty" policy), never the deleted ids.
    ids = {p.id for p in reopened.list_profiles()}
    assert not any(i.startswith("ghost_") for i in ids)


def test_migration_is_recorded_in_the_meta_table(tmp_path, monkeypatch):
    pfile, pdir = _stores(tmp_path)
    monkeypatch.setenv("NAZAK_PROFILE_STORE", JSON_MODE)
    pm_json = ProfileManager(pfile, pdir)
    pm_json.create_profile(BrowserProfile(id="marked_one", name="Marked"))

    monkeypatch.setenv("NAZAK_PROFILE_STORE", SQLITE_MODE)
    ProfileManager(pfile, pdir)

    assert _meta_value(sqlite_path_for(pfile), "json_migration") == "done", (
        "the one-shot migration must persist a marker, otherwise an empty table triggers a re-import"
    )


def test_deleting_one_profile_keeps_the_deletion_across_restarts(tmp_path, monkeypatch):
    """The narrower version of the same bug: partial deletions must stick too."""
    pfile, pdir = _stores(tmp_path)
    monkeypatch.setenv("NAZAK_PROFILE_STORE", JSON_MODE)
    pm_json = ProfileManager(pfile, pdir)
    pm_json.create_profile(BrowserProfile(id="gone", name="Gone"))
    pm_json.create_profile(BrowserProfile(id="kept", name="Kept"))

    monkeypatch.setenv("NAZAK_PROFILE_STORE", SQLITE_MODE)
    pm_sqlite = ProfileManager(pfile, pdir)
    assert pm_sqlite.delete_profile("gone") is True

    reopened = ProfileManager(pfile, pdir)
    assert reopened.get_profile("gone") is None
    assert reopened.get_profile("kept") is not None


def test_json_is_not_imported_into_a_store_that_sqlite_already_populated(tmp_path, monkeypatch):
    """A profiles.json appearing later must not be treated as a migration source."""
    pfile, pdir = _stores(tmp_path)
    monkeypatch.setenv("NAZAK_PROFILE_STORE", SQLITE_MODE)

    pm_sqlite = ProfileManager(pfile, pdir)  # seeds the ten presets into profiles.db
    assert len(pm_sqlite.list_profiles()) == 10
    assert not pfile.exists(), "the SQLite backend must not write profiles.json"

    # Someone drops an old JSON file next to the database.
    pfile.write_text(
        json.dumps([BrowserProfile(id="intruder", name="Intruder").model_dump()], ensure_ascii=False),
        encoding="utf-8",
    )

    reopened = ProfileManager(pfile, pdir)
    assert reopened.get_profile("intruder") is None, (
        "an unrequested JSON file must not be merged into a populated SQLite store"
    )
    assert reopened.get_profile("prof_01") is not None


def test_json_dropped_in_before_first_population_is_still_migrated(tmp_path, monkeypatch):
    """The helpful path must survive the fix: an empty, never-seeded store imports JSON."""
    pfile, pdir = _stores(tmp_path)
    monkeypatch.setenv("NAZAK_PROFILE_STORE", SQLITE_MODE)

    # Touch the database without ever populating it -> no migration marker yet.
    backend = SqliteProfileBackend(pfile, pdir)
    assert backend.load_all() == {}
    backend.close()
    assert _meta_value(sqlite_path_for(pfile), "json_migration") is None

    pfile.parent.mkdir(parents=True, exist_ok=True)
    pfile.write_text(
        json.dumps([BrowserProfile(id="restored_one", name="Restored").model_dump()], ensure_ascii=False),
        encoding="utf-8",
    )

    backend = SqliteProfileBackend(pfile, pdir)
    loaded = backend.load_all()
    backend.close()
    assert "restored_one" in loaded, "a JSON file dropped into a never-populated store must still migrate"


def test_rollback_to_json_still_sees_the_original_data(tmp_path, monkeypatch):
    """Rolling back to the JSON backend must not lose anything."""
    pfile, pdir = _stores(tmp_path)
    monkeypatch.setenv("NAZAK_PROFILE_STORE", JSON_MODE)
    pm_json = ProfileManager(pfile, pdir)
    pm_json.create_profile(BrowserProfile(id="rollback_one", name="Rollback"))

    monkeypatch.setenv("NAZAK_PROFILE_STORE", SQLITE_MODE)
    pm_sqlite = ProfileManager(pfile, pdir)
    pm_sqlite.create_profile(BrowserProfile(id="sqlite_only", name="SQLite Only"))

    monkeypatch.setenv("NAZAK_PROFILE_STORE", JSON_MODE)
    rolled_back = ProfileManager(pfile, pdir)
    assert rolled_back.get_profile("rollback_one") is not None, "JSON data must survive the round trip"
    assert rolled_back.get_profile("sqlite_only") is None, (
        "documented rollback: profiles created while on SQLite are not in the JSON file"
    )
    assert any(pfile.parent.glob("profiles.pre-sqlite.*.bak")), "the pre-migration backup must be kept"
