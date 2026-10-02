"""Shared helpers: output (Rich/JSON), input, managers, server mode, exit codes.

Exit codes (AI-agent contract):
  0 = ok, 1 = not found, 2 = validation/usage error, 4 = conflict/busy.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich.console import Console

console = Console()
err_console = Console(stderr=True)

EXIT_OK = 0
EXIT_NOT_FOUND = 1
EXIT_USAGE = 2
EXIT_CONFLICT = 4


@dataclass
class GlobalOptions:
    as_json: bool = False
    yes: bool = False
    server: str | None = None
    api_key: str | None = None
    verbose: bool = False


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "y")


class ApiError(Exception):
    """Проброс HTTP-ошибки API (server-режим) с исходным статусом."""

    def __init__(self, status: int, detail: str):
        super().__init__(f"API {status}: {detail}")
        self.status = status
        self.detail = detail


def api_error_code(status: int) -> int:
    """Маппинг HTTP-статуса API в CLI exit-код: 404->1, 400/409/422->2, остальное->4."""
    if status == 404:
        return EXIT_NOT_FOUND
    if status in (400, 409, 422):
        return EXIT_USAGE
    return EXIT_CONFLICT


def build_global_options(args) -> GlobalOptions:
    return GlobalOptions(
        as_json=bool(getattr(args, "json", False)) or _env_flag("NAZAK_JSON"),
        yes=bool(getattr(args, "yes", False)) or _env_flag("NAZAK_YES"),
        server=getattr(args, "server", None) or os.environ.get("NAZAK_SERVER") or None,
        api_key=getattr(args, "api_key", None) or os.environ.get("NAZAK_API_TOKEN"),
        verbose=bool(getattr(args, "verbose", False)) or _env_flag("NAZAK_VERBOSE"),
    )


def emit(data: Any, opt: GlobalOptions) -> None:
    """Human (Rich-safe) or machine output."""
    if opt.as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    else:
        if isinstance(data, (dict, list)):
            print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
        else:
            console.print(str(data))


def emit_error(message: str, opt: GlobalOptions, code: int = EXIT_USAGE, hint: str | None = None) -> int:
    """Ошибка + точная подсказка следующего шага (hint) — агент не гадает, что делать."""
    if opt.as_json:
        payload: dict[str, Any] = {"success": False, "error": message, "code": code}
        if hint:
            payload["hint"] = hint
        print(json.dumps(payload, ensure_ascii=False))
    else:
        err_console.print(f"[bold red]Ошибка:[/bold red] {message}")
        if hint:
            err_console.print(f"[dim]Подсказка: {hint}[/dim]")
    return code


def emit_success(message: str, opt: GlobalOptions, extra: dict | None = None) -> int:
    payload: dict[str, Any] = {"success": True, "message": message}
    if extra:
        payload.update(extra)
    if opt.as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        console.print(f"[bold green]✓[/bold green] {message}")
        if extra and opt.verbose:
            console.print(json.dumps(extra, ensure_ascii=False, indent=2, default=str))
    return EXIT_OK


def is_interactive() -> bool:
    """False под пайпом/в CI/у агентов — там спрашивать бесполезно, надо сразу говорить что делать."""
    try:
        return sys.stdin.isatty()
    except Exception:
        return False


def confirm(prompt: str, opt: GlobalOptions) -> bool:
    if opt.yes:
        return True
    if not is_interactive():
        # Не висим на input() в неинтерактиве: caller вернёт ошибку с hint про --yes.
        return False
    try:
        ans = input(f"{prompt} [y/N]: ").strip().lower()
    except (EOFError, OSError):
        return False
    return ans in ("y", "yes", "д", "да")


def require_confirm(prompt: str, opt: GlobalOptions, retry_hint: str) -> tuple[bool, int | None]:
    """confirm() + готовый код возврата для неинтерактивного отказа.

    Возвращает (ok, exit_code): при ok=True код None (продолжать),
    при отказе в интерактиве — (False, 0) «Отменено», в неинтерактиве — (False, 4) с hint.
    """
    if confirm(prompt, opt):
        return True, None
    if not is_interactive() or opt.as_json:
        emit_error("Требуется подтверждение", opt, EXIT_CONFLICT, hint=retry_hint)
        return False, EXIT_CONFLICT
    console.print("[yellow]Отменено[/yellow]")
    return False, EXIT_OK


def read_input_text(explicit: str | None = None, file: str | None = None, stdin_flag: bool = False) -> str:
    """Priority: explicit arg > --file > --stdin > NAZAK_* env handled by caller."""
    if explicit:
        # allow @path syntax
        if explicit.startswith("@"):
            p = Path(explicit[1:])
            if p.exists():
                return p.read_text(encoding="utf-8")
        return explicit
    if file:
        return Path(file).read_text(encoding="utf-8")
    if stdin_flag or (not sys.stdin.isatty()):
        try:
            data = sys.stdin.read()
            if data.strip():
                return data
        except Exception:
            pass
    return ""


def parse_ids(csv: str | list[str] | None, allow_all: bool = False) -> list[str]:
    if not csv:
        return []
    if isinstance(csv, list):
        out: list[str] = []
        for item in csv:
            out.extend([x.strip() for x in str(item).split(",") if x.strip()])
        return out
    return [x.strip() for x in str(csv).split(",") if x.strip()]


# --- managers (direct-core mode) ---

_managers: tuple | None = None


def get_managers():
    """Lazy singleton (ProfileManager, BrowserLauncher)."""
    global _managers
    if _managers is None:
        from nazak.config import EXTENSIONS_DIR, PROFILES_DIR, PROFILES_FILE
        from nazak.core.browser_launcher import BrowserLauncher
        from nazak.core.profile_manager import ProfileManager

        pm = ProfileManager(PROFILES_FILE, PROFILES_DIR)
        bl = BrowserLauncher(PROFILES_DIR, EXTENSIONS_DIR)
        _managers = (pm, bl)
    return _managers


def resolve_ids(requested: list[str], allow_all: bool = False) -> list[str]:
    if allow_all and (not requested or "all" in requested or "*" in requested):
        pm, _ = get_managers()
        return [p.id for p in pm.list_profiles()]
    return requested


# --- server (HTTP) mode ---


def server_request(opt: GlobalOptions, method: str, path: str, **kwargs) -> Any:
    """Thin httpx client to a running GUI/web server. Raises on transport error."""
    if not opt.server:
        raise RuntimeError("server mode not enabled")
    import httpx

    base = opt.server.rstrip("/")
    headers = {}
    if opt.api_key:
        headers["X-API-Key"] = opt.api_key
    with httpx.Client(base_url=base, headers=headers, timeout=60.0) as client:
        resp = client.request(method, path, **kwargs)
        if resp.status_code >= 500:
            raise RuntimeError(f"server error HTTP {resp.status_code}: {resp.text[:160]}")
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except Exception:
                raise RuntimeError(f"server returned non-JSON HTTP {resp.status_code}: {resp.text[:160]}") from None
            detail = body.get("detail", body) if isinstance(body, dict) else body
            raise ApiError(resp.status_code, str(detail))
        try:
            return resp.json()
        except Exception:
            raise RuntimeError(f"server returned non-JSON HTTP {resp.status_code}: {resp.text[:160]}") from None


def mask_proxy_dict(d: dict) -> dict:
    out = dict(d)
    if out.get("password"):
        out["password"] = "***"
    raw = out.get("raw")
    if isinstance(raw, str) and "@" in raw:
        import re

        out["raw"] = re.sub(r":[^:@/]*@", ":***@", raw, count=1)
    if out.get("rotation_url"):
        out["rotation_url"] = "***"
    return out
