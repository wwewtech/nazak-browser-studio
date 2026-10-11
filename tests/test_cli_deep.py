"""Deep CLI hunt: `profile`, `cookie`/`proxy`, `warmup`/`scenario`/`sync` and `common` helpers.

Фокус — слабо покрытые ветки CLI-команд (profiles 52%, cookies_proxies 37%, automation 54%,
common 67%): неверные/отсутствующие аргументы, неизвестные id, границы `--count`, `@file`/`--file`,
защита `--out` от молчаливой перезаписи, маскирование секретов, выбор сценариев/ротация прокси.

Тесты с `xfail` фиксируют НАЙДЕННЫЕ баги продукта (assert описывает корректное поведение).
"""

from __future__ import annotations

import contextlib
import json
import sys
import zipfile
from io import StringIO

import pytest

from nazak import cli
from nazak.cli_cmds import common as cli_common
from nazak.cli_cmds.common import GlobalOptions, UsageError, read_input_text, resolve_out_path
from nazak.models.health import GoogleReachability, HealthCheckResult, HealthStatus
from nazak.models.profile import BrowserProfile
from nazak.models.proxy import ProxyConfig, ProxyType

# --------------------------------------------------------------------------- helpers


def run(argv: list[str]) -> tuple[int, str, str]:
    old = sys.argv
    sys.argv = ["nazak", *argv]
    try:
        out, err = StringIO(), StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.run_cli()
        return int(code), out.getvalue(), err.getvalue()
    finally:
        sys.argv = old


def run_json(argv: list[str]) -> tuple[int, dict]:
    code, out, _ = run([*argv, "--json"])
    return code, json.loads(out)


def _drop(profile_id: str) -> None:
    run(["--yes", "profile", "delete", profile_id, "--json"])


@pytest.fixture()
def make_profile():
    """Создаёт профиль через CLI и удаляет всё созданное по завершении теста."""
    created: list[str] = []

    def _make(name: str, proxy: str = "direct", extra: list[str] | None = None) -> str:
        argv = ["profile", "create", "--name", name, "--proxy", proxy, *(extra or [])]
        code, payload = run_json(argv)
        assert code == 0, payload
        created.append(payload["profile_id"])
        return payload["profile_id"]

    yield _make
    for profile_id in created:
        _drop(profile_id)


VALID_COOKIES = json.dumps([{"name": "sid", "value": "v1", "domain": ".example.com", "path": "/"}])
NO_PROXY_GHOST = "prof_deep_ghost"


async def _stub_health(proxy, profile_dir=None, timeout_sec=8.0):
    """Заглушка реального checker-а: тесты никогда не ходят в сеть."""
    return HealthCheckResult(
        status=HealthStatus.HEALTHY,
        ping_ms=7.5,
        ip="203.0.113.7",
        country="NL",
        city="AMS",
        google=GoogleReachability(google_main=True, all_ok=True),
    )


# --------------------------------------------------------------------------- profiles: CRUD / ids


def test_profiles_crud_unknown_ids_are_not_found():
    for argv in (
        ["profile", "get", NO_PROXY_GHOST],
        ["profile", "update", NO_PROXY_GHOST, "--name", "Renamed"],
        ["profile", "delete", NO_PROXY_GHOST, "--yes"],
        ["profile", "clone", NO_PROXY_GHOST],
        ["profile", "bundle-export", NO_PROXY_GHOST],
        ["cookie", "export", NO_PROXY_GHOST],
        ["proxy", "check", NO_PROXY_GHOST],
        ["proxy", "rotate", NO_PROXY_GHOST],
    ):
        code, payload = run_json(argv)
        assert code == 1, f"{argv} -> {code} {payload}"
        assert payload["success"] is False


