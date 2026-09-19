"""GUI card: user-selected secrets storage mode.

Order: from none -> to dpapi -> to passphrase. plain = keep as-is.
"""

from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ...core.secrets_store import (
    SECRETS_MODES,
    SecretsError,
    get_current_mode,
    set_current_mode,
)


class SecretsModeCard(QGroupBox):
    """Let the user choose how account secrets are stored at rest.

    The choice is entirely the user's; the app never forces a mode.
    Switching to a stronger mode re-encrypts existing profiles in-place.
    """

    def __init__(self, parent=None):
        super().__init__("Security — Secrets Storage Mode", parent)
        self._build_ui()
        self._reload_current()

    def _build_ui(self):
        lay = QVBoxLayout(self)

        info = QLabel(
            "Choose how account passwords / TOTP secrets are stored on disk.\n"
            "• plain — readable (fastest; no protection)\n"
            "• dpapi — Windows user-bound encryption, no passphrase needed\n"
            "• passphrase — encrypted with YOUR passphrase (lost passphrase = data lost)"
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #9aa4b2; font-size: 12px;")
        lay.addWidget(info)

        row = QHBoxLayout()
        self.mode_combo = QComboBox()
        for m in SECRETS_MODES:
            self.mode_combo.addItem(m, m)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_selected)
        row.addWidget(QLabel("Mode:"))
        row.addWidget(self.mode_combo, 1)

        self.passphrase_edit = QLineEdit()
        self.passphrase_edit.setPlaceholderText("Passphrase (for 'passphrase' mode only)")
        self.passphrase_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.passphrase_edit.setVisible(False)
        row.addWidget(self.passphrase_edit, 2)
        lay.addLayout(row)

        btn_row = QHBoxLayout()
        self.apply_btn = QPushButton("Apply & re-encrypt profiles")
        self.apply_btn.clicked.connect(self._apply_mode)
        btn_row.addWidget(self.apply_btn)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        lay.addWidget(self.status_label)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: #333;")
        lay.addWidget(line)

    def _reload_current(self):
        mode = get_current_mode()
        idx = self.mode_combo.findData(mode)
        if idx >= 0:
            self.mode_combo.blockSignals(True)
            self.mode_combo.setCurrentIndex(idx)
            self.mode_combo.blockSignals(False)
        self.passphrase_edit.setVisible(mode == "passphrase")
        self.status_label.setText(f"Active mode: {mode}")

    def _on_mode_selected(self):
        m = self.mode_combo.currentData()
        self.passphrase_edit.setVisible(m == "passphrase")

    def _apply_mode(self):
        mode = self.mode_combo.currentData()
        passphrase = self.passphrase_edit.text() or None

        if mode == "passphrase" and not passphrase:
            QMessageBox.warning(
                self,
                "Passphrase required",
                "Enter a passphrase to use this mode, or pick dpapi/plain.",
            )
            return

        confirm = QMessageBox.question(
            self,
            "Confirm mode switch",
            f"Switch secrets mode to '{mode}' and re-encrypt existing profiles now?",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        try:
            effective = set_current_mode(mode, passphrase=passphrase)
        except SecretsError as exc:
            QMessageBox.critical(self, "Failed", str(exc))
            return

        re_count = self._reencrypt_existing_profiles()
        self.status_label.setText(f"Active mode: {effective} (re-encrypted {re_count} profiles)")
        QMessageBox.information(
            self,
            "Done",
            f"Mode '{effective}' applied. {re_count} profile(s) re-encrypted.",
        )

    def _reencrypt_existing_profiles(self) -> int:
        """Re-write every profile's notes in the newly selected mode.

        Delegates to the canonical ``ProfileManager.reencrypt_all_profile_secrets``
        which reveals plaintext before re-encrypting (never re-encrypts masked
        display values).
        """
        from ...config import PROFILES_DIR, PROFILES_FILE
        from ...core.profile_manager import ProfileManager

        pm = ProfileManager(PROFILES_FILE, PROFILES_DIR)
        return pm.reencrypt_all_profile_secrets()
