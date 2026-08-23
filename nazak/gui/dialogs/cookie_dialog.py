"""
Fluent Cookie Manager & Cache Cleaner Dialog.
Fluent Iconography Architecture.
"""
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel
from PyQt6.QtCore import Qt
from qfluentwidgets import (
    TextEdit, PrimaryPushButton, PushButton, InfoBar, InfoBarPosition, SimpleCardWidget, FluentIcon
)

from ...core.cookie_manager import parse_any_cookies, cookies_to_netscape
from ..style import FLUENT_DARK_QSS

class CookieManagerDialog(QDialog):
    def __init__(self, profile, profile_manager, parent=None):
        super().__init__(parent)
        self.profile = profile
        self.profile_manager = profile_manager
        self.setWindowTitle(f"Куки и кэш — {profile.name}")
        self.setMinimumSize(560, 460)
        self.setStyleSheet(FLUENT_DARK_QSS)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(22, 20, 22, 20)

        lbl_title = QLabel(f"Менеджер сессий: {self.profile.name}", self)
        lbl_title.setStyleSheet("color: #ffffff; font-size: 18px; font-weight: 700;")
        layout.addWidget(lbl_title)

        lbl_desc = QLabel("Вставьте куки в формате JSON • Cookie-Editor, EditThisCookie или Netscape HTTP Cookie File.", self)
        lbl_desc.setStyleSheet("color: #a1a1aa; font-size: 12px;")
        layout.addWidget(lbl_desc)

        self.cookie_editor = TextEdit(self)
        self.cookie_editor.setPlaceholderText('[{"name": "SID", "value": "...", "domain": ".google.com", "path": "/"}]')
        
        # Pre-populate with existing cookies if available
        existing_cookies = self.profile_manager.load_profile_cookies(self.profile.id)
        if existing_cookies:
            import json
            self.cookie_editor.setText(json.dumps(existing_cookies, indent=2, ensure_ascii=False))
            
        layout.addWidget(self.cookie_editor)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self.btn_clear_cache = PushButton(FluentIcon.DELETE, "Очистить кэш", self)
        self.btn_clear_cache.clicked.connect(self.on_clear_cache)
        btn_layout.addWidget(self.btn_clear_cache)

        btn_layout.addStretch()

        self.btn_close = PushButton("Закрыть", self)
        self.btn_close.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_close)

        self.btn_import = PrimaryPushButton(FluentIcon.ACCEPT, "Импортировать", self)
        self.btn_import.clicked.connect(self.on_import_cookies)
        btn_layout.addWidget(self.btn_import)

        layout.addLayout(btn_layout)

    def on_import_cookies(self):
        text = self.cookie_editor.toPlainText().strip()
        if not text:
            InfoBar.warning("Пустые данные", "Вставьте куки в поле ввода", parent=self, position=InfoBarPosition.TOP)
            return

        cookies = parse_any_cookies(text)
        if not cookies:
            InfoBar.error("Ошибка парсинга", "Не удалось распознать формат JSON или Netscape", parent=self, position=InfoBarPosition.TOP)
            return

        # Persist cookies to profile storage
        self.profile_manager.save_profile_cookies(self.profile.id, cookies)
        InfoBar.success("Куки импортированы", f"Успешно сохранено {len(cookies)} записей в профиль!", parent=self, position=InfoBarPosition.TOP)
        self.accept()

    def on_clear_cache(self):
        self.profile_manager.clear_profile_cache(self.profile.id)
        InfoBar.success("Кэш очищен", "Кэш браузера и Service Workers удалены", parent=self, position=InfoBarPosition.TOP)
