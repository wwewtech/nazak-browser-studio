"""Round-3b regression tests: лимиты распаковки, упаковка релиза, очередь (R3b-06, R3b-07, R3b-14)."""

from __future__ import annotations

import json
import math
import shutil
import zipfile
from pathlib import Path

from nazak.core import cookie_manager as cm, profile_manager as pm_mod, synchronizer as sync
from nazak.core.upload_queue import MAX_BATCH_DELAY_SECONDS, UploadQueueManager


def test_r3b_bundle_import_refuses_oversized_payload(tmp_path, monkeypatch):
    monkeypatch.setattr(pm_mod, "MAX_BUNDLE_TOTAL_BYTES", 1024)
    monkeypatch.setattr(pm_mod, "MAX_BUNDLE_ENTRY_BYTES", 1024)
    bundle = tmp_path / "bomb.nazak"
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("profile.json", json.dumps({"id": "x", "name": "Bomb"}))
        zf.writestr("data/blob.bin", b"\0" * (2 * 1024 * 1024))
    work = tmp_path / "work"
    pm = pm_mod.ProfileManager(work / "profiles.json", work / "profiles")
    assert pm.import_profile_bundle(bundle) is None
    # никаких полураспакованных каталогов не остаётся
    leftovers = [p for p in (work / "profiles").glob("*") if p.is_dir()] if (work / "profiles").exists() else []
    assert leftovers == []


def test_r3b_bundle_import_refuses_too_many_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(pm_mod, "MAX_BUNDLE_ENTRIES", 3)
    bundle = tmp_path / "many.nazak"
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("profile.json", json.dumps({"id": "x", "name": "Many"}))
        for i in range(5):
            zf.writestr(f"data/f{i}.bin", b"x")
    pm = pm_mod.ProfileManager(tmp_path / "w" / "profiles.json", tmp_path / "w" / "profiles")
    assert pm.import_profile_bundle(bundle) is None


def test_r3b_bundle_import_still_works_for_small_bundle(tmp_path):
    bundle = tmp_path / "ok.nazak"
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("profile.json", json.dumps({"id": "x", "name": "Legit"}))
        zf.writestr("data/Cookies", b"payload")
    pm = pm_mod.ProfileManager(tmp_path / "w" / "profiles.json", tmp_path / "w" / "profiles")
    imported = pm.import_profile_bundle(bundle)
    assert imported is not None
    assert (tmp_path / "w" / "profiles" / imported.id / "Cookies").read_bytes() == b"payload"


def test_r3b_cookie_zip_limits(tmp_path, monkeypatch):
    monkeypatch.setattr(cm, "MAX_COOKIE_ZIP_TOTAL_BYTES", 1024)
    monkeypatch.setattr(cm, "MAX_COOKIE_ZIP_ENTRY_BYTES", 1024)
    bomb = tmp_path / "cookies.zip"
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("huge.txt", "x" * (512 * 1024))
    assert cm.parse_cookie_files_from_zip(bomb) == {}

    monkeypatch.setattr(cm, "MAX_COOKIE_ZIP_ENTRIES", 1)
    many = tmp_path / "many.zip"
    with zipfile.ZipFile(many, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("a.txt", ".example.com\tTRUE\t/\tFALSE\t0\ta\t1")
        zf.writestr("b.txt", ".example.com\tTRUE\t/\tFALSE\t0\tb\t2")
    assert cm.parse_cookie_files_from_zip(many) == {}


def test_r3b_build_sanitizes_runtime_data(tmp_path, monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "nazak_build_probe", Path(__file__).resolve().parents[1] / "build_exe.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    app_dir = tmp_path / "dist" / "NazakBrowserStudio"
    data_dir = app_dir / "data"
    (data_dir / "assets").mkdir(parents=True)
    (data_dir / "assets" / "icon.ico").write_bytes(b"ico")
    (data_dir / "profiles" / "prof_1").mkdir(parents=True)
    (data_dir / "profiles" / "prof_1" / "Cookies").write_bytes(b"secret-session")
    (data_dir / "logs").mkdir()
    (data_dir / "logs" / "stdout.log").write_text("log", encoding="utf-8")
    (data_dir / "extensions").mkdir()
    (data_dir / "profiles.json").write_text('{"profiles": []}', encoding="utf-8")
    (data_dir / "profiles.json.bak").write_text("{}", encoding="utf-8")
    (data_dir / "secrets_mode.json").write_text('{"mode": "plain"}', encoding="utf-8")

    monkeypatch.setattr(module, "APP_DIR", app_dir)
    monkeypatch.setattr(module, "ROOT_DIR", tmp_path / "repo")
    (tmp_path / "repo" / "data" / "assets").mkdir(parents=True)
    (tmp_path / "repo" / "data" / "assets" / "banner.png").write_bytes(b"png")
    module.sanitize_app_data()

    remaining = sorted(p.name for p in data_dir.iterdir())
    assert remaining == ["assets"]
    assert (data_dir / "assets" / "icon.ico").exists()
    assert not (data_dir / "profiles").exists()
    assert not (data_dir / "profiles.json").exists()
    assert not (data_dir / "secrets_mode.json").exists()


def test_r3b_build_calls_sanitize_before_packaging():
    source = (Path(__file__).resolve().parents[1] / "build_exe.py").read_text(encoding="utf-8")
    body = source.split("def main():", 1)[1]
    assert body.index("sanitize_app_data()") < body.index("package_zip()")
    assert body.index("smoke_test()") < body.index("sanitize_app_data()")
    installer = (Path(__file__).resolve().parents[1] / "installer.iss").read_text(encoding="utf-8")
    assert "Excludes:" in installer
    assert "data\\profiles\\*" in installer
    assert "data\\profiles.json" in installer


def test_r3b_upload_queue_delay_constant_is_used():
    source = Path(sync.__file__).parent.joinpath("upload_queue.py").resolve().read_text(encoding="utf-8")
    assert "MAX_BATCH_DELAY_SECONDS" in source
    assert MAX_BATCH_DELAY_SECONDS == 3600
    assert "delay_between_accounts_sec + 5" not in source or "safe_delay" in source


def test_r3b_queue_manager_accepts_only_bounded_delay():
    manager = UploadQueueManager.__new__(UploadQueueManager)
    manager.is_running = False
    assert math.isfinite(float(MAX_BATCH_DELAY_SECONDS))
    # Значение из API уже ограничено моделью; здесь проверяем, что константа
    # совпадает с верхней границей pydantic-модели.
    from nazak.api.server import AutopostBatchRequest

    field = AutopostBatchRequest.model_fields["delay_seconds"]
    assert field.metadata, "delay_seconds must carry Field bounds"
    assert any(getattr(meta, "le", None) == MAX_BATCH_DELAY_SECONDS for meta in field.metadata)


def test_r3b_no_temp_leftovers():
    # Страховка: тесты не должны оставлять каталоги в репозитории.
    repo = Path(__file__).resolve().parents[1]
    for stray in (".testtmp", ".pytest_tmp", "r3b_tmp"):
        assert not (repo / stray).exists()
