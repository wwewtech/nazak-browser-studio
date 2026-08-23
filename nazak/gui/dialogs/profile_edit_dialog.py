"""
Fluent Profile Editor & Hardware Fingerprint Customizer Dialog.
Fluent Iconography Architecture.
"""
import uuid
import random
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QScrollArea, QWidget, QFrame, QLabel
)
from PyQt6.QtCore import Qt
from qfluentwidgets import (
    LineEdit, ComboBox, SwitchButton, PrimaryPushButton, PushButton,
    SimpleCardWidget, InfoBar, InfoBarPosition, FluentIcon
)

from ...models.profile import BrowserProfile, FingerprintConfig, ProxyConfig, ProxyType, GoogleSettings
from ...core.fingerprint_generator import GPU_PRESETS, SCREEN_RESOLUTIONS, generate_random_fingerprint
from ..style import FLUENT_DARK_QSS

class ProfileEditDialog(QDialog):
    def __init__(self, profile=None, profile_manager=None, parent=None):
        super().__init__(parent)
        self.profile = profile
        self.profile_manager = profile_manager
        self.is_create_mode = profile is None
        
        self.setWindowTitle("Новый профиль" if self.is_create_mode else f"Настройка: {profile.name}")
        self.resize(700, 680)
        self.setMinimumSize(660, 620)
        self.setStyleSheet(FLUENT_DARK_QSS)
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(24, 20, 24, 20)

        # Title
        title_text = "Создание изолированного профиля" if self.is_create_mode else f"Настройка профиля: {self.profile.name}"
        lbl_title = QLabel(title_text, self)
        lbl_title.setStyleSheet("color: #ffffff; font-size: 17px; font-weight: 700;")
        main_layout.addWidget(lbl_title)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(12)
        layout.setContentsMargins(0, 0, 8, 8)

        # 1. Base Information Card
        card_base = SimpleCardWidget(container)
        l_base = QVBoxLayout(card_base)
        l_base.setContentsMargins(16, 12, 16, 12)
        
        lbl_b = QLabel("Основная информация", card_base)
        lbl_b.setStyleSheet("color: #ffffff; font-weight: 700; font-size: 13px;")
        l_base.addWidget(lbl_b)
        
        self.input_name = LineEdit(card_base)
        self.input_name.setPlaceholderText("Имя профиля, например 01 • Google Ads USA")
        if self.profile:
            self.input_name.setText(self.profile.name)
        l_base.addWidget(self.input_name)

        self.input_group = LineEdit(card_base)
        self.input_group.setPlaceholderText("Группа (Google Ads, Warmup, YouTube)")
        if self.profile:
            self.input_group.setText(self.profile.group)
        else:
            self.input_group.setText("Google Ads")
        l_base.addWidget(self.input_group)
        layout.addWidget(card_base)

        # 2. Proxy Configuration Card
        card_proxy = SimpleCardWidget(container)
        l_proxy = QVBoxLayout(card_proxy)
        l_proxy.setContentsMargins(16, 12, 16, 12)
        
        lbl_p = QLabel("Настройка прокси HTTP / HTTPS / SOCKS5", card_proxy)
        lbl_p.setStyleSheet("color: #ffffff; font-weight: 700; font-size: 13px;")
        l_proxy.addWidget(lbl_p)
        
        self.input_proxy_raw = LineEdit(card_proxy)
        self.input_proxy_raw.setPlaceholderText("host:port:user:pass или socks5://user:pass@host:port (или direct)")
        if self.profile and self.profile.proxy.raw:
            self.input_proxy_raw.setText(self.profile.proxy.raw)
        else:
            self.input_proxy_raw.setText("direct")
        l_proxy.addWidget(self.input_proxy_raw)
        layout.addWidget(card_proxy)

        # 3. Hardware Fingerprint Spoofing Card
        card_fp = SimpleCardWidget(container)
        l_fp = QVBoxLayout(card_fp)
        l_fp.setContentsMargins(16, 14, 16, 14)
        
        h_fp_title = QHBoxLayout()
        lbl_fp = QLabel("Изоляция железа и цифровой отпечаток", card_fp)
        lbl_fp.setStyleSheet("color: #ffffff; font-weight: 700; font-size: 13px;")
        h_fp_title.addWidget(lbl_fp)
        h_fp_title.addStretch()
        
        self.btn_randomize = PushButton(FluentIcon.SYNC, "Сгенерировать отпечаток", card_fp)
        
        self.btn_randomize.clicked.connect(self.on_randomize_fp)
        h_fp_title.addWidget(self.btn_randomize)
        l_fp.addLayout(h_fp_title)

        grid_fp = QGridLayout()
        grid_fp.setVerticalSpacing(8)
        
        # GPU Preset
        lbl_g = QLabel("Видеокарта (GPU):", card_fp)
        lbl_g.setStyleSheet("color: #d4d4d8; font-size: 11px;")
        grid_fp.addWidget(lbl_g, 0, 0)
        self.combo_gpu = ComboBox(card_fp)
        for g in GPU_PRESETS:
            self.combo_gpu.addItem(g["unmasked_renderer"])
        grid_fp.addWidget(self.combo_gpu, 0, 1)

        # CPU Cores
        lbl_c = QLabel("Процессор (CPU):", card_fp)
        lbl_c.setStyleSheet("color: #d4d4d8; font-size: 11px;")
        grid_fp.addWidget(lbl_c, 1, 0)
        self.combo_cores = ComboBox(card_fp)
        for c in [6, 8, 12, 14, 16, 24, 32]:
            self.combo_cores.addItem(f"{c} Cores", userData=c)
        grid_fp.addWidget(self.combo_cores, 1, 1)

        # RAM
        lbl_r = QLabel("Память (RAM):", card_fp)
        lbl_r.setStyleSheet("color: #d4d4d8; font-size: 11px;")
        grid_fp.addWidget(lbl_r, 2, 0)
        self.combo_ram = ComboBox(card_fp)
        for r in [8, 16, 32, 64]:
            self.combo_ram.addItem(f"{r} GB", userData=r)
        grid_fp.addWidget(self.combo_ram, 2, 1)

        # Screen
        lbl_sc = QLabel("Разрешение экрана:", card_fp)
        lbl_sc.setStyleSheet("color: #d4d4d8; font-size: 11px;")
        grid_fp.addWidget(lbl_sc, 3, 0)
        self.combo_screen = ComboBox(card_fp)
        for s in SCREEN_RESOLUTIONS:
            self.combo_screen.addItem(f"{s['width']} × {s['height']}", userData=s)
        grid_fp.addWidget(self.combo_screen, 3, 1)

        l_fp.addLayout(grid_fp)

        # Switches Container (Padded)
        card_sw = QWidget(card_fp)
        card_sw.setStyleSheet("background-color: #202026; border-radius: 6px; padding: 6px;")
        h_switches = QHBoxLayout(card_sw)
        h_switches.setContentsMargins(8, 6, 8, 6)

        self.switch_canvas = SwitchButton(card_sw)
        self.switch_canvas.setChecked(True)
        lbl_sw1 = QLabel("Canvas 2D", card_sw)
        lbl_sw1.setStyleSheet("color: #d4d4d8; font-size: 11px; font-weight: 600;")
        h_switches.addWidget(lbl_sw1)
        h_switches.addWidget(self.switch_canvas)
        h_switches.addSpacing(14)

        self.switch_audio = SwitchButton(card_sw)
        self.switch_audio.setChecked(True)
        lbl_sw2 = QLabel("Audio Noise", card_sw)
        lbl_sw2.setStyleSheet("color: #d4d4d8; font-size: 11px; font-weight: 600;")
        h_switches.addWidget(lbl_sw2)
        h_switches.addWidget(self.switch_audio)
        h_switches.addSpacing(14)

        self.switch_port_scan = SwitchButton(card_sw)
        self.switch_port_scan.setChecked(True)
        lbl_sw3 = QLabel("Anti-Port Scan", card_sw)
        lbl_sw3.setStyleSheet("color: #d4d4d8; font-size: 11px; font-weight: 600;")
        h_switches.addWidget(lbl_sw3)
        h_switches.addWidget(self.switch_port_scan)
        h_switches.addStretch()
        l_fp.addWidget(card_sw)

        layout.addWidget(card_fp)

        scroll.setWidget(container)
        main_layout.addWidget(scroll)

        # Footer Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.btn_cancel = PushButton("Отмена", self)
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)

        self.btn_save = PrimaryPushButton(FluentIcon.ACCEPT, "Сохранить", self)
        
        self.btn_save.clicked.connect(self.on_save)
        btn_layout.addWidget(self.btn_save)

        main_layout.addLayout(btn_layout)

        if self.profile:
            self.load_profile_data()

    def load_profile_data(self):
        fp = self.profile.fingerprint
        if not fp:
            return
        idx = self.combo_gpu.findText(fp.webgl_unmasked_renderer)
        if idx >= 0:
            self.combo_gpu.setCurrentIndex(idx)
        idx = self.combo_cores.findText(f"{fp.hardware_concurrency} Cores")
        if idx >= 0:
            self.combo_cores.setCurrentIndex(idx)
        idx = self.combo_ram.findText(f"{fp.device_memory} GB")
        if idx >= 0:
            self.combo_ram.setCurrentIndex(idx)
        idx = self.combo_screen.findText(f"{fp.screen_width} × {fp.screen_height}")
        if idx >= 0:
            self.combo_screen.setCurrentIndex(idx)
            
        self.switch_canvas.setChecked(bool(fp.canvas_noise))
        self.switch_audio.setChecked(bool(fp.audio_noise))
        self.switch_port_scan.setChecked(bool(fp.block_port_scanning))

    def on_randomize_fp(self):
        new_fp = generate_random_fingerprint(os_type="windows")
        idx_gpu = self.combo_gpu.findText(new_fp.webgl_unmasked_renderer)
        if idx_gpu >= 0:
            self.combo_gpu.setCurrentIndex(idx_gpu)
        idx_cores = self.combo_cores.findText(f"{new_fp.hardware_concurrency} Cores")
        if idx_cores >= 0:
            self.combo_cores.setCurrentIndex(idx_cores)
        idx_ram = self.combo_ram.findText(f"{new_fp.device_memory} GB")
        if idx_ram >= 0:
            self.combo_ram.setCurrentIndex(idx_ram)
        idx_screen = self.combo_screen.findText(f"{new_fp.screen_width} × {new_fp.screen_height}")
        if idx_screen >= 0:
            self.combo_screen.setCurrentIndex(idx_screen)
            
        self.switch_canvas.setChecked(bool(new_fp.canvas_noise))
        self.switch_audio.setChecked(bool(new_fp.audio_noise))
        self.switch_port_scan.setChecked(bool(new_fp.block_port_scanning))
        InfoBar.success("Отпечаток сгенерирован", "Подобран согласованный набор характеристик железа", parent=self, position=InfoBarPosition.TOP)

    def on_save(self):
        name = self.input_name.text().strip()
        if not name:
            InfoBar.warning("Внимание", "Укажите имя профиля", parent=self, position=InfoBarPosition.TOP)
            return

        group = self.input_group.text().strip() or "General"
        proxy_raw = self.input_proxy_raw.text().strip()
        proxy_conf = ProxyConfig.parse(proxy_raw)

        fp = self.profile.fingerprint if self.profile else generate_random_fingerprint("windows")
        fp.webgl_unmasked_renderer = self.combo_gpu.currentText()
        fp.hardware_concurrency = self.combo_cores.currentData() or 16
        fp.device_memory = self.combo_ram.currentData() or 32
        
        scr_data = self.combo_screen.currentData()
        if scr_data:
            fp.screen_width = scr_data["width"]
            fp.screen_height = scr_data["height"]
            fp.screen_avail_width = scr_data["avail_w"]
            fp.screen_avail_height = scr_data["avail_h"]
            fp.device_pixel_ratio = scr_data["dpr"]

        fp.canvas_noise = self.switch_canvas.isChecked()
        fp.audio_noise = self.switch_audio.isChecked()
        fp.block_port_scanning = self.switch_port_scan.isChecked()

        if self.is_create_mode:
            new_id = f"prof_{uuid.uuid4().hex[:8]}"
            prof = BrowserProfile(
                id=new_id,
                name=name,
                group=group,
                proxy=proxy_conf,
                fingerprint=fp,
                google=GoogleSettings()
            )
            self.profile_manager.create_profile(prof)
        else:
            self.profile.name = name
            self.profile.group = group
            self.profile.proxy = proxy_conf
            self.profile.fingerprint = fp
            self.profile_manager.update_profile(self.profile)

        self.accept()
