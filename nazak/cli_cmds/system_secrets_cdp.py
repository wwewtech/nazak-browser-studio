"""`nazak system/secrets/cdp ...` — паритет SettingsView + Dolphin API + system/info."""

from __future__ import annotations

import getpass
import os

from rich.table import Table

from .common import (
    EXIT_CONFLICT,
    EXIT_NOT_FOUND,
    EXIT_OK,
    GlobalOptions,
    console,
    emit,
    emit_error,
    emit_success,
    get_managers,
    server_request,
)


def register(sp) -> None:
    s = sp.add_parser("system", help="Система: диагностика хоста")
    ssub = s.add_subparsers(dest="system_action", required=True)
    x = ssub.add_parser("info", help="Хост, Chrome, счётчики (алиас корневого info)")
    x.set_defaults(func=cmd_system_info)
    x = ssub.add_parser("doctor", help="Самопроверка окружения для агентов: Chrome/FFmpeg/данные/сервер")
    x.set_defaults(func=cmd_system_doctor)
    x = ssub.add_parser("schema", help="Машиночитаемая схема всех команд (для function-calling агентов)")
    x.set_defaults(func=cmd_system_schema)
    x = ssub.add_parser("version", help="Версии CLI/пакета/Python/платформы")
    x.set_defaults(func=cmd_system_version)

    s = sp.add_parser("secrets", help="Secrets storage: plain/dpapi/passphrase (выбор пользователя)")
    ssub = s.add_subparsers(dest="secrets_action", required=True)
    x = ssub.add_parser("get", help="Текущий режим хранения секретов")
    x.set_defaults(func=cmd_secrets_get)
    x = ssub.add_parser("set", help="Сменить режим (с перешифровкой)")
    x.add_argument("--mode", required=True, choices=["plain", "dpapi", "passphrase"])
    x.add_argument("--passphrase", default=None, help="Или env NAZAK_PASSPHRASE / --passphrase-stdin")
    x.add_argument("--passphrase-stdin", action="store_true", help="Читать passphrase из stdin")
    x.set_defaults(func=cmd_secrets_set)

    c = sp.add_parser("cdp", help="CDP/Dolphin-паритет: start/stop/active/info")
    csub = c.add_subparsers(dest="cdp_action", required=True)
    x = csub.add_parser("start", help="Старт профиля + CDP wsEndpoint")
    x.add_argument("profile_id")
    x.add_argument("--url", default=None)
    x.add_argument("--port", type=int, default=None)
    x.set_defaults(func=cmd_cdp_start)
    x = csub.add_parser("stop", help="Стоп профиля")
    x.add_argument("profile_id")
    x.set_defaults(func=cmd_cdp_stop)
    x = csub.add_parser("active", help="Активные браузеры с CDP")
    x.set_defaults(func=cmd_cdp_active)
    x = csub.add_parser("info", help="CDP info профиля (port + wsEndpoint)")
    x.add_argument("profile_id")
    x.set_defaults(func=cmd_cdp_info)


def _via_server(opt: GlobalOptions, method: str, path: str, **kw):
    emit(server_request(opt, method, path, **kw), opt)
    return EXIT_OK


def cmd_system_info(args, opt: GlobalOptions) -> int:
    if opt.server:
        return _via_server(opt, "GET", "/api/system/info")
    from nazak.config import EXTENSIONS_DIR, PROFILES_DIR, find_chrome_executable

    pm, bl = get_managers()
    chrome = find_chrome_executable()
    profiles = pm.list_profiles()
    running = sum(1 for p in profiles if bl.is_profile_running(p.id))
    payload = {
        "success": True,
        "chrome_installed": bool(chrome),
        "chrome_executable": chrome,
        "total_profiles": len(profiles),
        "running_profiles": running,
        "data_directory": str(PROFILES_DIR.resolve()),
        "extensions_directory": str(EXTENSIONS_DIR.resolve()),
        "platform": os.name,
    }
    if opt.as_json:
        emit(payload, opt)
    else:
        t = Table(title="System")
        t.add_column("Key")
        t.add_column("Value")
        for k, v in payload.items():
            if k == "success":
                continue
            t.add_row(k, str(v))
        console.print(t)
    return EXIT_OK