def test_mass_generate_count_and_os_mix_bounds():
    for count in ("201", "-3"):
        code, payload = run_json(["profile", "mass-generate", "--count", count])
        assert code == 2, f"count={count} должен быть отвергнут"
        assert "1..200" in payload["error"]

    code, _, _ = run(["profile", "mass-generate", "--count", "1", "--os-mix", "beos", "--json"])
    assert code == 2  # argparse choices

    code, payload = run_json(
        [
            "profile",
            "mass-generate",
            "--count",
            "2",
            "--os-mix",
            "all",
            "--group",
            "Deep MG",
            "--tags",
            "x,y",
            "--notes",
            "note-probe",
        ]
    )
    assert code == 0 and payload["created_count"] == 2
    ids = payload["profile_ids"]
    try:
        code, got = run_json(["profile", "get", ids[0]])
        assert code == 0
        prof = got["profile"]
        assert prof["group"] == "Deep MG"
        assert prof["google"]["tags"] == ["x", "y"]
        assert prof["google"]["notes"] == "note-probe"
    finally:
        for profile_id in ids:
            _drop(profile_id)


def test_seed_history_count_bounds():
    for count in ("4", "101", "0"):
        code, payload = run_json(["profile", "seed-history", NO_PROXY_GHOST, "--count", count])
        assert code == 2, f"count={count} должен быть отвергнут"
        assert "5..100" in payload["error"]


@pytest.mark.xfail(
    strict=False,
    reason="BUG: --count 26..100 (валиден по CLI-границе 5..100) молча сеет только 25 записей и возвращает success",
)
def test_seed_history_honours_requested_count(make_profile):
    profile_id = make_profile("Deep Seed100")
    code, payload = run_json(["profile", "seed-history", profile_id, "--count", "100"])
    # Корректно: либо выполнить ровно 100 записей, либо честно отвергнуть count>25 (exit 2).
    honoured = code == 2 or (code == 0 and payload.get("seeded_entries") == 100)
    assert honoured, f"count=100 молча превратился в {payload.get('seeded_entries')} записей (code={code})"


def test_clear_cache_unknown_profile_reports_success():
    code, payload = run_json(["profile", "clear-cache", NO_PROXY_GHOST])
    assert code == 1, f"неизвестный профиль -> {code} {payload}"
    assert payload["success"] is False


@pytest.mark.xfail(
    strict=False,
    reason="BUG: небезопасный id в clear-cache даёт exit 4 с сырым ValueError вместо usage(2)/not-found(1)",
)
def test_clear_cache_invalid_id_is_not_a_conflict():
    code, payload = run_json(["profile", "clear-cache", "../evil"])
    assert code in (1, 2), f"path traversal id -> {code} {payload}"


def test_batch_launch_reports_missing_profiles_and_requires_selection():
    code, payload = run_json(["profile", "batch-launch"])
    assert code == 2 and payload["success"] is False
    code, payload = run_json(["profile", "batch-stop"])
    assert code == 2

    code, payload = run_json(["profile", "batch-launch", "--profiles", NO_PROXY_GHOST])
    assert code == 0
    assert payload["results"][NO_PROXY_GHOST]["success"] is False


@pytest.mark.xfail(
    strict=False,
    reason="BUG: batch-stop по несуществующему id возвращает 'Остановлено: 1' и exit 0 (одиночный `profile stop` даёт exit 1)",
)
def test_batch_stop_unknown_profile_reports_false_success():
    code, payload = run_json(["profile", "batch-stop", "--profiles", NO_PROXY_GHOST])
    assert code == 1 or payload.get("stopped_count") == 0, f"ложная остановка: {code} {payload}"


# --------------------------------------------------------------------------- profiles: input/out guards


