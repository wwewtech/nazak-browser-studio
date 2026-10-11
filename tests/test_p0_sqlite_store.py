"""P0 refactor regression: SQLite profile store (backend, migration, single-row writes)."""

import json

import pytest

from nazak.core.profile_manager import ProfileManager
from nazak.core.profiles.store_json import JsonProfileBackend
from nazak.core.profiles.store_sqlite import (
    SqliteProfileBackend,
    backend_for,
    sqlite_path_for,
)
from nazak.models.profile import BrowserProfile


@pytest.fixture()
def sqlite_env(monkeypatch, tmp_path):
    monkeypatch.setenv("NAZAK_PROFILE_STORE", "sqlite")
    pfile = tmp_path / "profiles.json"
    pdir = tmp_path / "profiles"
    return pfile, pdir


def test_p0_backend_selector(sqlite_env, monkeypatch):
    pfile, pdir = sqlite_env
    assert isinstance(backend_for(pfile, pdir), SqliteProfileBackend)
    monkeypatch.delenv("NAZAK_PROFILE_STORE", raising=False)
    assert isinstance(backend_for(pfile, pdir), JsonProfileBackend)


def test_p0_sqlite_roundtrip(sqlite_env):
    pfile, pdir = sqlite_env
    pm = ProfileManager(pfile, pdir)
    assert len(pm.list_profiles()) == 10
    assert sqlite_path_for(pfile).exists()

    created = pm.create_profile(BrowserProfile(id="sq_rt", name="SQ Roundtrip"))
    assert created.id == "sq_rt"
    pm2 = ProfileManager(pfile, pdir)
    got = pm2.get_profile("sq_rt")
    assert got is not None and got.name == "SQ Roundtrip"

    got.name = "SQ Renamed"
    pm2.update_profile(got)
    assert ProfileManager(pfile, pdir).get_profile("sq_rt").name == "SQ Renamed"

    assert pm2.delete_profile("sq_rt") is True
    assert ProfileManager(pfile, pdir).get_profile("sq_rt") is None


def test_p0_sqlite_migrates_existing_json(tmp_path, monkeypatch):
    monkeypatch.setenv("NAZAK_PROFILE_STORE", "json")
    pfile = tmp_path / "profiles.json"
    pdir = tmp_path / "profiles"
    pmj = ProfileManager(pfile, pdir)
    pmj.create_profile(BrowserProfile(id="mig_json", name="Mig JSON"))
    assert pfile.exists()

    monkeypatch.setenv("NAZAK_PROFILE_STORE", "sqlite")
    pms = ProfileManager(pfile, pdir)
    assert pms.get_profile("mig_json") is not None
    assert sqlite_path_for(pfile).exists()
    # JSON original is preserved as a backup, never deleted.
    assert any(pfile.parent.glob("profiles.pre-sqlite.*.bak"))


def test_p0_sqlite_single_row_upsert(sqlite_env):
    pfile, pdir = sqlite_env
    backend = SqliteProfileBackend(pfile, pdir)
    prof = BrowserProfile(id="sq_one", name="One")
    backend.save_one(prof)
    backend.save_one(BrowserProfile(id="sq_one", name="One Updated"))
    loaded = backend.load_all()
    assert loaded["sq_one"].name == "One Updated"
    backend.delete_one("sq_one")
    assert "sq_one" not in backend.load_all()
    backend.close()


def test_p0_sqlite_survives_corrupt_json(tmp_path, monkeypatch):
    monkeypatch.setenv("NAZAK_PROFILE_STORE", "sqlite")
    pfile = tmp_path / "profiles.json"
    pdir = tmp_path / "profiles"
    pm = ProfileManager(pfile, pdir)
    pm.create_profile(BrowserProfile(id="sq_keep", name="Keep"))
    pfile.write_text("{ NOT VALID JSON", encoding="utf-8")
    pm2 = ProfileManager(pfile, pdir)
    assert pm2.get_profile("sq_keep") is not None


def test_p0_json_format_stays_bare_list(tmp_path, monkeypatch):
    monkeypatch.delenv("NAZAK_PROFILE_STORE", raising=False)
    pfile = tmp_path / "profiles.json"
    pdir = tmp_path / "profiles"
    pm = ProfileManager(pfile, pdir)
    data = json.loads(pfile.read_text(encoding="utf-8"))
    assert isinstance(data, list), "on-disk profiles.json must stay a bare list (compat)"
    assert any(isinstance(x, dict) and x.get("id") == "prof_01" for x in data)
