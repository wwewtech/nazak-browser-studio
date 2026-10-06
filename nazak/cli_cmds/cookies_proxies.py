"""`nazak cookie ...` и `nazak proxy ...` — паритет ProxiesView + BatchCookieDialog/CookieManagerDialog."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from .common import (
    EXIT_CONFLICT,
    EXIT_NOT_FOUND,
    EXIT_OK,
    GlobalOptions,
    UsageError,
    console,
    emit,
    emit_error,
    emit_success,
    get_managers,
    parse_ids,
    read_input_text,
    resolve_ids,
    resolve_out_path,
    server_request,
)


def register(sp) -> None:
    c = sp.add_parser("cookie", help="Cookies: импорт/экспорт, bulk, Netscape/ZIP")
    csub = c.add_subparsers(dest="cookie_action", required=True)

    s = csub.add_parser("import", help="Импорт cookies в профиль (JSON/Netscape, файл/stdin)")
    s.add_argument("profile_id")
    s.add_argument("--file", default=None)
    s.add_argument("--stdin", action="store_true")
    s.add_argument("data", nargs="?", default=None, help="Текст cookies или @file")
    s.set_defaults(func=cmd_cookie_import)

    s = csub.add_parser("export", help="Экспорт cookies профиля")
    s.add_argument("profile_id")
    s.add_argument("--format", default="json", choices=["json", "netscape"])
    s.add_argument("--out", default=None, help="Сохранить в файл")
    s.add_argument("--force", action="store_true", help="Перезаписать существующий --out")
    s.set_defaults(func=cmd_cookie_export)

    s = csub.add_parser("bulk-import", help="Мультипрофильный импорт (делимитеры ===/JSON-map/ZIP-папка)")
    s.add_argument("--group", default="Imported Cookies")
    s.add_argument("--no-autocreate", action="store_true", help="Не создавать недостающие профили")
    s.add_argument("--file", default=None)
    s.add_argument("--stdin", action="store_true")
    s.add_argument("data", nargs="?", default=None)
    s.set_defaults(func=cmd_cookie_bulk_import)

    s = csub.add_parser("bulk-export", help="Экспорт cookies нескольких профилей (json/zip)")
    s.add_argument("--profiles", default="", help="CSV или all")
    s.add_argument("--all", action="store_true")
    s.add_argument("--format", default="json", choices=["json", "zip"])
    s.add_argument("--out", default=None, help="Файл для zip/json")
    s.add_argument("--force", action="store_true", help="Перезаписать существующий --out")
    s.set_defaults(func=cmd_cookie_bulk_export)

    px = sp.add_parser("proxy", help="Прокси: проверки, тест строки, ротация IP")
    pxsub = px.add_subparsers(dest="proxy_action", required=True)

    s = pxsub.add_parser("check", help="Диагностика прокси профиля (алиас корневого check)")
    s.add_argument("profile_id")
    s.set_defaults(func=cmd_proxy_check)

    s = pxsub.add_parser("check-all", help="Проверить все профили")
    s.set_defaults(func=cmd_proxy_check_all)

    s = pxsub.add_parser("test", help="Проверить произвольную proxy-строку без профиля")
    s.add_argument("raw", help="host:port:user:pass | socks5://... | @file")
    s.set_defaults(func=cmd_proxy_test)

    s = pxsub.add_parser("rotate", help="Дёрнуть rotation_url профиля (мобильные прокси)")
    s.add_argument("profile_id")
    s.set_defaults(func=cmd_proxy_rotate)


def _via_server(opt: GlobalOptions, method: str, path: str, **kw):
    emit(server_request(opt, method, path, **kw), opt)
    return EXIT_OK


def cmd_cookie_import(args, opt: GlobalOptions) -> int:
    text = read_input_text(args.data, file=args.file, stdin_flag=args.stdin)
    if not text.strip():
        return emit_error("Нет данных cookies: аргумент/--file/stdin", opt)
    if opt.server:
        return _via_server(opt, "POST", f"/api/profiles/{args.profile_id}/cookies/import", json={"cookies_data": text})
    from nazak.core.cookie_manager import parse_any_cookies

    pm, _ = get_managers()
    if not pm.get_profile(args.profile_id):
        return emit_error("Профиль не найден", opt, EXIT_NOT_FOUND)
    cookies = parse_any_cookies(text)
    if not cookies:
        return emit_error("Не распознано: поддерживаются JSON / Netscape", opt)
    pm.save_profile_cookies(args.profile_id, cookies)
    return emit_success(f"Импортировано cookies: {len(cookies)}", opt, {"parsed_cookies_count": len(cookies)})


def cmd_cookie_export(args, opt: GlobalOptions) -> int:
    if opt.server:
        return _via_server(opt, "GET", f"/api/profiles/{args.profile_id}/cookies/export?format={args.format}")
    from nazak.core.cookie_manager import cookies_to_netscape

    pm, _ = get_managers()
    if not pm.get_profile(args.profile_id):
        return emit_error("Профиль не найден", opt, EXIT_NOT_FOUND)
    cookies = pm.load_profile_cookies(args.profile_id)
    if args.format == "netscape":
        payload = {
            "success": True,
            "format": "netscape",
            "content": cookies_to_netscape(cookies),
            "cookies_count": len(cookies),
        }
    else:
        payload = {"success": True, "format": "json", "cookies": cookies, "cookies_count": len(cookies)}
    if args.out:
        out_path = resolve_out_path(args.out, opt, force=getattr(args, "force", False))
        default_body = json.dumps(cookies, ensure_ascii=False, indent=2)
        out_path.write_text(str(payload.get("content") or default_body), encoding="utf-8")
        return emit_success(f"Сохранено в {out_path} ({len(cookies)} шт.)", opt, {"cookies_count": len(cookies)})
    emit(payload, opt)
    return EXIT_OK


def cmd_cookie_bulk_import(args, opt: GlobalOptions) -> int:
    text = read_input_text(args.data, file=args.file, stdin_flag=args.stdin)
    if not text.strip():
        return emit_error("Нет данных: аргумент/--file/stdin", opt)
    if opt.server:
        return _via_server(
            opt,
            "POST",
            "/api/cookies/bulk-import",
            json={"cookies_data": text, "auto_create_missing": not args.no_autocreate, "group": args.group},
        )
    from nazak.core.cookie_manager import parse_bulk_cookie_input

    pm, _ = get_managers()
    cmap = parse_bulk_cookie_input(text)
    if not cmap:
        return emit_error("Cookies не распознаны (=== Profile === / JSON-map / Netscape)", opt)
    res = pm.batch_import_cookies(cmap, auto_create_missing=not args.no_autocreate, group=args.group)
    return emit_success("Bulk-import готов", opt, {"results": res})


def cmd_cookie_bulk_export(args, opt: GlobalOptions) -> int:
    ids = resolve_ids(parse_ids(args.profiles), allow_all=args.all)
    if not ids:
        return emit_error("Укажите --profiles id1,id2 или --all", opt)
    if opt.server:
        if args.format == "zip":
            emit(
                {
                    "success": True,
                    "hint": "В server-режиме ZIP скачивается GET-запросом: POST /api/cookies/bulk-export вернёт файл",
                },
                opt,
            )
        return _via_server(opt, "POST", "/api/cookies/bulk-export", json={"profile_ids": ids, "format": args.format})
    pm, _ = get_managers()
    data = pm.export_all_cookies(ids)
    if args.format == "zip":
        from nazak.core.cookie_manager import create_cookies_zip_archive

        out = (
            resolve_out_path(args.out, opt, force=getattr(args, "force", False))
            if args.out
            else Path("nazak_cookies.zip")
        )
        if out.exists() and not (getattr(args, "force", False) or opt.yes):
            raise UsageError(f"Файл уже существует: {out}. Добавьте --force (или --yes), чтобы перезаписать")
        out.write_bytes(create_cookies_zip_archive(data, format_type="json"))
        return emit_success(f"ZIP сохранён: {out} ({len(data)} профилей)", opt, {"profiles_count": len(data)})
    if args.out:
        out_path = resolve_out_path(args.out, opt, force=getattr(args, "force", False))
        out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return emit_success(f"Сохранено в {out_path}", opt, {"profiles_count": len(data)})
    emit({"success": True, "cookies": data, "profiles_count": len(data)}, opt)
    return EXIT_OK


def _proxy_label(raw: str) -> str:
    """Прокси для вывода: без пароля (audit R3 — `proxy test host:port:user:pass` печатал пароль)."""
    from nazak.models.proxy import ProxyConfig

    try:
        return ProxyConfig.parse(raw).to_display_string()
    except Exception:
        return "<unparsed proxy>"


def _print_health(profile_name: str, res, opt: GlobalOptions, *, proxy_label: str | None = None) -> None:
    if opt.as_json:
        payload = {"success": True, "profile": profile_name, "health": res.model_dump()}
        if proxy_label:
            payload["proxy"] = proxy_label
        emit(payload, opt)
        return
    console.print(f"[bold]Диагностика {profile_name}:[/bold]")
    console.print(f" • Статус: {res.status.value.upper()}")
    console.print(f" • Ping: {res.ping_ms} ms")
    console.print(f" • IP: {res.ip} ({res.country}, {res.city})")
    console.print(
        f" • Google: main={res.google.google_main} auth={res.google.google_accounts} ads={res.google.google_ads} yt={res.google.youtube}"
    )
    console.print(f" • Изоляция диска: {'OK' if res.data_isolation_ok else 'FAIL'}")


def cmd_proxy_check(args, opt: GlobalOptions) -> int:
    if opt.server:
        return _via_server(opt, "POST", f"/api/profiles/{args.profile_id}/check")
    from nazak.config import PROFILES_DIR
    from nazak.core.proxy_checker import check_proxy_health

    pm, _ = get_managers()
    p = pm.get_profile(args.profile_id)
    if not p:
        return emit_error("Профиль не найден", opt, EXIT_NOT_FOUND)
    res = asyncio.run(check_proxy_health(p.proxy, profile_dir=PROFILES_DIR / p.id))
    p.last_health_check = res
    if res.latitude is not None and res.longitude is not None:
        p.fingerprint.geolocation.latitude = res.latitude
        p.fingerprint.geolocation.longitude = res.longitude
    if res.timezone_name:
        p.fingerprint.timezone = res.timezone_name
    pm.update_profile(p)
    _print_health(p.name, res, opt)
    return EXIT_OK


def cmd_proxy_check_all(args, opt: GlobalOptions) -> int:
    if opt.server:
        return _via_server(opt, "POST", "/api/profiles/check-all")
    from nazak.config import PROFILES_DIR
    from nazak.core.proxy_checker import check_proxy_health

    pm, _ = get_managers()
    profiles = pm.list_profiles()
    if not profiles:
        return emit_success("Нет профилей", opt, {"total_checked": 0})
    for p in profiles:
        res = asyncio.run(check_proxy_health(p.proxy, profile_dir=PROFILES_DIR / p.id))
        p.last_health_check = res
        pm.update_profile(p)
        if opt.as_json:
            continue
        console.print(f"[{p.id}] {p.name}: {res.status.value} ping={res.ping_ms}")
    if opt.as_json:
        emit({"success": True, "total_checked": len(profiles)}, opt)
    else:
        console.print(f"[bold green]✓ Проверено: {len(profiles)}[/bold green]")
    return EXIT_OK


def cmd_proxy_test(args, opt: GlobalOptions) -> int:
    raw = read_input_text(args.raw) or args.raw
    if opt.server:
        return _via_server(opt, "POST", "/api/profiles/test-proxy", json={"raw_proxy": raw})
    from nazak.core.proxy_checker import check_proxy_health
    from nazak.models.proxy import ProxyConfig

    proxy = ProxyConfig.parse(raw)
    res = asyncio.run(check_proxy_health(proxy, profile_dir=None))
    # Audit R3: в вывод уходит только безопасная форма (user:***@host:port).
    _print_health(_proxy_label(raw), res, opt, proxy_label=_proxy_label(raw))
    return EXIT_OK


def cmd_proxy_rotate(args, opt: GlobalOptions) -> int:
    if opt.server:
        return _via_server(opt, "POST", f"/api/profiles/{args.profile_id}/rotate-proxy")
    import urllib.request

    pm, _ = get_managers()
    p = pm.get_profile(args.profile_id)
    if not p:
        return emit_error("Профиль не найден", opt, EXIT_NOT_FOUND)
    url = (p.proxy.rotation_url or "").strip()
    if not url or url in ("***", "<encrypted: unavailable passphrase>") or url.startswith("<encrypted"):
        return emit_error("rotation_url не задан или замаскирован", opt, EXIT_CONFLICT)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Nazak-Studio"})
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            body = resp.read().decode("utf-8", errors="ignore")[:200]
            return emit_success(f"IP rotated (HTTP {resp.status})", opt, {"status_code": resp.status, "response": body})
    except Exception as e:
        return emit_error(f"Ротация не удалась: {e}", opt, EXIT_CONFLICT)
