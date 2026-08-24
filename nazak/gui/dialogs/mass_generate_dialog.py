"""
Fluent Mass Profile Generator Dialog.
Generates N (1 to 500) hardware-isolated profiles with automatic proxy round-robin and realistic GPU/OS mixes.
Windows 11 Fluent Iconography & Zero-Emoji Architecture.
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel
)
from PyQt6.QtCore import Qt
from qfluentwidgets import (
    LineEdit, TextEdit, ComboBox, Slider, PrimaryPushButton, PushButton,
    SimpleCardWidget, InfoBar, InfoBarPosition, FluentIcon
)

from ..style import FLUENT_DARK_QSS

class MassGenerateDialog(QDialog):
    def __init__(self, profile_manager, parent=None):
        super().__init__(parent)
        self.profile_manager = profile_manager
        self.setWindowTitle("Массовая генерация профилей")
        self.resize(680, 580)
        self.setMinimumSize(640, 520)
        self.setStyleSheet(FLUENT_DARK_QSS)
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(14)
        main_layout.setContentsMargins(24, 20, 24, 20)

        # Title & Subtitle
        lbl_title = QLabel("Массовое создание изолированных профилей", self)
        lbl_title.setStyleSheet("color: #ffffff; font-size: 18px; font-weight: 700;")
        main_layout.addWidget(lbl_title)

        lbl_desc = QLabel("Мгновенное создание фермы профилей с уникальными GPU, CPU, RAM, Audio/Canvas шумом и распределением прокси.", self)
        lbl_desc.setStyleSheet("color: #a1a1aa; font-size: 12px;")
        main_layout.addWidget(lbl_desc)

        # 1. Base Setup Card
        card_base = SimpleCardWidget(self)
        l_base = QVBoxLayout(card_base)
        l_base.setContentsMargins(16, 14, 16, 14)
        l_base.setSpacing(10)

        grid = QGridLayout()
        grid.setVerticalSpacing(10)

        # Count Slider
        lbl_c = QLabel("Количество профилей:", card_base)
        lbl_c.setStyleSheet("color: #d4d4d8; font-size: 12px; font-weight: 600;")
        grid.addWidget(lbl_c, 0, 0)

        h_slider = QHBoxLayout()
        self.slider_count = Slider(Qt.Orientation.Horizontal, card_base)
        self.slider_count.setRange(1, 100)
        self.slider_count.setValue(10)
        self.slider_count.valueChanged.connect(self.on_slider_changed)
        
        self.lbl_count_val = QLabel("10 профилей", card_base)
        self.lbl_count_val.setStyleSheet("color: #38bdf8; font-weight: 700; font-size: 13px; min-width: 90px;")
        h_slider.addWidget(self.slider_count)
        h_slider.addWidget(self.lbl_count_val)
        grid.addLayout(h_slider, 0, 1)

        # Group Name
        lbl_g = QLabel("Группа профилей:", card_base)
        lbl_g.setStyleSheet("color: #d4d4d8; font-size: 12px;")
        grid.addWidget(lbl_g, 1, 0)

        self.edit_group = LineEdit(card_base)
        self.edit_group.setText("Mass Farm")
        grid.addWidget(self.edit_group, 1, 1)

        # OS Distribution
        lbl_os = QLabel("Операционная система:", card_base)
        lbl_os.setStyleSheet("color: #d4d4d8; font-size: 12px;")
        grid.addWidget(lbl_os, 2, 0)

        self.combo_os = ComboBox(card_base)
        self.combo_os.addItem("Windows 10/11 (Рекомендуется)", userData="windows")
        self.combo_os.addItem("macOS Sonoma / Sequoia (MacBook / M-series)", userData="mac")
        self.combo_os.addItem("Linux Ubuntu / Debian", userData="linux")
        self.combo_os.addItem("Смешанный микс (Win + Mac + Linux)", userData="all")
        grid.addWidget(self.combo_os, 2, 1)

        # Target Start Page
        lbl_page = QLabel("Стартовая страница:", card_base)
        lbl_page.setStyleSheet("color: #d4d4d8; font-size: 12px;")
        grid.addWidget(lbl_page, 3, 0)

        self.combo_page = ComboBox(card_base)
        self.combo_page.addItem("Google Авторизация (Login)", userData="google_login")
        self.combo_page.addItem("YouTube Studio (Творческая студия)", userData="youtube_studio")
        self.combo_page.addItem("Google Ads (Рекламный кабинет)", userData="google_ads")
        self.combo_page.addItem("Google Поиск (Search)", userData="google_search")
        grid.addWidget(self.combo_page, 3, 1)

        l_base.addLayout(grid)
        main_layout.addWidget(card_base)

        # 2. Proxy List Card
        card_proxy = SimpleCardWidget(self)
        l_prox = QVBoxLayout(card_proxy)
        l_prox.setContentsMargins(16, 14, 16, 14)
        l_prox.setSpacing(8)

        lbl_p_title = QLabel("Список прокси (1 строка на профиль, распределение по кругу):", card_proxy)
        lbl_p_title.setStyleSheet("color: #ffffff; font-weight: 600; font-size: 12px;")
        l_prox.addWidget(lbl_p_title)

        self.txt_proxies = TextEdit(card_proxy)
        self.txt_proxies.setFixedHeight(110)
        self.txt_proxies.setPlaceholderText(
            "host:port:user:pass\n"
            "socks5://user:pass@host:port\n"
            "192.168.1.1:8080\n"
            "Оставьте пустым для прямого подключения (Direct)"
        )
        l_prox.addWidget(self.txt_proxies)
        main_layout.addWidget(card_proxy)

        # 3. Action Buttons
        h_footer = QHBoxLayout()
        h_footer.addStretch()

        btn_cancel = PushButton("Отмена", self)
        btn_cancel.clicked.connect(self.reject)
        h_footer.addWidget(btn_cancel)

        self.btn_generate = PrimaryPushButton(FluentIcon.ADD, "Сгенерировать профили", self)
        self.btn_generate.clicked.connect(self.on_generate_profiles)
        h_footer.addWidget(self.btn_generate)
        main_layout.addLayout(h_footer)

    def on_slider_changed(self, val):
        self.lbl_count_val.setText(f"{val} профилей")

    def on_generate_profiles(self):
        count = self.slider_count.value()
        group = self.edit_group.text().strip() or "Mass Farm"
        os_type = self.combo_os.currentData() or "windows"
        target_page = self.combo_page.currentData() or "google_login"

        proxy_text = self.txt_proxies.toPlainText().strip()
        proxy_lines = [p.strip() for p in proxy_text.splitlines() if p.strip()] if proxy_text else None

        created = self.profile_manager.mass_generate_profiles(
            count=count,
            group=group,
            proxy_list=proxy_lines,
            os_mix=os_type,
            tags=["Mass Generated", group],
            auto_open_page=target_page
        )

        InfoBar.success("Успешно создано", f"Сгенерировано {len(created)} новых изолированных профилей!", parent=self, position=InfoBarPosition.TOP)
        self.accept()
