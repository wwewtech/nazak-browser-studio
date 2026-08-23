"""
Fluent Splash Screen for Nazak Browser Studio PRO.
Displays high-resolution branding logo with smooth startup telemetry.
"""
from pathlib import Path
from PyQt6.QtWidgets import QSplashScreen, QWidget, QVBoxLayout, QLabel, QGraphicsDropShadowEffect
from PyQt6.QtGui import QPixmap, QColor, QFont, QPainter, QLinearGradient, QBrush, QPen
from PyQt6.QtCore import Qt, QTimer, QRectF

from ..config import DATA_DIR

class NazakSplashScreen(QSplashScreen):
    """
    Minimalist Obsidian Splash Screen with vector logo and hardware status telemetry.
    """
    def __init__(self):
        # Create 480x280 rounded obsidian splash pixmap
        pixmap = QPixmap(480, 280)
        pixmap.fill(QColor(0, 0, 0, 0))

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        # Background Card with 1px border
        rect = QRectF(4, 4, 472, 272)
        grad = QLinearGradient(0, 0, 480, 280)
        grad.setColorAt(0.0, QColor(20, 22, 28))
        grad.setColorAt(0.6, QColor(13, 14, 18))
        grad.setColorAt(1.0, QColor(9, 10, 13))

        painter.setBrush(QBrush(grad))
        painter.setPen(QPen(QColor(45, 48, 62), 1.5))
        painter.drawRoundedRect(rect, 14, 14)

        # Logo Icon
        logo_path = DATA_DIR / "assets" / "app_icon.png"
        if not logo_path.exists():
            logo_path = Path(__file__).resolve().parent.parent.parent / "data" / "assets" / "app_icon.png"

        if logo_path.exists():
            logo_pix = QPixmap(str(logo_path)).scaled(80, 80, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            painter.drawPixmap(40, 60, logo_pix)

        # Title
        font_title = QFont("Segoe UI Variable Display", 18, QFont.Weight.Bold)
        font_title.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, -0.4)
        painter.setFont(font_title)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(140, 85, "NAZAK BROWSER STUDIO")

        # Pro Tag
        painter.setBrush(QBrush(QColor(0, 120, 212, 50)))
        painter.setPen(QPen(QColor(56, 189, 248), 1.2))
        painter.drawRoundedRect(QRectF(405, 68, 42, 20), 4, 4)
        font_tag = QFont("Segoe UI Variable Text", 9, QFont.Weight.Bold)
        painter.setFont(font_tag)
        painter.setPen(QColor(56, 189, 248))
        painter.drawText(414, 82, "PRO")

        # Subtitle
        font_sub = QFont("Segoe UI Variable Text", 10, QFont.Weight.Medium)
        painter.setFont(font_sub)
        painter.setPen(QColor(161, 161, 170))
        painter.drawText(140, 112, "Next-Gen Anti-Detect & YouTube Shorts Autoposter")

        # Status Telemetry Bar line
        painter.setPen(QPen(QColor(35, 38, 48), 1.0))
        painter.drawLine(40, 180, 440, 180)

        # Pulse indicator dot
        painter.setBrush(QBrush(QColor(56, 189, 248)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(44, 212, 7, 7)

        # Status text
        font_status = QFont("Segoe UI Variable Text", 10, QFont.Weight.Normal)
        painter.setFont(font_status)
        painter.setPen(QColor(212, 212, 216))
        painter.drawText(60, 219, "Инициализация аппаратного щита железа и Chromium...")

        # Version string
        font_ver = QFont("Segoe UI Variable Text", 9, QFont.Weight.Normal)
        painter.setFont(font_ver)
        painter.setPen(QColor(113, 113, 122))
        painter.drawText(390, 245, "v1.3.0 Release")

        painter.end()

        super().__init__(pixmap, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def show_and_fade(self, duration_ms=1100, on_finished=None):
        self.show()
        if on_finished:
            QTimer.singleShot(duration_ms, lambda: (self.close(), on_finished()))
