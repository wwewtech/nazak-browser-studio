"""
Windows 11 Fluent Design System - Global Stylesheet & Color Tokens.
Obsidian Dark Mode Architecture with High-Contrast Typography & Tactile States.
"""
from PyQt6.QtGui import QFont

def apply_app_typography(app):
    """Configures high-precision anti-aliased Segoe UI Variable typography."""
    font = QFont("Segoe UI", 9)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias | QFont.StyleStrategy.PreferQuality)
    font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    app.setFont(font)

FLUENT_DARK_QSS = """
/* Global Window & Background */
QWidget {
    font-family: "Segoe UI Variable Text", "Segoe UI", -apple-system, BlinkMacSystemFont, "Inter", "Roboto", sans-serif;
    color: #f4f4f5;
    selection-background-color: #0078d4;
    selection-color: #ffffff;
}

MSFluentWindow, FluentWindow, QMainWindow {
    background-color: #121214;
}

/* Sleek Fluent 6px Overlay Scrollbars */
QScrollBar:vertical {
    background: transparent;
    width: 6px;
    margin: 2px 0px 2px 0px;
}

QScrollBar::handle:vertical {
    background: #3f3f46;
    min-height: 28px;
    border-radius: 3px;
}

QScrollBar::handle:vertical:hover {
    background: #71717a;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
    background: none;
}

QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
}

QScrollBar:horizontal {
    background: transparent;
    height: 6px;
    margin: 0px 2px 0px 2px;
}

QScrollBar::handle:horizontal {
    background: #3f3f46;
    min-width: 28px;
    border-radius: 3px;
}

QScrollBar::handle:horizontal:hover {
    background: #71717a;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
    background: none;
}

QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: transparent;
}

QScrollArea {
    background-color: transparent;
    border: none;
}

QScrollArea > QWidget > QWidget {
    background-color: transparent;
}

/* Custom Card Styling */
SimpleCardWidget, ElevatedCardWidget, CardWidget {
    background-color: #1a1a1e;
    border: 1px solid #27272e;
    border-radius: 10px;
}

SimpleCardWidget:hover, ElevatedCardWidget:hover {
    border: 1px solid #3b3b45;
}

/* Headers and Labels */
SubtitleLabel {
    font-family: "Segoe UI Variable Display", "Segoe UI", sans-serif;
    color: #ffffff;
    font-size: 20px;
    font-weight: 700;
    letter-spacing: -0.3px;
}

BodyLabel {
    font-family: "Segoe UI Variable Text", "Segoe UI", sans-serif;
    color: #f4f4f5;
    font-size: 13px;
    font-weight: 600;
}

CaptionLabel {
    font-family: "Segoe UI Variable Text", "Segoe UI", sans-serif;
    color: #a1a1aa;
    font-size: 11px;
}

/* Native Fluent Buttons handled via setTheme & setThemeColor */

/* Input Fields */
LineEdit, SearchLineEdit, TextEdit {
    font-family: "Segoe UI Variable Text", "Segoe UI", sans-serif;
    background-color: #16161a;
    color: #ffffff;
    border: 1px solid #2e2e38;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
    selection-background-color: #0078d4;
}

LineEdit:focus, SearchLineEdit:focus, TextEdit:focus {
    border: 1px solid #0078d4;
    background-color: #141418;
}

/* ComboBox */
ComboBox {
    font-family: "Segoe UI Variable Text", "Segoe UI", sans-serif;
    background-color: #222228;
    color: #f4f4f5;
    border: 1px solid #32323a;
    border-radius: 6px;
    padding: 5px 12px;
    font-size: 12px;
    min-height: 24px;
}

ComboBox:hover {
    border-color: #454550;
    background-color: #282830;
}

/* Tables */
QTableWidget, TableWidget {
    font-family: "Cascadia Code", "Cascadia Mono", "Segoe UI Variable Text", "Segoe UI", monospace;
    background-color: #16161a;
    color: #f4f4f5;
    border: 1px solid #27272e;
    border-radius: 8px;
    gridline-color: #222228;
    selection-background-color: #0078d4;
    selection-color: #ffffff;
    font-size: 12px;
}

QHeaderView::section {
    font-family: "Segoe UI Variable Display", "Segoe UI", sans-serif;
    background-color: #1e1e24;
    color: #a1a1aa;
    font-weight: 600;
    font-size: 11px;
    border: none;
    border-bottom: 1px solid #27272e;
    padding: 8px 10px;
}

/* Dialogs */
QDialog {
    background-color: #16161a;
    color: #f4f4f5;
}

/* Checkboxes */
QCheckBox, CheckBox {
    font-family: "Segoe UI Variable Text", "Segoe UI", sans-serif;
    color: #e4e4e7;
    font-size: 12px;
    spacing: 8px;
}

/* Tooltips */
QToolTip {
    font-family: "Segoe UI Variable Text", "Segoe UI", sans-serif;
    background-color: #27272e;
    color: #ffffff;
    border: 1px solid #3f3f46;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 11px;
}
"""
