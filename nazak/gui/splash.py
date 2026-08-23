"""
Minimalist Executive Splash Screen for Nazak Browser Studio PRO.
Zero AI-slop: No fake telemetry logs, no fake window chrome.
Pure monolithic brand emblem, Swiss typography, and smooth indeterminate hairline loader.
"""
from pathlib import Path
from PyQt6.QtWidgets import QSplashScreen, QWidget, QVBoxLayout, QLabel, QGraphicsDropShadowEffect, QProgressBar
from PyQt6.QtGui import QPixmap, QColor, QFont, QPainter, QLinearGradient, QBrush, QPen, QPainterPath, QPolygonF
from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF

from ..config import DATA_DIR

class NazakSplashScreen(QSplashScreen):
    """
    Monolithic Executive Splash Screen.
    Presents the mathematical brand prism, bespoke Swiss typography, and clean hairline loader.
    """
    def __init__(self):
        # 460 x 280 Frameless Card
        w, h = 460, 280
        pixmap = QPixmap(w, h)
        pixmap.fill(QColor(0, 0, 0, 0))

        p = QPainter(pixmap)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        # 1. Main Obsidian Card (Matte #09090b with subtle 1px border)
        rect = QRectF(2, 2, w - 4, h - 4)
        card_path = QPainterPath()
        card_path.addRoundedRect(rect, 14, 14)

        p.setBrush(QBrush(QColor(9, 9, 11)))
        p.setPen(QPen(QColor(39, 39, 42), 1.5))
        p.drawPath(card_path)

        # Subtle Top Edge Highlight
        p.setPen(QPen(QColor(255, 255, 255, 18), 1))
        p.drawLine(20, 3, w - 20, 3)

        # 2. Draw Mathematical Stealth Prism Emblem
        cx, cy, s = w / 2, 95, 130
        W = s * 0.24
        G = s * 0.22
        H = s * 0.84
        S = s * 0.08
        D = s * 0.28

        poly_left = QPolygonF([
            QPointF(cx - G/2 - W, cy - H/2 + S),
            QPointF(cx - G/2,     cy - H/2),
            QPointF(cx - G/2,     cy + H/2 - S),
            QPointF(cx - G/2 - W, cy + H/2),
        ])

        poly_right = QPolygonF([
            QPointF(cx + G/2,     cy - H/2 + S),
            QPointF(cx + G/2 + W, cy - H/2),
            QPointF(cx + G/2 + W, cy + H/2 - S),
            QPointF(cx + G/2,     cy + H/2),
        ])

        poly_diag = QPolygonF([
            QPointF(cx - G/2,     cy - H/2),
            QPointF(cx - G/2,     cy - H/2 + D),
            QPointF(cx + G/2,     cy + H/2),
            QPointF(cx + G/2,     cy + H/2 - D),
        ])

        g_left = QLinearGradient(cx - G/2 - W, cy - H/2, cx - G/2, cy + H/2)
        g_left.setColorAt(0.0, QColor(255, 255, 255))
        g_left.setColorAt(0.5, QColor(245, 248, 255))
        g_left.setColorAt(1.0, QColor(215, 220, 230))

        g_diag = QLinearGradient(cx - G/2, cy - H/2, cx + G/2, cy + H/2)
        g_diag.setColorAt(0.0, QColor(59, 130, 246))
        g_diag.setColorAt(0.5, QColor(37, 99, 235))
        g_diag.setColorAt(1.0, QColor(29, 78, 216))

        g_right = QLinearGradient(cx + G/2, cy - H/2, cx + G/2 + W, cy + H/2)
        g_right.setColorAt(0.0, QColor(235, 240, 248))
        g_right.setColorAt(1.0, QColor(165, 170, 180))

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(g_diag))
        p.drawPolygon(poly_diag)
        p.setBrush(QBrush(g_left))
        p.drawPolygon(poly_left)
        p.setBrush(QBrush(g_right))
        p.drawPolygon(poly_right)

        # 3. Monumental Brand Name
        font_brand = QFont("Segoe UI Variable Display", 22, QFont.Weight.Bold)
        font_brand.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, -0.6)
        p.setFont(font_brand)
        p.setPen(QColor(255, 255, 255))
        p.drawText(QRectF(0, 172, w, 32), Qt.AlignmentFlag.AlignCenter, "NAZAK")

        # 4. Refined Russian Subtitle
        font_sub = QFont("Segoe UI Variable Text", 10, QFont.Weight.DemiBold)
        font_sub.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2.0)
        p.setFont(font_sub)
        p.setPen(QColor(113, 113, 122))
        p.drawText(QRectF(0, 206, w, 20), Qt.AlignmentFlag.AlignCenter, "АНТИДЕТЕКТ СТУДИЯ")

        # 5. Version String in Bottom-Right
        font_ver = QFont("JetBrains Mono", 8, QFont.Weight.Normal)
        p.setFont(font_ver)
        p.setPen(QColor(82, 82, 91))
        p.drawText(QRectF(w - 75, h - 22, 60, 14), Qt.AlignmentFlag.AlignRight, "v1.3.0")

        # 6. Sleek Hairline Loading Track & Blue Glow Bar at the very bottom
        track_rect = QRectF(0, h - 4, w, 4)
        p.setBrush(QBrush(QColor(24, 24, 27)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRect(track_rect)

        # Animated / Active Accent Fill
        active_grad = QLinearGradient(0, 0, w, 0)
        active_grad.setColorAt(0.0, QColor(37, 99, 235))
        active_grad.setColorAt(0.5, QColor(59, 130, 246))
        active_grad.setColorAt(1.0, QColor(96, 165, 250))
        p.setBrush(QBrush(active_grad))
        p.drawRect(QRectF(0, h - 4, w, 4))

        p.end()

        super().__init__(pixmap, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def show_and_fade(self, duration_ms=850, on_finished=None):
        self.show()
        if on_finished:
            QTimer.singleShot(duration_ms, lambda: (self.close(), on_finished()))
