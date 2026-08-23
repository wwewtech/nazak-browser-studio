"""
Bespoke Non-Generic Editorial Brand Banners for Nazak Browser Studio in Russian.
Pure Swiss geometric poster layout.
"""
import sys
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import (
    QImage, QPainter, QColor, QPen, QBrush, QLinearGradient,
    QPainterPath, QFont, QPolygonF, QFontMetrics
)
from PyQt6.QtCore import Qt, QPointF, QRectF

def draw_prism(p: QPainter, cx: float, cy: float, size: float):
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    s = size
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

    p.setPen(QPen(QColor(255, 255, 255, 180), s * 0.008))
    p.drawLine(QPointF(cx - G/2, cy - H/2), QPointF(cx - G/2, cy + H/2 - S))

def generate_banners():
    app = QApplication.instance() or QApplication(sys.argv)
    assets_dir = Path("D:/nazak/data/assets")

    # =========================================================================
    # OPTION A: Centered Monumental Swiss Monolith in Russian (1280 x 440)
    # =========================================================================
    b_centered = QImage(1280, 440, QImage.Format.Format_ARGB32_Premultiplied)
    b_centered.fill(QColor(6, 7, 9))
    p1 = QPainter(b_centered)
    p1.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p1.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    # 1. Outer Border
    p1.setPen(QPen(QColor(24, 26, 32), 1.5))
    p1.setBrush(Qt.BrushStyle.NoBrush)
    p1.drawRect(0, 0, 1279, 439)

    # 2. Top-Centered Icon Emblem
    draw_prism(p1, 640, 105, 130)

    # 3. Main Wordmark (Centered, Massive, Pure White)
    font_title = QFont("Segoe UI Variable Display", 36, QFont.Weight.Bold)
    font_title.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 6.0)
    p1.setFont(font_title)
    p1.setPen(QColor(255, 255, 255))
    p1.drawText(QRectF(0, 185, 1280, 50), Qt.AlignmentFlag.AlignCenter, "N A Z A K")

    # 4. Russian Subtitle
    font_sub = QFont("Segoe UI Variable Text", 15, QFont.Weight.Medium)
    font_sub.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, -0.2)
    p1.setFont(font_sub)
    p1.setPen(QColor(161, 161, 170))
    p1.drawText(QRectF(0, 245, 1280, 28), Qt.AlignmentFlag.AlignCenter, "Антидетект-платформа нового поколения и автономная студия Shorts")

    # 5. Centered Monolithic Hardware Chips (Russian)
    font_chip = QFont("JetBrains Mono", 10, QFont.Weight.Medium)
    p1.setFont(font_chip)
    fm = QFontMetrics(font_chip)

    chips = [
        "100% ИЗОЛЯЦИЯ ЖЕЛЕЗА И CANVAS",
        "ЖИВОЙ 2FA TOTP RFC 6238",
        "STEALTH CDP АВТОПОСТИНГ",
        "WINDOWS / MACOS / LINUX"
    ]

    total_w = sum(fm.horizontalAdvance(c) + 32 for c in chips) + (len(chips) - 1) * 12
    start_x = (1280 - total_w) / 2
    y_chip = 315

    for chip in chips:
        w_c = fm.horizontalAdvance(chip) + 32
        h_c = 34
        
        # Chip background
        p1.setBrush(QBrush(QColor(18, 20, 26)))
        p1.setPen(QPen(QColor(39, 42, 54), 1))
        p1.drawRoundedRect(QRectF(start_x, y_chip, w_c, h_c), 6, 6)

        # Dot indicator
        p1.setBrush(QBrush(QColor(59, 130, 246)))
        p1.setPen(Qt.PenStyle.NoPen)
        p1.drawEllipse(QPointF(start_x + 14, y_chip + 17), 3, 3)

        # Text
        p1.setPen(QColor(228, 228, 231))
        p1.drawText(QRectF(start_x + 24, y_chip + 7, w_c - 28, 20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, chip)

        start_x += w_c + 12

    # 6. Muted Version Footer (Russian)
    font_foot = QFont("JetBrains Mono", 9, QFont.Weight.Normal)
    p1.setFont(font_foot)
    p1.setPen(QColor(82, 82, 91))
    p1.drawText(QRectF(0, 390, 1280, 20), Qt.AlignmentFlag.AlignCenter, "ВЕРСИЯ 1.3.0 PRO  •  ОТКРЫТЫЙ ИСХОДНЫЙ КОД  •  ЛИЦЕНЗИЯ MIT")

    p1.end()
    b_centered.save(str(assets_dir / "banner.png"))
    b_centered.save(str(assets_dir / "banner_centered.png"))
    print("Saved Russian banner.png!")

if __name__ == "__main__":
    generate_banners()
