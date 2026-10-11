"""
Nazak Browser Studio - Main Application Entry Point.
Supports Pure Desktop Fluent GUI (no console), Web Mode, and CLI.
"""

import argparse
import os
import sys
import traceback
import webbrowser
from pathlib import Path

# Add project root to sys.path if not present
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from nazak.api.server import app as fastapi_app, configure_local_access, enforce_exposure_policy
from nazak.cli import run_cli
from nazak.config import DEFAULT_HOST, DEFAULT_PORT, LOGS_DIR, ensure_data_dirs


# Robust stream redirection for the pure windowed GUI (no console attached).
#
# P1: this used to be a bare `open(path, "a")` per write() call with no rotation,
# so a long-running GUI grew data/logs/stdout.log without bound (and opened a file
# handle on every stderr write). Writes now go through a size-rotated handler.
class _RotatingStream:
    """File-like stdout/stderr replacement that rotates its log file."""

    def __init__(self, log_path: Path, max_bytes: int = 5 * 1024 * 1024, backup_count: int = 3):
        self.log_path = log_path
        self._max_bytes = max_bytes
        self._backup_count = backup_count
        self._handler = None

    @property
    def encoding(self) -> str:
        return "utf-8"

    def _ensure_handler(self):
        if self._handler is None:
            from logging.handlers import RotatingFileHandler

            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            # NOTE: delay=False on purpose. With delay=True the handler does not
            # reopen the file after doRollover(), so the primary log would not
            # exist until the next write. Creation is still lazy relative to
            # import: this method only runs on the first write().
            self._handler = RotatingFileHandler(
                str(self.log_path),
                maxBytes=self._max_bytes,
                backupCount=self._backup_count,
                encoding="utf-8",
            )
        return self._handler

    def write(self, s):
        if not s:
            return
        try:
            handler = self._ensure_handler()
            handler.acquire()
            try:
                handler.stream.write(s)
                handler.stream.flush()
                if self._max_bytes > 0 and handler.stream.tell() >= self._max_bytes:
                    handler.doRollover()
            finally:
                handler.release()
        except Exception:
            # A logging failure must never take the GUI down.
            pass

    def flush(self):
        try:
            if self._handler is not None and self._handler.stream is not None:
                self._handler.stream.flush()
        except Exception:
            pass

    def isatty(self) -> bool:
        return False


if sys.stdout is None:
    sys.stdout = _RotatingStream(LOGS_DIR / "stdout.log")
if sys.stderr is None:
    sys.stderr = _RotatingStream(LOGS_DIR / "stderr.log")


def main():
    # P1: the data tree is created here (an explicit entry point) instead of at
    # import time, so importing config/main never mutates the filesystem.
    ensure_data_dirs()

    parser = argparse.ArgumentParser(description="Nazak Browser Studio - Windows 11 Multi-Profile Anti-Detect Browser")
    parser.add_argument(
        "--mode",
        choices=["gui", "web", "cli"],
        default="gui",
        help="Launch mode: gui (pure desktop window), web (browser UI), cli (terminal)",
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=(
            "Server bind address (default: 127.0.0.1 loopback). "
            "Binding to 0.0.0.0 exposes the API/Swagger to your LAN — only do so deliberately."
        ),
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Server port (default: 8899)")
    parser.add_argument("--no-browser", action="store_true", help="Don't auto-open browser in web mode")

    _cli_groups = (
        "profile",
        "cookie",
        "proxy",
        "warmup",
        "scenario",
        "sync",
        "autopost",
        "account",
        "cdp",
        "secrets",
        "system",
        "list",
        "launch",
        "stop",
        "check",
        "check-all",
        "info",
        "help",
    )
    if len(sys.argv) > 1 and sys.argv[1] in _cli_groups:
        raise SystemExit(run_cli())
        return

    args, _unknown = parser.parse_known_args()

    # Trust whatever port we are about to bind (local-only origin policy).
    configure_local_access(args.port)

    # Audit R3: a non-loopback bind without NAZAK_API_TOKEN no longer starts —
    # otherwise any client passes the guard simply by sending Host: 127.0.0.1.
    enforce_exposure_policy(args.host)

    if args.mode == "gui":
        try:
            from nazak.gui.main_window import launch_gui

            launch_gui(host=args.host, port=args.port)
        except Exception:
            # Write crash log
            crash_file = LOGS_DIR / "crash.log"
            try:
                with open(crash_file, "a", encoding="utf-8") as f:
                    f.write(f"\n--- Crash at {os.environ.get('USERNAME', 'user')} ---\n")
                    traceback.print_exc(file=f)
            except Exception:
                pass

            # Fallback to web mode if Qt fails
            start_web_mode(args.host, args.port, not args.no_browser)

    elif args.mode == "web":
        start_web_mode(args.host, args.port, not args.no_browser)

    elif args.mode == "cli":
        # Forward everything after `--mode cli` to the rich CLI parser
        # (strip launcher-only flags so `profile list --json` etc. just work).
        cleaned: list[str] = []
        skip_next = False
        for tok in sys.argv[1:]:
            if skip_next:
                skip_next = False
                continue
            if tok == "--mode":
                skip_next = True
                continue
            if tok.startswith("--mode="):
                continue
            cleaned.append(tok)
        sys.argv = [sys.argv[0], *cleaned]
        raise SystemExit(run_cli())


def start_web_mode(host: str, port: int, open_browser: bool = True):
    import uvicorn

    if host == "0.0.0.0":  # nosec B104 - compared, not bound; enforce_exposure_policy() guards the bind
        import logging

        logging.getLogger(__name__).warning(
            "Binding the API server to 0.0.0.0 exposes Swagger/API to the local network. "
            "Use 127.0.0.1 unless remote access is intended."
        )

    if open_browser:
        try:
            webbrowser.open(f"http://{host}:{port}")
        except Exception:
            pass

    uvicorn.run(fastapi_app, host=host, port=port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
