"""
Main Native Windows 11 Fluent Application Window.
Built with QFluentWidgets (MSFluentWindow / FluentWindow) with Mica material and NavigationInterface.
"""

from pathlib import Path

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QColor, QIcon
from PyQt6.QtWidgets import QApplication, QWidget
from qfluentwidgets import (
    FluentIcon,
    FluentWindow,
    MSFluentWindow,
    NavigationItemPosition,
    Theme,
    setTheme,
    setThemeColor,
)

from .style import FLUENT_DARK_QSS
from .views.accounts_view import AccountsView
from .views.autopost_view import AutopostView
from .views.profiles_view import ProfilesView
from .views.proxies_view import ProxiesView
from .views.settings_view import SettingsView
from .views.warmup_view import WarmupView


class NazakFluentMainWindow(MSFluentWindow):
    def __init__(self, profile_manager, browser_launcher, parent=None):
        super().__init__(parent)
        self.profile_manager = profile_manager
        self.browser_launcher = browser_launcher

        self.init_window()
        self.init_navigation()

    def init_window(self):
        self.setWindowTitle("Nazak Browser Studio PRO")
        self.resize(1200, 800)
        self.setMinimumSize(1020, 680)

        # Enforce Dark Theme & Windows Accent Color
        setTheme(Theme.DARK)
        setThemeColor("#0078d4")

        # Apply Obsidian Global Stylesheet
        self.setStyleSheet(FLUENT_DARK_QSS)

        # Paint root window background obsidian dark
        self.setBackgroundColor(QColor(18, 18, 20))

        # Set Window Branding Icon
        from ..config import DATA_DIR

        icon_path = DATA_DIR / "assets" / "icon.ico"
        if not icon_path.exists():
            icon_path = Path(__file__).resolve().parent.parent.parent / "data" / "assets" / "icon.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

    def init_navigation(self):
        # 1. Profiles Dashboard (Primary)
        self.profiles_view = ProfilesView(self.profile_manager, self.browser_launcher, self)
        self.addSubInterface(
            self.profiles_view, FluentIcon.APPLICATION, "Профили", FluentIcon.APPLICATION, NavigationItemPosition.TOP
        )

        # 2. YouTube Shorts Autoposter
        self.autopost_view = AutopostView(self.profile_manager, self.browser_launcher, self)
        self.addSubInterface(
            self.autopost_view, FluentIcon.SEND, "Автопостинг", FluentIcon.SEND, NavigationItemPosition.TOP
        )

        # 3. Account Provisioning & Dual-Mode Activation
        self.accounts_view = AccountsView(self.profile_manager, self.browser_launcher, self)
        self.addSubInterface(
            self.accounts_view, FluentIcon.PEOPLE, "Аккаунты", FluentIcon.PEOPLE, NavigationItemPosition.TOP
        )

        # 4. Proxies & Bulk Import
        self.proxies_view = ProxiesView(self.profile_manager, self.browser_launcher, self)
        self.addSubInterface(
            self.proxies_view, FluentIcon.GLOBE, "Прокси", FluentIcon.GLOBE, NavigationItemPosition.TOP
        )

        # 5. Google Warmup Bot
        self.warmup_view = WarmupView(self.profile_manager, self.browser_launcher, self)
        self.addSubInterface(
            self.warmup_view, FluentIcon.ROBOT, "Прогрев", FluentIcon.ROBOT, NavigationItemPosition.TOP
        )

        # 6. Settings (Bottom pinned)
        self.settings_view = SettingsView(self)
        self.addSubInterface(
            self.settings_view, FluentIcon.SETTING, "Настройки", FluentIcon.SETTING, NavigationItemPosition.BOTTOM
        )

        # Live Inter-Tab Synchronization
        self.stackedWidget.currentChanged.connect(self._on_tab_changed)

        # Default to Profiles view
        self.navigationInterface.setCurrentItem(self.profiles_view.objectName())

    def _on_tab_changed(self, index: int):
        widget = self.stackedWidget.widget(index)
        if widget is self.profiles_view:
            self.profiles_view.refresh_profiles()
        elif widget is self.accounts_view:
            self.accounts_view.refresh_table()
        elif widget is self.proxies_view:
            self.proxies_view.refresh_table()
        elif widget is self.warmup_view:
            self.warmup_view.populate_profiles()
