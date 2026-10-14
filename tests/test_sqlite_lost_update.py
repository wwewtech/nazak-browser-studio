"""SQLite cross-process lost-update regression (hunt round 3, C-05)."""

from __future__ import annotations

from pathlib import Path

from nazak.core.profiles.service import ProfileService
from nazak.core.profiles.store_sqlite import SqliteProfileBackend
from nazak.models.profile import BrowserProfile


def _fresh(tmp_path: Path) -> ProfileService:
    """Build a sqlite-backed service with its own connection (a 'process').

    The backend is constructed DIRECTLY as SqliteProfileBackend (not through
    the env-driven backend_for) so this suite is immune to the ambient
    NAZAK_PROFILE_STORE and cannot leak the sqlite choice into other tests.
    """
    backend = SqliteProfileBackend(profiles_file=tmp_path / "p.json", profiles_dir=tmp_path / "profiles")
    svc = ProfileService(backend=backend, profiles_dir=tmp_path / "profiles")
    svc.load(lambda: [])
    return svc


def test_sqlite_second_manager_writes_survive(tmp_path):
    """C-05: two services over one sqlite DB must not erase each other.

    save_all used to DELETE the whole table and re-insert the caller's
    snapshot — instance A's save destroyed every row instance B committed
    after A's load.
    """
    a = _fresh(tmp_path)
    a.create(BrowserProfile(id="c1", name="One"))

    b = _fresh(tmp_path)
    b.create(BrowserProfile(id="c2", name="Two"))

    a.create(BrowserProfile(id="c3", name="Three"))

    reloaded = _fresh(tmp_path)
    ids = {p.id for p in reloaded.list_all()}
    assert {"c1", "c2", "c3"} <= ids, f"sqlite lost update: missing {sorted({'c1', 'c2', 'c3'} - ids)}"


def test_sqlite_delete_survives_foreign_save(tmp_path):
    """A delete through instance A must not be undone by B's save_all."""
    a = _fresh(tmp_path)
    a.create(BrowserProfile(id="keep", name="Keep"))
    a.create(BrowserProfile(id="drop", name="Drop"))

    b = _fresh(tmp_path)
    a.delete("drop")
    # B (still holding 'drop' in its snapshot) saves — the row must stay dead.
    b.create(BrowserProfile(id="b_new", name="BNew"))

    reloaded = _fresh(tmp_path)
    ids = {p.id for p in reloaded.list_all()}
    assert "drop" not in ids, "sqlite: delete resurrected by a foreign save_all"
    assert "b_new" in ids, "sqlite: foreign write lost"
    assert "keep" in ids
