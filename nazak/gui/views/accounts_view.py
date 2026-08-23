"""
Accounts & Provisioning View.
Batch importer for marketplace Gmail accounts (Login:Pass:2FA:Recovery),
fingerprint auto-provisioning, TOTP token telemetry, and dual-mode posting setup (Browser Stealth vs OAuth API).
"""
import json
import time
from typing import Optional, List
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QHeaderView,
    QTableWidgetItem, QAbstractItemView
)
from PyQt6.QtCore import Qt, QTimer
from qfluentwidgets import (
    SimpleCardWidget, PrimaryPushButton, PushButton, LineEdit,
    TextEdit, ComboBox, TableWidget, SubtitleLabel, BodyLabel,
    CaptionLabel, FluentIcon, InfoBar, InfoBarPosition
)

from ...core.account_provisioner import AccountProvisioner, parse_account_string, generate_totp_rfc6238
from ...models.profile import BrowserProfile, ProfileStatus


class AccountsView(QWidget):
    def __init__(self, profile_manager, browser_launcher, parent=None):
        super().__init__(parent)
        self.setObjectName("AccountsView")
        self.profile_manager = profile_manager
        self.browser_launcher = browser_launcher
        self.provisioner = AccountProvisioner(self.profile_manager, self.profile_manager.profiles_dir)

        self.init_ui()
        self.refresh_table()

        # Real-time TOTP 1-second ticker
        self.totp_timer = QTimer(self)
        self.totp_timer.timeout.connect(self.refresh_totp_codes)
        self.totp_timer.start(1000)

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(16)

        # 1. Header with CTA
        header_layout = QHBoxLayout()
        titles_layout = QVBoxLayout()
        titles_layout.setSpacing(4)

        self.title_label = SubtitleLabel("Импорт и подготовка аккаунтов", self)
        self.title_label.setStyleSheet("font-family: 'Segoe UI Variable Display', 'Segoe UI', sans-serif; font-size: 22px; font-weight: 700; color: #ffffff;")
        
        self.desc_label = CaptionLabel("Пакетный импорт Gmail (Login:Pass:2FA:Recovery), создание отпечатков железа и авто-активация", self)
        self.desc_label.setStyleSheet("font-family: 'Segoe UI Variable Text', 'Segoe UI', sans-serif; font-size: 12px; color: #a1a1aa;")

        titles_layout.addWidget(self.title_label)
        titles_layout.addWidget(self.desc_label)
        header_layout.addLayout(titles_layout)
        header_layout.addStretch()

        self.btn_provision = PrimaryPushButton(FluentIcon.ADD, "Создать профили и активировать", self)
        self.btn_provision.clicked.connect(self.on_provision_clicked)
        header_layout.addWidget(self.btn_provision)

        main_layout.addLayout(header_layout)

        # 2. KPI Telemetry Cards
        kpi_layout = QHBoxLayout()
        kpi_layout.setSpacing(16)

        self.card_total = SimpleCardWidget(self)
        l_total = QVBoxLayout(self.card_total)
        l_total.setContentsMargins(16, 12, 16, 12)
        lbl_t1 = CaptionLabel("ВСЕГО ИМПОРТИРОВАНО", self.card_total)
        lbl_t1.setStyleSheet("color: #71717a; font-weight: 700; font-size: 11px;")
        self.lbl_val_total = BodyLabel("0", self.card_total)
        self.lbl_val_total.setStyleSheet("font-family: 'Segoe UI Variable Display', 'Segoe UI', sans-serif; font-size: 24px; font-weight: 700; color: #ffffff;")
        l_total.addWidget(lbl_t1)
        l_total.addWidget(self.lbl_val_total)

        self.card_mode = SimpleCardWidget(self)
        l_mode = QVBoxLayout(self.card_mode)
        l_mode.setContentsMargins(16, 12, 16, 12)
        lbl_m1 = CaptionLabel("РЕЖИМ ПОСТИНГА", self.card_mode)
        lbl_m1.setStyleSheet("color: #71717a; font-weight: 700; font-size: 11px;")
        self.lbl_val_mode = BodyLabel("Браузерный Stealth • YouTube Studio", self.card_mode)
        self.lbl_val_mode.setStyleSheet("font-family: 'Segoe UI Variable Text', 'Segoe UI', sans-serif; font-size: 15px; font-weight: 700; color: #38bdf8;")
        l_mode.addWidget(lbl_m1)
        l_mode.addWidget(self.lbl_val_mode)

        self.card_status = SimpleCardWidget(self)
        l_stat = QVBoxLayout(self.card_status)
        l_stat.setContentsMargins(16, 12, 16, 12)
        lbl_s1 = CaptionLabel("СТАТУС ИЗОЛЯЦИИ", self.card_status)
        lbl_s1.setStyleSheet("color: #71717a; font-weight: 700; font-size: 11px;")
        self.lbl_val_status = BodyLabel("100% Аппаратная маскировка", self.card_status)
        self.lbl_val_status.setStyleSheet("font-family: 'Segoe UI Variable Text', 'Segoe UI', sans-serif; font-size: 15px; font-weight: 700; color: #22c55e;")
        l_stat.addWidget(lbl_s1)
        l_stat.addWidget(self.lbl_val_status)

        kpi_layout.addWidget(self.card_total)
        kpi_layout.addWidget(self.card_mode)
        kpi_layout.addWidget(self.card_status)
        main_layout.addLayout(kpi_layout)

        # 3. Input & Setup Grid
        config_card = SimpleCardWidget(self)
        config_layout = QVBoxLayout(config_card)
        config_layout.setContentsMargins(18, 16, 18, 16)
        config_layout.setSpacing(12)

        lbl_input_title = BodyLabel("Пакетный ввод строк с маркетов (Retriv / DarkStore)", config_card)
        lbl_input_title.setStyleSheet("font-weight: 700; color: #ffffff;")
        config_layout.addWidget(lbl_input_title)

        self.txt_accounts = TextEdit(config_card)
        self.txt_accounts.setPlaceholderText(
            "Вставьте строки в формате:\n"
            "login@gmail.com:Password123:JBSWY3DPEHPK3PXP:recovery@mail.com\n"
            "login@gmail.com;Password123;JBSWY3DPEHPK3PXP;recovery@mail.com\n"
            "login@gmail.com|Password123|JBSWY3DPEHPK3PXP|recovery@mail.com"
        )
        self.txt_accounts.setFixedHeight(85)
        config_layout.addWidget(self.txt_accounts)

        # Controls Row
        ctrl_layout = QHBoxLayout()
        ctrl_layout.setSpacing(12)

        lbl_grp = CaptionLabel("Группа:", config_card)
        lbl_grp.setStyleSheet("color: #a1a1aa; font-weight: 600;")
        self.edit_group = LineEdit(config_card)
        self.edit_group.setText("Retriv Gmail 2020-2024")
        self.edit_group.setFixedWidth(200)

        lbl_pm = CaptionLabel("Режим постинга:", config_card)
        lbl_pm.setStyleSheet("color: #a1a1aa; font-weight: 600;")
        self.cmb_mode = ComboBox(config_card)
        self.cmb_mode.addItems([
            "Браузерный Stealth • YouTube Studio (Без лимитов API)",
            "YouTube Data API v3 • Google Cloud OAuth 2.0"
        ])
        self.cmb_mode.currentIndexChanged.connect(self.on_mode_changed)

        ctrl_layout.addWidget(lbl_grp)
        ctrl_layout.addWidget(self.edit_group)
        ctrl_layout.addSpacing(12)
        ctrl_layout.addWidget(lbl_pm)
        ctrl_layout.addWidget(self.cmb_mode)
        ctrl_layout.addStretch()

        config_layout.addLayout(ctrl_layout)
        main_layout.addWidget(config_card)

        # 4. Table of Provisioned Accounts
        self.table = TableWidget(self)
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "Email / Профиль", "Группа", "2FA Ключ", "Текущий 2FA Код", "Режим", "Действия"
        ])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setColumnWidth(3, 140)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setColumnWidth(5, 130)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)

        main_layout.addWidget(self.table, 1)

        # Timer to refresh TOTP codes every 15s
        self.totp_timer = QTimer(self)
        self.totp_timer.timeout.connect(self.refresh_totp_codes)
        self.totp_timer.start(15000)

    def on_mode_changed(self, idx):
        if idx == 0:
            self.lbl_val_mode.setText("Браузерный Stealth • YouTube Studio")
        else:
            self.lbl_val_mode.setText("Google Cloud OAuth 2.0 • Data API v3")

    def on_provision_clicked(self):
        raw_text = self.txt_accounts.toPlainText().strip()
        if not raw_text:
            InfoBar.warning(
                title="Пустой ввод",
                content="Вставьте хотя бы одну строку в формате login:pass:2fa:recovery.",
                parent=self,
                position=InfoBarPosition.TOP_RIGHT,
                duration=3500
            )
            return

        group = self.edit_group.text().strip() or "Imported"
        mode = "browser_stealth" if self.cmb_mode.currentIndex() == 0 else "oauth_api"

        created = self.provisioner.batch_import_and_create_profiles(
            raw_text=raw_text,
            group_name=group,
            posting_mode=mode
        )

        if created:
            self.txt_accounts.clear()
            self.refresh_table()
            InfoBar.success(
                title="Успешный импорт",
                content=f"Создано {len(created)} изолированных профилей с аппаратными отпечатками железа!",
                parent=self,
                position=InfoBarPosition.TOP_RIGHT,
                duration=4000
            )
        else:
            InfoBar.error(
                title="Ошибка парсинга",
                content="Не удалось распознать формат строк. Проверьте разделители (login:pass:2fa:recovery).",
                parent=self,
                position=InfoBarPosition.TOP_RIGHT,
                duration=4000
            )

    def refresh_table(self):
        profiles = self.profile_manager.list_profiles()
        imported = [
            p for p in profiles 
            if "Imported" in p.group or "Retriv" in p.group or "DarkStore" in p.group or "2FA" in p.google.tags or bool(p.google.notes and "account_email" in p.google.notes)
        ]
        
        self.lbl_val_total.setText(str(len(imported)))
        self.table.setRowCount(len(imported))

        for row, prof in enumerate(imported):
            notes = {}
            if prof.google.notes:
                try:
                    notes = json.loads(prof.google.notes)
                except Exception:
                    pass

            email = notes.get("account_email", prof.google.target_account_email or prof.name)
            totp_sec = notes.get("totp_secret", "")
            current_totp = generate_totp_rfc6238(totp_sec) if totp_sec else "—"
            mode = "Браузер" if notes.get("posting_mode") == "browser_stealth" else "OAuth API"

            item_email = QTableWidgetItem(f"{email} • {prof.name}")
            self.table.setItem(row, 0, item_email)

            item_grp = QTableWidgetItem(prof.group)
            self.table.setItem(row, 1, item_grp)

            item_sec = QTableWidgetItem(totp_sec if totp_sec else "—")
            item_sec.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 2, item_sec)

            item_code = QTableWidgetItem(current_totp)
            item_code.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 3, item_code)

            item_mode = QTableWidgetItem(mode)
            item_mode.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 4, item_mode)

            actions_widget = QWidget()
            act_layout = QHBoxLayout(actions_widget)
            act_layout.setContentsMargins(4, 2, 4, 2)
            act_layout.setSpacing(6)

            btn_launch = PrimaryPushButton(FluentIcon.PLAY, "Запуск", actions_widget)
            btn_launch.setFixedHeight(26)
            btn_launch.setFixedWidth(95)
            btn_launch.clicked.connect(lambda _, p=prof: self.launch_profile(p))
            act_layout.addWidget(btn_launch)

            self.table.setCellWidget(row, 5, actions_widget)

    def refresh_totp_codes(self):
        for row in range(self.table.rowCount()):
            sec_item = self.table.item(row, 2)
            if sec_item and sec_item.text() != "—":
                code = generate_totp_rfc6238(sec_item.text())
                code_item = self.table.item(row, 3)
                if code_item:
                    code_item.setText(code)

    def launch_profile(self, profile: BrowserProfile):
        try:
            ok, pid, err = self.browser_launcher.launch(profile)
            if ok:
                profile.status = ProfileStatus.RUNNING
                profile.pid = pid
                self.profile_manager.update_profile(profile)
                InfoBar.success(
                    title="Браузер запущен",
                    content=f"Профиль {profile.name} открыт в изолированном окне (PID {pid}).",
                    parent=self,
                    position=InfoBarPosition.TOP_RIGHT,
                    duration=3000
                )
            else:
                InfoBar.error(
                    title="Ошибка запуска",
                    content=err or "Не удалось запустить браузер",
                    parent=self,
                    position=InfoBarPosition.TOP_RIGHT,
                    duration=4000
                )
        except Exception as e:
            InfoBar.error(
                title="Исключение при запуске",
                content=str(e),
                parent=self,
                position=InfoBarPosition.TOP_RIGHT,
                duration=4000
            )
