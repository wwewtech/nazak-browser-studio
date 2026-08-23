"""
Fluent Proxy Bulk Manager & Diagnostics Inspector View.
Fluent Vector Iconography & Zero-Emoji Architecture.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidgetItem, QScrollArea, QLabel, QHeaderView
)
from PyQt6.QtCore import Qt
from qfluentwidgets import (
    TextEdit, LineEdit, PrimaryPushButton, PushButton,
    SimpleCardWidget, TableWidget, InfoBar, InfoBarPosition, FluentIcon
)

from ..workers import CheckAllProxiesWorker
from ...models.profile import BrowserProfile, ProxyConfig, GoogleSettings
from ...core.fingerprint_generator import generate_random_fingerprint
from ...models.health import HealthStatus

class ProxiesView(QWidget):
    def __init__(self, profile_manager, browser_launcher, parent=None):
        super().__init__(parent)
        self.profile_manager = profile_manager
        self.browser_launcher = browser_launcher
        self.setObjectName("proxies_view")
        self.init_ui()
        self.refresh_table()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(14)
        main_layout.setContentsMargins(24, 20, 24, 20)

        # Header
        lbl_title = QLabel("Прокси и пакетный импорт", self)
        lbl_title.setStyleSheet("color: #ffffff; font-size: 22px; font-weight: 700; letter-spacing: -0.4px;")
        
        lbl_desc = QLabel("Массовый ввод прокси HTTP / HTTPS / SOCKS5 с автоматической генерацией аппаратных отпечатков", self)
        lbl_desc.setStyleSheet("color: #a1a1aa; font-size: 12px;")
        
        main_layout.addWidget(lbl_title)
        main_layout.addWidget(lbl_desc)

        # 1. Bulk Import Card
        card_bulk = SimpleCardWidget(self)
        l_bulk = QVBoxLayout(card_bulk)
        l_bulk.setContentsMargins(16, 14, 16, 14)
        
        lbl_b1 = QLabel("Вставьте список прокси — 1 строка для каждого нового профиля", card_bulk)
        lbl_b1.setStyleSheet("color: #ffffff; font-weight: 700; font-size: 13px;")
        l_bulk.addWidget(lbl_b1)

        self.input_proxies = TextEdit(card_bulk)
        self.input_proxies.setMaximumHeight(90)
        self.input_proxies.setPlaceholderText("host:port:user:pass\nsocks5://user:pass@host:port\n192.168.1.1:8080")
        l_bulk.addWidget(self.input_proxies)

        h_bulk_actions = QHBoxLayout()
        self.input_group_name = LineEdit(card_bulk)
        self.input_group_name.setText("Google Ads")
        self.input_group_name.setPlaceholderText("Название группы...")
        h_bulk_actions.addWidget(self.input_group_name)

        btn_import = PrimaryPushButton(FluentIcon.FOLDER_ADD, "Импортировать и создать", card_bulk)
        
        btn_import.clicked.connect(self.on_bulk_import)
        h_bulk_actions.addWidget(btn_import)
        l_bulk.addLayout(h_bulk_actions)

        main_layout.addWidget(card_bulk)

        # 2. Live Diagnostic Table Card
        card_table = SimpleCardWidget(self)
        l_table = QVBoxLayout(card_table)
        l_table.setContentsMargins(16, 14, 16, 14)
        
        h_tbl_head = QHBoxLayout()
        lbl_t1 = QLabel("Таблица сетевой диагностики и Google Reachability", card_table)
        lbl_t1.setStyleSheet("color: #ffffff; font-weight: 700; font-size: 13px;")
        h_tbl_head.addWidget(lbl_t1)
        h_tbl_head.addStretch()

        btn_check_all = PushButton(FluentIcon.SEARCH, "Проверить все прокси", card_table)
        btn_check_all.clicked.connect(self.on_check_all)
        h_tbl_head.addWidget(btn_check_all)
        l_table.addLayout(h_tbl_head)

        self.table = TableWidget(card_table)
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "Профиль", "Прокси сервер", "Пинг", "Внешний IP • Страна", "Google Статус", "YouTube Доступ"
        ])
        
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        
        self.table.setColumnWidth(0, 240)
        self.table.setColumnWidth(1, 150)
        self.table.setColumnWidth(2, 80)
        self.table.setColumnWidth(3, 230)
        self.table.setColumnWidth(4, 120)

        l_table.addWidget(self.table)
        main_layout.addWidget(card_table)

    def refresh_table(self):
        profiles = self.profile_manager.list_profiles()
        self.table.setRowCount(len(profiles))
        for row, p in enumerate(profiles):
            self.table.setItem(row, 0, QTableWidgetItem(p.name))
            
            proxy_str = p.proxy.raw or f"{p.proxy.host}:{p.proxy.port}" if p.proxy.host else "Direct"
            self.table.setItem(row, 1, QTableWidgetItem(proxy_str))

            if p.last_health_check:
                h = p.last_health_check
                self.table.setItem(row, 2, QTableWidgetItem(f"{h.ping_ms or 1} ms"))
                
                country_part = f" • {h.country}" if h.country else ""
                self.table.setItem(row, 3, QTableWidgetItem(f"{h.ip or '-'}{country_part}"))
                
                g_status = "Google OK" if h.status == HealthStatus.HEALTHY else "DEAD"
                self.table.setItem(row, 4, QTableWidgetItem(g_status))
                
                yt_status = "Доступен" if h.google.youtube else "Блок"
                self.table.setItem(row, 5, QTableWidgetItem(yt_status))
            else:
                self.table.setItem(row, 2, QTableWidgetItem("-"))
                self.table.setItem(row, 3, QTableWidgetItem("-"))
                self.table.setItem(row, 4, QTableWidgetItem("Не проверен"))
                self.table.setItem(row, 5, QTableWidgetItem("-"))

    def on_bulk_import(self):
        text = self.input_proxies.toPlainText().strip()
        if not text:
            InfoBar.warning("Пустой ввод", "Вставьте строки прокси в поле", parent=self, position=InfoBarPosition.TOP)
            return

        lines = [l.strip() for l in text.splitlines() if l.strip()]
        grp = self.input_group_name.text().strip() or "Imported"
        
        created = 0
        start_idx = len(self.profile_manager.list_profiles()) + 1
        for idx, line in enumerate(lines, start=start_idx):
            p_conf = ProxyConfig.parse(line)
            fp = generate_random_fingerprint("windows")
            host_str = p_conf.host or "Direct"
            prof = BrowserProfile(
                name=f"Profile {idx:02d} • {host_str}",
                group=grp,
                proxy=p_conf,
                fingerprint=fp,
                google=GoogleSettings()
            )
            self.profile_manager.create_profile(prof)
            created += 1

        self.input_proxies.clear()
        self.refresh_table()
        InfoBar.success("Успешный импорт", f"Создано {created} профилей с уникальными отпечатками", parent=self, position=InfoBarPosition.TOP)

    def on_check_all(self):
        profs = self.profile_manager.list_profiles()
        InfoBar.info("Диагностика", f"Проверка {len(profs)} прокси...", parent=self, position=InfoBarPosition.TOP)
        
        self.worker = CheckAllProxiesWorker(profs, self.profile_manager.profiles_dir)
        self.worker.finished_signal.connect(self.on_checks_done)
        self.worker.start()

    def on_checks_done(self, results):
        for pid, res in results:
            prof = self.profile_manager.get_profile(pid)
            if prof:
                prof.last_health_check = res
                self.profile_manager.update_profile(prof)
        self.refresh_table()
        InfoBar.success("Готово", "Все прокси протестированы", parent=self, position=InfoBarPosition.TOP)
