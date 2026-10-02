"""`nazak profile ...` — полный CRUD + ферма (паритет ProfilesView + MassGenerateDialog + ProfileEditDialog)."""

from __future__ import annotations

import argparse
from pathlib import Path

from rich.table import Table

from .common import (
    EXIT_CONFLICT,
    EXIT_NOT_FOUND,
    EXIT_OK,
    EXIT_USAGE,
    GlobalOptions,
    confirm,
    console,
    emit,
    emit_error,
    emit_success,
    get_managers,
    parse_ids,
    read_input_text,
    resolve_ids,
    server_request,
)


def register(sp) -> None:
    p = sp.add_parser("profile", help="Профили: CRUD, запуск, ферма, бандлы")
    sub = p.add_subparsers(dest="profile_action", required=True)

    s = sub.add_parser("list", help="Список профилей (алиас корневого list)")
    s.add_argument("--group", default=None, help="Фильтр по группе")
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("get", help="Карточка профиля")
    s.add_argument("profile_id", help="ID профиля")
    s.set_defaults(func=cmd_get)

    s = sub.add_parser("create", help="Создать изолированный профиль")
    s.add_argument("--name", required=True, help="Имя профиля")
    s.add_argument("--group", default="Manual", help="Группа")
    s.add_argument("--proxy", default="direct", help="host:port:user:pass | socks5://... | direct; @file тоже")
    s.add_argument("--os", default="windows", choices=["windows", "mac", "linux"], help="ОС фингерпринта")
    s.add_argument("--target-page", default="google_login", help="Стартовая страница")
    s.add_argument("--tags", default=None, help="Теги через запятую")
    s.set_defaults(func=cmd_create)

    s = sub.add_parser("update", help="Обновить имя/группу/прокси профиля")
    s.add_argument("profile_id", help="ID профиля")
    s.add_argument("--name", default=None)
    s.add_argument("--group", default=None)
    s.add_argument("--proxy", default=None, help="Новая proxy-строка (без значения = не менять)")
    s.set_defaults(func=cmd_update)

    s = sub.add_parser("delete", help="Удалить профиль и данные")
    s.add_argument("profile_id", help="ID профиля")
    s.set_defaults(func=cmd_delete)

    s = sub.add_parser("clone", help="Клонировать с новым fingerprint")
    s.add_argument("profile_id", help="ID исходника")
    s.add_argument("--new-name", default=None, help="Имя клона")
    s.set_defaults(func=cmd_clone)

    s = sub.add_parser("launch", help="Запустить браузер (можно --url, --cdp-port)")
    s.add_argument("profile_id", help="ID профиля")
    s.add_argument("--url", default=None, help="Стартовый URL (http/https/about)")
    s.add_argument("--cdp-port", type=int, default=None, help="Фиксированный CDP-порт")
    s.set_defaults(func=cmd_launch)

    s = sub.add_parser("stop", help="Остановить профиль")
    s.add_argument("profile_id", help="ID профиля")
    s.set_defaults(func=cmd_stop)

    s = sub.add_parser("batch-launch", help="Запустить несколько: --profiles id1,id2 | --all")
    s.add_argument("--profiles", default="", help="CSV или all")
    s.add_argument("--all", action="store_true", help="Все профили")
    s.set_defaults(func=cmd_batch_launch)

    s = sub.add_parser("batch-stop", help="Остановить несколько")
    s.add_argument("--profiles", default="", help="CSV или all")
    s.add_argument("--all", action="store_true")
    s.set_defaults(func=cmd_batch_stop)

    s = sub.add_parser("bulk-import", help="Массовый импорт из proxy-строк (файл/stdin)")
    s.add_argument("--group", default="Google Ads")
    s.add_argument("--target-page", default="google_login")
    s.add_argument("--file", default=None, help="Файл со строками прокси")
    s.add_argument("--stdin", action="store_true", help="Читать stdin")
    s.add_argument("lines", nargs="?", default=None, help="Строки или @file")
    s.set_defaults(func=cmd_bulk_import)

    s = sub.add_parser("mass-generate", help="Ферма 1-100+ профилей (паритет MassGenerateDialog)")
    s.add_argument("--count", type=int, default=10, help="1..200")
    s.add_argument("--group", default="Mass Farm")
    s.add_argument("--os-mix", default="windows", choices=["windows", "mac", "linux", "all"])
    s.add_argument("--target-page", default="google_login")
    s.add_argument("--tags", default=None, help="CSV теги")
    s.add_argument("--file", default=None, help="Файл с прокси (round-robin)")
    s.add_argument("--notes", default=None)
    s.set_defaults(func=cmd_mass_generate)

    s = sub.add_parser("fingerprint", help="Сгенерировать случайный fingerprint JSON")
    s.add_argument("--os", default="windows", choices=["windows", "mac", "linux"])
    s.set_defaults(func=cmd_fingerprint)

    s = sub.add_parser("clear-cache", help="Очистить кэш (только остановленный)")
    s.add_argument("profile_id")
    s.set_defaults(func=cmd_clear_cache)

    s = sub.add_parser("seed-history", help="Органичный history-seeder (анти empty-profile)")
    s.add_argument("profile_id")
    s.add_argument("--count", type=int, default=25, help="5..100")
    s.set_defaults(func=cmd_seed_history)

    s = sub.add_parser("bundle-export", help="Экспорт .nazak бандла")
    s.add_argument("profile_id")
    s.add_argument("--out", default=None, help="Путь сохранения")
    s.set_defaults(func=cmd_bundle_export)

    s = sub.add_parser("bundle-import", help="Импорт .nazak бандла")
    s.add_argument("bundle", help="Путь к .nazak/.zip")
    s.add_argument("--new-name", default=None)
    s.set_defaults(func=cmd_bundle_import)


