"""`nazak autopost ...` и `nazak account ...` — паритет AutopostView + AccountsView + live_flow скрипта."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

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
    parse_ids,
    read_input_text,
    resolve_ids,
    server_request,
)


def register(sp) -> None:
    a = sp.add_parser("autopost", help="Автопостинг Shorts/Reels: uniqueizer, spintax, очередь")
    asub = a.add_subparsers(dest="autopost_action", required=True)

    s = asub.add_parser("status", help="Статус очереди + FFmpeg")
    s.set_defaults(func=cmd_autopost_status)

    s = asub.add_parser("preview", help="Превью Spintax title/description (первые 5)")
    s.add_argument("--profiles", default="", help="CSV профилей")
    s.add_argument("--all", action="store_true")
    s.add_argument("--title", default="{Video|New video|Fresh upload} {2026} #shorts")
    s.add_argument("--desc", default="New upload via Nazak Browser Studio.\n\n#shorts")
    s.add_argument("--tg", default="@your_channel")
    s.set_defaults(func=cmd_autopost_preview)

    s = asub.add_parser("uniquify", help="FFmpeg-уникализация видео под каждый профиль")
    s.add_argument("--video", required=True, help="Исходный mp4/mov/mkv")
    s.add_argument("--profiles", default="", help="CSV профилей")
    s.add_argument("--all", action="store_true")
    s.set_defaults(func=cmd_autopost_uniquify)

    s = asub.add_parser("launch", help="Запуск фоновой загрузки (YouTube Shorts / Instagram Reels)")
    s.add_argument("--profiles", default="", help="CSV профилей")
    s.add_argument("--all", action="store_true")
    s.add_argument("--video", default=None)
    s.add_argument(
        "--platform", default="youtube_shorts", choices=["youtube_shorts", "instagram_reels", "youtube", "instagram"]
    )
    s.add_argument("--title", default="{Video|New video|Fresh upload} {2026} #shorts")
    s.add_argument("--desc", default="New upload via Nazak Browser Studio.\n\n#shorts")
    s.add_argument("--tg", default="@your_channel")
    s.add_argument("--delay", type=int, default=10, help="Пауза между аккаунтами, сек")
    s.add_argument("--demo", action="store_true", help="Сгенерировать ffmpeg тестовый клип если нет видео")
    s.add_argument("--wait", action="store_true", help="Дождаться завершения вместо фона")
    s.set_defaults(func=cmd_autopost_launch)

    s = asub.add_parser("cancel", help="Отменить running-очередь")
    s.set_defaults(func=cmd_autopost_cancel)

    acc = sp.add_parser("account", help="Аккаунты: импорт login:pass:2fa:recovery, TOTP, auto-login")
    accsub = acc.add_subparsers(dest="account_action", required=True)

    s = accsub.add_parser("import", help="Batch-импорт аккаунтов маркетплейсов")
    s.add_argument("--group", default="Imported Gmail")
    s.add_argument("--mode", default="browser_stealth", choices=["browser_stealth", "oauth_api"])
    s.add_argument("--file", default=None)
    s.add_argument("--stdin", action="store_true")
    s.add_argument("data", nargs="?", default=None, help="Текст или @file")
    s.set_defaults(func=cmd_account_import)

    s = accsub.add_parser("list", help="Список импортированных аккаунтов")
    s.set_defaults(func=cmd_account_list)

    s = accsub.add_parser("totp", help="Текущий TOTP-код профиля (RFC6238 live)")
    s.add_argument("profile_id")
    s.set_defaults(func=cmd_account_totp)

    s = accsub.add_parser("login", help="Авто-логин Google + загрузка Shorts (ex cli_auto_login_and_upload)")
    s.add_argument("--profile", default=None, help="ID профиля (иначе автовыбор)")
    s.add_argument("--email", default=None, help="Фильтр по email")
    s.add_argument("--video", default=None, help="Видео для загрузки")
    s.add_argument("--data-file", default=None, help="Файл data1.txt для импорта если профилей нет")
    s.set_defaults(func=cmd_account_login)


def _via_server(opt: GlobalOptions, method: str, path: str, **kw):
    emit(server_request(opt, method, path, **kw), opt)
    return EXIT_OK


# --- autopost ---

_upload_mgr = None


def _get_upload_mgr():
    global _upload_mgr
    if _upload_mgr is None:
        from nazak.core.upload_queue import UploadQueueManager

        pm, bl = get_managers()
        _upload_mgr = UploadQueueManager(pm, bl, None)
    return _upload_mgr


def cmd_autopost_status(args, opt: GlobalOptions) -> int:
    if opt.server:
        return _via_server(opt, "GET", "/api/autopost/status")
    from nazak.core.video_uniquifier import VideoUniquifier

    mgr = _get_upload_mgr()
    vu = VideoUniquifier()
    payload = {
        "success": True,
        "is_running": mgr.is_running,
        "ffmpeg_available": vu.is_ffmpeg_available(),
        "ffmpeg_path": vu.ffmpeg_path,
        "jobs": mgr.get_jobs_status(),
    }
    emit(payload, opt)
    return EXIT_OK


def cmd_autopost_preview(args, opt: GlobalOptions) -> int:
    ids = resolve_ids(parse_ids(args.profiles), allow_all=args.all)
    if not ids:
        return emit_error("Укажите --profiles id1,id2 или --all", opt)
    if opt.server:
        return _via_server(
            opt,
            "POST",
            "/api/autopost/preview-spintax",
            json={
                "profile_ids": ids,
                "title_template": args.title,
                "description_template": args.desc,
                "tg_channel": args.tg,
            },
        )
    from nazak.core.spintax import format_video_metadata

    pm, _ = get_managers()
    samples = []
    for pid in ids[:5]:
        prof = pm.get_profile(pid)
        pname = prof.name if prof else pid
        meta = format_video_metadata(
            title_template=args.title,
            description_template=args.desc,
            profile_name=pname,
            profile_id=pid,
            tg_channel=args.tg,
        )
        samples.append(
            {"profile_id": pid, "profile_name": pname, "title": meta["title"], "description": meta["description"]}
        )
    if opt.as_json:
        emit({"success": True, "samples": samples}, opt)
    else:
        for smp in samples:
            console.print(f"[bold cyan]{smp['profile_name']}[/bold cyan] ({smp['profile_id']})")
            console.print(f"  Title: {smp['title']}")
            console.print(f"  Desc:  {smp['description'][:160]}")
    return EXIT_OK


def cmd_autopost_uniquify(args, opt: GlobalOptions) -> int:
    ids = resolve_ids(parse_ids(args.profiles), allow_all=args.all)
    if not ids:
        return emit_error("Укажите --profiles id1,id2 или --all", opt)
    src = Path(args.video)
    if not src.exists():
        return emit_error(f"Видео не найдено: {args.video}", opt, EXIT_NOT_FOUND)
    if opt.server:
        return _via_server(
            opt, "POST", "/api/autopost/uniquify", json={"source_video_path": str(src), "profile_ids": ids}
        )
    from nazak.core.video_uniquifier import VideoUniquifier

    vu = VideoUniquifier()
    results = asyncio.run(asyncio.to_thread(vu.batch_uniquify, src, ids))
    formatted = {
        pid: {"success": ok, "output_path": str(path.resolve()) if path else None, "error": err}
        for pid, (ok, path, err) in results.items()
    }
    emit({"success": True, "results": formatted, "count": len(formatted)}, opt)
    return EXIT_OK


def cmd_autopost_launch(args, opt: GlobalOptions) -> int:
    from nazak.core.upload_queue import normalize_upload_platform

    ids = resolve_ids(parse_ids(args.profiles), allow_all=args.all)
    if not ids:
        return emit_error("Укажите --profiles id1,id2 или --all", opt)
    platform = normalize_upload_platform(args.platform)
    if opt.server:
        body = {
            "profile_ids": ids,
            "platform": platform,
            "title_template": args.title,
            "description_template": args.desc,
            "tg_channel": args.tg,
            "delay_seconds": args.delay,
            "demo": args.demo,
        }
        if args.video:
            body["source_video_path"] = args.video
        return _via_server(opt, "POST", "/api/autopost/launch", json=body)
    from nazak.config import DATA_DIR
    from nazak.core.video_uniquifier import find_ffmpeg

    mgr = _get_upload_mgr()
    if mgr.is_running:
        return emit_error("Очередь уже запущена (autopost cancel для остановки)", opt, EXIT_CONFLICT)
    if args.video:
        src = Path(args.video)
        if not src.exists():
            return emit_error(f"Видео не найдено: {args.video}", opt, EXIT_NOT_FOUND)
    else:
        src = DATA_DIR / "videos" / "source.mp4"
        if not src.exists():
            if not args.demo:
                return emit_error("Нет source-видео: укажите --video или --demo", opt)
            ffmpeg = find_ffmpeg()
            if not ffmpeg:
                return emit_error("ffmpeg не найден для --demo", opt, EXIT_CONFLICT)
            import subprocess

            src.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc=size=1080x1920:rate=30:duration=5",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=440:duration=5",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-shortest",
                    str(src),
                ],
                capture_output=True,
                check=False,
            )
    coro = mgr.run_batch_upload(
        profile_ids=ids,
        source_video_path=src,
        title_template=args.title,
        description_template=args.desc,
        tg_channel=args.tg,
        delay_between_accounts_sec=args.delay,
        platform=platform,
    )
    if args.wait:
        asyncio.run(coro)
        emit({"success": True, "platform": platform, "jobs": mgr.get_jobs_status()}, opt)
    else:
        import threading

        threading.Thread(target=lambda: asyncio.run(coro), daemon=True, name="NazakAutopost").start()
        return emit_success(
            f"Автопостинг запущен фоном ({platform}, {len(ids)} проф.)", opt, {"platform": platform, "profiles": ids}
        )
    return EXIT_OK


def cmd_autopost_cancel(args, opt: GlobalOptions) -> int:
    if opt.server:
        return _via_server(opt, "POST", "/api/autopost/cancel")
    _get_upload_mgr().cancel_all()
    return emit_success("Отмена запрошена", opt)


# --- accounts ---


def cmd_account_import(args, opt: GlobalOptions) -> int:
    text = read_input_text(args.data, file=args.file, stdin_flag=args.stdin)
    if not text.strip():
        return emit_error("Нет данных: login:pass:2fa:recovery через аргумент/--file/stdin", opt)
    if opt.server:
        return emit_error("account import доступен только в direct-режиме (без --server)", opt)
    from nazak.config import PROFILES_DIR
    from nazak.core.account_provisioner import AccountProvisioner

    pm, _ = get_managers()
    prov = AccountProvisioner(pm, PROFILES_DIR)
    posting = "browser_stealth" if args.mode == "browser_stealth" else "oauth_api"
    profiles = prov.batch_import_and_create_profiles(text, group_name=args.group, posting_mode=posting)
    ids = [p.id for p in profiles]
    if not profiles:
        return emit_error("Не распознано ни одного аккаунта (формат login:pass:2fa:recovery)", opt)
    if opt.as_json:
        emit({"success": True, "created_count": len(ids), "profile_ids": ids, "group": args.group}, opt)
    else:
        t = Table(title=f"Imported {len(ids)}")
        t.add_column("Profile ID")
        t.add_column("Name")
        for p in profiles:
            t.add_row(p.id, p.name)
        console.print(t)
    return EXIT_OK


def _extract_account_notes(p) -> dict:
    if p.google and p.google.notes:
        try:
            notes = json.loads(p.google.notes)
            if isinstance(notes, dict):
                return notes
        except Exception:
            pass
    return {}


def cmd_account_list(args, opt: GlobalOptions) -> int:
    if opt.server:
        data = server_request(opt, "GET", "/api/profiles")
        profs = data if isinstance(data, list) else data.get("data", data)
        emit(profs, opt)
        return EXIT_OK
    from nazak.core.secrets_store import mask_secret

    pm, _ = get_managers()
    rows = []
    for p in pm.list_profiles():
        notes = _extract_account_notes(p)
        email = notes.get("account_email") or (p.google.target_account_email if p.google else "")
        group_lower = (p.group or "").lower()
        looks_like_account = bool(
            email
            or notes.get("totp_secret")
            or "retriv" in group_lower
            or "darkstore" in group_lower
            or "gmail" in group_lower
        )
        if not looks_like_account:
            continue
        rows.append(
            {
                "profile_id": p.id,
                "name": p.name,
                "group": p.group,
                "email": email or "-",
                "totp_masked": mask_secret(notes.get("totp_secret", "")),
                "mode": (p.google.posting_mode if p.google and getattr(p.google, "posting_mode", None) else "browser"),
            }
        )
    if opt.as_json:
        emit({"success": True, "count": len(rows), "accounts": rows}, opt)
    else:
        t = Table(title=f"Accounts ({len(rows)})")
        for c in ("Profile", "Name", "Email", "2FA", "Mode"):
            t.add_column(c)
        for r in rows:
            t.add_row(r["profile_id"], r["name"], r["email"], r["totp_masked"], r["mode"])
        console.print(t)
    return EXIT_OK


def cmd_account_totp(args, opt: GlobalOptions) -> int:
    from nazak.core.account_provisioner import generate_totp_rfc6238
    from nazak.core.secrets_store import decrypt_notes

    pm, _ = get_managers()
    p = pm.get_profile(args.profile_id)
    if not p:
        return emit_error("Профиль не найден", opt, EXIT_NOT_FOUND)
    notes = _extract_account_notes(p)
    try:
        revealed = decrypt_notes(notes)
    except Exception:
        revealed = notes
    secret = revealed.get("totp_secret", "")
    if not secret or secret.startswith("<encrypted"):
        return emit_error("TOTP-секрет отсутствует или закрыт passphrase (secrets set)", opt, EXIT_CONFLICT)
    try:
        code = generate_totp_rfc6238(secret)
    except Exception as e:
        return emit_error(f"Невалидный TOTP-секрет: {e}", opt)
    emit({"success": True, "profile_id": p.id, "totp_code": code}, opt)
    return EXIT_OK


def cmd_account_login(args, opt: GlobalOptions) -> int:
    """Тонкая обёртка над cli_auto_login_and_upload.run_live_flow с параметрами."""
    import os

    if args.email:
        os.environ["GOOGLE_EMAIL"] = args.email
    if args.video:
        os.environ["NAZAK_TEST_VIDEO"] = args.video
    if args.data_file:
        os.environ["NAZAK_DATA_FILE"] = args.data_file
    if args.profile and not args.email:
        # передаём как email-фильтр по id через env; live_flow умеет матчить по name/id
        os.environ["GOOGLE_EMAIL"] = args.profile
    if opt.server:
        return emit_error("account login работает только в direct-режиме", opt)
    from nazak.cli_auto_login_and_upload import run_live_flow

    if opt.as_json:
        # live_flow болтлив (print/эмодзи): в --json его прогресс уходит в stderr,
        # а stdout остаётся одним JSON-документом — парсер агента не ломается.
        import contextlib
        import io
        import sys as _sys

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ok = asyncio.run(run_live_flow())
        _sys.stderr.write(buf.getvalue())
    else:
        ok = asyncio.run(run_live_flow())
    if ok:
        return emit_success("Auto-login + upload завершён", opt)
    return emit_error("Auto-login завершился с ошибкой (см. вывод + screenshots/live_run)", opt, EXIT_CONFLICT)
