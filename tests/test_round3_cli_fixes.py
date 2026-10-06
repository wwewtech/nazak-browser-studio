"""Round-3 audit regression tests — CLI (agent-first) surface (R3-03, R3-04, R3-08, R3-12, R3-26).

Проверяют: маскирование секретов с `--reveal`, честный `account totp`, ошибки ввода
`@file`/`--out`, устойчивость парсера аккаунтов и точный матч профиля в `account login`.
"""

import asyncio
import contextlib
import json
import sys
from io import StringIO

import pytest

from nazak import cli
from nazak.core.account_provisioner import parse_account_string
from nazak.models.profile import BrowserProfile, GoogleSettings

TOTP_SECRET = "JBSWY3DPEHPK3PXP"
ACCOUNT_PASSWORD = "AccPass456!"


# --------------------------------------------------------------------------- CLI helpers
def run_cli(argv: list[str]) -> tuple[int, str, str]:
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
    code, out, _ = run_cli([*argv, "--json"])
    return code, json.loads(out)


@pytest.fixture()
def seeded_profile():
    """Профиль с паролем прокси и секретами аккаунта в режиме plain."""
    from nazak.config import PROFILES_DIR, PROFILES_FILE
    from nazak.core.profile_manager import ProfileManager
    from nazak.models.proxy import ProxyConfig, ProxyType

    pm = ProfileManager(PROFILES_FILE, PROFILES_DIR)
    payload = {
        "account_email": "farm.account@gmail.com",
        "account_password": ACCOUNT_PASSWORD,
        "totp_secret": TOTP_SECRET,
    }
    profile = BrowserProfile(
        id="r3_secrets",
        name="R3 Secrets",
        proxy=ProxyConfig(type=ProxyType.HTTP, host="1.2.3.4", port=8080, username="pxuser", password="pxSecret123"),
        google=GoogleSettings(notes=json.dumps(payload)),
    )
    try:
        pm.create_profile(profile)
    except ValueError:
        pass  # уже создан другим тестом в этой сессии
    # CLI держит ленивый singleton менеджеров (common._managers): после записи в
    # profiles.json его нужно сбросить, иначе кэш из ранее выполненного CLI-теста
    # «не увидит» этот профиль.
    import nazak.cli_cmds.common as cli_common

    cli_common._managers = None
    return "r3_secrets"


# --------------------------------------------------------------------------- R3-03 / R3-04
def test_r3_profile_get_masks_secrets_by_default(seeded_profile):
    code, payload = run_json(["profile", "get", seeded_profile])
    assert code == 0
    dumped = json.dumps(payload)
    assert "pxSecret123" not in dumped, "пароль прокси утёк в вывод без --reveal"
    assert ACCOUNT_PASSWORD not in dumped, "пароль аккаунта утёк в вывод без --reveal"
    assert TOTP_SECRET not in dumped, "TOTP-сид утёк в вывод без --reveal"
    assert payload["profile"]["proxy"]["password"] == "***"
    assert "secrets_hint" in payload["profile"]


def test_r3_profile_get_reveal_is_explicit(seeded_profile):
    code, payload = run_json(["--reveal", "profile", "get", seeded_profile])
    assert code == 0
    assert payload["profile"]["proxy"]["password"] == "pxSecret123"
    notes = json.loads(payload["profile"]["google"]["notes"])
    assert notes["account_password"] == ACCOUNT_PASSWORD
    assert "_totp_raw" not in notes, "служебный ключ попал в вывод"


def test_r3_account_totp_returns_real_code(seeded_profile):
    code, payload = run_json(["account", "totp", seeded_profile])
    assert code == 0 and payload["success"] is True
    assert payload["totp_code"] != "000000", "снова фиктивный код"
    assert len(payload["totp_code"]) == 6 and payload["totp_code"].isdigit()


def test_r3_account_totp_reports_failure_honestly():
    code, payload = run_json(["account", "totp", "prof_does_not_exist"])
    assert code == 1  # EXIT_NOT_FOUND
    assert payload["success"] is False


def test_r3_totp_generator_raises_on_garbage():
    from nazak.core.account_provisioner import generate_totp_rfc6238

    with pytest.raises(ValueError):
        generate_totp_rfc6238("JBS...PKXP")  # маска, а не base32


# --------------------------------------------------------------------------- R3-12/R3-26 input hardening
def test_r3_at_file_typo_is_an_error_not_data(tmp_path):
    code, payload = run_json(["proxy", "test", f"@{tmp_path / 'missing.txt'}"])
    assert code == 2  # EXIT_USAGE
    assert payload["success"] is False
    assert "не найден" in payload["error"]


def test_r3_out_refuses_silent_overwrite(tmp_path):
    target = tmp_path / "cookies_export.json"
    target.write_text("keep me", encoding="utf-8")
    code, payload = run_json(["cookie", "bulk-export", "--profiles", "all", "--out", str(target)])
    assert code == 2
    assert target.read_text(encoding="utf-8") == "keep me", "существующий файл перезаписан без --force"


def test_r3_account_parser_keeps_password_with_delimiter():
    parsed = parse_account_string(f"user_01@gmail.com:p@ss:w0rd:{TOTP_SECRET}")
    assert parsed is not None
    assert parsed["email"] == "user_01@gmail.com"
    assert parsed["password"] == "p@ss:w0rd"
    assert parsed["totp_secret"] == TOTP_SECRET


def test_r3_account_parser_rejects_delimiter_inside_email():
    # ";"-разделитель, внутри пароля ":" — email не должен «склеиваться» с паролем
    parsed = parse_account_string("user_02@gmail.com;pass:word;HXDMVJECJJWSRB3H")
    assert parsed is not None
    assert parsed["email"] == "user_02@gmail.com"
    assert parsed["password"] == "pass:word"


def test_r3_account_login_with_unknown_id_does_not_pick_another_profile(monkeypatch):
    """R3-08: промах по id не должен логинить «первый попавшийся» профиль."""
    import types

    # cli_auto_login_and_upload импортирует playwright на уровне модуля
    fake_pkg = types.ModuleType("playwright")
    fake_api = types.ModuleType("playwright.async_api")
    fake_api.async_playwright = lambda *a, **k: None
    fake_pkg.async_api = fake_api
    monkeypatch.setitem(sys.modules, "playwright", fake_pkg)
    monkeypatch.setitem(sys.modules, "playwright.async_api", fake_api)

    from nazak.cli_auto_login_and_upload import run_live_flow
    from nazak.config import PROFILES_DIR, PROFILES_FILE
    from nazak.core.profile_manager import ProfileManager

    pm = ProfileManager(PROFILES_FILE, PROFILES_DIR)
    pm.create_profile(
        BrowserProfile(
            id="r3_login_target",
            name="R3 Login Target",
            google=GoogleSettings(notes=json.dumps({"account_email": "real@example.com"})),
        )
    )
    monkeypatch.setenv("GOOGLE_EMAIL", "prof_that_does_not_exist")
    out = StringIO()
    with contextlib.redirect_stdout(out):
        ok = asyncio.run(run_live_flow())
    assert ok is False, "поток продолжился на чужом профиле"
    assert "не найден" in out.getvalue()
