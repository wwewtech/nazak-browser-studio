"""
Fluent Profiles Dashboard View.
Windows 11 Fluent Iconography & Zero-Emoji Typography Architecture.
"""
from pathlib import Path
from typing import List, Dict, Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QScrollArea, QFrame, QLabel
)
from PyQt6.QtCore import Qt, pyqtSignal as Signal, QTimer
from qfluentwidgets import (
    SearchLineEdit, PrimaryPushButton, PushButton,
    SubtitleLabel, BodyLabel, CaptionLabel, SimpleCardWidget,
    InfoBar, InfoBarPosition, ComboBox, FluentIcon
)

from ..dialogs.profile_edit_dialog import ProfileEditDialog
from ..dialogs.cookie_dialog import CookieManagerDialog
from ..workers import ProxyCheckWorker, CheckAllProxiesWorker
from ...models.profile import BrowserProfile, ProfileStatus
from ...models.health import HealthStatus
from ...core.browser_launcher import find_chrome_executable

class ProfileCard(SimpleCardWidget):
    launch_clicked = Signal(str)
    stop_clicked = Signal(str)
    check_clicked = Signal(str)
    cookies_clicked = Signal(str)
    edit_clicked = Signal(str)
    clone_clicked = Signal(str)
    delete_clicked = Signal(str)

    def __init__(self, profile: BrowserProfile, is_running: bool = False, parent=None):
        super().__init__(parent)
        self.profile = profile
        self.is_running = is_running
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 14, 16, 14)

        # 1. Header: Name + Status Badge Pill
        h_top = QHBoxLayout()
        self.lbl_name = QLabel(self.profile.name, self)
        self.lbl_name.setStyleSheet("color: #ffffff; font-weight: 700; font-size: 13px;")
        h_top.addWidget(self.lbl_name)
        h_top.addStretch()

        self.lbl_status = QLabel(self._get_status_text(), self)
        self.lbl_status.setStyleSheet(self._get_status_style())
        h_top.addWidget(self.lbl_status)
        layout.addLayout(h_top)

        # 2. Hardware Specs Chip (Clean Monospace Telemetry)
        fp = self.profile.fingerprint
        gpu_raw = (fp.webgl_unmasked_renderer or fp.webgl_renderer or "Integrated GPU") if fp else "Integrated GPU"
        gpu_short = str(gpu_raw).replace("(R)", "").replace("(TM)", "").replace("NVIDIA GeForce ", "").replace("AMD Radeon ", "").replace("Graphics", "").replace("  ", " ").strip()
        cores = fp.hardware_concurrency if fp else 16
        ram = fp.device_memory if fp else 32
        w = fp.screen_width if fp else 1920
        h = fp.screen_height if fp else 1080
        hw_text = f"GPU: {gpu_short}  •  {cores} Cores  •  {ram} GB  •  {w}×{h}"
        
        lbl_hw = QLabel(hw_text, self)
        lbl_hw.setStyleSheet(
            "background-color: #22222a; color: #d4d4d8; font-size: 11px; "
            "font-family: 'Segoe UI Variable Text', monospace; border: 1px solid #2e2e3a; "
            "border-radius: 6px; padding: 4px 8px;"
        )
        layout.addWidget(lbl_hw)

        # 3. Network & Proxy Diagnostic Chip
        proxy = self.profile.proxy
        proxy_str = f"{proxy.host}:{proxy.port}" if proxy.host else "Direct Connection"
        
        diag_str = "Не проверен"
        diag_color = "#71717a"
        if self.profile.last_health_check:
            h = self.profile.last_health_check
            if h.status == HealthStatus.HEALTHY:
                city_part = f" • {h.city}" if h.city else ""
                diag_str = f"Google OK{city_part} • {h.ping_ms or 1} ms"
                diag_color = "#34d399"
            elif h.status == HealthStatus.DEAD:
                diag_str = "Прокси недоступен"
                diag_color = "#f87171"
            else:
                diag_str = f"Online • {h.city or 'Ready'}"
                diag_color = "#fbbf24"

        h_net = QHBoxLayout()
        lbl_proxy = QLabel(f"Proxy: {proxy_str}", self)
        lbl_proxy.setStyleSheet("color: #a1a1aa; font-size: 11px; font-weight: 500;")
        h_net.addWidget(lbl_proxy)
        h_net.addStretch()

        lbl_diag = QLabel(diag_str, self)
        lbl_diag.setStyleSheet(f"color: {diag_color}; font-size: 11px; font-weight: 600;")
        h_net.addWidget(lbl_diag)
        layout.addLayout(h_net)

        # 4. Action Buttons Toolbar with Fluent Vector Icons
        h_actions = QHBoxLayout()
        h_actions.setSpacing(6)

        if self.is_running:
            self.btn_action = PushButton(FluentIcon.PAUSE, "Стоп", self)
            
            self.btn_action.clicked.connect(lambda: self.stop_clicked.emit(self.profile.id))
        else:
            self.btn_action = PrimaryPushButton(FluentIcon.PLAY, "Запуск", self)
            
            self.btn_action.clicked.connect(lambda: self.launch_clicked.emit(self.profile.id))
        h_actions.addWidget(self.btn_action)

        btn_check = PushButton(FluentIcon.ZOOM, "Тест", self)
        btn_check.clicked.connect(lambda: self.check_clicked.emit(self.profile.id))
        h_actions.addWidget(btn_check)

        btn_cookies = PushButton(FluentIcon.DOCUMENT, "Куки", self)
        btn_cookies.setToolTip("Менеджер куки и очистка кэша")
        btn_cookies.clicked.connect(lambda: self.cookies_clicked.emit(self.profile.id))
        h_actions.addWidget(btn_cookies)

        btn_edit = PushButton(FluentIcon.SETTING, "Опции", self)
        btn_edit.setToolTip("Настройка профиля и железа")
        btn_edit.clicked.connect(lambda: self.edit_clicked.emit(self.profile.id))
        h_actions.addWidget(btn_edit)

        btn_clone = PushButton(FluentIcon.COPY, "Клон", self)
        btn_clone.setToolTip("Клонировать с новыми отпечатками")
        btn_clone.clicked.connect(lambda: self.clone_clicked.emit(self.profile.id))
        h_actions.addWidget(btn_clone)

        btn_delete = PushButton(FluentIcon.DELETE, "", self)
        btn_delete.setToolTip("Удалить профиль")
        btn_delete.setStyleSheet("background-color: #222228; color: #f87171; border: 1px solid #382424;")
        btn_delete.clicked.connect(lambda: self.delete_clicked.emit(self.profile.id))
        h_actions.addWidget(btn_delete)

        layout.addLayout(h_actions)

    def _get_status_text(self) -> str:
        if self.is_running:
            return f"RUNNING • PID {self.profile.pid or ''}"
        elif self.profile.status == ProfileStatus.ERROR:
            return "ERROR"
        return "STOPPED"

    def _get_status_style(self) -> str:
        if self.is_running:
            return "background-color: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.4); border-radius: 10px; padding: 2px 8px; font-weight: 700; font-size: 10px;"
        elif self.profile.status == ProfileStatus.ERROR:
            return "background-color: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.4); border-radius: 10px; padding: 2px 8px; font-weight: 700; font-size: 10px;"
        return "background-color: rgba(113, 113, 122, 0.15); color: #a1a1aa; border: 1px solid rgba(113, 113, 122, 0.3); border-radius: 10px; padding: 2px 8px; font-weight: 600; font-size: 10px;"


