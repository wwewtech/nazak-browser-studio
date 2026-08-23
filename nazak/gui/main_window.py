"""
PyQt6 / PyQt-Fluent-Widgets Application Launcher for Nazak Browser Studio PRO.
Launches the native Windows 11 Fluent interface (MSFluentWindow / FluentWindow)
along with the background FastAPI server thread.
"""
import sys
import os
import time
import threading
import uvicorn
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

from ..config import DEFAULT_HOST, DEFAULT_PORT, PROFILES_FILE, PROFILES_DIR, EXTENSIONS_DIR
from ..core.profile_manager import ProfileManager
from ..core.browser_launcher import BrowserLauncher
from ..api.server import app as fastapi_app
from .app_window import NazakFluentMainWindow

class ServerThread(threading.Thread):
    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT):
        super().__init__(daemon=True, name="NazakUvicornServer")
        self.host = host
        self.port = port
        self.server = None

    def run(self):
        try:
            config = uvicorn.Config(
                app=fastapi_app,
                host=self.host,
                port=self.port,
                log_level="error",
                access_log=False
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
    # 1. Start background FastAPI server thread
    server_thread = ServerThread(host=host, port=port)
    server_thread.start()
    time.sleep(0.3)

    # 2. Enable High DPI Scaling for crisp typography
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    # 3. Start Qt Application
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv if sys.argv else ["NazakBrowserStudio"])
    app.setApplicationName("NazakBrowserStudio")

    # Initialize Core Engines
    profile_manager = ProfileManager(PROFILES_FILE, PROFILES_DIR)
    browser_launcher = BrowserLauncher(PROFILES_DIR, EXTENSIONS_DIR)

    # 4. Create Native Windows 11 Fluent Window
    window = NazakFluentMainWindow(profile_manager, browser_launcher)
    window.show()

    exit_code = app.exec()
    server_thread.stop()
    sys.exit(exit_code)
