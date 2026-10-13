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
    reveal: bool = False


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "y")


class ApiError(Exception):
    """Re-raises an API HTTP error (server mode) preserving the original status."""

    def __init__(self, status: int, detail: str):
        super().__init__(f"API {status}: {detail}")
        self.status = status
        self.detail = detail


class UsageError(Exception):
    """Input/path error (exit code 2): malformed @file, overwrite without --force, etc.

    A dedicated type is needed so the CLI can tell "the agent passed a bad argument"
    apart from "the environment broke" (the latter stays EXIT_CONFLICT).
    """


def api_error_code(status: int) -> int:
    """Maps an API HTTP status to a CLI exit code: 404->1, 400/409/422->2, anything else->4."""
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
        reveal=bool(getattr(args, "reveal", False)) or _env_flag("NAZAK_REVEAL"),
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
    """Error plus an exact next-step hint — the agent does not have to guess what to do."""
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
    """False under a pipe/in CI/for agents — asking there is pointless; just state what to do."""
    try:
        return sys.stdin.isatty()
    except Exception:
        return False


def confirm(prompt: str, opt: GlobalOptions) -> bool:
    if opt.yes:
        return True
    if not is_interactive():
        # Do not hang on input() in non-interactive mode: the caller returns an error with a --yes hint.
        return False
    try:
        ans = input(f"{prompt} [y/N]: ").strip().lower()
    except (EOFError, OSError):
        return False
    return ans in ("y", "yes", "д", "да")


def require_confirm(prompt: str, opt: GlobalOptions, retry_hint: str) -> tuple[bool, int | None]:
    """confirm() plus a ready-made return code for a non-interactive refusal.

    Returns (ok, exit_code): with ok=True the code is None (continue),
    on refusal in interactive mode — (False, 0) "Cancelled", in non-interactive mode — (False, 4) with a hint.
    """
    if confirm(prompt, opt):
        return True, None
    if not is_interactive() or opt.as_json:
        emit_error("Требуется подтверждение", opt, EXIT_CONFLICT, hint=retry_hint)
        return False, EXIT_CONFLICT
    console.print("[yellow]Отменено[/yellow]")
    return False, EXIT_OK


_MAX_INPUT_BYTES = 16 * 1024 * 1024


def _read_text_file(path: Path, *, what: str) -> str:
    """Reads an input file with explicit errors instead of silently substituting the path."""
    if not path.exists():
        raise UsageError(f"{what} не найден: {path}")
    if path.is_dir():
        raise UsageError(f"{what} указывает на каталог, а не на файл: {path}")
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise UsageError(f"{what} недоступен: {path} ({exc})") from exc
    if size > _MAX_INPUT_BYTES:
        raise UsageError(f"{what} слишком большой: {path} ({size} байт > {_MAX_INPUT_BYTES})")
    try:
        # utf-8-sig strips a UTF-8 BOM (the Notepad default) instead of leaving it
        # in the payload, where it corrupted the first proxy/account/cookie record.
        return path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        raise UsageError(f"{what} не читается: {path} ({exc})") from exc


def read_input_text(explicit: str | None = None, file: str | None = None, stdin_flag: bool = False) -> str:
    """Priority: explicit arg > --file > --stdin > NAZAK_* env handled by caller.

    Audit R3: a typo'd ``@path`` used to be silently returned as *data*
    (the "@path" string was handed to the proxy/cookie parser). Now it is an explicit
    input error, and the file size is capped so an agent cannot pull a gigabyte into memory.
    """
    if explicit:
        # allow @path syntax
        if explicit.startswith("@"):
            return _read_text_file(Path(explicit[1:]).expanduser(), what="Файл из @path")
        return explicit
    if file:
        return _read_text_file(Path(file).expanduser(), what="Файл --file")
    if stdin_flag or (not sys.stdin.isatty()):
        try:
            data = sys.stdin.read()
            if data.strip():
                return data
        except Exception:
            pass
    return ""


