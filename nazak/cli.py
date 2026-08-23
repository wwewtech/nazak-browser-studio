"""
Rich Command Line Interface for Nazak Browser Studio.
"""
import sys
import os
import asyncio
from typing import Optional

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

# Add paths
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

try:
    from nazak.config import PROFILES_FILE, PROFILES_DIR, EXTENSIONS_DIR, find_chrome_executable, DEFAULT_HOST, DEFAULT_PORT
    from nazak.models.profile import ProfileStatus
    from nazak.core.profile_manager import ProfileManager
    from nazak.core.browser_launcher import BrowserLauncher
    from nazak.core.proxy_checker import check_proxy_health
except ImportError:
    from config import PROFILES_FILE, PROFILES_DIR, EXTENSIONS_DIR, find_chrome_executable, DEFAULT_HOST, DEFAULT_PORT
    from models.profile import ProfileStatus
    from core.profile_manager import ProfileManager
    from core.browser_launcher import BrowserLauncher
    from core.proxy_checker import check_proxy_health

console = Console()

def run_cli():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help", "help"):
        print_help()
        return

    cmd = args[0].lower()
    pm = ProfileManager(PROFILES_FILE, PROFILES_DIR)
    bl = BrowserLauncher(PROFILES_DIR, EXTENSIONS_DIR)

    if cmd == "list":
        list_profiles(pm, bl)
    elif cmd == "launch":
        if len(args) < 2:
            console.print("[red]Ошибка: Укажите ID профиля (например: NazakBrowserStudio.exe launch prof_01)[/red]")
            return
        profile_id = args[1]
        custom_url = args[2] if len(args) > 2 else None
        launch_profile_cli(pm, bl, profile_id, custom_url)
    elif cmd == "stop":
        if len(args) < 2:
            console.print("[red]Ошибка: Укажите ID профиля (например: NazakBrowserStudio.exe stop prof_01)[/red]")
            return
        profile_id = args[1]
        stop_profile_cli(pm, bl, profile_id)
    elif cmd == "check":
        if len(args) < 2:
            console.print("[red]Ошибка: Укажите ID профиля (например: NazakBrowserStudio.exe check prof_01)[/red]")
            return
        profile_id = args[1]
        check_profile_cli(pm, profile_id)
    elif cmd == "check-all":
        check_all_cli(pm)
    elif cmd == "info":
        show_system_info()
    else:
        console.print(f"[red]Неизвестная команда: {cmd}[/red]")
        print_help()

def print_help():
    console.print(Panel("""
[bold yellow]Nazak Browser Studio - CLI Инструмент[/bold yellow]

[bold]Команды:[/bold]
  [green]list[/green]                     - Список всех профилей и их статус
  [green]launch <id> [url][/green]        - Запустить браузер для профиля (с опциональным URL)
  [green]stop <id>[/green]                - Остановить запущенный профиль
  [green]check <id>[/green]               - Полная диагностика прокси, Google и изоляции
  [green]check-all[/green]                - Диагностика всех профилей
  [green]info[/green]                     - Информация о системе и пути к Chrome
    """, title="Справка"))

def list_profiles(pm: ProfileManager, bl: BrowserLauncher):
    profiles = pm.list_profiles()
    table = Table(title=f"Профили браузеров (Всего: {len(profiles)})")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Имя профиля", style="bold white")
    table.add_column("Группа", style="yellow")
    table.add_column("Статус", style="green")
    table.add_column("Прокси", style="blue")
    table.add_column("Пинг", justify="right")
    table.add_column("Google Статус", style="magenta")

    for p in profiles:
        running = bl.is_profile_running(p.id)
        status = "[bold green]RUNNING[/bold green]" if running else "[dim]STOPPED[/dim]"
        proxy_str = p.proxy.to_display_string() if not p.proxy.is_direct() else "Direct"
        
        hc = p.last_health_check
        ping_str = f"{hc.ping_ms} ms" if hc and hc.ping_ms else "-"
        g_status = "[green]✓ Ready[/green]" if (hc and hc.google and hc.google.all_ok) else "[dim]Not Checked[/dim]"

        table.add_row(p.id, p.name, p.group, status, proxy_str, ping_str, g_status)

    console.print(table)

