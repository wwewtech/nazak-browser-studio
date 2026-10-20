"""Store integrity regressions (hunt round 7): deliberate-delete persistence,
stale-reference resurrection, and the demo-preset seed contract.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nazak.core.profile_manager import ProfileManager
from nazak.core.profiles.service import ProfileService
from nazak.core.profiles.store_json import JsonProfileBackend
from nazak.core.profiles.store_sqlite import SqliteProfileBackend
from nazak.models.profile import BrowserProfile


def _fresh_sqlite(tmp_path: Path) -> ProfileService:
    backend = SqliteProfileBackend(profiles_file=tmp_path / "p.json", profiles_dir=tmp_path / "profiles")
    svc = ProfileService(backend=backend, profiles_dir=tmp_path / "profiles")
    svc.load(lambda: [])
    return svc


def _fresh_json(tmp_path: Path) -> ProfileService:
    backend = JsonProfileBackend(profiles_file=tmp_path / "p.json", profiles_dir=tmp_path / "profiles")
    svc = ProfileService(backend=backend, profiles_dir=tmp_path / "profiles")
    svc.load(lambda: [])
    return svc


# ---------------------------------------------------------------------------
# F-04: a deliberate delete-all must never be reseeded with the demo fleet
# ---------------------------------------------------------------------------
def test_f04_delete_all_survives_restart_json(tmp_path):
    pfile, pdir = tmp_path / "profiles.json", tmp_path / "profiles"
    pm = ProfileManager(pfile, pdir)
    assert len(pm.profiles) == 10, "fresh install seeds the demo presets"
    for pid in list(pm.profiles):
        pm.delete_profile(pid)
    assert json.loads(pfile.read_text(encoding="utf-8")) == []

    reopened = ProfileManager(pfile, pdir)
    assert reopened.list_profiles() == [], (
        "a deliberate delete-all was reseeded with prof_01..prof_10 on restart (F-04)"
    )


def test_f04_fresh_install_still_seeds(tmp_path):
    pfile, pdir = tmp_path / "profiles.json", tmp_path / "profiles"
    # no file at all -> first run -> the demo fleet must still be provisioned
    pm = ProfileManager(pfile, pdir)
    assert len(pm.list_profiles()) == 10


def test_f04_delete_all_survives_restart_sqlite(tmp_path, monkeypatch):
    monkeypatch.setenv("NAZAK_PROFILE_STORE", "sqlite")
    pfile, pdir = tmp_path / "profiles.json", tmp_path / "profiles"
    pm = ProfileManager(pfile, pdir)
    assert len(pm.profiles) == 10
    for pid in list(pm.profiles):
        pm.delete_profile(pid)
    reopened = ProfileManager(pfile, pdir)
    assert reopened.list_profiles() == [], "sqlite twin of F-04: delete-all was reseeded"


def test_f04_service_load_honours_mark_seen_empty(tmp_path):
    svc = _fresh_json(tmp_path)
    svc.create(BrowserProfile(id="only", name="Only"))
    svc.delete("only")
    # simulate an app restart: a brand-new service over the same store
    reopened = _fresh_json(tmp_path)
    assert reopened.list_all() == []


# ---------------------------------------------------------------------------
# X-02: a stale in-memory snapshot must not resurrect a deleted profile
# ---------------------------------------------------------------------------
def test_x02_stale_update_cannot_resurrect_sqlite(tmp_path):
    a = _fresh_sqlite(tmp_path)
    a.create(BrowserProfile(id="keep", name="Keep"))
    a.create(BrowserProfile(id="drop", name="Drop"))

    b = _fresh_sqlite(tmp_path)
    stale = b.get("drop")

    a.delete("drop")
    stale.name = "Drop-renamed"
    assert b.update(stale) is None, "a stale snapshot resurrected a deleted profile (X-02)"
    ids = {p.id for p in _fresh_sqlite(tmp_path).list_all()}
    assert "drop" not in ids


def test_x02_stale_update_cannot_resurrect_json(tmp_path):
    a = _fresh_json(tmp_path)
    a.create(BrowserProfile(id="keep", name="Keep"))
    a.create(BrowserProfile(id="drop", name="Drop"))

    b = _fresh_json(tmp_path)
    stale = b.get("drop")

    a.delete("drop")
    stale.name = "Drop-renamed"
    assert b.update(stale) is None, "json twin of X-02: resurrection through update"
    ids = {p.id for p in _fresh_json(tmp_path).list_all()}
    assert "drop" not in ids


def test_x02_live_update_still_works_after_foreign_delete_of_OTHER_id(tmp_path):
    svc = _fresh_json(tmp_path)
    svc.create(BrowserProfile(id="a", name="A"))
    svc.create(BrowserProfile(id="b", name="B"))
    svc.delete("b")
    live = svc.get("a")
    live.name = "A2"
    updated = svc.update(live)
    assert updated is not None and updated.name == "A2", "the tombstone of another id must not block live updates"


# ---------------------------------------------------------------------------
# X-11: navigate commands to a stuck pump must not execute stale
# ---------------------------------------------------------------------------
def test_x11_command_queue_is_bounded():
    from nazak.core.synchronizer import MAX_PENDING_COMMANDS, SynchronizerSession

    session = SynchronizerSession("m", ["w"])
    assert session.commands.maxsize == MAX_PENDING_COMMANDS


def test_x11_stale_commands_are_dropped_when_session_inactive():
    from types import SimpleNamespace

    from nazak.core.synchronizer import SynchronizerManager, SynchronizerSession

    mgr = SynchronizerManager(SimpleNamespace())
    session = SynchronizerSession("m", ["w1"])
    session.active = False  # session already torn down
    session.commands.put({"command": "navigate", "url": "http://stale", "reply": None})
    assert mgr._pop_command(session) is None, "a stale command was kept for later execution (X-11)"


def test_x11_navigate_refuses_when_queue_is_full(monkeypatch):
    import asyncio
    import queue as q
    from types import SimpleNamespace

    from nazak.core.synchronizer import MAX_PENDING_COMMANDS, SynchronizerManager, SynchronizerSession

    mgr = SynchronizerManager(SimpleNamespace())
    session = SynchronizerSession("m", ["w1"])
    session.active = True
    mgr.current_session = session
    mgr._pump_thread = SimpleNamespace(is_alive=lambda: True)  # pump "alive" but never drains

    # fill the command queue without parking a waiter: put_nowait directly
    for i in range(MAX_PENDING_COMMANDS):
        session.commands.put({"command": "navigate", "url": f"http://x{i}", "reply": None})
    assert session.commands.qsize() == MAX_PENDING_COMMANDS

    outcomes = asyncio.run(mgr.mirror_navigation("http://y"))
    assert outcomes == {"w1": False}, "a full command queue must refuse instead of piling up"
    assert session.commands.qsize() == MAX_PENDING_COMMANDS, "the refused command must not enter the queue"


def test_x11_waiter_gets_a_reply_when_a_stale_command_is_dropped():
    """A command dequeued after the session went inactive must answer its
    waiter (empty outcomes) instead of leaving it parked for 45 s."""
    import queue as q
    from types import SimpleNamespace

    from nazak.core.synchronizer import SynchronizerManager, SynchronizerSession

    mgr = SynchronizerManager(SimpleNamespace())
    session = SynchronizerSession("m", ["w1"])
    reply: q.Queue = q.Queue()
    session.commands.put({"command": "navigate", "url": "http://x", "reply": reply})
    session.active = False  # torn down before the pump got to the command
    assert mgr._pop_command(session) is None
    assert reply.get_nowait() == {}, "the parked waiter was never answered (45 s hang)"
