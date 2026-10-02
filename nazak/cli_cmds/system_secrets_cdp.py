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
    payload = {"success": True, "chrome_installed": bool(chrome), "chrome_executable": chrome,
               "total_profiles": len(profiles), "running_profiles": running,
               "data_directory": str(PROFILES_DIR.resolve()), "extensions_directory": str(EXTENSIONS_DIR.resolve()),
               "platform": os.name}
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


def cmd_secrets_get(args, opt: GlobalOptions) -> int:
    if opt.server:
        return _via_server(opt, "GET", "/api/security/secrets-mode")
    from nazak.config import DATA_DIR
    from nazak.core.secrets_store import SECRETS_MODES, get_current_mode, load_mode, set_mode_file

    set_mode_file(DATA_DIR / "secrets_mode.json")
    load_mode()
    emit({"success": True, "mode": get_current_mode(), "available_modes": list(SECRETS_MODES),
          "platform": os.name,
          "notes": "plain=читаемо; dpapi=Windows; passphrase=Fernet+PBKDF2 (фраза нигде не хранится)"}, opt)
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
    emit({"success": True, "automation": {"port": port, "wsEndpoint": ws, "ws_endpoint": ws},
          "pid": pid, "profile_id": p.id,
          "hint": "Подключение: playwright connect_over_cdp(wsEndpoint)"}, opt)
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
            active.append({"profile_id": p.id, "name": p.name,
                           "pid": bl.profile_pids.get(p.id), "automation": cdp})
    if opt.as_json:
        emit({"success": True, "active_count": len(active), "profiles": active}, opt)
    else:
        t = Table(title=f"Active CDP ({len(active)})")
        for c in ("Profile", "Name", "PID", "Port", "wsEndpoint"):
            t.add_column(c)
        for a in active:
            auto = a["automation"] or {}
            t.add_row(a["profile_id"], a["name"], str(a["pid"] or "-"),
                      str(auto.get("port") or "-"), str(auto.get("ws_endpoint") or auto.get("wsEndpoint") or "-"))
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
