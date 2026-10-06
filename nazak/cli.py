"""
Rich Command Line Interface for Nazak Browser Studio.
Полный паритет с GUI: profile/cookie/proxy/warmup/scenario/sync/autopost/account/cdp/secrets/system.
AI-agent контракт: --json + exit-коды 0/1/2/4. Backward-compat: list/launch/stop/check/check-all/info.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:
        pass

from rich.panel import Panel
from rich.table import Table

# Add paths
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from nazak.cli_cmds import automation, autopost_accounts, cookies_proxies, profiles, system_secrets_cdp
from nazak.cli_cmds.common import (
    EXIT_OK,
    EXIT_USAGE,
    GlobalOptions,
    UsageError,
    build_global_options,
    console,
)
from nazak.config import EXTENSIONS_DIR, PROFILES_DIR, find_chrome_executable

GROUPS_HELP = """[bold yellow]Nazak Browser Studio — CLI (паритет с GUI)[/bold yellow]

[bold]Группы (новое, всё из GUI):[/bold]
  [green]profile[/green]   CRUD, launch/stop, batch, bulk-import, mass-generate, bundle, seed-history, clear-cache
  [green]cookie[/green]    import/export, bulk-import/bulk-export (json/netscape/zip)
  [green]proxy[/green]     check/check-all/test/rotate
  [green]warmup[/green]    plan/launch --niche --steps
  [green]scenario[/green]  list/run --scenario --profiles --concurrency
  [green]sync[/green]      start/stop/status/tile/navigate (Master→Workers)
  [green]autopost[/green]  status/preview/uniquify/launch/cancel (Shorts/Reels, FFmpeg, Spintax)
  [green]account[/green]   import/list/totp/login (login:pass:2fa:recovery)
  [green]cdp[/green]       start/stop/active/info (Dolphin-паритет /v1.0/*)
  [green]secrets[/green]   get/set (plain/dpapi/passphrase)
  [green]system[/green]    info

[bold]Совместимость (старые команды работают):[/bold]
  [green]list[/green] / [green]launch <id> [url][/green] / [green]stop <id>[/green] / [green]check <id>[/green] / [green]check-all[/green] / [green]info[/green]

[bold]Глобальные флаги (для людей и ИИ-агентов):[/bold]
  [cyan]--json[/cyan] machine-readable вывод  [cyan]--yes[/cyan] без подтверждений
  [cyan]--reveal[/cyan] показать секреты открытым текстом (по умолчанию маскируются)
  [cyan]--server URL[/cyan] выполнить через running API  [cyan]--api-key KEY[/cyan] ($NAZAK_API_TOKEN)
  Примеры:
    profile list --json | proxy check prof_01 | scenario list
    autopost launch --profiles prof_01,prof_02 --video clip.mp4 --wait
    account import --file accounts.txt --group "Retriv Gmail" --mode browser_stealth
    profile get prof_01 --reveal --json   # пароли/2FA только по явному запросу
"""


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="nazak",
        description="Nazak Browser Studio CLI — полный паритет с GUI, удобен ИИ-агентам (--json).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--json", action="store_true", help="Machine-readable JSON вывод")
    ap.add_argument("--yes", "-y", action="store_true", help="Не спрашивать подтверждений")
    ap.add_argument(
        "--reveal",
        action="store_true",
        help="Раскрыть секреты (пароли прокси/аккаунтов, TOTP). По умолчанию вывод маскируется",
    )
    ap.add_argument("--server", default=None, help="Base URL running API, напр. http://127.0.0.1:8899")
    ap.add_argument("--api-key", default=None, help="X-API-Key (или env NAZAK_API_TOKEN)")
    ap.add_argument("--verbose", "-v", action="store_true")
    sub = ap.add_subparsers(dest="group")

    profiles.register(sub)
    cookies_proxies.register(sub)
    automation.register(sub)
    autopost_accounts.register(sub)
    system_secrets_cdp.register(sub)

    # --- legacy root aliases (backward-compat) ---
    a = sub.add_parser("list", help="[legacy] Список профилей")
    a.add_argument("--group-filter", default=None)
    a.set_defaults(func=_legacy_list)

    a = sub.add_parser("launch", help="[legacy] launch <id> [url]")
    a.add_argument("profile_id")
    a.add_argument("url", nargs="?", default=None)
    a.set_defaults(func=_legacy_launch)

    a = sub.add_parser("stop", help="[legacy] stop <id>")
    a.add_argument("profile_id")
    a.set_defaults(func=_legacy_stop)

    a = sub.add_parser("check", help="[legacy] check <id>")
    a.add_argument("profile_id")
    a.set_defaults(func=_legacy_check)

    a = sub.add_parser("check-all", help="[legacy] Проверить все")
    a.set_defaults(func=_legacy_check_all)

    a = sub.add_parser("info", help="[legacy] Системная информация")
    a.set_defaults(func=_legacy_info)

    a = sub.add_parser("help", help="Справка по группам")
    a.set_defaults(func=_show_help)
    return ap


def print_help():
    console.print(Panel(GROUPS_HELP, title="Help"))


def _show_help(args, opt: GlobalOptions) -> int:
    print_help()
    build_parser().print_help()
    return EXIT_OK


# --- legacy shims -> новые модули ---


def _legacy_list(args, opt: GlobalOptions) -> int:
    ns = argparse.Namespace(group=getattr(args, "group_filter", None))
    return profiles.cmd_list(ns, opt)


def _legacy_launch(args, opt: GlobalOptions) -> int:
    ns = argparse.Namespace(profile_id=args.profile_id, url=args.url, cdp_port=None)
    return profiles.cmd_launch(ns, opt)


def _legacy_stop(args, opt: GlobalOptions) -> int:
    ns = argparse.Namespace(profile_id=args.profile_id)
    return profiles.cmd_stop(ns, opt)


def _legacy_check(args, opt: GlobalOptions) -> int:
    ns = argparse.Namespace(profile_id=args.profile_id)
    return cookies_proxies.cmd_proxy_check(ns, opt)


def _legacy_check_all(args, opt: GlobalOptions) -> int:
    return cookies_proxies.cmd_proxy_check_all(args, opt)


def _legacy_info(args, opt: GlobalOptions) -> int:
    return system_secrets_cdp.cmd_system_info(args, opt)


def _hoist_global_flags(argv: list[str]) -> list[str]:
    """Позволяет `profile list --json` и `--json profile list`: выносит глобальные флаги вперёд."""
    hoisted: list[str] = []
    rest: list[str] = []
    i = 0
    take_value = {"--server", "--api-key"}
    while i < len(argv):
        tok = argv[i]
        if tok in ("--json", "--yes", "-y", "--verbose", "-v", "--reveal"):
            hoisted.append(tok)
        elif tok in take_value:
            hoisted.append(tok)
            if i + 1 < len(argv):
                hoisted.append(argv[i + 1])
                i += 1
        elif tok.startswith("--server=") or tok.startswith("--api-key="):
            hoisted.append(tok)
        else:
            rest.append(tok)
        i += 1
    return [*hoisted, *rest]


def run_cli() -> int:
    # Совместимость: `cli.py list` / exe без `profile` префикса уже приходит сюда из main.py.
    # argparse покрывает и legacy, и новые группы — отдельный ручной парсинг не нужен,
    # кроме bare `launch <id> [url]` когда argparse вызван как `prog launch ...`: он уже зарегистрирован.
    parser = build_parser()
    argv = _hoist_global_flags(sys.argv[1:])
    if not argv or argv[0] == "help":
        print_help()
        return EXIT_OK
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        code = e.code
        if code is None:
            return EXIT_OK
        try:
            return int(code)
        except (TypeError, ValueError):
            return EXIT_USAGE
    if not getattr(args, "func", None) and not getattr(args, "group", None):
        print_help()
        return EXIT_USAGE
    if not getattr(args, "func", None):
        print_help()
        parser.print_help()
        return EXIT_USAGE
    opt = build_global_options(args)
    try:
        code = args.func(args, opt)
        return int(code if code is not None else EXIT_OK)
    except KeyboardInterrupt:
        console.print("[yellow]Прервано[/yellow]")
        return 130
    except BrokenPipeError:
        return EXIT_OK
    except UsageError as exc:
        # Ошибка ввода/пути: чистый exit 2 без traceback.
        from nazak.cli_cmds.common import emit_error

        return emit_error(str(exc), opt, EXIT_USAGE, hint="Проверьте аргументы: system schema --json")
    except Exception as exc:  # транспорт/API: чистый JSON вместо traceback
        from nazak.cli_cmds.common import EXIT_CONFLICT, ApiError, api_error_code, emit_error

        if opt.verbose:
            raise
        if isinstance(exc, ApiError):
            return emit_error(
                f"API: {exc.detail}",
                opt,
                api_error_code(exc.status),
                hint="Проверьте ID/параметры командой system schema --json",
            )
        return emit_error(f"Команда не выполнена: {exc}", opt, EXIT_CONFLICT)


def list_profiles(pm, bl):
    """Оставлено для тестов/обратной совместимости импортов."""
    from nazak.models.profile import ProfileStatus  # noqa

    profiles_list = pm.list_profiles()
    table = Table(title=f"Browser Profiles (Total: {len(profiles_list)})")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Profile Name", style="bold white")
    table.add_column("Group", style="yellow")
    table.add_column("Status", style="green")
    table.add_column("Proxy", style="blue")
    table.add_column("Ping", justify="right")
    table.add_column("Google Status", style="magenta")
    for p in profiles_list:
        running = bl.is_profile_running(p.id)
        status = "[bold green]ACTIVE[/bold green]" if running else "[dim]STOPPED[/dim]"
        proxy_str = p.proxy.to_display_string() if not p.proxy.is_direct() else "Direct"
        hc = p.last_health_check
        ping_str = f"{hc.ping_ms} ms" if hc and hc.ping_ms else "-"
        g_status = "[green]✓ Ready[/green]" if (hc and hc.google and hc.google.all_ok) else "[dim]Not checked[/dim]"
        table.add_row(p.id, p.name, p.group, status, proxy_str, ping_str, g_status)
    console.print(table)


def launch_profile_cli(pm, bl, profile_id: str, custom_url: str | None = None):
    from nazak.models.profile import ProfileStatus

    profile = pm.get_profile(profile_id)
    if not profile:
        console.print(f"[red]Profile '{profile_id}' not found![/red]")
        return
    console.print(f"[cyan]Launching browser for profile '{profile.name}'...[/cyan]")
    ok, pid, err = bl.launch(profile, custom_url=custom_url)
    if ok:
        profile.status = ProfileStatus.RUNNING
        profile.pid = pid
        pm.update_profile(profile)
        console.print(f"[bold green]✓ Profile launched successfully (PID: {pid})[/bold green]")
    else:
        console.print(f"[bold red]✕ Launch error: {err}[/bold red]")


def stop_profile_cli(pm, bl, profile_id: str):
    from nazak.models.profile import ProfileStatus

    profile = pm.get_profile(profile_id)
    if not profile:
        console.print(f"[red]Profile '{profile_id}' not found![/red]")
        return
    bl.stop(profile_id)
    profile.status = ProfileStatus.STOPPED
    profile.pid = None
    pm.update_profile(profile)
    console.print(f"[bold green]✓ Profile '{profile.name}' stopped.[/bold green]")


def check_profile_cli(pm, profile_id: str):
    profile = pm.get_profile(profile_id)
    if not profile:
        console.print(f"[red]Profile '{profile_id}' not found![/red]")
        return
    from nazak.core.proxy_checker import check_proxy_health

    console.print(f"[cyan]Running diagnostics for '{profile.name}'...[/cyan]")
    res = asyncio.run(check_proxy_health(profile.proxy, profile_dir=PROFILES_DIR / profile.id))
    profile.last_health_check = res
    pm.update_profile(profile)
    console.print("[bold]Diagnostics results:[/bold]")
    console.print(f" • Status: {res.status.value.upper()}")
    console.print(f" • Ping: {res.ping_ms} ms")


def check_all_cli(pm):
    for p in pm.list_profiles():
        check_profile_cli(pm, p.id)
        console.print("-" * 40)


def show_system_info():
    chrome_exe = find_chrome_executable()
    console.print(
        Panel(
            f"[bold]Chrome/Chromium Exe:[/bold] {chrome_exe or '[red]Not found[/red]'}\n"
            f"[bold]Profiles Directory:[/bold] {PROFILES_DIR.resolve()!s}\n"
            f"[bold]Extensions Directory:[/bold] {EXTENSIONS_DIR.resolve()!s}",
            title="System Configuration",
        )
    )


if __name__ == "__main__":
    raise SystemExit(run_cli())