def resolve_out_path(raw: str, opt: GlobalOptions, *, force: bool = False) -> Path:
    """Where to write --out: never silently overwrite someone else's file.

    An agent that substituted the wrong path must not clobber an existing file:
    overwriting requires an explicit --force (or --yes).
    """
    if not raw:
        raise UsageError("Пустой путь для --out")
    path = Path(raw).expanduser()
    if path.is_dir():
        raise UsageError(f"--out указывает на каталог: {path}")
    if path.exists() and not (force or opt.yes):
        raise UsageError(f"Файл уже существует: {path}. Добавьте --force (или --yes), чтобы перезаписать")
    parent = path.parent if str(path.parent) else Path(".")
    if not parent.exists():
        raise UsageError(f"Каталог для --out не существует: {parent}")
    return path


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
        from nazak.config import EXTENSIONS_DIR, PROFILES_DIR, PROFILES_FILE, ensure_data_dirs
        from nazak.core.browser_launcher import BrowserLauncher
        from nazak.core.profile_manager import ProfileManager

        # P1: explicit entry point — importing config no longer creates the tree.
        ensure_data_dirs()
        pm = ProfileManager(PROFILES_FILE, PROFILES_DIR)
        bl = BrowserLauncher(PROFILES_DIR, EXTENSIONS_DIR)
        _managers = (pm, bl)
    return _managers


def resolve_ids(requested: list[str], allow_all: bool = False) -> list[str]:
    # `--profiles all` is documented in the help text of every batch command,
    # so the bare keyword must expand too — not only the separate --all flag
    # (previously `--profiles all` selected nothing and reported 0 profiles).
    effective = requested or []
    if allow_all or "all" in effective or "*" in effective:
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
    """Mask proxy credentials for CLI output.

    Handles both documented shapes. The previous version only masked
    ``user:pass@host:port``, so the equally documented ``host:port:user:pass``
    form printed the real password in ``raw`` (and therefore into stdout, logs
    and agent transcripts) while the ``password`` field looked masked.
    """
    out = dict(d)
    if out.get("password"):
        out["password"] = "***"
    raw = out.get("raw")
    if isinstance(raw, str) and raw:
        out["raw"] = _mask_raw_proxy_string(raw)
    if out.get("rotation_url"):
        out["rotation_url"] = "***"
    return out


def _mask_raw_proxy_string(raw: str) -> str:
    """Replace the secret segment of a proxy string with ``***``."""
    import re

    if "@" in raw:
        return re.sub(r":[^:@/]*@", ":***@", raw, count=1)
    if "://" in raw:
        # scheme://host:port — no credentials to hide
        return raw
    # host:port:user:pass  (the credentials are the trailing two segments)
    parts = raw.split(":")
    if len(parts) >= 4:
        return ":".join([*parts[:-2], "***", "***"])
    if len(parts) == 3:
        return ":".join([*parts[:-1], "***"])
    return raw


def _strip_helper_keys(notes: dict) -> dict:
    """Drops helper keys (`_totp_raw`) while keeping the mode marker."""
    return {k: v for k, v in notes.items() if not k.startswith("_") or k == "_secrets_mode"}


def mask_notes_json(notes_raw: object, *, reveal: bool = False) -> str | None:
    """Profile notes JSON with masked (or revealed) secrets.

    Returns None if notes is not a JSON object (free-form text is left untouched).
    """
    if not isinstance(notes_raw, str) or not notes_raw.lstrip().startswith("{"):
        return None
    try:
        notes = json.loads(notes_raw)
    except Exception:
        return None
    if not isinstance(notes, dict):
        return None
    from nazak.core.secrets_store import decrypt_notes, reveal_notes

    opened = reveal_notes(notes) if reveal else decrypt_notes(notes)
    return json.dumps(_strip_helper_keys(opened), ensure_ascii=False)


def profile_for_output(profile, *, reveal: bool = False) -> dict:
    """Full profile for CLI output with secrets masked by default.

    Audit R3: `profile get` printed the proxy password and google.notes with
    account_password/totp_secret in the clear — to stdout, agent logs and
    transcripts. Revealing now happens only on an explicit --reveal.
    """
    data = profile.model_dump()
    proxy = data.get("proxy")
    if isinstance(proxy, dict) and not reveal:
        data["proxy"] = mask_proxy_dict(proxy)
    google = data.get("google")
    if isinstance(google, dict):
        masked = mask_notes_json(google.get("notes"), reveal=reveal)
        if masked is not None:
            google["notes"] = masked
    return data
