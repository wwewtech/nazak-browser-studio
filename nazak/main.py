"""
Nazak Browser Studio PRO - Main Application Entry Point.
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

from nazak.api.server import app as fastapi_app
from nazak.cli import run_cli
from nazak.config import DEFAULT_HOST, DEFAULT_PORT, LOGS_DIR


# Robust SafeStream redirection for pure windowed GUI without console
class SafeStream:
    def __init__(self, log_path: Path):
        self.log_path = log_path

    def write(self, s):
        if not s:
            return
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(s)
        except Exception:
            pass

    def flush(self):
        pass


if sys.stdout is None:
    sys.stdout = SafeStream(LOGS_DIR / "stdout.log")
if sys.stderr is None:
    sys.stderr = SafeStream(LOGS_DIR / "stderr.log")


def main():
    parser = argparse.ArgumentParser(
        description="Nazak Browser Studio PRO - Windows 11 Multi-Profile Anti-Detect Browser"
    )
    parser.add_argument(
        "--mode",
        choices=["gui", "web", "cli"],
        default="gui",
        help="Launch mode: gui (pure desktop window), web (browser UI), cli (terminal)",
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="Server host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Server port (default: 8899)")
    parser.add_argument("--no-browser", action="store_true", help="Don't auto-open browser in web mode")

    if len(sys.argv) > 1 and sys.argv[1] in ("list", "launch", "stop", "check", "check-all", "info", "help"):
        run_cli()
        return

    args, _unknown = parser.parse_known_args()

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
        run_cli()


def start_web_mode(host: str, port: int, open_browser: bool = True):
    import uvicorn

    if open_browser:
        try:
            webbrowser.open(f"http://{host}:{port}")
        except Exception:
            pass

    uvicorn.run(fastapi_app, host=host, port=port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
