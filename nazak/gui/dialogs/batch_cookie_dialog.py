"""
Fluent Batch Cookie Importer Dialog.
Supports multi-profile delimited text, JSON maps, directory scanner, and zip archives.
Windows 11 Fluent Iconography & Zero-Emoji Architecture.
"""

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidgetItem,
    QVBoxLayout,
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

from ...core.cookie_manager import parse_bulk_cookie_input, parse_cookie_files_from_dir, parse_cookie_files_from_zip
from ..style import FLUENT_DARK_QSS


class BatchCookieDialog(QDialog):
    def __init__(self, profile_manager, parent=None):
        super().__init__(parent)
        self.profile_manager = profile_manager
        self.setWindowTitle("Bulk Cookie Import")
        self.resize(740, 620)
        self.setMinimumSize(680, 560)
        self.setStyleSheet(FLUENT_DARK_QSS)
        self.parsed_cookies_map = {}
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(24, 20, 24, 20)

        # Title & Subtitle
        lbl_title = QLabel("Bulk Session Cookie Import", self)
        lbl_title.setStyleSheet("color: #ffffff; font-size: 18px; font-weight: 700;")
        main_layout.addWidget(lbl_title)

        lbl_desc = QLabel(
            "Import cookies for multiple profiles from delimited text, a JSON dictionary, a folder, or a ZIP archive.", self
        )
        lbl_desc.setStyleSheet("color: #a1a1aa; font-size: 12px;")
        main_layout.addWidget(lbl_desc)

        # 1. Quick File Actions Bar
        card_files = SimpleCardWidget(self)
        l_files = QHBoxLayout(card_files)
        l_files.setContentsMargins(14, 10, 14, 10)
        l_files.setSpacing(10)

        btn_folder = PushButton(FluentIcon.FOLDER, "Select Cookie Folder", card_files)
        btn_folder.clicked.connect(self.on_pick_folder)
        l_files.addWidget(btn_folder)

        btn_zip = PushButton(FluentIcon.DOCUMENT, "Select ZIP Archive", card_files)
        btn_zip.clicked.connect(self.on_pick_zip)
        l_files.addWidget(btn_zip)

        l_files.addStretch()
        main_layout.addWidget(card_files)

        # 2. Text Input Card
        card_input = SimpleCardWidget(self)
        l_input = QVBoxLayout(card_input)
        l_input.setContentsMargins(14, 12, 14, 12)
        l_input.setSpacing(8)

        lbl_inp = QLabel("Or paste cookies delimited by === Profile Name / ID ===", card_input)
        lbl_inp.setStyleSheet("color: #ffffff; font-weight: 600; font-size: 12px;")
        l_input.addWidget(lbl_inp)

        self.txt_cookies = TextEdit(card_input)
        self.txt_cookies.setFixedHeight(120)
        self.txt_cookies.setPlaceholderText(
            "=== 01 - Google Ads USA ===\n"
            '[{"name": "SID", "value": "...", "domain": ".google.com", "path": "/"}]\n\n'
            "=== 02 - Google Ads USA ===\n"
            "# Netscape HTTP Cookie File\n"
            ".google.com\tTRUE\t/\tTRUE\t0\tSID\tabc123"
        )
        self.txt_cookies.textChanged.connect(self.on_text_changed)
        l_input.addWidget(self.txt_cookies)

        h_opts = QHBoxLayout()
        self.chk_autocreate = CheckBox("Create new profiles for unmatched profiles", card_input)
        self.chk_autocreate.setChecked(True)
        h_opts.addWidget(self.chk_autocreate)

        h_opts.addStretch()
        lbl_g = QLabel("Group:", card_input)
        lbl_g.setStyleSheet("color: #a1a1aa; font-size: 11px;")
        h_opts.addWidget(lbl_g)

        self.edit_group = LineEdit(card_input)
        self.edit_group.setText("Imported Cookies")
        self.edit_group.setFixedWidth(160)
        h_opts.addWidget(self.edit_group)
        l_input.addLayout(h_opts)

        main_layout.addWidget(card_input)

        # 3. Preview Table Card
        card_table = SimpleCardWidget(self)
        l_tbl = QVBoxLayout(card_table)
        l_tbl.setContentsMargins(14, 12, 14, 12)
        l_tbl.setSpacing(8)

        lbl_t_title = QLabel("Recognized Sessions for Import", card_table)
        lbl_t_title.setStyleSheet("color: #ffffff; font-weight: 600; font-size: 12px;")
        l_tbl.addWidget(lbl_t_title)

        self.table = TableWidget(card_table)
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Profile Name / ID", "Cookie Count", "Profile Status"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(1, 130)
        self.table.setColumnWidth(2, 170)
        l_tbl.addWidget(self.table)

        main_layout.addWidget(card_table)

        # 4. Action Buttons Footer
        h_footer = QHBoxLayout()
        h_footer.addStretch()

        btn_cancel = PushButton("Cancel", self)
        btn_cancel.clicked.connect(self.reject)
        h_footer.addWidget(btn_cancel)

        self.btn_import = PrimaryPushButton(FluentIcon.ACCEPT, "Import All", self)
        self.btn_import.clicked.connect(self.on_import_all)
        h_footer.addWidget(self.btn_import)
        main_layout.addLayout(h_footer)

    def on_pick_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Cookie Folder")
        if folder:
            parsed = parse_cookie_files_from_dir(Path(folder))
            if parsed:
                self.parsed_cookies_map = parsed
                self.update_preview_table()
                InfoBar.success(
                    "Files Read",
                    f"Found {len(parsed)} cookie files",
                    parent=self,
                    position=InfoBarPosition.TOP,
                )
            else:
                InfoBar.warning(
                    "Warning",
                    "No valid .json / .txt cookie files found in the selected folder",
                    parent=self,
                    position=InfoBarPosition.TOP,
                )

    def on_pick_zip(self):
        zip_file, _ = QFileDialog.getOpenFileName(self, "Select ZIP Archive with Cookies", "", "ZIP Files (*.zip)")
        if zip_file:
            parsed = parse_cookie_files_from_zip(Path(zip_file))
            if parsed:
                self.parsed_cookies_map = parsed
                self.update_preview_table()
                InfoBar.success(
                    "Archive Read",
                    f"Recognized {len(parsed)} profiles from the archive",
                    parent=self,
                    position=InfoBarPosition.TOP,
                )
            else:
                InfoBar.warning(
                    "Warning",
                    "Failed to extract cookies from the selected archive",
                    parent=self,
                    position=InfoBarPosition.TOP,
                )

    def on_text_changed(self):
        text = self.txt_cookies.toPlainText().strip()
        if text:
            self.parsed_cookies_map = parse_bulk_cookie_input(text)
            self.update_preview_table()

    def update_preview_table(self):
        self.table.setRowCount(len(self.parsed_cookies_map))
        existing_profiles = self.profile_manager.list_profiles()
        id_set = {p.id.lower() for p in existing_profiles}
        name_set = {p.name.lower() for p in existing_profiles}

        for row, (p_ident, cookies) in enumerate(self.parsed_cookies_map.items()):
            self.table.setItem(row, 0, QTableWidgetItem(p_ident))
            self.table.setItem(row, 1, QTableWidgetItem(f"{len(cookies)} cookies"))

            p_lower = p_ident.lower()
            is_matched = (
                p_lower in id_set or p_lower in name_set or any(p_lower in p.name.lower() for p in existing_profiles)
            )
            status_str = "Existing profile" if is_matched else "New profile will be created"
            self.table.setItem(row, 2, QTableWidgetItem(status_str))

    def on_import_all(self):
        if not self.parsed_cookies_map:
            text = self.txt_cookies.toPlainText().strip()
            if text:
                self.parsed_cookies_map = parse_bulk_cookie_input(text)

        if not self.parsed_cookies_map:
            InfoBar.warning(
                "Empty Data",
                "Paste cookies or select files for import",
                parent=self,
                position=InfoBarPosition.TOP,
            )
            return

        res = self.profile_manager.batch_import_cookies(
            self.parsed_cookies_map,
            auto_create_missing=self.chk_autocreate.isChecked(),
            group=self.edit_group.text().strip() or "Imported Cookies",
        )

        msg = f"Imported: {res['matched']} updated, {res['created']} created"
        InfoBar.success("Import Complete", msg, parent=self, position=InfoBarPosition.TOP)
        self.accept()