# --- helpers ---

def _profile_row(p, running: bool) -> dict:
    proxy = p.proxy.to_display_string() if hasattr(p.proxy, "to_display_string") else str(p.proxy)
    hc = p.last_health_check
    return {
        "id": p.id,
        "name": p.name,
        "group": p.group,
        "status": "running" if running else "stopped",
        "proxy": proxy,
        "ping_ms": (hc.ping_ms if hc and hc.ping_ms else None),
        "google_ok": bool(hc and hc.google and hc.google.all_ok),
    }


def _via_server(opt: GlobalOptions, method: str, path: str, **kw):
    data = server_request(opt, method, path, **kw)
    emit(data, opt)
    return EXIT_OK


# --- commands ---

def cmd_list(args, opt: GlobalOptions) -> int:
    if opt.server:
        return _via_server(opt, "GET", "/api/profiles")
    pm, bl = get_managers()
    rows = [_profile_row(p, bl.is_profile_running(p.id)) for p in pm.list_profiles()]
    if args.group:
        rows = [r for r in rows if pm.get_profile(r["id"]) and pm.get_profile(r["id"]).group == args.group]
    if opt.as_json:
        emit({"success": True, "count": len(rows), "profiles": rows}, opt)
    else:
        t = Table(title=f"Profiles ({len(rows)})")
        for c in ("ID", "Name", "Group", "Status", "Proxy", "Ping", "Google"):
            t.add_column(c)
        for r in rows:
            t.add_row(r["id"], r["name"], r["group"], r["status"], r["proxy"],
                      f"{r['ping_ms']} ms" if r["ping_ms"] else "-",
                      "OK" if r["google_ok"] else "-")
        console.print(t)
    return EXIT_OK


def cmd_get(args, opt: GlobalOptions) -> int:
    if opt.server:
        return _via_server(opt, "GET", f"/api/profiles/{args.profile_id}")
    pm, bl = get_managers()
    p = pm.get_profile(args.profile_id)
    if not p:
        return emit_error(f"Профиль '{args.profile_id}' не найден", opt, EXIT_NOT_FOUND)
    d = p.model_dump()
    d["live_running"] = bl.is_profile_running(p.id)
    cdp = bl.get_cdp_info(p.id) if d["live_running"] else None
    if cdp:
        d["cdp"] = cdp
    emit({"success": True, "profile": d}, opt)
    return EXIT_OK


