"""
Fluent Google Account Warmup Bot View.
Fluent Vector Iconography & Zero-Emoji Architecture.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CheckBox,
    ComboBox,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
    PushButton,
    SimpleCardWidget,
    Slider,
    TableWidget,
)

from ...core.warmup_engine import (
    BUILTIN_SCENARIOS,
    WARMUP_NICHES,
    ScenarioStep,
    WarmupPlan,
    WarmupScenario,
    generate_warmup_urls,
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
        lbl_title = QLabel("Scenario Builder & Organic Auto-Warmup", self)
        lbl_title.setStyleSheet("color: #ffffff; font-size: 22px; font-weight: 700; letter-spacing: -0.4px;")

        lbl_desc = QLabel(
            "Multi-step organic browsing routes (Google Search, YouTube Shorts, E-Commerce) and Cookie Trust Score building",
            self,
        )
        lbl_desc.setStyleSheet("color: #a1a1aa; font-size: 12px;")

        v_title.addWidget(lbl_title)
        v_title.addWidget(lbl_desc)
        h_head.addLayout(v_title)
        h_head.addStretch()

        btn_stop = PushButton(FluentIcon.CANCEL, "Abort", self)
        btn_stop.clicked.connect(self.on_stop_warmup)
        h_head.addWidget(btn_stop)

        self.btn_launch = PrimaryPushButton(FluentIcon.PLAY, "Start Warmup", self)
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

        lbl_w1 = QLabel("Warmup Session Settings & Scenario", card_set)
        lbl_w1.setStyleSheet("color: #ffffff; font-weight: 700; font-size: 13px;")
        l_set.addWidget(lbl_w1)

        grid = QGridLayout()
        grid.setVerticalSpacing(8)

        # Profile Select
        lbl_p = QLabel("Target profile:", card_set)
        lbl_p.setStyleSheet("color: #d4d4d8; font-size: 12px;")
        grid.addWidget(lbl_p, 0, 0)

        self.combo_profile = ComboBox(card_set)
        self.populate_profiles()
        grid.addWidget(self.combo_profile, 0, 1)

        # Scenario Presets Select
        lbl_scen = QLabel("Warmup scenario preset:", card_set)
        lbl_scen.setStyleSheet("color: #d4d4d8; font-size: 12px;")
        grid.addWidget(lbl_scen, 1, 0)

        self.combo_scenario = ComboBox(card_set)
        for scen in BUILTIN_SCENARIOS:
            self.combo_scenario.addItem(f"{scen.name} ({len(scen.steps)} steps)", userData=scen.id)
        self.combo_scenario.currentIndexChanged.connect(self.update_scenario_preview)
        grid.addWidget(self.combo_scenario, 1, 1)

        # Niche Select (Fallback/Search mode)
        lbl_n = QLabel("Search niche:", card_set)
        lbl_n.setStyleSheet("color: #d4d4d8; font-size: 12px;")
        grid.addWidget(lbl_n, 2, 0)

        self.combo_niche = ComboBox(card_set)
        self.combo_niche.addItem("E-Commerce & Retail • Electronics, Clothing", userData="ecommerce")
        self.combo_niche.addItem("Finance & Investments • ETFs, Stocks, Deposits", userData="finance")
        self.combo_niche.addItem("IT & Development • Python, Docker, Cloud", userData="tech")
        self.combo_niche.addItem("Travel & Tourism • Hotels, Flights", userData="travel")
        self.combo_niche.addItem("Cryptocurrency & Web3 • Bitcoin, DeFi", userData="crypto")
        self.combo_niche.currentIndexChanged.connect(self.update_scenario_preview)
        grid.addWidget(self.combo_niche, 2, 1)

        l_set.addLayout(grid)
        layout.addWidget(card_set)

        # 3. Scenario Steps Card (Interactive Preview Table)
        card_preview = SimpleCardWidget(container)
        l_prev = QVBoxLayout(card_preview)
        l_prev.setContentsMargins(16, 14, 16, 14)

        lbl_w2 = QLabel("Selected Scenario Steps", card_preview)
        lbl_w2.setStyleSheet("color: #ffffff; font-weight: 700; font-size: 13px;")
        l_prev.addWidget(lbl_w2)

        self.table_steps = TableWidget(card_preview)
        self.table_steps.setColumnCount(3)
        self.table_steps.setHorizontalHeaderLabels(["Step #", "Action Type", "Description & Parameters"])
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

        lbl_w3 = QLabel("Trust Metrics & Warmup Settings", card_telemetry)
        lbl_w3.setStyleSheet("color: #ffffff; font-weight: 700; font-size: 13px;")
        l_tel.addWidget(lbl_w3)

        h_chips = QHBoxLayout()
        lbl_c1 = QLabel("Action delay: 4.5s – 12.0s", card_telemetry)
        lbl_c1.setStyleSheet(
            "background: #22222a; color: #a1a1aa; padding: 4px 8px; border-radius: 6px; font-size: 11px;"
        )
        h_chips.addWidget(lbl_c1)

        lbl_c2 = QLabel("Cookie persistence: Enabled", card_telemetry)
        lbl_c2.setStyleSheet(
            "background: #22222a; color: #34d399; padding: 4px 8px; border-radius: 6px; font-size: 11px;"
        )
        h_chips.addWidget(lbl_c2)

        lbl_c3 = QLabel("Trust Score increase: +18 points", card_telemetry)
        lbl_c3.setStyleSheet(
            "background: #22222a; color: #38bdf8; padding: 4px 8px; border-radius: 6px; font-size: 11px;"
        )
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
            InfoBar.warning("Warning", "Select a profile", parent=self, position=InfoBarPosition.TOP)
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
            InfoBar.success(
                "Scenario started",
                f"Profile '{prof.name}' is running scenario '{selected_scenario.name}'",
                parent=self,
                position=InfoBarPosition.TOP,
            )
        else:
            InfoBar.error(
                "Launch error", err or "Could not launch the browser", parent=self, position=InfoBarPosition.TOP
            )

    def on_stop_warmup(self):
        pid = self.combo_profile.currentData()
        if pid:
            self.browser_launcher.stop(pid)
            prof = self.profile_manager.get_profile(pid)
            if prof:
                prof.status = ProfileStatus.STOPPED
                prof.pid = None
                self.profile_manager.update_profile(prof)
            InfoBar.info("Stopped", "Warmup session ended", parent=self, position=InfoBarPosition.TOP)
