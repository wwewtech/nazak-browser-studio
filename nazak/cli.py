"""
Rich Command Line Interface for Nazak Browser Studio.
"""

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

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Add paths
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from nazak.config import (
    EXTENSIONS_DIR,
    PROFILES_DIR,
    PROFILES_FILE,
    find_chrome_executable,
)
from nazak.core.browser_launcher import BrowserLauncher
from nazak.core.profile_manager import ProfileManager
from nazak.core.proxy_checker import check_proxy_health
from nazak.models.profile import ProfileStatus

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
            console.print("[red]Error: Provide a profile ID (e.g.: NazakBrowserStudio.exe launch prof_01)[/red]")
            return
        profile_id = args[1]
        custom_url = args[2] if len(args) > 2 else None
        launch_profile_cli(pm, bl, profile_id, custom_url)
    elif cmd == "stop":
        if len(args) < 2:
            console.print("[red]Error: Provide a profile ID (e.g.: NazakBrowserStudio.exe stop prof_01)[/red]")
            return
        profile_id = args[1]
        stop_profile_cli(pm, bl, profile_id)
    elif cmd == "check":
        if len(args) < 2:
            console.print("[red]Error: Provide a profile ID (e.g.: NazakBrowserStudio.exe check prof_01)[/red]")
            return
        profile_id = args[1]
        check_profile_cli(pm, profile_id)
    elif cmd == "check-all":
        check_all_cli(pm)
    elif cmd == "info":
        show_system_info()
    else:
        console.print(f"[red]Unknown command: {cmd}[/red]")
        print_help()


def print_help():
    console.print(
        Panel(
            """
[bold yellow]Nazak Browser Studio - CLI Tool[/bold yellow]

[bold]Commands:[/bold]
  [green]list[/green]                     - List all profiles and their status
  [green]launch <id> [url][/green]        - Launch the browser for a profile (with an optional URL)
  [green]stop <id>[/green]                - Stop a running profile
  [green]check <id>[/green]               - Full diagnostics of proxy, Google and isolation
  [green]check-all[/green]                - Run diagnostics on all profiles
  [green]info[/green]                     - System info and Chrome executable path
    """,
            title="Help",
        )
    )


def list_profiles(pm: ProfileManager, bl: BrowserLauncher):
    profiles = pm.list_profiles()
    table = Table(title=f"Browser Profiles (Total: {len(profiles)})")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Profile Name", style="bold white")
    table.add_column("Group", style="yellow")
    table.add_column("Status", style="green")
    table.add_column("Proxy", style="blue")
    table.add_column("Ping", justify="right")
    table.add_column("Google Status", style="magenta")

    for p in profiles:
        running = bl.is_profile_running(p.id)
        status = "[bold green]ACTIVE[/bold green]" if running else "[dim]STOPPED[/dim]"
        proxy_str = p.proxy.to_display_string() if not p.proxy.is_direct() else "Direct"

        hc = p.last_health_check
        ping_str = f"{hc.ping_ms} ms" if hc and hc.ping_ms else "-"
        g_status = "[green]✓ Ready[/green]" if (hc and hc.google and hc.google.all_ok) else "[dim]Not checked[/dim]"

        table.add_row(p.id, p.name, p.group, status, proxy_str, ping_str, g_status)

    console.print(table)


def launch_profile_cli(pm: ProfileManager, bl: BrowserLauncher, profile_id: str, custom_url: str | None = None):
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


def stop_profile_cli(pm: ProfileManager, bl: BrowserLauncher, profile_id: str):
    profile = pm.get_profile(profile_id)
    if not profile:
        console.print(f"[red]Profile '{profile_id}' not found![/red]")
        return
    bl.stop(profile_id)
    profile.status = ProfileStatus.STOPPED
    profile.pid = None
    pm.update_profile(profile)
    console.print(f"[bold green]✓ Profile '{profile.name}' stopped.[/bold green]")


def check_profile_cli(pm: ProfileManager, profile_id: str):
    profile = pm.get_profile(profile_id)
    if not profile:
        console.print(f"[red]Profile '{profile_id}' not found![/red]")
        return
    console.print(f"[cyan]Running diagnostics for '{profile.name}'...[/cyan]")
    res = asyncio.run(check_proxy_health(profile.proxy, profile_dir=PROFILES_DIR / profile.id))
    profile.last_health_check = res
    pm.update_profile(profile)

    console.print("[bold]Diagnostics results:[/bold]")
    console.print(f" • Status: {res.status.value.upper()}")
    console.print(f" • Ping: {res.ping_ms} ms")
    console.print(f" • IP: {res.ip} ({res.country}, {res.city})")
    console.print(f" • ISP: {res.isp} ({res.asn})")
    console.print(f" • Google Search: {'[green]OK[/green]' if res.google.google_main else '[red]FAIL[/red]'}")
    console.print(f" • Google Auth: {'[green]OK[/green]' if res.google.google_accounts else '[red]FAIL[/red]'}")
    console.print(f" • Google Ads: {'[green]OK[/green]' if res.google.google_ads else '[red]FAIL[/red]'}")
    console.print(f" • YouTube: {'[green]OK[/green]' if res.google.youtube else '[red]FAIL[/red]'}")
    console.print(f" • Disk isolation: {'[green]OK[/green]' if res.data_isolation_ok else '[red]FAIL[/red]'}")


def check_all_cli(pm: ProfileManager):
    profiles = pm.list_profiles()
    console.print(f"[cyan]Checking all {len(profiles)} profiles...[/cyan]")
    for p in profiles:
        check_profile_cli(pm, p.id)
        console.print("-" * 40)


def show_system_info():
    chrome_exe = find_chrome_executable()
    console.print(
        Panel(
            f"""
[bold]Chrome/Chromium Exe:[/bold] {chrome_exe or "[red]Not found[/red]"}
[bold]Profiles Directory:[/bold] {PROFILES_DIR.resolve()!s}
[bold]Extensions Directory:[/bold] {EXTENSIONS_DIR.resolve()!s}
    """,
            title="System Configuration",
        )
    )


if __name__ == "__main__":
    run_cli()
