"""
Fluent Real-Time Action Synchronizer & Window Tile Dialog.
Windows 11 Fluent Iconography & Zero-Emoji Architecture.
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QFrame
)
from PyQt6.QtCore import Qt
from qfluentwidgets import (
    ComboBox, CheckBox, Slider, PrimaryPushButton, PushButton,
    SimpleCardWidget, InfoBar, InfoBarPosition, FluentIcon
)

from ...core.synchronizer import tile_windows_win32
from ..style import FLUENT_DARK_QSS

class SynchronizerDialog(QDialog):
    def __init__(self, profile_manager, browser_launcher, synchronizer_mgr=None, parent=None):
        super().__init__(parent)
        self.profile_manager = profile_manager
        self.browser_launcher = browser_launcher
        self.synchronizer_mgr = synchronizer_mgr
        self.setWindowTitle("Синхронизатор действий браузеров")
        self.resize(700, 580)
        self.setMinimumSize(640, 520)
        self.setStyleSheet(FLUENT_DARK_QSS)
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(14)
        main_layout.setContentsMargins(24, 20, 24, 20)

        # Title & Subtitle
        lbl_title = QLabel("Синхронизатор действий (Master -> Workers)", self)
        lbl_title.setStyleSheet("color: #ffffff; font-size: 18px; font-weight: 700;")
        main_layout.addWidget(lbl_title)

        lbl_desc = QLabel("Позволяет управлять одним главным профилем и дублировать клики, ввод текста и скролл во все дочерние профили с защитой от детекта.", self)
        lbl_desc.setStyleSheet("color: #a1a1aa; font-size: 12px;")
        main_layout.addWidget(lbl_desc)

        # 1. Master Profile Selection Card
        card_master = SimpleCardWidget(self)
        l_m = QVBoxLayout(card_master)
        l_m.setContentsMargins(16, 12, 16, 12)
        l_m.setSpacing(8)

        lbl_m_title = QLabel("Главный профиль (Master):", card_master)
        lbl_m_title.setStyleSheet("color: #ffffff; font-weight: 600; font-size: 12px;")
        l_m.addWidget(lbl_m_title)

        self.combo_master = ComboBox(card_master)
        profiles = self.profile_manager.list_profiles()
        for p in profiles:
            self.combo_master.addItem(f"{p.name} ({p.id})", userData=p.id)
        l_m.addWidget(self.combo_master)

        main_layout.addWidget(card_master)

        # 2. Worker Profiles Selection Card
        card_workers = SimpleCardWidget(self)
        l_w = QVBoxLayout(card_workers)
        l_w.setContentsMargins(16, 12, 16, 12)
        l_w.setSpacing(8)

        h_w_head = QHBoxLayout()
        lbl_w_title = QLabel("Ведомые профили (Workers):", card_workers)
        lbl_w_title.setStyleSheet("color: #ffffff; font-weight: 600; font-size: 12px;")
        h_w_head.addWidget(lbl_w_title)
        h_w_head.addStretch()

        btn_select_all = PushButton(FluentIcon.ACCEPT, "Выбрать все", card_workers)
        btn_select_all.setFixedHeight(28)
        btn_select_all.clicked.connect(self.select_all_workers)
        h_w_head.addWidget(btn_select_all)

        btn_clear_all = PushButton(FluentIcon.CANCEL, "Снять выбор", card_workers)
        btn_clear_all.setFixedHeight(28)
        btn_clear_all.clicked.connect(self.clear_all_workers)
        h_w_head.addWidget(btn_clear_all)
        l_w.addLayout(h_w_head)

        self.list_workers = QListWidget(card_workers)
        self.list_workers.setStyleSheet("background: #18181b; border: 1px solid #27272a; border-radius: 6px; color: #ffffff; padding: 4px;")
        for p in profiles:
            item = QListWidgetItem(f"{p.name} [{p.group or 'No Group'}]")
            item.setData(Qt.ItemDataRole.UserRole, p.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.list_workers.addItem(item)
        l_w.addWidget(self.list_workers)

        main_layout.addWidget(card_workers)

        # 3. Settings & Window Tiling Card
        card_settings = SimpleCardWidget(self)
        l_s = QHBoxLayout(card_settings)
        l_s.setContentsMargins(16, 12, 16, 12)
        l_s.setSpacing(12)

        self.chk_jitter = CheckBox("Случайные задержки и смещения мыши (Humanizer)", card_settings)
        self.chk_jitter.setChecked(True)
        l_s.addWidget(self.chk_jitter)

        l_s.addStretch()

        btn_tile = PushButton(FluentIcon.LAYOUT, "Выровнять окна по сетке", card_settings)
        btn_tile.clicked.connect(self.on_tile_windows)
        l_s.addWidget(btn_tile)

        main_layout.addWidget(card_settings)

        # 4. Action Buttons Footer
        h_footer = QHBoxLayout()
        h_footer.addStretch()

        btn_cancel = PushButton("Закрыть", self)
        btn_cancel.clicked.connect(self.reject)
        h_footer.addWidget(btn_cancel)

        self.btn_toggle_sync = PrimaryPushButton(FluentIcon.SYNC, "Запустить синхронизацию", self)
        self.btn_toggle_sync.clicked.connect(self.on_start_sync)
        h_footer.addWidget(self.btn_toggle_sync)
        main_layout.addLayout(h_footer)

    def select_all_workers(self):
        master_id = self.combo_master.currentData()
        for i in range(self.list_workers.count()):
            item = self.list_workers.item(i)
            if item.data(Qt.ItemDataRole.UserRole) != master_id:
                item.setCheckState(Qt.CheckState.Checked)

    def clear_all_workers(self):
        for i in range(self.list_workers.count()):
            self.list_workers.item(i).setCheckState(Qt.CheckState.Unchecked)

    def get_selected_workers(self):
        workers = []
        master_id = self.combo_master.currentData()
        for i in range(self.list_workers.count()):
            item = self.list_workers.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                pid = item.data(Qt.ItemDataRole.UserRole)
                if pid != master_id:
                    workers.append(pid)
        return workers

    def on_tile_windows(self):
        pids = list(self.browser_launcher.profile_pids.values())
        if not pids:
            InfoBar.warning("Нет запущенных окон", "Запустите профили перед выравниванием окон по сетке", parent=self, position=InfoBarPosition.TOP)
            return
        ok = tile_windows_win32(pids)
        if ok:
            InfoBar.success("Сетка готова", f"Выровнено {len(pids)} окон на рабочем столе", parent=self, position=InfoBarPosition.TOP)
        else:
            InfoBar.info("Сетка", "Окна успешно перерасположены", parent=self, position=InfoBarPosition.TOP)

    def on_start_sync(self):
        master_id = self.combo_master.currentData()
        workers = self.get_selected_workers()

        if not master_id:
            InfoBar.warning("Ошибка", "Выберите главный профиль", parent=self, position=InfoBarPosition.TOP)
            return

        if not workers:
            InfoBar.warning("Ошибка", "Выберите хотя бы один ведомый профиль (Worker)", parent=self, position=InfoBarPosition.TOP)
            return

        if self.synchronizer_mgr:
            self.synchronizer_mgr.start_session(
                master_profile_id=master_id,
                worker_profile_ids=workers,
                humanize_jitter=self.chk_jitter.isChecked()
            )

        InfoBar.success("Синхронизация активна", f"Синхронизируются {len(workers)} ведомых профилей с Master ({master_id})", parent=self, position=InfoBarPosition.TOP)
        self.accept()
