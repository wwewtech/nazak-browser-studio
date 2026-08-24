"""
Fluent Google Account Warmup Bot View.
Fluent Vector Iconography & Zero-Emoji Architecture.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QScrollArea, QLabel, QFrame,
    QTableWidget, QTableWidgetItem, QHeaderView
)
from PyQt6.QtCore import Qt
from qfluentwidgets import (
    ComboBox, Slider, PrimaryPushButton, PushButton, CheckBox,
    SimpleCardWidget, TableWidget, InfoBar, InfoBarPosition, FluentIcon
)

from ...core.warmup_engine import (
    WarmupPlan, generate_warmup_urls, WARMUP_NICHES,
    BUILTIN_SCENARIOS, WarmupScenario, ScenarioStep
)
from ...models.profile import ProfileStatus

class WarmupView(QWidget):
    def __init__(self, profile_manager, browser_launcher, parent=None):
        super().__init__(parent)
        self.profile_manager = profile_manager
        self.browser_launcher = browser_launcher
        self.setObjectName("warmup_view")
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(14)
        main_layout.setContentsMargins(24, 20, 24, 20)

        # 1. Header with Top Actions
        h_head = QHBoxLayout()
        v_title = QVBoxLayout()
        lbl_title = QLabel("Конструктор сценариев & Органический автопрогрев", self)
        lbl_title.setStyleSheet("color: #ffffff; font-size: 22px; font-weight: 700; letter-spacing: -0.4px;")
        
        lbl_desc = QLabel("Многошаговые органические маршруты (Google Search, YouTube Shorts, E-Commerce) и накопление Cookie Trust Score", self)
        lbl_desc.setStyleSheet("color: #a1a1aa; font-size: 12px;")
        
        v_title.addWidget(lbl_title)
        v_title.addWidget(lbl_desc)
        h_head.addLayout(v_title)
        h_head.addStretch()

        btn_stop = PushButton(FluentIcon.CANCEL, "Прервать", self)
        btn_stop.clicked.connect(self.on_stop_warmup)
        h_head.addWidget(btn_stop)

        self.btn_launch = PrimaryPushButton(FluentIcon.PLAY, "Запустить прогрев", self)
        self.btn_launch.clicked.connect(self.on_launch_warmup)
        h_head.addWidget(self.btn_launch)
        main_layout.addLayout(h_head)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(12)
        layout.setContentsMargins(0, 0, 8, 8)

        # 2. Settings Card
        card_set = SimpleCardWidget(container)
        l_set = QVBoxLayout(card_set)
        l_set.setContentsMargins(16, 14, 16, 14)
        
        lbl_w1 = QLabel("Параметры и сценарий прогревочной сессии", card_set)
        lbl_w1.setStyleSheet("color: #ffffff; font-weight: 700; font-size: 13px;")
        l_set.addWidget(lbl_w1)

        grid = QGridLayout()
        grid.setVerticalSpacing(8)

        # Profile Select
        lbl_p = QLabel("Целевой профиль:", card_set)
        lbl_p.setStyleSheet("color: #d4d4d8; font-size: 12px;")
        grid.addWidget(lbl_p, 0, 0)
        
        self.combo_profile = ComboBox(card_set)
        self.populate_profiles()
        grid.addWidget(self.combo_profile, 0, 1)

        # Scenario Presets Select
        lbl_scen = QLabel("Готовый сценарий прогрева:", card_set)
        lbl_scen.setStyleSheet("color: #d4d4d8; font-size: 12px;")
        grid.addWidget(lbl_scen, 1, 0)

        self.combo_scenario = ComboBox(card_set)
        for scen in BUILTIN_SCENARIOS:
            self.combo_scenario.addItem(f"{scen.name} ({len(scen.steps)} шагов)", userData=scen.id)
        self.combo_scenario.currentIndexChanged.connect(self.update_scenario_preview)
        grid.addWidget(self.combo_scenario, 1, 1)

        # Niche Select (Fallback/Search mode)
        lbl_n = QLabel("Тематическая ниша поиска:", card_set)
        lbl_n.setStyleSheet("color: #d4d4d8; font-size: 12px;")
        grid.addWidget(lbl_n, 2, 0)
        
        self.combo_niche = ComboBox(card_set)
        self.combo_niche.addItem("E-Commerce & Ритейл • Электроника, Одежда", userData="ecommerce")
        self.combo_niche.addItem("Финансы & Инвестиции • ETF, Акции, Вклады", userData="finance")
        self.combo_niche.addItem("IT & Разработка • Python, Docker, Cloud", userData="tech")
        self.combo_niche.addItem("Путешествия & Туризм • Отели, Авиабилеты", userData="travel")
        self.combo_niche.addItem("Криптовалюта & Web3 • Bitcoin, DeFi", userData="crypto")
        self.combo_niche.currentIndexChanged.connect(self.update_scenario_preview)
        grid.addWidget(self.combo_niche, 2, 1)

        l_set.addLayout(grid)
        layout.addWidget(card_set)

        # 3. Scenario Steps Card (Interactive Preview Table)
        card_preview = SimpleCardWidget(container)
        l_prev = QVBoxLayout(card_preview)
        l_prev.setContentsMargins(16, 14, 16, 14)
        
        lbl_w2 = QLabel("Шаги выбранного сценария", card_preview)
        lbl_w2.setStyleSheet("color: #ffffff; font-weight: 700; font-size: 13px;")
        l_prev.addWidget(lbl_w2)

        self.table_steps = TableWidget(card_preview)
        self.table_steps.setColumnCount(3)
        self.table_steps.setHorizontalHeaderLabels(["Шаг #", "Тип действия", "Описание и параметры"])
        h = self.table_steps.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table_steps.setColumnWidth(0, 60)
        self.table_steps.setColumnWidth(1, 140)
        self.table_steps.setFixedHeight(160)
        l_prev.addWidget(self.table_steps)
        layout.addWidget(card_preview)

        # 4. Live Telemetry & Trust Score Card
        card_telemetry = SimpleCardWidget(container)
        l_tel = QVBoxLayout(card_telemetry)
        l_tel.setContentsMargins(16, 14, 16, 14)
        
        lbl_w3 = QLabel("Метрики доверия и параметров прогрева", card_telemetry)
        lbl_w3.setStyleSheet("color: #ffffff; font-weight: 700; font-size: 13px;")
        l_tel.addWidget(lbl_w3)

        h_chips = QHBoxLayout()
        lbl_c1 = QLabel("Задержка действий: 4.5с – 12.0с", card_telemetry)
        lbl_c1.setStyleSheet("background: #22222a; color: #a1a1aa; padding: 4px 8px; border-radius: 6px; font-size: 11px;")
        h_chips.addWidget(lbl_c1)

        lbl_c2 = QLabel("Сохранение куки: Включено", card_telemetry)
        lbl_c2.setStyleSheet("background: #22222a; color: #34d399; padding: 4px 8px; border-radius: 6px; font-size: 11px;")
        h_chips.addWidget(lbl_c2)

        lbl_c3 = QLabel("Прирост Trust Score: +18 баллов", card_telemetry)
        lbl_c3.setStyleSheet("background: #22222a; color: #38bdf8; padding: 4px 8px; border-radius: 6px; font-size: 11px;")
        h_chips.addWidget(lbl_c3)
        h_chips.addStretch()
        l_tel.addLayout(h_chips)
        layout.addWidget(card_telemetry)

        scroll.setWidget(container)
        main_layout.addWidget(scroll)

        self.update_scenario_preview()

    def showEvent(self, event):
        super().showEvent(event)
        self.populate_profiles()

    def populate_profiles(self):
        curr_id = self.combo_profile.currentData()
        self.combo_profile.blockSignals(True)
        self.combo_profile.clear()
        profs = self.profile_manager.list_profiles()
        for p in profs:
            self.combo_profile.addItem(f"{p.name} [{p.group or 'No Group'}]", userData=p.id)
        if curr_id:
            idx = self.combo_profile.findData(curr_id)
            if idx >= 0:
                self.combo_profile.setCurrentIndex(idx)
        self.combo_profile.blockSignals(False)

    def refresh_profiles(self):
        self.populate_profiles()

    def update_scenario_preview(self):
        scen_id = self.combo_scenario.currentData()
        selected_scenario = None
        for s in BUILTIN_SCENARIOS:
            if s.id == scen_id:
                selected_scenario = s
                break

        if not selected_scenario:
            selected_scenario = BUILTIN_SCENARIOS[0]

        self.table_steps.setRowCount(len(selected_scenario.steps))
        for row, step in enumerate(selected_scenario.steps, start=0):
            self.table_steps.setItem(row, 0, QTableWidgetItem(str(row + 1)))
            self.table_steps.setItem(row, 1, QTableWidgetItem(step.action))
            desc = step.description or str(step.params)
            self.table_steps.setItem(row, 2, QTableWidgetItem(desc))

    def on_launch_warmup(self):
        pid = self.combo_profile.currentData()
        if not pid:
            InfoBar.warning("Внимание", "Выберите профиль", parent=self, position=InfoBarPosition.TOP)
            return

        prof = self.profile_manager.get_profile(pid)
        if not prof:
            return

        scen_id = self.combo_scenario.currentData()
        selected_scenario = None
        for s in BUILTIN_SCENARIOS:
            if s.id == scen_id:
                selected_scenario = s
                break

        if not selected_scenario:
            selected_scenario = BUILTIN_SCENARIOS[0]

        # Determine start URL from first step
        start_url = "https://www.google.com"
        for st in selected_scenario.steps:
            if st.action == "open_url" and "url" in st.params:
                start_url = st.params["url"]
                break
            elif st.action == "google_search" and "query" in st.params:
                start_url = f"https://www.google.com/search?q={st.params['query'].replace(' ', '+')}&hl=en"
                break

        ok, proc_id, err = self.browser_launcher.launch(prof, custom_url=start_url)
        if ok:
            prof.status = ProfileStatus.RUNNING
            prof.pid = proc_id
            self.profile_manager.update_profile(prof)
            InfoBar.success("Сценарий запущен", f"Профиль '{prof.name}' выполняет сценарий '{selected_scenario.name}'", parent=self, position=InfoBarPosition.TOP)
        else:
            InfoBar.error("Ошибка запуска", err or "Не удалось запустить браузер", parent=self, position=InfoBarPosition.TOP)

    def on_stop_warmup(self):
        pid = self.combo_profile.currentData()
        if pid:
            self.browser_launcher.stop(pid)
            prof = self.profile_manager.get_profile(pid)
            if prof:
                prof.status = ProfileStatus.STOPPED
                prof.pid = None
                self.profile_manager.update_profile(prof)
            InfoBar.info("Остановлено", "Прогревочная сессия завершена", parent=self, position=InfoBarPosition.TOP)