def cmd_create(args, opt: GlobalOptions) -> int:
    if opt.server:
        from nazak.models.profile import BrowserProfile

        payload = {"name": args.name, "group": args.group}
        return _via_server(opt, "POST", "/api/profiles", json=payload)
    from nazak.core.fingerprint_generator import generate_random_fingerprint
    from nazak.models.profile import BrowserProfile, GoogleSettings
    from nazak.models.proxy import ProxyConfig

    pm, _ = get_managers()
    proxy_raw = read_input_text(args.proxy) or args.proxy
    fp = generate_random_fingerprint(os_type=args.os)
    tags = [t.strip() for t in (args.tags or "").split(",") if t.strip()]
    prof = BrowserProfile(name=args.name, group=args.group,
                          proxy=ProxyConfig.parse(proxy_raw),
                          fingerprint=fp,
                          google=GoogleSettings(auto_open_page=args.target_page, tags=tags))
    saved = pm.create_profile(prof)
    return emit_success(f"Профиль создан: {saved.id} ({saved.name})", opt, {"profile_id": saved.id})


def cmd_update(args, opt: GlobalOptions) -> int:
    if opt.server:
        pm, _ = get_managers()  # fetch current for merge via API PUT needs full object; use GET first
        cur = server_request(opt, "GET", f"/api/profiles/{args.profile_id}")
        if isinstance(cur, dict) and cur.get("detail"):
            return emit_error(str(cur.get("detail")), opt, EXIT_NOT_FOUND)
        if args.name:
            cur["name"] = args.name
        if args.group:
            cur["group"] = args.group
        return _via_server(opt, "PUT", f"/api/profiles/{args.profile_id}", json=cur)
    from nazak.models.proxy import ProxyConfig

    pm, _ = get_managers()
    p = pm.get_profile(args.profile_id)
    if not p:
        return emit_error(f"Профиль '{args.profile_id}' не найден", opt, EXIT_NOT_FOUND)
    if args.name:
        p.name = args.name
    if args.group:
        p.group = args.group
    if args.proxy:
        p.proxy = ProxyConfig.parse(read_input_text(args.proxy) or args.proxy)
    updated = pm.update_profile(p)
    if not updated:
        return emit_error("Не удалось обновить профиль", opt, EXIT_USAGE)
    return emit_success(f"Профиль обновлён: {p.id}", opt, {"profile_id": p.id})


def cmd_delete(args, opt: GlobalOptions) -> int:
    if opt.server:
        return _via_server(opt, "DELETE", f"/api/profiles/{args.profile_id}")
    pm, bl = get_managers()
    p = pm.get_profile(args.profile_id)
    if not p:
        return emit_error(f"Профиль '{args.profile_id}' не найден", opt, EXIT_NOT_FOUND)
    if not confirm(f"Удалить профиль '{p.name}' ({p.id}) с данными?", opt):
        if opt.as_json:
            emit({"success": False, "cancelled": True}, opt)
        else:
            console.print("[yellow]Отменено[/yellow]")
        return EXIT_OK
    if bl.is_profile_running(args.profile_id):
        bl.stop(args.profile_id)
    ok = pm.delete_profile(args.profile_id, delete_data=True)
    if not ok:
        return emit_error("Не удалось удалить", opt, EXIT_USAGE)
    return emit_success(f"Профиль удалён: {args.profile_id}", opt)


def cmd_clone(args, opt: GlobalOptions) -> int:
    if opt.server:
        q = f"?new_name={args.new_name}" if args.new_name else ""
        return _via_server(opt, "POST", f"/api/profiles/{args.profile_id}/clone{q}")
    pm, _ = get_managers()
    cloned = pm.clone_profile(args.profile_id, args.new_name)
    if not cloned:
        return emit_error("Исходник не найден", opt, EXIT_NOT_FOUND)
    return emit_success(f"Клон создан: {cloned.id}", opt, {"profile_id": cloned.id})


def cmd_launch(args, opt: GlobalOptions) -> int:
    if opt.server:
        body: dict = {}
        if args.url:
            body["custom_url"] = args.url
        if args.cdp_port:
            body["cdp_port"] = args.cdp_port
        return _via_server(opt, "POST", f"/api/profiles/{args.profile_id}/launch", json=body)
    from nazak.models.profile import ProfileStatus

    pm, bl = get_managers()
    p = pm.get_profile(args.profile_id)
    if not p:
        return emit_error(f"Профиль '{args.profile_id}' не найден", opt, EXIT_NOT_FOUND)
    if args.cdp_port:
        ok, pid, port, ws, err = bl.launch_with_cdp(p, custom_url=args.url, port=args.cdp_port)
        if not ok:
            return emit_error(err or "Launch failed", opt, EXIT_CONFLICT)
        p.status, p.pid = ProfileStatus.RUNNING, pid
        pm.update_profile(p)
        return emit_success(f"Запущен {p.id} pid={pid}", opt, {"pid": pid, "port": port, "wsEndpoint": ws})
    ok, pid, err = bl.launch(p, custom_url=args.url)
    if not ok:
        return emit_error(err or "Launch failed", opt, EXIT_CONFLICT)
    p.status, p.pid = ProfileStatus.RUNNING, pid
    pm.update_profile(p)
    return emit_success(f"Запущен {p.id} pid={pid}", opt, {"pid": pid})


