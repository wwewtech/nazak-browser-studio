"""
Fluent YouTube Shorts Stealth Autoposter View.
Fluent Iconography & Zero-Emoji Architecture.
"""

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CheckBox,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    SimpleCardWidget,
    TableWidget,
    TextEdit,
)

from ...core.spintax import format_video_metadata, parse_spintax
from ..workers import AutopostBatchWorker


class AutopostView(QWidget):
    def __init__(self, profile_manager, browser_launcher, parent=None):
        super().__init__(parent)
        self.profile_manager = profile_manager
        self.browser_launcher = browser_launcher
        self.setObjectName("autopost_view")
        self.worker = None
        self.init_ui()
        self.on_preview_spintax()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(14)
        main_layout.setContentsMargins(24, 20, 24, 20)

        # 1. Header with Top Action Button
        h_head = QHBoxLayout()
        v_title = QVBoxLayout()
        lbl_title = QLabel("Автопостинг YouTube Shorts", self)
        lbl_title.setStyleSheet("color: #ffffff; font-size: 22px; font-weight: 700; letter-spacing: -0.4px;")

        lbl_desc = QLabel(
            "Автономная уникализация видео через FFmpeg, генерация спинтакс-заголовков и публикация Shorts через CDP",
            self,
        )
        lbl_desc.setStyleSheet("color: #a1a1aa; font-size: 12px;")

        v_title.addWidget(lbl_title)
        v_title.addWidget(lbl_desc)
        h_head.addLayout(v_title)
        h_head.addStretch()

        self.btn_start_top = PrimaryPushButton(FluentIcon.SEND, "Запустить автопостинг", self)
        self.btn_start_top.clicked.connect(self.on_start_autopost)
        h_head.addWidget(self.btn_start_top)
        main_layout.addLayout(h_head)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(14)
        layout.setContentsMargins(0, 0, 8, 12)

        # 1. Source Video & Target TG Card
        card_src = SimpleCardWidget(container)
        l_src = QVBoxLayout(card_src)
        l_src.setContentsMargins(16, 14, 16, 14)

        lbl_s1 = QLabel("Исходный видеоролик и воронка", card_src)
        lbl_s1.setStyleSheet("color: #ffffff; font-weight: 700; font-size: 13px;")
        l_src.addWidget(lbl_s1)

        h_file = QHBoxLayout()
        self.input_video_path = LineEdit(card_src)
        self.input_video_path.setText("data/videos/source.mp4")
        self.input_video_path.setPlaceholderText("Путь к MP4 файлу...")
        h_file.addWidget(self.input_video_path)

        btn_browse = PushButton(FluentIcon.FOLDER, "Обзор...", card_src)
        btn_browse.clicked.connect(self.on_browse_file)
        h_file.addWidget(btn_browse)
        l_src.addLayout(h_file)

        self.input_tg = LineEdit(card_src)
        self.input_tg.setText("@speed_vpn_bot")
        self.input_tg.setPlaceholderText("Telegram-канал или бот воронки, например @my_vpn_bot")
        l_src.addWidget(self.input_tg)
        layout.addWidget(card_src)

        # 2. Spintax Templates Card
        card_spin = SimpleCardWidget(container)
        l_spin = QVBoxLayout(card_spin)
        l_spin.setContentsMargins(16, 14, 16, 14)

        h_spin_head = QHBoxLayout()
        lbl_s2 = QLabel("Спинтакс-шаблоны метаданных", card_spin)
        lbl_s2.setStyleSheet("color: #ffffff; font-weight: 700; font-size: 13px;")
        h_spin_head.addWidget(lbl_s2)
        h_spin_head.addStretch()

        btn_preview = PushButton(FluentIcon.SYNC, "Сгенерировать примеры", card_spin)
        btn_preview.clicked.connect(self.on_preview_spintax)
        h_spin_head.addWidget(btn_preview)
        l_spin.addLayout(h_spin_head)

        self.input_title = LineEdit(card_spin)
        self.input_title.setText("{Лучший|Топ|Рабочий} {VPN|Впн} для {РФ|России} 2026 #shorts #vpn #ютуб")
        self.input_title.textChanged.connect(self.on_preview_spintax)
        l_spin.addWidget(self.input_title)

        self.input_desc = TextEdit(card_spin)
        self.input_desc.setMaximumHeight(75)
        self.input_desc.setText(
            "{Скачать быстрый VPN без ограничений:|Как смотреть ютуб в 4K в РФ:} {tg}\nПромокод на скидку: {promo}\n\n#shorts #vpn #впн #ютуб"
        )
        self.input_desc.textChanged.connect(self.on_preview_spintax)
        l_spin.addWidget(self.input_desc)

        self.lbl_preview_sample = QLabel("", card_spin)
        self.lbl_preview_sample.setStyleSheet(
            "color: #38bdf8; font-family: monospace; font-size: 11px; background: #22222a; padding: 8px 12px; border-radius: 6px; border: 1px solid #2e2e3a;"
        )
        l_spin.addWidget(self.lbl_preview_sample)
        layout.addWidget(card_spin)

        # 3. Target Profiles Selector Card
        card_profs = SimpleCardWidget(container)
        l_profs = QVBoxLayout(card_profs)
        l_profs.setContentsMargins(16, 14, 16, 14)

        h_prof_head = QHBoxLayout()
        lbl_s3 = QLabel("Выбор аккаунтов для публикации", card_profs)
        lbl_s3.setStyleSheet("color: #ffffff; font-weight: 700; font-size: 13px;")
        h_prof_head.addWidget(lbl_s3)
        h_prof_head.addStretch()

        btn_all = PushButton("Выбрать все", card_profs)
        btn_all.clicked.connect(lambda: self.toggle_all_checkboxes(True))
        h_prof_head.addWidget(btn_all)

        btn_none = PushButton("Снять", card_profs)
        btn_none.clicked.connect(lambda: self.toggle_all_checkboxes(False))
        h_prof_head.addWidget(btn_none)
        l_profs.addLayout(h_prof_head)

        self.profile_checkboxes = {}
        grid_p = QGridLayout()
        profiles = self.profile_manager.list_profiles()
        for idx, p in enumerate(profiles):
            cb = CheckBox(f"{p.name}", card_profs)
            cb.setChecked(True)
            self.profile_checkboxes[p.id] = cb
            grid_p.addWidget(cb, idx // 2, idx % 2)
        l_profs.addLayout(grid_p)
        layout.addWidget(card_profs)

        # 4. Status Progress Table Card
        card_table = SimpleCardWidget(container)
        l_table = QVBoxLayout(card_table)
        l_table.setContentsMargins(16, 14, 16, 14)

        lbl_s4 = QLabel("Журнал очереди автопостинга", card_table)
        lbl_s4.setStyleSheet("color: #ffffff; font-weight: 700; font-size: 13px;")
        l_table.addWidget(lbl_s4)

        self.table = TableWidget(card_table)
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Профиль", "Статус", "Прогресс", "Ссылка"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumHeight(160)
        l_table.addWidget(self.table)
        layout.addWidget(card_table)

        scroll.setWidget(container)
        main_layout.addWidget(scroll)

        # Launch Button with Fluent Icon
        h_bot = QHBoxLayout()
        h_bot.addStretch()

        self.btn_start_bottom = PrimaryPushButton(FluentIcon.SEND, "Запустить автопостинг", self)
        self.btn_start_bottom.setMinimumWidth(240)
        self.btn_start_bottom.clicked.connect(self.on_start_autopost)
        h_bot.addWidget(self.btn_start_bottom)
        main_layout.addLayout(h_bot)

    def on_browse_file(self):
        fname, _ = QFileDialog.getOpenFileName(self, "Выберите видеофайл MP4", "", "Video Files (*.mp4 *.mov *.mkv)")
        if fname:
            self.input_video_path.setText(fname)

    def on_preview_spintax(self):
        t_tmpl = self.input_title.text()
        d_tmpl = self.input_desc.toPlainText()
        tg = self.input_tg.text()
        sample = format_video_metadata(t_tmpl, d_tmpl, "Profile 01", "prof_01", tg)
        self.lbl_preview_sample.setText(
            f"Превью заголовка: {sample['title']}\nПревью описания: {sample['description'].splitlines()[0]}"
        )

    def toggle_all_checkboxes(self, checked: bool):
        for cb in self.profile_checkboxes.values():
            cb.setChecked(checked)

    def on_start_autopost(self):
        selected_ids = [pid for pid, cb in self.profile_checkboxes.items() if cb.isChecked()]
        if not selected_ids:
            InfoBar.warning("Внимание", "Выберите хотя бы один профиль", parent=self, position=InfoBarPosition.TOP)
            return

        vpath = Path(self.input_video_path.text().strip())
        if not vpath.exists():
            vpath.parent.mkdir(parents=True, exist_ok=True)
            vpath.write_bytes(b"DEMO_MP4_DATA" + bytes(1024))

        self.table.setRowCount(len(selected_ids))
        for row, pid in enumerate(selected_ids):
            prof = self.profile_manager.get_profile(pid)
            pname = prof.name if prof else pid
            self.table.setItem(row, 0, QTableWidgetItem(pname))
            self.table.setItem(row, 1, QTableWidgetItem("В ОЧЕРЕДИ"))
            self.table.setItem(row, 2, QTableWidgetItem("Ожидание старта"))
            self.table.setItem(row, 3, QTableWidgetItem("-"))

        for btn in (self.btn_start_top, self.btn_start_bottom):
            btn.setEnabled(False)
            btn.setText("Выполняется...")

        self.worker = AutopostBatchWorker(
            profile_manager=self.profile_manager,
            browser_launcher=self.browser_launcher,
            profile_ids=selected_ids,
            source_video_path=vpath,
            title_template=self.input_title.text(),
            description_template=self.input_desc.toPlainText(),
            tg_channel=self.input_tg.text(),
        )
        self.worker.job_update_signal.connect(self.on_job_update)
        self.worker.batch_finished_signal.connect(self.on_batch_finished)
        self.worker.start()

        InfoBar.success(
            "Очередь запущена",
            f"Автопостинг начат для {len(selected_ids)} профилей",
            parent=self,
            position=InfoBarPosition.TOP,
        )

    def on_job_update(self, profile_id: str, status: str, message: str):
        for row in range(self.table.rowCount()):
            item_p = self.table.item(row, 0)
            if item_p:
                prof = self.profile_manager.get_profile(profile_id)
                pname = prof.name if prof else profile_id
                if item_p.text() == pname:
                    self.table.setItem(row, 1, QTableWidgetItem(status.upper()))
                    self.table.setItem(row, 2, QTableWidgetItem(message))
                    if "http" in message:
                        self.table.setItem(row, 3, QTableWidgetItem(message))
                    break

    def on_batch_finished(self, results):
        for btn in (self.btn_start_top, self.btn_start_bottom):
            btn.setEnabled(True)
            btn.setText("Запустить автопостинг")
        InfoBar.success(
            "Очередь завершена", f"Обработано {len(results)} публикаций", parent=self, position=InfoBarPosition.TOP
        )
