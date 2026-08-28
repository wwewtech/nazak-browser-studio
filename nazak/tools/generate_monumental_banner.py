"""
Monumental Executive Brand Banner Generator for Nazak Browser Studio.
Zero grid lines. Massive, bold display typography. High-impact Swiss aesthetic.
"""

import sys
from pathlib import Path

from PIL import Image
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PyQt6.QtWidgets import QApplication


def generate_monumental_banner():
    _app = QApplication.instance() or QApplication(sys.argv)
    assets_dir = Path("D:/nazak/data/assets")
    assets_dir.mkdir(parents=True, exist_ok=True)

    def draw_mathematical_stealth_prism(p: QPainter, cx: float, cy: float, size: float):
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        s = size
        W = s * 0.24
        G = s * 0.22
        H = s * 0.84
        S = s * 0.08
        D = s * 0.28

        # 1. Left Vertical Monolith
        poly_left = QPolygonF(
            [
                QPointF(cx - G / 2 - W, cy - H / 2 + S),
                QPointF(cx - G / 2, cy - H / 2),
                QPointF(cx - G / 2, cy + H / 2 - S),
                QPointF(cx - G / 2 - W, cy + H / 2),
            ]
        )

        # 2. Right Vertical Monolith
        poly_right = QPolygonF(
            [
                QPointF(cx + G / 2, cy - H / 2 + S),
                QPointF(cx + G / 2 + W, cy - H / 2),
                QPointF(cx + G / 2 + W, cy + H / 2 - S),
                QPointF(cx + G / 2, cy + H / 2),
            ]
        )

        # 3. Seamless Diagonal Shutter
        poly_diag = QPolygonF(
            [
                QPointF(cx - G / 2, cy - H / 2),
                QPointF(cx - G / 2, cy - H / 2 + D),
                QPointF(cx + G / 2, cy + H / 2),
                QPointF(cx + G / 2, cy + H / 2 - D),
            ]
        )

        # Left Facet: Pure Satin White to Platinum
        g_left = QLinearGradient(cx - G / 2 - W, cy - H / 2, cx - G / 2, cy + H / 2)
        g_left.setColorAt(0.0, QColor(255, 255, 255))
        g_left.setColorAt(0.5, QColor(245, 248, 255))
        g_left.setColorAt(1.0, QColor(215, 220, 230))

        # Diagonal: Deep Electric Cobalt Blue
        g_diag = QLinearGradient(cx - G / 2, cy - H / 2, cx + G / 2, cy + H / 2)
        g_diag.setColorAt(0.0, QColor(59, 130, 246))
        g_diag.setColorAt(0.5, QColor(37, 99, 235))
        g_diag.setColorAt(1.0, QColor(29, 78, 216))

        # Right Facet: Titanium Silver to Graphite
        g_right = QLinearGradient(cx + G / 2, cy - H / 2, cx + G / 2 + W, cy + H / 2)
        g_right.setColorAt(0.0, QColor(235, 240, 248))
        g_right.setColorAt(1.0, QColor(165, 170, 180))

        p.setPen(Qt.PenStyle.NoPen)

        # Draw Diagonal
        p.setBrush(QBrush(g_diag))
        p.drawPolygon(poly_diag)

        # Draw Left Blade
        p.setBrush(QBrush(g_left))
        p.drawPolygon(poly_left)

        # Draw Right Blade
        p.setBrush(QBrush(g_right))
        p.drawPolygon(poly_right)

        # 1px hairline light reflection on seam
        p.setPen(QPen(QColor(255, 255, 255, 180), s * 0.008))
        p.drawLine(QPointF(cx - G / 2, cy - H / 2), QPointF(cx - G / 2, cy + H / 2 - S))

    # -------------------------------------------------------------------------
    # High-Impact Banner (1280x420) — Monumental Swiss Craft
    # -------------------------------------------------------------------------
    banner = QImage(1280, 420, QImage.Format.Format_ARGB32_Premultiplied)
    banner.fill(QColor(8, 9, 11))
    p = QPainter(banner)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    # 1. Subtle Outer Border (1px hairline)
    p.setPen(QPen(QColor(28, 30, 36), 1.5))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRect(0, 0, 1279, 419)

    # 2. Draw Large Brand Glyph on the Left
    draw_mathematical_stealth_prism(p, 190, 210, 310)

    # 3. Vertical Hairline Separator
    p.setPen(QPen(QColor(30, 32, 40), 1))
    p.drawLine(350, 45, 350, 375)

    # 4. Monospace Badge / Micro Header
    font_badge = QFont("JetBrains Mono", 10, QFont.Weight.DemiBold)
    font_badge.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)
    p.setFont(font_badge)
    p.setPen(QColor(59, 130, 246))
    p.drawText(390, 105, "● HARDWARE-ISOLATED CHROMIUM ENGINE")

    # 5. MASSIVE DISPLAY WORDMARK
    font_hero = QFont("Segoe UI Variable Display", 44, QFont.Weight.ExtraBold)
    font_hero.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, -1.6)
    p.setFont(font_hero)
    p.setPen(QColor(255, 255, 255))
    p.drawText(388, 178, "NAZAK BROWSER STUDIO")

    # 6. High-Contrast Sub-headline
    font_tagline = QFont("Segoe UI Variable Text", 17, QFont.Weight.DemiBold)
    font_tagline.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, -0.2)
    p.setFont(font_tagline)
    p.setPen(QColor(212, 212, 216))
    p.drawText(390, 230, "Next-Gen Anti-Detect Platform & Autonomous Shorts Studio")

    # 7. Thin Divider
    p.setPen(QPen(QColor(30, 32, 40), 1))
    p.drawLine(390, 268, 1220, 268)

    # 8. Dynamic Flow Bullet Items with FontMetrics
    font_bullets = QFont("Segoe UI Variable Text", 13, QFont.Weight.Medium)
    p.setFont(font_bullets)
    fm = QFontMetrics(font_bullets)

    bullets = [
        ("100% GPU & Canvas Shield", QColor(161, 161, 170)),
        ("Live 2FA TOTP Engine", QColor(161, 161, 170)),
        ("FFmpeg Video Uniqueizer", QColor(161, 161, 170)),
        ("Win / macOS / Linux", QColor(59, 130, 246)),
    ]

    cur_x = 390
    y_bullets = 315
    for i, (text, color) in enumerate(bullets):
        p.setPen(color)
        p.drawText(cur_x, y_bullets, text)
        cur_x += fm.horizontalAdvance(text) + 16
        if i < len(bullets) - 1:
            p.setPen(QColor(60, 64, 76))
            p.drawText(cur_x, y_bullets, "•")
            cur_x += fm.horizontalAdvance("•") + 16

    p.end()
    banner.save(str(assets_dir / "banner.png"))
    print("Saved refined monumental banner!")


if __name__ == "__main__":
    generate_monumental_banner()