def cmd_stop(args, opt: GlobalOptions) -> int:
    if opt.server:
        return _via_server(opt, "POST", f"/api/profiles/{args.profile_id}/stop")
    from nazak.models.profile import ProfileStatus

    pm, bl = get_managers()
    p = pm.get_profile(args.profile_id)
    if not p:
        return emit_error(f"Профиль '{args.profile_id}' не найден", opt, EXIT_NOT_FOUND)
    bl.stop(args.profile_id)
    p.status, p.pid = ProfileStatus.STOPPED, None
    pm.update_profile(p)
    return emit_success(f"Остановлен {p.name}", opt)


def cmd_batch_launch(args, opt: GlobalOptions) -> int:
    ids = resolve_ids(parse_ids(args.profiles), allow_all=args.all)
    if not ids:
        return emit_error("Укажите --profiles id1,id2 или --all", opt)
    if opt.server:
        return _via_server(opt, "POST", "/api/profiles/batch-launch", json={"profile_ids": ids})
    from nazak.models.profile import ProfileStatus

    pm, bl = get_managers()
    results: dict = {}
    for pid in ids:
        prof = pm.get_profile(pid)
        if not prof:
            results[pid] = {"success": False, "error": "not found"}
            continue
        ok, p_id, err = bl.launch(prof)
        if ok:
            prof.status, prof.pid = ProfileStatus.RUNNING, p_id
            pm.update_profile(prof)
            results[pid] = {"success": True, "pid": p_id}
        else:
            results[pid] = {"success": False, "error": err}
    emit({"success": True, "results": results}, opt)
    return EXIT_OK


def cmd_batch_stop(args, opt: GlobalOptions) -> int:
    ids = resolve_ids(parse_ids(args.profiles), allow_all=args.all)
    if not ids:
        return emit_error("Укажите --profiles id1,id2 или --all", opt)
    if opt.server:
        return _via_server(opt, "POST", "/api/profiles/batch-stop", json={"profile_ids": ids})
    from nazak.models.profile import ProfileStatus

    pm, bl = get_managers()
    for pid in ids:
        bl.stop(pid)
        prof = pm.get_profile(pid)
        if prof:
            prof.status, prof.pid = ProfileStatus.STOPPED, None
            pm.update_profile(prof)
    return emit_success(f"Остановлено: {len(ids)}", opt, {"stopped_count": len(ids)})


def cmd_bulk_import(args, opt: GlobalOptions) -> int:
    text = read_input_text(args.lines, file=args.file, stdin_flag=args.stdin)
    if not text.strip():
        return emit_error("Нет proxy-строк: передайте аргумент, --file или stdin", opt)
    if opt.server:
        return _via_server(opt, "POST", "/api/profiles/bulk-import",
                            json={"proxy_lines": text, "group": args.group, "target_page": args.target_page})
    from nazak.core.fingerprint_generator import generate_random_fingerprint
    from nazak.models.profile import BrowserProfile, GoogleSettings
    from nazak.models.proxy import ProxyConfig

    pm, _ = get_managers()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    created = 0
    for idx, line in enumerate(lines, start=len(pm.list_profiles()) + 1):
        proxy = ProxyConfig.parse(line)
        fp = generate_random_fingerprint(os_type="windows")
        prof = BrowserProfile(name=f"Profile {idx:02d} ({proxy.host or 'Direct'})",
                              group=args.group, proxy=proxy, fingerprint=fp,
                              google=GoogleSettings(auto_open_page=args.target_page,
                                                    tags=["Bulk Import", args.group]))
        pm.create_profile(prof)
        created += 1
    return emit_success(f"Импортировано профилей: {created}", opt, {"created_count": created})