def cmd_system_doctor(args, opt: GlobalOptions) -> int:
    """Preflight для агентов: первый шаг перед любой серией команд."""
    import sys as _sys

    from nazak.config import PROFILES_DIR, PROFILES_FILE

    checks: list[dict] = []

    def _add(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    _add("data_dir", PROFILES_DIR.exists() and os.access(PROFILES_DIR, os.W_OK), str(PROFILES_DIR))
    try:
        pm, _bl = get_managers()
        n = len(pm.list_profiles())
        _add("profiles_db", True, f"{n} профилей в {PROFILES_FILE.name}")
    except Exception as exc:
        _add("profiles_db", False, str(exc)[:160])

    from nazak.config import find_chrome_executable

    chrome = find_chrome_executable()
    _add("chrome", bool(chrome), chrome or "не найден: launch/cdp/account login невозможны")

    from nazak.core.video_uniquifier import find_ffmpeg

    ffmpeg = find_ffmpeg()
    _add("ffmpeg", bool(ffmpeg), ffmpeg or "не найден: autopost uniquify/launch --demo невозможны")

    from nazak.core.secrets_store import get_current_mode

    try:
        _add("secrets_mode", True, get_current_mode())
    except Exception as exc:
        _add("secrets_mode", False, str(exc)[:160])

    _add("python", True, _sys.version.split()[0])
    if opt.server:
        try:
            server_request(opt, "GET", "/api/system/info")
            _add("api_server", True, opt.server)
        except Exception as exc:
            _add("api_server", False, str(exc)[:160])
    else:
        _add("api_server", True, "direct-core режим (сервер не требуется)")

    overall = all(c["ok"] for c in checks if c["name"] not in ("api_server",))
    payload = {
        "success": True,
        "overall_ok": overall,
        "checks": checks,
        "hint": "Если overall_ok=false — чините красные пункты; launch/upload без chrome не взлетят",
    }
    if opt.as_json:
        emit(payload, opt)
    else:
        t = Table(title="Doctor")
        t.add_column("Check")
        t.add_column("OK")
        t.add_column("Detail")
        for c in checks:
            t.add_row(c["name"], "OK" if c["ok"] else "FAIL", c["detail"])
        console.print(t)
    return EXIT_OK if overall else EXIT_CONFLICT


def cmd_system_version(args, opt: GlobalOptions) -> int:
    import platform as _platform
    import sys as _sys

    try:
        from nazak import __version__
    except Exception:
        __version__ = "unknown"
    emit(
        {
            "success": True,
            "nazak": __version__,
            "python": _sys.version.split()[0],
            "platform": _platform.platform(),
            "exe": getattr(_sys, "frozen", False),
        },
        opt,
    )
    return EXIT_OK


def cmd_system_schema(args, opt: GlobalOptions) -> int:
    """Интроспекция argparse-парсера: точная схема всех групп/команд/аргументов."""
    import argparse as _argparse

    from nazak.cli import build_parser

    parser = build_parser()
    merged: dict[str, dict] = {}
    for action in parser._actions:
        if not isinstance(action, _argparse._SubParsersAction):
            continue
        top_helps = {a.dest: a.help or "" for a in getattr(action, "_choices_actions", [])}
        for top_name, top_sub in action.choices.items():
            nested = [a for a in top_sub._actions if isinstance(a, _argparse._SubParsersAction)]
            if nested:
                commands: list[dict] = []
                for sub_act in nested:
                    cmd_helps = {a.dest: a.help or "" for a in getattr(sub_act, "_choices_actions", [])}
                    for cmd_name, cmd_sub in sub_act.choices.items():
                        commands.append(
                            {
                                "name": cmd_name,
                                "help": cmd_sub.description or cmd_helps.get(cmd_name, ""),
                                "args": _schema_args(cmd_sub),
                            }
                        )
                merged[top_name] = {
                    "group": top_name,
                    "help": top_sub.description or top_helps.get(top_name, ""),
                    "commands": commands,
                }
            else:
                legacy = merged.setdefault(
                    "legacy", {"group": "legacy", "help": "Backward-compat корневые команды", "commands": []}
                )
                legacy["commands"].append(
                    {
                        "name": top_name,
                        "help": top_sub.description or top_helps.get(top_name, ""),
                        "args": _schema_args(top_sub),
                    }
                )
    emit(
        {
            "success": True,
            "schema_version": 1,
            "global_flags": ["--json", "--yes", "--server", "--api-key", "--verbose"],
            "env": ["NAZAK_JSON", "NAZAK_YES", "NAZAK_SERVER", "NAZAK_API_TOKEN", "NAZAK_PASSPHRASE"],
            "exit_codes": {"0": "ok", "1": "not found", "2": "usage/validation", "4": "conflict/busy"},
            "groups": list(merged.values()),
        },
        opt,
    )
    return EXIT_OK


def _schema_args(subparser) -> list[dict]:
    out: list[dict] = []
    for a in subparser._actions:
        if a.dest in ("help",):
            continue
        flags = list(a.option_strings) or [a.dest]
        entry: dict = {
            "flags": flags,
            "dest": a.dest,
            "required": bool(getattr(a, "required", False)),
            "help": a.help or "",
        }
        if getattr(a, "choices", None):
            try:
                entry["choices"] = sorted(str(c) for c in a.choices)
            except Exception:
                entry["choices"] = [str(c) for c in a.choices]
        default = getattr(a, "default", None)
        if default not in (None, "==SUPPRESS=="):
            entry["default"] = default
        out.append(entry)
    return out


def cmd_secrets_get(args, opt: GlobalOptions) -> int:
    if opt.server:
        return _via_server(opt, "GET", "/api/security/secrets-mode")
    from nazak.config import DATA_DIR
    from nazak.core.secrets_store import SECRETS_MODES, get_current_mode, load_mode, set_mode_file

    set_mode_file(DATA_DIR / "secrets_mode.json")
    load_mode()
    emit(
        {
            "success": True,
            "mode": get_current_mode(),
            "available_modes": list(SECRETS_MODES),
            "platform": os.name,
            "notes": "plain=читаемо; dpapi=Windows; passphrase=Fernet+PBKDF2 (фраза нигде не хранится)",
        },
        opt,
    )
    return EXIT_OK


def cmd_secrets_set(args, opt: GlobalOptions) -> int:
    passphrase = args.passphrase or os.environ.get("NAZAK_PASSPHRASE")
    if args.passphrase_stdin and not passphrase:
        passphrase = getpass.getpass("Passphrase: ")
    if opt.server:
        body: dict = {"mode": args.mode}
        if passphrase:
            body["passphrase"] = passphrase
        return _via_server(opt, "POST", "/api/security/secrets-mode", json=body)
    from nazak.config import DATA_DIR, PROFILES_DIR, PROFILES_FILE
    from nazak.core.profile_manager import ProfileManager
    from nazak.core.secrets_store import SecretsError, load_mode, set_current_mode, set_mode_file

    set_mode_file(DATA_DIR / "secrets_mode.json")
    load_mode()
    try:
        effective = set_current_mode(args.mode, passphrase=passphrase)
    except SecretsError as e:
        return emit_error(str(e), opt)
    try:
        ProfileManager(PROFILES_FILE, PROFILES_DIR).reencrypt_all_profile_secrets()
    except Exception as e:
        return emit_error(f"Режим '{effective}' включён, но перешифровка упала: {e}", opt, EXIT_CONFLICT)
    return emit_success(f"Secrets mode: {effective} (перешифровано)", opt, {"mode": effective})


def cmd_cdp_start(args, opt: GlobalOptions) -> int:
    if opt.server:
        params = ""
        if args.url:
            params += f"?custom_url={args.url}"
            if args.port:
                params += f"&port={args.port}"
        elif args.port:
            params += f"?port={args.port}"
        return _via_server(opt, "GET", f"/v1.0/browser_profiles/{args.profile_id}/start{params}")
    from nazak.models.profile import ProfileStatus

    pm, bl = get_managers()
    p = pm.get_profile(args.profile_id)
    if not p:
        return emit_error("Профиль не найден", opt, EXIT_NOT_FOUND)
    ok, pid, port, ws, err = bl.launch_with_cdp(p, custom_url=args.url, port=args.port)
    if not ok:
        return emit_error(err or "CDP start failed", opt, EXIT_CONFLICT)
    p.status, p.pid = ProfileStatus.RUNNING, pid
    pm.update_profile(p)
    emit(
        {
            "success": True,
            "automation": {"port": port, "wsEndpoint": ws, "ws_endpoint": ws},
            "pid": pid,
            "profile_id": p.id,
            "hint": "Подключение: playwright connect_over_cdp(wsEndpoint)",
        },
        opt,
    )
    return EXIT_OK


def cmd_cdp_stop(args, opt: GlobalOptions) -> int:
    if opt.server:
        return _via_server(opt, "GET", f"/v1.0/browser_profiles/{args.profile_id}/stop")
    from nazak.models.profile import ProfileStatus

    pm, bl = get_managers()
    p = pm.get_profile(args.profile_id)
    if not p:
        return emit_error("Профиль не найден", opt, EXIT_NOT_FOUND)
    bl.stop(args.profile_id)
    p.status, p.pid = ProfileStatus.STOPPED, None
    pm.update_profile(p)
    return emit_success(f"CDP остановлен: {p.id}", opt)


def cmd_cdp_active(args, opt: GlobalOptions) -> int:
    if opt.server:
        return _via_server(opt, "GET", "/v1.0/browser_profiles/active")
    pm, bl = get_managers()
    active = []
    for p in pm.list_profiles():
        if bl.is_profile_running(p.id):
            cdp = bl.get_cdp_info(p.id)
            active.append({"profile_id": p.id, "name": p.name, "pid": bl.profile_pids.get(p.id), "automation": cdp})
    if opt.as_json:
        emit({"success": True, "active_count": len(active), "profiles": active}, opt)
    else:
        t = Table(title=f"Active CDP ({len(active)})")
        for c in ("Profile", "Name", "PID", "Port", "wsEndpoint"):
            t.add_column(c)
        for a in active:
            auto = a["automation"] or {}
            t.add_row(
                a["profile_id"],
                a["name"],
                str(a["pid"] or "-"),
                str(auto.get("port") or "-"),
                str(auto.get("ws_endpoint") or auto.get("wsEndpoint") or "-"),
            )
        console.print(t)
    return EXIT_OK


def cmd_cdp_info(args, opt: GlobalOptions) -> int:
    if opt.server:
        return _via_server(opt, "GET", f"/api/v1/profiles/{args.profile_id}/cdp")
    _, bl = get_managers()
    cdp = bl.get_cdp_info(args.profile_id)
    if not cdp:
        return emit_error("Профиль не запущен или CDP неактивен", opt, EXIT_NOT_FOUND)
    emit({"success": True, "cdp": cdp}, opt)
    return EXIT_OK
