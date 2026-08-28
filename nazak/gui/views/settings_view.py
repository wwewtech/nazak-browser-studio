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

        lbl_title = QLabel("Настройки приложения", self)
        lbl_title.setStyleSheet("color: #ffffff; font-size: 22px; font-weight: 700; letter-spacing: -0.4px;")

        lbl_desc = QLabel("Параметры внешнего вида, путей к исполняемым файлам и сетевых интеграций", self)
        lbl_desc.setStyleSheet("color: #a1a1aa; font-size: 12px;")

        main_layout.addWidget(lbl_title)
        main_layout.addWidget(lbl_desc)

        # 1. Appearance Card
        card_theme = SimpleCardWidget(self)
        l_theme = QVBoxLayout(card_theme)
        l_theme.setContentsMargins(16, 14, 16, 14)

        lbl_t1 = QLabel("Оформление интерфейса", card_theme)
        lbl_t1.setStyleSheet("color: #ffffff; font-weight: 700; font-size: 13px;")
        l_theme.addWidget(lbl_t1)

        h_theme = QHBoxLayout()
        lbl_th = QLabel("Тема приложения:", card_theme)
        lbl_th.setStyleSheet("color: #d4d4d8; font-size: 12px;")
        h_theme.addWidget(lbl_th)

        self.combo_theme = ComboBox(card_theme)
        self.combo_theme.addItem("Тёмная обсидиановая", userData=Theme.DARK)
        self.combo_theme.addItem("Светлая", userData=Theme.LIGHT)
        self.combo_theme.currentIndexChanged.connect(self.on_theme_changed)
        h_theme.addWidget(self.combo_theme)
        h_theme.addStretch()
        l_theme.addLayout(h_theme)
        main_layout.addWidget(card_theme)

        # 2. System Paths & Chrome Detection Card
        card_env = SimpleCardWidget(self)
        l_env = QVBoxLayout(card_env)
        l_env.setContentsMargins(16, 14, 16, 14)

        lbl_t2 = QLabel("Системное окружение и Chromium", card_env)
        lbl_t2.setStyleSheet("color: #ffffff; font-weight: 700; font-size: 13px;")
        l_env.addWidget(lbl_t2)

        chrome_exe = find_chrome_executable() or "Не найден"
        lbl_c1 = QLabel(f"Исполняемый файл Chromium: {chrome_exe}", card_env)
        lbl_c1.setStyleSheet("color: #a1a1aa; font-size: 11px;")
        l_env.addWidget(lbl_c1)

        lbl_c2 = QLabel(f"Каталог хранения профилей: {PROFILES_DIR}", card_env)
        lbl_c2.setStyleSheet("color: #a1a1aa; font-size: 11px;")
        l_env.addWidget(lbl_c2)

        lbl_c3 = QLabel("Встроенный API сервер: http://127.0.0.1:8899", card_env)
        lbl_c3.setStyleSheet("color: #a1a1aa; font-size: 11px;")
        l_env.addWidget(lbl_c3)
        main_layout.addWidget(card_env)

        # 3. About Card
        card_about = SimpleCardWidget(self)
        l_about = QVBoxLayout(card_about)
        l_about.setContentsMargins(16, 14, 16, 14)

        lbl_t3 = QLabel("О программе", card_about)
        lbl_t3.setStyleSheet("color: #ffffff; font-weight: 700; font-size: 13px;")
        l_about.addWidget(lbl_t3)

        lbl_a1 = QLabel("Nazak Browser Studio PRO v1.3.0", card_about)
        lbl_a1.setStyleSheet("color: #38bdf8; font-weight: 600; font-size: 12px;")
        l_about.addWidget(lbl_a1)

        lbl_a2 = QLabel(
            "Автономный антидетект-браузер с мультипрофилями, менеджер Google-аккаунтов и автопостер YouTube Shorts",
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
            InfoBar.success(
                "Тема обновлена", "Оформление интерфейса изменено", parent=self, position=InfoBarPosition.TOP
            )