class ProfilesView(QWidget):
    def __init__(self, profile_manager, browser_launcher, parent=None):
        super().__init__(parent)
        self.profile_manager = profile_manager
        self.browser_launcher = browser_launcher
        self.setObjectName("profiles_view")
        self.init_ui()
        self.refresh_profiles()

        # Background process poller timer (1.5s)
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self._poll_running_state)
        self.poll_timer.start(1500)

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(14)
        main_layout.setContentsMargins(24, 20, 24, 20)

        # 1. Header & Metrics Bar
        h_head = QHBoxLayout()
        v_title = QVBoxLayout()
        
        lbl_title = QLabel("Управление профилями браузера", self)
        lbl_title.setStyleSheet("color: #ffffff; font-size: 22px; font-weight: 700; letter-spacing: -0.4px;")
        
        lbl_desc = QLabel("100% аппаратная изоляция железа, защита от сканирования портов и чистые сессии", self)
        lbl_desc.setStyleSheet("color: #a1a1aa; font-size: 12px;")
        
        v_title.addWidget(lbl_title)
        v_title.addWidget(lbl_desc)
        h_head.addLayout(v_title)
        h_head.addStretch()

        self.btn_new_prof = PrimaryPushButton(FluentIcon.ADD, "Новый профиль", self)
        
        self.btn_new_prof.clicked.connect(self.on_create_profile)
        h_head.addWidget(self.btn_new_prof)
        main_layout.addLayout(h_head)

        # 2. Telemetry KPI Cards Strip
        h_metrics = QHBoxLayout()
        h_metrics.setSpacing(12)

        # Card 1: Total
        self.card_total = SimpleCardWidget(self)
        l1 = QVBoxLayout(self.card_total)
        l1.setContentsMargins(14, 12, 14, 12)
        lbl_t1 = QLabel("Всего профилей", self.card_total)
        lbl_t1.setStyleSheet("color: #a1a1aa; font-size: 11px; font-weight: 600; text-transform: uppercase;")
        self.lbl_metric_total = QLabel("10", self.card_total)
        self.lbl_metric_total.setStyleSheet("color: #ffffff; font-size: 26px; font-weight: 700;")
        l1.addWidget(lbl_t1)
        l1.addWidget(self.lbl_metric_total)
        h_metrics.addWidget(self.card_total)

        # Card 2: Active
        self.card_active = SimpleCardWidget(self)
        l2 = QVBoxLayout(self.card_active)
        l2.setContentsMargins(14, 12, 14, 12)
        lbl_t2 = QLabel("Активных браузеров", self.card_active)
        lbl_t2.setStyleSheet("color: #a1a1aa; font-size: 11px; font-weight: 600; text-transform: uppercase;")
        self.lbl_metric_active = QLabel("0", self.card_active)
        self.lbl_metric_active.setStyleSheet("color: #34d399; font-size: 26px; font-weight: 700;")
        l2.addWidget(lbl_t2)
        l2.addWidget(self.lbl_metric_active)
        h_metrics.addWidget(self.card_active)

        # Card 3: Reachability
        self.card_reach = SimpleCardWidget(self)
        l3 = QVBoxLayout(self.card_reach)
        l3.setContentsMargins(14, 12, 14, 12)
        lbl_t3 = QLabel("Google Reachability", self.card_reach)
        lbl_t3.setStyleSheet("color: #a1a1aa; font-size: 11px; font-weight: 600; text-transform: uppercase;")
        self.lbl_metric_reach = QLabel("100%", self.card_reach)
        self.lbl_metric_reach.setStyleSheet("color: #38bdf8; font-size: 26px; font-weight: 700;")
        l3.addWidget(lbl_t3)
        l3.addWidget(self.lbl_metric_reach)
        h_metrics.addWidget(self.card_reach)

        main_layout.addLayout(h_metrics)

        # 3. Search & Command Bar Container
        card_cmd = SimpleCardWidget(self)
        h_cmd = QHBoxLayout(card_cmd)
        h_cmd.setContentsMargins(10, 8, 10, 8)
        h_cmd.setSpacing(10)

        self.search_box = SearchLineEdit(card_cmd)
        self.search_box.setPlaceholderText("Поиск профилей по имени, группе, прокси...")
        self.search_box.textChanged.connect(self.on_filter_changed)
        h_cmd.addWidget(self.search_box, stretch=2)

        self.combo_group = ComboBox(card_cmd)
        self.combo_group.addItem("Все группы")
        self.combo_group.currentIndexChanged.connect(self.on_filter_changed)
        h_cmd.addWidget(self.combo_group, stretch=1)

        self.btn_check_all = PushButton(FluentIcon.SEARCH, "Проверить все", card_cmd)
        self.btn_check_all.clicked.connect(self.on_check_all_proxies)
        h_cmd.addWidget(self.btn_check_all)

        self.btn_stop_all = PushButton(FluentIcon.PAUSE, "Остановить все", card_cmd)
        self.btn_stop_all.clicked.connect(self.on_stop_all)
        h_cmd.addWidget(self.btn_stop_all)

        main_layout.addWidget(card_cmd)

        # 4. Scrollable Profiles Grid
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)

        self.grid_container = QWidget()
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setSpacing(12)
        self.grid_layout.setContentsMargins(0, 0, 8, 0)
        self.scroll.setWidget(self.grid_container)

        main_layout.addWidget(self.scroll)

    def _poll_running_state(self):
        profiles = self.profile_manager.list_profiles()
        running_cnt = sum(1 for p in profiles if self.browser_launcher.is_profile_running(p.id))
        if self.lbl_metric_active.text() != str(running_cnt):
            self.lbl_metric_active.setText(str(running_cnt))
            self.refresh_profiles()

    def refresh_profiles(self):
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        query = self.search_box.text().strip().lower()
        selected_group = self.combo_group.currentText()

        profiles = self.profile_manager.list_profiles()
        
        self.lbl_metric_total.setText(str(len(profiles)))
        running_cnt = sum(1 for p in profiles if self.browser_launcher.is_profile_running(p.id))
        self.lbl_metric_active.setText(str(running_cnt))

        groups = sorted(list(set(p.group for p in profiles if p.group)))
        current_g = self.combo_group.currentText()
        self.combo_group.blockSignals(True)
        self.combo_group.clear()
        self.combo_group.addItem("Все группы")
        for g in groups:
            self.combo_group.addItem(g)
        idx = self.combo_group.findText(current_g)
        if idx >= 0:
            self.combo_group.setCurrentIndex(idx)
        self.combo_group.blockSignals(False)

        filtered = []
        for p in profiles:
            if selected_group != "Все группы" and p.group != selected_group:
                continue
            if query and query not in p.name.lower() and query not in (p.proxy.host or "").lower():
                continue
            filtered.append(p)

        for i, p in enumerate(filtered):
            is_run = self.browser_launcher.is_profile_running(p.id)
            card = ProfileCard(p, is_running=is_run, parent=self.grid_container)
            card.launch_clicked.connect(self.on_launch_profile)
            card.stop_clicked.connect(self.on_stop_profile)
            card.check_clicked.connect(self.on_check_single_proxy)
            card.cookies_clicked.connect(self.on_open_cookies)
            card.edit_clicked.connect(self.on_edit_profile)
            card.clone_clicked.connect(self.on_clone_profile)
            card.delete_clicked.connect(self.on_delete_profile)
            self.grid_layout.addWidget(card, i // 2, i % 2)

    def on_filter_changed(self):
        self.refresh_profiles()

    def on_create_profile(self):
        diag = ProfileEditDialog(profile=None, profile_manager=self.profile_manager, parent=self)
        if diag.exec():
            self.refresh_profiles()
            InfoBar.success("Профиль создан", "Новый изолированный профиль добавлен", parent=self, position=InfoBarPosition.TOP)

    def on_edit_profile(self, profile_id: str):
        prof = self.profile_manager.get_profile(profile_id)
        if prof:
            diag = ProfileEditDialog(profile=prof, profile_manager=self.profile_manager, parent=self)
            if diag.exec():
                self.refresh_profiles()
                InfoBar.success("Профиль обновлен", f"Настройки '{prof.name}' сохранены", parent=self, position=InfoBarPosition.TOP)

    def on_open_cookies(self, profile_id: str):
        prof = self.profile_manager.get_profile(profile_id)
        if prof:
            diag = CookieManagerDialog(profile=prof, profile_manager=self.profile_manager, parent=self)
            diag.exec()

    def on_launch_profile(self, profile_id: str):
        prof = self.profile_manager.get_profile(profile_id)
        if not prof:
            return
            
        chrome_exe = find_chrome_executable()
        if not chrome_exe:
            InfoBar.error("Chromium не найден", "Установите Google Chrome или Edge для запуска профилей", parent=self, position=InfoBarPosition.TOP)
            return

        ok, pid, err = self.browser_launcher.launch(prof)
        if ok:
            prof.status = ProfileStatus.RUNNING
            prof.pid = pid
            self.profile_manager.update_profile(prof)
            self.refresh_profiles()
            InfoBar.success("Браузер запущен", f"Профиль '{prof.name}' • PID {pid}", parent=self, position=InfoBarPosition.TOP)
        else:
            InfoBar.error("Ошибка запуска", err or "Не удалось запустить Chromium", parent=self, position=InfoBarPosition.TOP)

    def on_stop_profile(self, profile_id: str):
        self.browser_launcher.stop(profile_id)
        prof = self.profile_manager.get_profile(profile_id)
        if prof:
            prof.status = ProfileStatus.STOPPED
            prof.pid = None
            self.profile_manager.update_profile(prof)
        self.refresh_profiles()
        InfoBar.info("Профиль остановлен", f"Браузер '{prof.name if prof else profile_id}' закрыт", parent=self, position=InfoBarPosition.TOP)

    def on_stop_all(self):
        for p in self.profile_manager.list_profiles():
            self.browser_launcher.stop(p.id)
            p.status = ProfileStatus.STOPPED
            p.pid = None
            self.profile_manager.update_profile(p)
        self.refresh_profiles()
        InfoBar.info("Все остановлены", "Все запущенные процессы браузера завершены", parent=self, position=InfoBarPosition.TOP)

    def on_check_single_proxy(self, profile_id: str):
        prof = self.profile_manager.get_profile(profile_id)
        if not prof:
            return
        
        InfoBar.info("Проверка...", f"Тестирование связи для {prof.name}", parent=self, position=InfoBarPosition.TOP)
        
        self.check_worker = ProxyCheckWorker(
            profile_id=profile_id,
            proxy_config=prof.proxy,
            profile_dir=self.profile_manager.profiles_dir / profile_id
        )
        self.check_worker.finished_signal.connect(self._on_single_check_done)
        self.check_worker.start()

    def _on_single_check_done(self, profile_id: str, res):
        prof = self.profile_manager.get_profile(profile_id)
        if prof:
            prof.last_health_check = res
            if res.latitude and res.longitude:
                prof.fingerprint.geolocation.latitude = res.latitude
                prof.fingerprint.geolocation.longitude = res.longitude
            if res.timezone_name:
                prof.fingerprint.timezone = res.timezone_name
            self.profile_manager.update_profile(prof)
            self.refresh_profiles()
            
            if res.status == HealthStatus.HEALTHY:
                city_str = f" • {res.city}" if res.city else ""
                InfoBar.success("Прокси в норме", f"{prof.name}: Google OK{city_str} • {res.ping_ms or 1} ms", parent=self, position=InfoBarPosition.TOP)
            else:
                InfoBar.warning("Внимание", f"{prof.name}: {res.error_message or 'Сбои сервисов'}", parent=self, position=InfoBarPosition.TOP)

    def on_check_all_proxies(self):
        profs = self.profile_manager.list_profiles()
        InfoBar.info("Запуск проверки", f"Проверка {len(profs)} прокси...", parent=self, position=InfoBarPosition.TOP)
        
        self.all_worker = CheckAllProxiesWorker(profs, self.profile_manager.profiles_dir)
        self.all_worker.finished_signal.connect(self._on_all_checks_done)
        self.all_worker.start()

    def _on_all_checks_done(self, results):
        for pid, res in results:
            prof = self.profile_manager.get_profile(pid)
            if prof:
                prof.last_health_check = res
                self.profile_manager.update_profile(prof)
        self.refresh_profiles()
        InfoBar.success("Проверка завершена", "Все профили протестированы!", parent=self, position=InfoBarPosition.TOP)

    def on_clone_profile(self, profile_id: str):
        cloned = self.profile_manager.clone_profile(profile_id)
        if cloned:
            self.refresh_profiles()
            InfoBar.success("Профиль клонирован", f"Создана копия '{cloned.name}' с новыми отпечатками", parent=self, position=InfoBarPosition.TOP)

    def on_delete_profile(self, profile_id: str):
        prof = self.profile_manager.get_profile(profile_id)
        pname = prof.name if prof else profile_id
        self.browser_launcher.stop(profile_id)
        self.profile_manager.delete_profile(profile_id, delete_data=True)
        self.refresh_profiles()
        InfoBar.info("Профиль удален", f"'{pname}' и его данные удалены", parent=self, position=InfoBarPosition.TOP)