def launch_profile_cli(pm: ProfileManager, bl: BrowserLauncher, profile_id: str, custom_url: Optional[str] = None):
    profile = pm.get_profile(profile_id)
    if not profile:
        console.print(f"[red]Профиль '{profile_id}' не найден![/red]")
        return
    console.print(f"[cyan]Запуск браузера для профиля '{profile.name}'...[/cyan]")
    ok, pid, err = bl.launch(profile, custom_url=custom_url)
    if ok:
        profile.status = ProfileStatus.RUNNING
        profile.pid = pid
        pm.update_profile(profile)
        console.print(f"[bold green]✓ Профиль запущен успешно (PID: {pid})[/bold green]")
    else:
        console.print(f"[bold red]✕ Ошибка запуска: {err}[/bold red]")

def stop_profile_cli(pm: ProfileManager, bl: BrowserLauncher, profile_id: str):
    profile = pm.get_profile(profile_id)
    if not profile:
        console.print(f"[red]Профиль '{profile_id}' не найден![/red]")
        return
    bl.stop(profile_id)
    profile.status = ProfileStatus.STOPPED
    profile.pid = None
    pm.update_profile(profile)
    console.print(f"[bold green]✓ Профиль '{profile.name}' остановлен.[/bold green]")

def check_profile_cli(pm: ProfileManager, profile_id: str):
    profile = pm.get_profile(profile_id)
    if not profile:
        console.print(f"[red]Профиль '{profile_id}' не найден![/red]")
        return
    console.print(f"[cyan]Выполнение диагностики для '{profile.name}'...[/cyan]")
    res = asyncio.run(check_proxy_health(profile.proxy, profile_dir=PROFILES_DIR / profile.id))
    profile.last_health_check = res
    pm.update_profile(profile)

    console.print(f"[bold]Результаты диагностики:[/bold]")
    console.print(f" • Статус: {res.status.value.upper()}")
    console.print(f" • Пинг: {res.ping_ms} ms")
    console.print(f" • IP: {res.ip} ({res.country}, {res.city})")
    console.print(f" • Провайдер: {res.isp} ({res.asn})")
    console.print(f" • Google Search: {'[green]OK[/green]' if res.google.google_main else '[red]FAIL[/red]'}")
    console.print(f" • Google Auth: {'[green]OK[/green]' if res.google.google_accounts else '[red]FAIL[/red]'}")
    console.print(f" • Google Ads: {'[green]OK[/green]' if res.google.google_ads else '[red]FAIL[/red]'}")
    console.print(f" • YouTube: {'[green]OK[/green]' if res.google.youtube else '[red]FAIL[/red]'}")
    console.print(f" • Изоляция диска: {'[green]OK[/green]' if res.data_isolation_ok else '[red]FAIL[/red]'}")

def check_all_cli(pm: ProfileManager):
    profiles = pm.list_profiles()
    console.print(f"[cyan]Запуск проверки всех {len(profiles)} профилей...[/cyan]")
    for p in profiles:
        check_profile_cli(pm, p.id)
        console.print("-" * 40)

def show_system_info():
    chrome_exe = find_chrome_executable()
    console.print(Panel(f"""
[bold]Chrome/Chromium Exe:[/bold] {chrome_exe or '[red]Не найден[/red]'}
[bold]Profiles Directory:[/bold] {str(PROFILES_DIR.resolve())}
[bold]Extensions Directory:[/bold] {str(EXTENSIONS_DIR.resolve())}
    """, title="Системная конфигурация"))

if __name__ == "__main__":
    run_cli()
