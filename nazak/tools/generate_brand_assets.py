"""
Bespoke High-Craft Brand Identity Generator for Nazak Browser Studio.
Eliminates all AI-slop tropes: no neon circles, no generic radial glow blobs.
Pure Bauhaus / Swiss mathematical isometric prism geometry with exact vertex topology.
"""
import sys
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import (
    QImage, QPainter, QColor, QPen, QBrush, QLinearGradient,
    QPainterPath, QFont, QPolygonF
)
from PyQt6.QtCore import Qt, QPointF, QRectF
from PIL import Image

def generate_bespoke_brand():
    app = QApplication.instance() or QApplication(sys.argv)
    assets_dir = Path("D:/nazak/data/assets")
    assets_dir.mkdir(parents=True, exist_ok=True)

    def draw_mathematical_stealth_prism(p: QPainter, cx: float, cy: float, size: float, mode: str = "dark"):
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        s = size
        W = s * 0.24   # Pillar Width
        G = s * 0.22   # Center Gap
        H = s * 0.84   # Total Height
        S = s * 0.08   # Top/Bottom Bevel Slope
        D = s * 0.28   # Diagonal Beam Thickness

        # 1. Left Vertical Monolith
        poly_left = QPolygonF([
            QPointF(cx - G/2 - W, cy - H/2 + S),  # Top-left
            QPointF(cx - G/2,     cy - H/2),      # Top-right
            QPointF(cx - G/2,     cy + H/2 - S),  # Bottom-right
            QPointF(cx - G/2 - W, cy + H/2),      # Bottom-left
        ])

        # 2. Right Vertical Monolith
        poly_right = QPolygonF([
            QPointF(cx + G/2,     cy - H/2 + S),  # Top-left
            QPointF(cx + G/2 + W, cy - H/2),      # Top-right
            QPointF(cx + G/2 + W, cy + H/2 - S),  # Bottom-right
            QPointF(cx + G/2,     cy + H/2),      # Bottom-left
        ])

        # 3. Seamless Diagonal Shutter (100% exact vertex topology matching pillars)
        poly_diag = QPolygonF([
            QPointF(cx - G/2,     cy - H/2),          # Shared with Left Top-Right
            QPointF(cx - G/2,     cy - H/2 + D),      # Left Inner Drop
            QPointF(cx + G/2,     cy + H/2),          # Shared with Right Bottom-Left
            QPointF(cx + G/2,     cy + H/2 - D),      # Right Inner Rise
        ])

        if mode == "dark":
            # Left Facet: Pure Satin Titanium
            g_left = QLinearGradient(cx - G/2 - W, cy - H/2, cx - G/2, cy + H/2)
            g_left.setColorAt(0.0, QColor(255, 255, 255))
            g_left.setColorAt(0.5, QColor(240, 243, 248))
            g_left.setColorAt(1.0, QColor(210, 215, 225))

            # Diagonal: Deep Electric Cobalt Beam (The optical core)
            g_diag = QLinearGradient(cx - G/2, cy - H/2, cx + G/2, cy + H/2)
            g_diag.setColorAt(0.0, QColor(59, 130, 246))   # Cobalt
            g_diag.setColorAt(0.5, QColor(37, 99, 235))   # Electric Royal
            g_diag.setColorAt(1.0, QColor(29, 78, 216))   # Deep Sapphire

            # Right Facet: Graphite Titanium
            g_right = QLinearGradient(cx + G/2, cy - H/2, cx + G/2 + W, cy + H/2)
            g_right.setColorAt(0.0, QColor(230, 235, 242))
            g_right.setColorAt(1.0, QColor(160, 165, 175))

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

            # Subtle Precision Chamfer Line (1px hairline highlight on seam)
            p.setPen(QPen(QColor(255, 255, 255, 160), s * 0.008))
            p.drawLine(QPointF(cx - G/2, cy - H/2), QPointF(cx - G/2, cy + H/2 - S))

        elif mode == "pure_mono":
            # 100% Monochrome Black & White (No blue, pure Swiss brutalist aesthetic)
            g_left = QLinearGradient(cx - G/2 - W, cy - H/2, cx - G/2, cy + H/2)
            g_left.setColorAt(0.0, QColor(255, 255, 255))
            g_left.setColorAt(1.0, QColor(220, 220, 225))

            g_diag = QLinearGradient(cx - G/2, cy - H/2, cx + G/2, cy + H/2)
            g_diag.setColorAt(0.0, QColor(130, 135, 145))
            g_diag.setColorAt(1.0, QColor(70, 75, 85))

            g_right = QLinearGradient(cx + G/2, cy - H/2, cx + G/2 + W, cy + H/2)
            g_right.setColorAt(0.0, QColor(240, 243, 248))
            g_right.setColorAt(1.0, QColor(170, 175, 185))

            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(g_diag))
            p.drawPolygon(poly_diag)
            p.setBrush(QBrush(g_left))
            p.drawPolygon(poly_left)
            p.setBrush(QBrush(g_right))
            p.drawPolygon(poly_right)

        else:
            # Monochrome Light Mode (Jet Black on White)
            g_left_l = QLinearGradient(cx - G/2 - W, cy - H/2, cx - G/2, cy + H/2)
            g_left_l.setColorAt(0.0, QColor(15, 15, 18))
            g_left_l.setColorAt(1.0, QColor(35, 35, 42))

            g_diag_l = QLinearGradient(cx - G/2, cy - H/2, cx + G/2, cy + H/2)
            g_diag_l.setColorAt(0.0, QColor(37, 99, 235))
            g_diag_l.setColorAt(1.0, QColor(29, 78, 216))

            g_right_l = QLinearGradient(cx + G/2, cy - H/2, cx + G/2 + W, cy + H/2)
            g_right_l.setColorAt(0.0, QColor(24, 24, 28))
            g_right_l.setColorAt(1.0, QColor(55, 55, 65))

            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(g_diag_l))
            p.drawPolygon(poly_diag)
            p.setBrush(QBrush(g_left_l))
            p.drawPolygon(poly_left)
            p.setBrush(QBrush(g_right_l))
            p.drawPolygon(poly_right)

    # 1. Dark App Icon & Logo (1024x1024 Matte Obsidian Squircle)
    img_dark = QImage(1024, 1024, QImage.Format.Format_ARGB32_Premultiplied)
    img_dark.fill(QColor(0, 0, 0, 0))
    p_dark = QPainter(img_dark)
    p_dark.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    
    bg_path = QPainterPath()
    bg_path.addRoundedRect(QRectF(48, 48, 928, 928), 210, 210)
    
    bg_grad = QLinearGradient(0, 0, 0, 1024)
    bg_grad.setColorAt(0.0, QColor(20, 20, 24))
    bg_grad.setColorAt(1.0, QColor(10, 10, 12))
    p_dark.setBrush(QBrush(bg_grad))
    p_dark.setPen(QPen(QColor(39, 39, 42), 3.5))
    p_dark.drawPath(bg_path)

    # Inner subtle rim line
    rim_path = QPainterPath()
    rim_path.addRoundedRect(QRectF(52, 52, 920, 920), 206, 206)
    p_dark.setPen(QPen(QColor(255, 255, 255, 18), 2))
    p_dark.setBrush(Qt.BrushStyle.NoBrush)
    p_dark.drawPath(rim_path)

    draw_mathematical_stealth_prism(p_dark, 512, 512, 600, mode="dark")
    p_dark.end()
    img_dark.save(str(assets_dir / "logo_dark.png"))

    # 2. Light App Icon & Logo (1024x1024 Pure Architectural White)
    img_light = QImage(1024, 1024, QImage.Format.Format_ARGB32_Premultiplied)
    img_light.fill(QColor(0, 0, 0, 0))
    p_light = QPainter(img_light)
    p_light.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    bg_path_l = QPainterPath()
    bg_path_l.addRoundedRect(QRectF(48, 48, 928, 928), 210, 210)
    bg_grad_l = QLinearGradient(0, 0, 0, 1024)
    bg_grad_l.setColorAt(0.0, QColor(255, 255, 255))
    bg_grad_l.setColorAt(1.0, QColor(244, 244, 245))
    p_light.setBrush(QBrush(bg_grad_l))
    p_light.setPen(QPen(QColor(228, 228, 231), 3.5))
    p_light.drawPath(bg_path_l)

    draw_mathematical_stealth_prism(p_light, 512, 512, 600, mode="light")
    p_light.end()
    img_light.save(str(assets_dir / "logo_light.png"))

    # 3. Transparent Logos (Dark & Light)
    img_td = QImage(1024, 1024, QImage.Format.Format_ARGB32_Premultiplied)
    img_td.fill(QColor(0, 0, 0, 0))
    p_td = QPainter(img_td)
    draw_mathematical_stealth_prism(p_td, 512, 512, 720, mode="dark")
    p_td.end()
    img_td.save(str(assets_dir / "logo_dark_transparent.png"))

    img_tl = QImage(1024, 1024, QImage.Format.Format_ARGB32_Premultiplied)
    img_tl.fill(QColor(0, 0, 0, 0))
    p_tl = QPainter(img_tl)
    draw_mathematical_stealth_prism(p_tl, 512, 512, 720, mode="light")
    p_tl.end()
    img_tl.save(str(assets_dir / "logo_light_transparent.png"))

    # 4. Multi-Resolution Windows ICO
    pil_img = Image.open(str(assets_dir / "logo_dark.png"))
    icon_sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)]
    pil_img.save(str(assets_dir / "icon.ico"), format="ICO", sizes=icon_sizes)
    pil_img.resize((256, 256), Image.Resampling.LANCZOS).save(str(assets_dir / "app_icon.png"))

    # 5. Editorial Swiss-Style GitHub Banner (1280x360)
    banner = QImage(1280, 360, QImage.Format.Format_ARGB32_Premultiplied)
    banner.fill(QColor(9, 9, 11))
    p_b = QPainter(banner)
    p_b.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p_b.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    # 1. Subtle Hairline Technical Grid
    p_b.setPen(QPen(QColor(24, 24, 27), 1))
    for x in range(0, 1280, 80):
        p_b.drawLine(x, 0, x, 360)
    for y in range(0, 360, 60):
        p_b.drawLine(0, y, 1280, y)

    # Outer Frame
    p_b.setPen(QPen(QColor(39, 39, 42), 1.5))
    p_b.setBrush(Qt.BrushStyle.NoBrush)
    p_b.drawRect(0, 0, 1279, 359)

    # Draw Brand Glyph on the left
    draw_mathematical_stealth_prism(p_b, 170, 180, 240, mode="dark")

    # Vertical Hairline Divider
    p_b.setPen(QPen(QColor(39, 39, 42), 1))
    p_b.drawLine(320, 40, 320, 320)

    # Micro Monospace Header Tag
    font_mono = QFont("JetBrains Mono", 10, QFont.Weight.Medium)
    p_b.setFont(font_mono)
    p_b.setPen(QColor(113, 113, 122))
    p_b.drawText(360, 85, "SYS // ANTI-DETECT ARCHITECTURE • V1.3.0 RELEASE")

    # Main Brand Name in High-Discipline Grotesk
    font_brand = QFont("Segoe UI Variable Display", 34, QFont.Weight.Bold)
    font_brand.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, -0.8)
    p_b.setFont(font_brand)
    p_b.setPen(QColor(255, 255, 255))
    p_b.drawText(360, 140, "NAZAK BROWSER STUDIO")

    # Subtitle / Philosophy
    font_sub = QFont("Segoe UI Variable Text", 14, QFont.Weight.Medium)
    p_b.setFont(font_sub)
    p_b.setPen(QColor(161, 161, 170))
    p_b.drawText(360, 185, "Hardware-Isolated Chromium Engine • Autonomous Shorts Studio")

    # Monospace Telemetry Grid Bottom Section
    p_b.setPen(QPen(QColor(39, 39, 42), 1))
    p_b.drawLine(360, 220, 1220, 220)

    font_specs = QFont("JetBrains Mono", 10, QFont.Weight.Normal)
    p_b.setFont(font_specs)

    # Spec 1
    p_b.setPen(QColor(82, 82, 91))
    p_b.drawText(360, 255, "HARDWARE SHIELD")
    p_b.setPen(QColor(244, 244, 245))
    p_b.drawText(360, 280, "RTX 4090 / Canvas Noise / WebRTC")

    # Spec 2
    p_b.setPen(QColor(82, 82, 91))
    p_b.drawText(660, 255, "AUTHENTICATION")
    p_b.setPen(QColor(244, 244, 245))
    p_b.drawText(660, 280, "RFC 6238 Live 2FA • One-Click Accs")

    # Spec 3
    p_b.setPen(QColor(82, 82, 91))
    p_b.drawText(960, 255, "AUTOPOSTER")
    p_b.setPen(QColor(59, 130, 246))
    p_b.drawText(960, 280, "FFmpeg Uniqueizer + Stealth CDP")

    p_b.end()
    banner.save(str(assets_dir / "banner.png"))
    print("Saved all perfected mathematical assets!")

if __name__ == "__main__":
    generate_bespoke_brand()