def test_bulk_import_input_errors_and_file_import(tmp_path):
    code, payload = run_json(["profile", "bulk-import"])
    assert code == 2 and "proxy-строк" in payload["error"]

    code, payload = run_json(["profile", "bulk-import", f"@{tmp_path / 'nope.txt'}"])
    assert code == 2 and "не найден" in payload["error"]

    code, payload = run_json(["profile", "bulk-import", f"@{tmp_path}"])
    assert code == 2 and "каталог" in payload["error"]

    code, payload = run_json(["profile", "bulk-import", "--file", str(tmp_path)])
    assert code == 2 and "каталог" in payload["error"]

    big = tmp_path / "big.txt"
    big.write_bytes(b"1.1.1.1:8080\n" * (17 * 1024 * 1024 // 13))  # > 16 MB лимита
    code, payload = run_json(["profile", "bulk-import", f"@{big}"])
    assert code == 2 and "слишком большой" in payload["error"]

    src = tmp_path / "proxies.txt"
    src.write_text("1.1.1.1:8080\n2.2.2.2:8081\n\n", encoding="utf-8")
    code, payload = run_json(["profile", "bulk-import", "--file", str(src), "--group", "DeepBI"])
    assert code == 0 and payload["created_count"] == 2

    code, listed = run_json(["profile", "list", "--group", "DeepBI"])
    try:
        assert code == 0 and listed["count"] == 2
        assert all(row["group"] == "DeepBI" for row in listed["profiles"])
    finally:
        for row in listed.get("profiles", []):
            _drop(row["id"])


def test_profile_create_tags_proxy_masking_and_update(make_profile):
    profile_id = make_profile(
        "Deep Tags",
        proxy="1.2.3.4:8080:pxuser:pxDeepSecret",
        extra=["--group", "DeepG", "--tags", " a , b ,, c "],
    )
    code, got = run_json(["profile", "get", profile_id])
    assert code == 0
    prof = got["profile"]
    assert prof["google"]["tags"] == ["a", "b", "c"]
    assert prof["group"] == "DeepG"
    assert prof["proxy"]["username"] == "pxuser"
    assert prof["proxy"]["password"] == "***"

    code, _ = run_json(["profile", "update", profile_id, "--group", "DeepG2", "--proxy", "socks5://u:pw@9.9.9.9:1080"])
    assert code == 0
    code, got = run_json(["profile", "get", profile_id])
    prof = got["profile"]
    assert prof["group"] == "DeepG2"
    assert (prof["proxy"]["type"], prof["proxy"]["host"], prof["proxy"]["port"]) == ("socks5", "9.9.9.9", 1080)
    assert prof["proxy"]["password"] == "***"


def test_profile_get_does_not_leak_proxy_raw_password(make_profile):
    secret = "pxDeepSecret123"
    profile_id = make_profile("Deep Leak", proxy=f"1.2.3.4:8080:pxuser:{secret}")
    code, got = run_json(["profile", "get", profile_id])
    assert code == 0
    assert secret not in json.dumps(got, ensure_ascii=False), "пароль прокси утёк в вывод без --reveal"


@pytest.mark.xfail(
    strict=False,
    reason="BUG: profile launch --url file://... отдаёт exit 4 (conflict) вместо usage(2) для недопустимой схемы",
)
def test_profile_launch_rejects_disallowed_url_scheme_as_usage_error(monkeypatch, make_profile):
    import nazak.core.browser_launcher as launcher

    # Фейковый путь к Chrome: sanitize_launch_url обязан отклонить URL ДО subprocess.Popen.
    monkeypatch.setattr(launcher, "find_chrome_executable", lambda: r"C:\fake\chrome.exe")
    profile_id = make_profile("Deep LaunchUrl")

    code, payload = run_json(["profile", "launch", profile_id, "--url", "file:///C:/Windows/win.ini"])
    assert code == 2, f"недопустимая схема URL -> {code} {payload}"


def test_bundle_export_out_guard_and_force(tmp_path, make_profile):
    profile_id = make_profile("Deep Bundle")
    target = tmp_path / "bundle.nazak"
    target.write_text("keep me", encoding="utf-8")

    code, payload = run_json(["profile", "bundle-export", profile_id, "--out", str(target)])
    assert code == 2 and payload["success"] is False
    assert target.read_text(encoding="utf-8") == "keep me", "существующий файл перезаписан без --force"

    code, _ = run_json(["profile", "bundle-export", profile_id, "--out", str(target), "--force"])
    assert code == 0 and zipfile.is_zipfile(target)

    code, payload = run_json(["profile", "bundle-export", profile_id, "--out", str(tmp_path)])
    assert code == 2 and "каталог" in payload["error"]

    code, payload = run_json(["profile", "bundle-export", profile_id, "--out", str(tmp_path / "nodir" / "b.nazak")])
    assert code == 2 and "не существует" in payload["error"]


def test_bundle_export_import_roundtrip_and_garbage(tmp_path, make_profile):
    profile_id = make_profile("Deep Roundtrip")
    bundle = tmp_path / "rt.nazak"
    code, _ = run_json(["profile", "bundle-export", profile_id, "--out", str(bundle)])
    assert code == 0 and bundle.exists()

    code, payload = run_json(["profile", "bundle-import", str(bundle), "--new-name", "Deep Imported"])
    assert code == 0
    imported = payload["profile_id"]
    assert imported != profile_id
    try:
        code, got = run_json(["profile", "get", imported])
        assert code == 0 and got["profile"]["name"] == "Deep Imported"
    finally:
        _drop(imported)

    garbage = tmp_path / "garbage.nazak"
    garbage.write_text("not a zip at all", encoding="utf-8")
    code, payload = run_json(["profile", "bundle-import", str(garbage)])
    assert code == 2 and payload["success"] is False

    code, payload = run_json(["profile", "bundle-import", str(tmp_path)])
    assert code == 2

    code, payload = run_json(["profile", "bundle-import", str(tmp_path / "missing.nazak")])
    assert code == 1 and payload["success"] is False


def test_profile_delete_without_yes_non_interactive(monkeypatch, make_profile):
    monkeypatch.setattr(cli_common, "is_interactive", lambda: False)
    profile_id = make_profile("Deep Confirm")

    code, out, err = run(["profile", "delete", profile_id])
    assert code == 4, "неинтерактивный отказ должен быть conflict, а не зависание/0"
    assert "--yes" in (out + err)

    code, _ = run_json(["profile", "get", profile_id])
    assert code == 0, "профиль не должен быть удалён без подтверждения"


# --------------------------------------------------------------------------- cookies


def test_cookie_import_validation(make_profile):
    profile_id = make_profile("Deep Cookie")

    code, payload = run_json(["cookie", "import", profile_id])
    assert code == 2 and payload["success"] is False

    code, payload = run_json(["cookie", "import", profile_id, "not-a-cookie"])
    assert code == 2 and "распознано" in payload["error"]

    code, payload = run_json(["cookie", "bulk-import", "--group", "DeepCK", "=== OnlyHeader ==="])
    assert code == 2 and payload["success"] is False

    code, payload = run_json(["cookie", "import", NO_PROXY_GHOST, VALID_COOKIES])
    assert code == 1 and payload["success"] is False

    code, payload = run_json(["cookie", "import", profile_id, VALID_COOKIES])
    assert code == 0 and payload["parsed_cookies_count"] == 1


def test_cookie_export_formats_and_out_guards(tmp_path, make_profile):
    profile_id = make_profile("Deep CkExp")
    assert run_json(["cookie", "import", profile_id, VALID_COOKIES])[0] == 0

    code, payload = run_json(["cookie", "export", profile_id])
    assert code == 0 and payload["format"] == "json" and payload["cookies_count"] == 1

    code, payload = run_json(["cookie", "export", profile_id, "--format", "netscape"])
    assert code == 0 and payload["format"] == "netscape" and ".example.com" in payload["content"]

    keep = tmp_path / "keep.json"
    keep.write_text("keep me", encoding="utf-8")
    code, payload = run_json(["cookie", "export", profile_id, "--out", str(keep)])
    assert code == 2 and keep.read_text(encoding="utf-8") == "keep me"

    code, payload = run_json(["cookie", "export", profile_id, "--out", str(tmp_path)])
    assert code == 2 and "каталог" in payload["error"]

    out = tmp_path / "cookies.json"
    code, _ = run_json(["cookie", "export", profile_id, "--out", str(out)])
    assert code == 0
    assert json.loads(out.read_text(encoding="utf-8"))[0]["name"] == "sid"


@pytest.mark.xfail(
    strict=False,
    reason="BUG: `--profiles all` (значение из help) не раскрывается в список профилей: молча экспортируется 0",
)
def test_cookie_bulk_export_profiles_all_is_expanded(make_profile):
    profile_id = make_profile("Deep BulkAll")
    assert run_json(["cookie", "import", profile_id, VALID_COOKIES])[0] == 0

    code, control = run_json(["cookie", "bulk-export", "--all"])
    assert code == 0 and profile_id in control["cookies"], "профиль обязан попасть в --all экспорт"

    code, payload = run_json(["cookie", "bulk-export", "--profiles", "all"])
    assert code == 0
    assert payload["profiles_count"] >= 1 and profile_id in payload["cookies"], f"all -> {payload}"


def test_cookie_bulk_export_zip_out_guard(tmp_path, make_profile):
    profile_id = make_profile("Deep Zip")
    assert run_json(["cookie", "import", profile_id, VALID_COOKIES])[0] == 0

    out = tmp_path / "ck.zip"
    code, payload = run_json(["cookie", "bulk-export", "--profiles", profile_id, "--format", "zip", "--out", str(out)])
    assert code == 0 and zipfile.is_zipfile(out) and payload["profiles_count"] == 1

    code, payload = run_json(["cookie", "bulk-export", "--profiles", profile_id, "--format", "zip", "--out", str(out)])
    assert code == 2 and "уже существует" in payload["error"]

    code, _ = run_json(
        ["cookie", "bulk-export", "--profiles", profile_id, "--format", "zip", "--out", str(out), "--force"]
    )
    assert code == 0 and zipfile.is_zipfile(out)


# --------------------------------------------------------------------------- proxies


def test_proxy_test_and_check_all_use_no_network(monkeypatch, make_profile):
    monkeypatch.setattr("nazak.core.proxy_checker.check_proxy_health", _stub_health)

    code, payload = run_json(["proxy", "test", "1.2.3.4:8080:pxuser:pxDeepSecret"])
    assert code == 0
    assert "pxDeepSecret" not in json.dumps(payload, ensure_ascii=False), "пароль прокси утёк в proxy test"
    assert payload["proxy"] == "http://pxuser:***@1.2.3.4:8080"
    assert payload["health"]["status"] == "healthy"

    code, payload = run_json(["proxy", "test", "socks5://u:pw@1.2.3.4:1080"])
    assert code == 0 and payload["proxy"] == "socks5://u:***@1.2.3.4:1080"

    make_profile("Deep CheckAll")
    pm, _ = cli_common.get_managers()
    code, payload = run_json(["proxy", "check-all"])
    assert code == 0 and payload["total_checked"] == len(pm.list_profiles())


def test_proxy_rotate_refuses_unsafe_rotation_url(make_profile):
    pm, _ = cli_common.get_managers()
    direct = make_profile("Deep RotNone")

    code, payload = run_json(["proxy", "rotate", direct])
    assert code == 4 and "rotation_url" in payload["error"]

    masked = pm.create_profile(
        BrowserProfile(
            name="Deep RotMask",
            proxy=ProxyConfig(type=ProxyType.HTTP, host="1.2.3.4", port=8080, rotation_url="***"),
        )
    )
    ftp = pm.create_profile(
        BrowserProfile(
            name="Deep RotFtp",
            proxy=ProxyConfig(type=ProxyType.HTTP, host="1.2.3.4", port=8080, rotation_url="ftp://rotate.example/x"),
        )
    )
    try:
        code, payload = run_json(["proxy", "rotate", masked.id])
        assert code == 4 and "замаскирован" in payload["error"]

        code, payload = run_json(["proxy", "rotate", ftp.id])
        assert code == 2 and "http://" in payload["error"], "не-http схема ротации не должна уходить в сеть"
    finally:
        _drop(masked.id)
        _drop(ftp.id)


# --------------------------------------------------------------------------- automation


def test_automation_requires_targets(make_profile):
    profile_id = make_profile("Deep Auto")

    code, payload = run_json(["scenario", "run", "--scenario", "scen_ecom_trust"])
    assert code == 2 and "--profiles" in payload["error"]

    code, payload = run_json(["scenario", "run", "--profiles", profile_id, "--scenario", "bogus"])
    assert code == 2 and "Неизвестный scenario" in payload["error"]

    code, payload = run_json(["scenario", "run", "--profiles", NO_PROXY_GHOST, "--scenario", "scen_ecom_trust"])
    assert code == 1 and payload["success"] is False

    code, payload = run_json(["sync", "start", "--master", NO_PROXY_GHOST, "--workers", ""])
    assert code == 2

    code, payload = run_json(["sync", "start", "--master", NO_PROXY_GHOST, "--workers", "w1"])
    assert code == 1 and payload["success"] is False

    code, _, _ = run(["sync", "start", "--workers", "w1", "--json"])
    assert code == 2  # обязательный --master


@pytest.mark.xfail(
    strict=False,
    reason="BUG: отсутствующий/битый --scenario-file даёт exit 4 с сырым OSError/JSONDecodeError вместо usage(2)",
)
def test_scenario_run_bad_scenario_file_is_usage_error(tmp_path, make_profile):
    profile_id = make_profile("Deep ScenFile")

    code, payload = run_json(
        ["scenario", "run", "--profiles", profile_id, "--scenario-file", str(tmp_path / "no.json")]
    )
    assert code == 2, payload

    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    code, payload = run_json(["scenario", "run", "--profiles", profile_id, "--scenario-file", str(bad)])
    assert code == 2, payload


@pytest.mark.xfail(
    strict=False,
    reason="BUG: sync navigate принимает file://javascript: URL и отвечает exit 0/success (URL валидируется только внутри воркера)",
)
def test_sync_navigate_rejects_non_http_urls():
    for url in ("file:///C:/Windows/win.ini", "javascript:alert(1)"):
        code, payload = run_json(["sync", "navigate", url])
        assert code == 2, f"{url} -> {code} {payload}"


# --------------------------------------------------------------------------- common helpers


def test_common_input_out_and_confirm_helpers(tmp_path, monkeypatch):
    existing = tmp_path / "exists.txt"
    existing.write_text("x", encoding="utf-8")
    opt = GlobalOptions()

    with pytest.raises(UsageError):
        resolve_out_path("", opt)
    with pytest.raises(UsageError):
        resolve_out_path(str(tmp_path), opt)
    with pytest.raises(UsageError):
        resolve_out_path(str(existing), opt)
    assert resolve_out_path(str(existing), opt, force=True) == existing
    with pytest.raises(UsageError):
        resolve_out_path(str(tmp_path / "nodir" / "f.txt"), opt)

    with pytest.raises(UsageError):
        read_input_text("@" + str(tmp_path / "missing.txt"))
    with pytest.raises(UsageError):
        read_input_text("@" + str(tmp_path))
    latin = tmp_path / "latin.txt"
    latin.write_bytes(b"1.2.3.4:8080\xff\xfe\n")
    assert "1.2.3.4:8080" in read_input_text("@" + str(latin)), "битая кодировка не должна ронять чтение входного файла"

    monkeypatch.setattr(cli_common, "is_interactive", lambda: False)
    assert cli_common.confirm("delete?", GlobalOptions()) is False
    assert cli_common.confirm("delete?", GlobalOptions(yes=True)) is True

    buf = StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        ok, code = cli_common.require_confirm(
            "delete?", GlobalOptions(as_json=True), retry_hint="profile delete X --yes"
        )
    assert ok is False and code == 4
    assert '"success": false' in buf.getvalue() and "--yes" in buf.getvalue()
