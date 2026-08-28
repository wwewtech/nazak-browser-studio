import ctypes
import os
import sys
import threading
import time
from pathlib import Path

import uvicorn
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from ..api.server import app as fastapi_app
from ..config import DATA_DIR, DEFAULT_HOST, DEFAULT_PORT, EXTENSIONS_DIR, PROFILES_DIR, PROFILES_FILE
from ..core.browser_launcher import BrowserLauncher
from ..core.profile_manager import ProfileManager
from .app_window import NazakFluentMainWindow
from .splash import NazakSplashScreen


class ServerThread(threading.Thread):
    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT):
        super().__init__(daemon=True, name="NazakUvicornServer")
        self.host = host
        self.port = port
        self.server = None

    def run(self):
        try:
            config = uvicorn.Config(
                app=fastapi_app, host=self.host, port=self.port, log_level="error", access_log=False
            )
            self.server = uvicorn.Server(config)
            self.server.run()
        except Exception:
            # If port 8899 is already taken by another instance, keep GUI running smoothly
            pass

    def stop(self):
        if self.server:
            self.server.should_exit = True


def launch_gui(host=DEFAULT_HOST, port=DEFAULT_PORT):
    # Set Windows 10/11 Taskbar App ID so icon displays properly
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Nazak.BrowserStudio.Pro.1.3")
        except Exception:
            pass

    # 1. Start background FastAPI server thread
    server_thread = ServerThread(host=host, port=port)
    server_thread.start()

    # 2. Enable High DPI Scaling for crisp typography
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    # 3. Start Qt Application
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv if sys.argv else ["NazakBrowserStudio"])
    app.setApplicationName("NazakBrowserStudio")
    app.setApplicationDisplayName("Nazak Browser Studio PRO")

    # Set Application Icon
    icon_path = DATA_DIR / "assets" / "icon.ico"
    if not icon_path.exists():
        icon_path = Path(__file__).resolve().parent.parent.parent / "data" / "assets" / "icon.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    # 4. Display Sleek Startup Splash Screen
    splash = NazakSplashScreen()
    splash.show()
    app.processEvents()

    # Initialize Core Engines while splash is visible
    profile_manager = ProfileManager(PROFILES_FILE, PROFILES_DIR)
    browser_launcher = BrowserLauncher(PROFILES_DIR, EXTENSIONS_DIR)

    # 5. Create Native Windows 11 Fluent Window
    window = NazakFluentMainWindow(profile_manager, browser_launcher)
    if icon_path.exists():
        window.setWindowIcon(QIcon(str(icon_path)))

    # Transition from Splash to Main Window after brief telemetry display
    splash.show_and_fade(duration_ms=900, on_finished=window.show)

    sys.exit(app.exec())

    exit_code = app.exec()
    server_thread.stop()
    sys.exit(exit_code)
