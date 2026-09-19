"""
Fluent Application Settings View.
Fluent Iconography & Zero-Emoji Architecture.
"""

import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget
from qfluentwidgets import (
    ComboBox,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    PasswordLineEdit,
    PushButton,
    SimpleCardWidget,
    Theme,
    setTheme,
)

from ...config import DATA_DIR, PROFILES_DIR, PROFILES_FILE
from ...core import secrets_store
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

        # 3. Secrets Storage Card (user-selectable mode: plain / dpapi / passphrase)
        card_sec = SimpleCardWidget(self)
        l_sec = QVBoxLayout(card_sec)
        l_sec.setContentsMargins(16, 14, 16, 14)

        lbl_t_sec = QLabel("Secrets Storage (your choice)", card_sec)
        lbl_t_sec.setStyleSheet("color: #ffffff; font-weight: 700; font-size: 13px;")
        l_sec.addWidget(lbl_t_sec)

        lbl_sec_desc = QLabel(
            "Choose how account credentials (passwords, TOTP secrets) are stored:\n"
            "- Plain: readable, fastest, no protection.\n"
            "- DPAPI: encrypted by Windows for this user account (Windows only).\n"
            "- Passphrase: encrypted with your own passphrase (lost passphrase = lost data).",
            card_sec,
        )
        lbl_sec_desc.setStyleSheet("color: #a1a1aa; font-size: 11px;")
        l_sec.addWidget(lbl_sec_desc)

        h_sec = QHBoxLayout()
        lbl_mode = QLabel("Storage mode:", card_sec)
        lbl_mode.setStyleSheet("color: #d4d4d8; font-size: 12px;")
        h_sec.addWidget(lbl_mode)

        self.combo_secrets_mode = ComboBox(card_sec)
        self._mode_values = ["plain", "dpapi", "passphrase"] if os.name == "nt" else ["plain", "passphrase"]
        for m in self._mode_values:
            self.combo_secrets_mode.addItem(m.capitalize(), userData=m)
        self.combo_secrets_mode.setCurrentIndex(self._mode_values.index(secrets_store.get_current_mode()))
        h_sec.addWidget(self.combo_secrets_mode)

        self.edit_passphrase = PasswordLineEdit(card_sec)
        self.edit_passphrase.setPlaceholderText("Passphrase (passphrase mode only)")
        self.edit_passphrase.setFixedWidth(240)
        h_sec.addWidget(self.edit_passphrase)

        btn_apply = PushButton("Apply", card_sec)
        btn_apply.setIcon(FluentIcon.SAVE)
        btn_apply.clicked.connect(self.on_apply_secrets_mode)
        h_sec.addWidget(btn_apply)
        h_sec.addStretch()
        l_sec.addLayout(h_sec)
        main_layout.addWidget(card_sec)

        # 4. About Card
        card_about = SimpleCardWidget(self)
        l_about = QVBoxLayout(card_about)
        l_about.setContentsMargins(16, 14, 16, 14)

        lbl_t3 = QLabel("About", card_about)
        lbl_t3.setStyleSheet("color: #ffffff; font-weight: 700; font-size: 13px;")
        l_about.addWidget(lbl_t3)

        lbl_a1 = QLabel("Nazak Browser Studio v1.6.0", card_about)
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

    def on_apply_secrets_mode(self):
        """Persist the user's storage-mode choice; passphrase stays in RAM only."""
        mode = self.combo_secrets_mode.currentData()
        passphrase = self.edit_passphrase.text() or None
        try:
            secrets_store.set_mode_file(DATA_DIR / "secrets_mode.json")
            effective = secrets_store.set_current_mode(mode, passphrase=passphrase)
        except secrets_store.SecretsError as exc:
            InfoBar.error("Secrets mode rejected", str(exc), parent=self, position=InfoBarPosition.TOP)
            return
        self.edit_passphrase.clear()
        reencrypted = 0
        try:
            reencrypted = self._reencrypt_profile_secrets()
        except Exception:
            reencrypted = 0
        if effective == "plain":
            InfoBar.warning(
                "Plain mode active",
                "Credentials are stored unencrypted - your choice, noted for transparency.",
                parent=self,
                position=InfoBarPosition.TOP,
            )
        else:
            InfoBar.success(
                "Secrets mode updated",
                f"Mode '{effective}' applied; {reencrypted} profile(s) re-encrypted.",
                parent=self,
                position=InfoBarPosition.TOP,
            )

    def _reencrypt_profile_secrets(self) -> int:
        """Re-write existing profile notes in the newly selected mode."""
        from ..core.profile_manager import ProfileManager

        pm = ProfileManager(PROFILES_FILE, PROFILES_DIR)
        return pm.reencrypt_all_profile_secrets()
