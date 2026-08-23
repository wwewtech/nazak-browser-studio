"""
Bespoke Minimalist Splash Screen for Nazak Browser Studio PRO.
Swiss architecture, tactile dark mode, and monospace hardware telemetry.
"""
from pathlib import Path
from PyQt6.QtWidgets import QSplashScreen
from PyQt6.QtGui import QPixmap, QColor, QFont, QPainter, QLinearGradient, QBrush, QPen
from PyQt6.QtCore import Qt, QTimer, QRectF

from ..config import DATA_DIR

class NazakSplashScreen(QSplashScreen):
    """
    Precision Swiss Splash Screen with mathematical glyph and hardware status telemetry.
    """
    def __init__(self):
        pixmap = QPixmap(520, 290)
        pixmap.fill(QColor(0, 0, 0, 0))

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        # 1. Background Obsidian Container
        rect = QRectF(4, 4, 512, 282)
        grad = QLinearGradient(0, 0, 0, 290)
        grad.setColorAt(0.0, QColor(18, 18, 22))
        grad.setColorAt(1.0, QColor(10, 10, 12))

        painter.setBrush(QBrush(grad))
        painter.setPen(QPen(QColor(39, 39, 42), 1.5))
        painter.drawRoundedRect(rect, 12, 12)

        # Inner Top Rim Light
        painter.setPen(QPen(QColor(255, 255, 255, 20), 1))
        painter.drawLine(18, 6, 502, 6)

        # 2. Logo Icon
        logo_path = DATA_DIR / "assets" / "app_icon.png"
        if not logo_path.exists():
            logo_path = Path(__file__).resolve().parent.parent.parent / "data" / "assets" / "app_icon.png"

        if logo_path.exists():
            logo_pix = QPixmap(str(logo_path)).scaled(84, 84, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            painter.drawPixmap(36, 44, logo_pix)

        # 3. Monospace Category Tag
        font_mono_tag = QFont("JetBrains Mono", 9, QFont.Weight.Medium)
        painter.setFont(font_mono_tag)
        painter.setPen(QColor(113, 113, 122))
        painter.drawText(140, 62, "SYS // HARDWARE-ISOLATED ENGINE")

        # 4. Main Title
        font_title = QFont("Segoe UI Variable Display", 18, QFont.Weight.Bold)
        font_title.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, -0.4)
        painter.setFont(font_title)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(140, 92, "NAZAK BROWSER STUDIO")

        # 5. Subtitle
        font_sub = QFont("Segoe UI Variable Text", 10, QFont.Weight.Medium)
        painter.setFont(font_sub)
        painter.setPen(QColor(161, 161, 170))
        painter.drawText(140, 118, "Next-Gen Anti-Detect & YouTube Shorts Autoposter")

        # 6. Hairline Divider
        painter.setPen(QPen(QColor(39, 39, 42), 1.0))
        painter.drawLine(36, 165, 484, 165)

        # 7. Monospace Hardware Telemetry
        font_status = QFont("JetBrains Mono", 9, QFont.Weight.Normal)
        painter.setFont(font_status)

        # Pulsing blue indicator square
        painter.setBrush(QBrush(QColor(59, 130, 246)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRect(38, 196, 6, 6)

        painter.setPen(QColor(212, 212, 216))
        painter.drawText(54, 203, "INITIALIZING HARDWARE ISOLATION & CHROMIUM...")

        # Version & Architecture
        painter.setPen(QColor(113, 113, 122))
        painter.drawText(38, 242, "BUILD: V1.3.0 PRO")
        painter.drawText(390, 242, "WIN64 // FLUENT")

        painter.end()

        super().__init__(pixmap, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def show_and_fade(self, duration_ms=1000, on_finished=None):
        self.show()
        if on_finished:
            QTimer.singleShot(duration_ms, lambda: (self.close(), on_finished()))