def cmd_mass_generate(args, opt: GlobalOptions) -> int:
    if not 1 <= args.count <= 200:
        return emit_error("count должен быть 1..200", opt)
    proxy_text = read_input_text(file=args.file) if args.file else ""
    proxy_lines = [line for line in proxy_text.splitlines() if line.strip()] if proxy_text else None
    tags = [t.strip() for t in (args.tags or "").split(",") if t.strip()] or None
    if opt.server:
        return _via_server(opt, "POST", "/api/profiles/mass-generate",
                            json={"count": args.count, "group": args.group, "proxy_lines": proxy_text or None,
                                  "os_mix": args.os_mix, "tags": tags, "target_page": args.target_page,
                                  "notes": args.notes})
    pm, _ = get_managers()
    created = pm.mass_generate_profiles(count=args.count, group=args.group,
                                        proxy_list=proxy_lines, os_mix=args.os_mix,
                                        tags=tags, auto_open_page=args.target_page, notes=args.notes)
    ids = [p.id for p in created]
    return emit_success(f"Сгенерировано: {len(ids)}", opt, {"created_count": len(ids), "profile_ids": ids})


def cmd_fingerprint(args, opt: GlobalOptions) -> int:
    if opt.server:
        return _via_server(opt, "POST", f"/api/profiles/randomize-fingerprint?os_type={args.os}")
    from nazak.core.fingerprint_generator import generate_random_fingerprint

    fp = generate_random_fingerprint(os_type=args.os)
    emit({"success": True, "fingerprint": fp.model_dump()}, opt)
    return EXIT_OK


def cmd_clear_cache(args, opt: GlobalOptions) -> int:
    if opt.server:
        return _via_server(opt, "POST", f"/api/profiles/{args.profile_id}/clear-cache")
    pm, bl = get_managers()
    if bl.is_profile_running(args.profile_id):
        return emit_error("Сначала остановите браузер (profile stop)", opt, EXIT_CONFLICT)
    ok = pm.clear_profile_cache(args.profile_id)
    if not ok:
        return emit_error("Профиль не найден", opt, EXIT_NOT_FOUND)
    return emit_success("Кэш очищен", opt)


def cmd_seed_history(args, opt: GlobalOptions) -> int:
    if not 5 <= args.count <= 100:
        return emit_error("count должен быть 5..100", opt)
    if opt.server:
        return _via_server(opt, "POST", f"/api/profiles/{args.profile_id}/seed-history?entries_count={args.count}")
    pm, _ = get_managers()
    if not pm.get_profile(args.profile_id):
        return emit_error("Профиль не найден", opt, EXIT_NOT_FOUND)
    n = pm.seed_profile_history(args.profile_id, entries_count=args.count)
    return emit_success(f"Seeded записей: {n}", opt, {"seeded_entries": n})


def cmd_bundle_export(args, opt: GlobalOptions) -> int:
    if opt.server:
        emit({"success": True, "hint": "В server-режиме скачайте GET /api/profiles/{id}/bundle/export через curl/браузер"}, opt)
        return _via_server(opt, "GET", f"/api/profiles/{args.profile_id}/bundle/export")
    pm, _ = get_managers()
    out = Path(args.out) if args.out else None
    path = pm.export_profile_bundle(args.profile_id, output_path=out)
    if not path:
        return emit_error("Не удалось создать бандл (профиль не найден?)", opt, EXIT_NOT_FOUND)
    return emit_success(f"Бандл: {path}", opt, {"path": str(path)})


def cmd_bundle_import(args, opt: GlobalOptions) -> int:
    if opt.server:
        return emit_error("bundle-import поддерживается только в direct-режиме (без --server)", opt)
    from pathlib import Path as P

    pm, _ = get_managers()
    bundle = P(args.bundle)
    if not bundle.exists():
        return emit_error(f"Файл не найден: {args.bundle}", opt, EXIT_NOT_FOUND)
    prof = pm.import_profile_bundle(bundle, new_name=args.new_name)
    if not prof:
        return emit_error("Не удалось импортировать (битый архив?)", opt, EXIT_USAGE)
    return emit_success(f"Импортирован: {prof.id}", opt, {"profile_id": prof.id})


def add_legacy_parsers(sp: argparse.ArgumentParser) -> None:
    """Ничего не делает здесь; legacy обрабатывается в cli.py."""
