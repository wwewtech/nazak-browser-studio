"""
Fluent Application Settings View.
Fluent Iconography & Zero-Emoji Architecture.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget
from qfluentwidgets import ComboBox, FluentIcon, InfoBar, InfoBarPosition, PushButton, SimpleCardWidget, Theme, setTheme

from ...config import DATA_DIR, PROFILES_DIR
from ...core.browser_launcher import find_chrome_executable


class SettingsView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("settings_view")
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(14)
        main_layout.setContentsMargins(24, 20, 24, 20)

        lbl_title = QLabel("Application Settings", self)
        lbl_title.setStyleSheet("color: #ffffff; font-size: 22px; font-weight: 700; letter-spacing: -0.4px;")

        lbl_desc = QLabel("Appearance, executable paths and network integration settings", self)
        lbl_desc.setStyleSheet("color: #a1a1aa; font-size: 12px;")

        main_layout.addWidget(lbl_title)
        main_layout.addWidget(lbl_desc)

        # 1. Appearance Card
        card_theme = SimpleCardWidget(self)
        l_theme = QVBoxLayout(card_theme)
        l_theme.setContentsMargins(16, 14, 16, 14)

        lbl_t1 = QLabel("Interface Appearance", card_theme)
        lbl_t1.setStyleSheet("color: #ffffff; font-weight: 700; font-size: 13px;")
        l_theme.addWidget(lbl_t1)

        h_theme = QHBoxLayout()
        lbl_th = QLabel("Application theme:", card_theme)
        lbl_th.setStyleSheet("color: #d4d4d8; font-size: 12px;")
        h_theme.addWidget(lbl_th)

        self.combo_theme = ComboBox(card_theme)
        self.combo_theme.addItem("Dark Obsidian", userData=Theme.DARK)
        self.combo_theme.addItem("Light", userData=Theme.LIGHT)
        self.combo_theme.currentIndexChanged.connect(self.on_theme_changed)
        h_theme.addWidget(self.combo_theme)
        h_theme.addStretch()
        l_theme.addLayout(h_theme)
        main_layout.addWidget(card_theme)

        # 2. System Paths & Chrome Detection Card
        card_env = SimpleCardWidget(self)
        l_env = QVBoxLayout(card_env)
        l_env.setContentsMargins(16, 14, 16, 14)

        lbl_t2 = QLabel("System Environment & Chromium", card_env)
        lbl_t2.setStyleSheet("color: #ffffff; font-weight: 700; font-size: 13px;")
        l_env.addWidget(lbl_t2)

        chrome_exe = find_chrome_executable() or "Not found"
        lbl_c1 = QLabel(f"Chromium executable: {chrome_exe}", card_env)
        lbl_c1.setStyleSheet("color: #a1a1aa; font-size: 11px;")
        l_env.addWidget(lbl_c1)

        lbl_c2 = QLabel(f"Profile storage directory: {PROFILES_DIR}", card_env)
        lbl_c2.setStyleSheet("color: #a1a1aa; font-size: 11px;")
        l_env.addWidget(lbl_c2)

        lbl_c3 = QLabel("Built-in API server: http://127.0.0.1:8899", card_env)
        lbl_c3.setStyleSheet("color: #a1a1aa; font-size: 11px;")
        l_env.addWidget(lbl_c3)
        main_layout.addWidget(card_env)

        # 3. About Card
        card_about = SimpleCardWidget(self)
        l_about = QVBoxLayout(card_about)
        l_about.setContentsMargins(16, 14, 16, 14)

        lbl_t3 = QLabel("About", card_about)
        lbl_t3.setStyleSheet("color: #ffffff; font-weight: 700; font-size: 13px;")
        l_about.addWidget(lbl_t3)

        lbl_a1 = QLabel("Nazak Browser Studio v1.3.0", card_about)
        lbl_a1.setStyleSheet("color: #38bdf8; font-weight: 600; font-size: 12px;")
        l_about.addWidget(lbl_a1)

        lbl_a2 = QLabel(
            "Standalone multi-profile anti-detect browser, Google account manager and YouTube Shorts autoposter",
            card_about,
        )
        lbl_a2.setStyleSheet("color: #a1a1aa; font-size: 11px;")
        l_about.addWidget(lbl_a2)
        main_layout.addWidget(card_about)

        main_layout.addStretch()

    def on_theme_changed(self):
        theme = self.combo_theme.currentData()
        if theme is not None:
            setTheme(theme)
            InfoBar.success("Theme updated", "Interface appearance changed", parent=self, position=InfoBarPosition.TOP)
