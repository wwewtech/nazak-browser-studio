"""
Brand Asset Generator for Nazak Browser Studio.
Renders high-res anti-aliased vector logos, application icons, and GitHub banners using QPainter & Pillow.
"""
import sys
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import (
    QImage, QPainter, QColor, QPen, QBrush, QLinearGradient,
    QRadialGradient, QPainterPath, QFont, QFontDatabase, QPolygonF
)
from PyQt6.QtCore import Qt, QPointF, QRectF
from PIL import Image

def create_brand_assets():
    app = QApplication.instance() or QApplication(sys.argv)
    
    assets_dir = Path("D:/nazak/data/assets")
    assets_dir.mkdir(parents=True, exist_ok=True)

    def draw_nazak_symbol(painter: QPainter, cx: float, cy: float, size: float, dark_mode: bool = True):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        s = size
        w_bar = s * 0.24
        h_bar = s * 0.88
        corner_r = s * 0.08

        # Subtle Ambient Aura
        if dark_mode:
            aura = QRadialGradient(cx, cy, s * 0.7)
            aura.setColorAt(0.0, QColor(0, 120, 212, 60))
            aura.setColorAt(0.5, QColor(56, 189, 248, 20))
            aura.setColorAt(1.0, QColor(0, 0, 0, 0))
            painter.setBrush(QBrush(aura))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(cx, cy), s * 0.75, s * 0.75)

        # Left Vertical Pillar
        path_left = QPainterPath()
        rect_left = QRectF(cx - s * 0.44, cy - h_bar * 0.5, w_bar, h_bar)
        path_left.addRoundedRect(rect_left, corner_r, corner_r)

        # Right Vertical Pillar
        path_right = QPainterPath()
        rect_right = QRectF(cx + s * 0.44 - w_bar, cy - h_bar * 0.5, w_bar, h_bar)
        path_right.addRoundedRect(rect_right, corner_r, corner_r)

        # Diagonal Conduit / Geometric Bridge
        path_diag = QPainterPath()
        p1 = QPointF(cx - s * 0.44 + w_bar * 0.1, cy - h_bar * 0.45)
        p2 = QPointF(cx + s * 0.44 - w_bar * 0.1, cy + h_bar * 0.45)
        p3 = QPointF(cx + s * 0.44 - w_bar * 1.05, cy + h_bar * 0.45)
        p4 = QPointF(cx - s * 0.44 + w_bar * 1.05, cy - h_bar * 0.45)
        path_diag.moveTo(p1)
        path_diag.lineTo(p2)
        path_diag.lineTo(p3)
        path_diag.lineTo(p4)
        path_diag.closeSubpath()

        if dark_mode:
            # Pillars: Pure Titanium to Crisp White
            grad_pillar = QLinearGradient(cx, cy - h_bar * 0.5, cx, cy + h_bar * 0.5)
            grad_pillar.setColorAt(0.0, QColor(255, 255, 255))
            grad_pillar.setColorAt(0.6, QColor(240, 244, 250))
            grad_pillar.setColorAt(1.0, QColor(200, 210, 225))

            # Diagonal: Cyber Azure to Neon Cyan Gradient
            grad_diag = QLinearGradient(p1.x(), p1.y(), p2.x(), p2.y())
            grad_diag.setColorAt(0.0, QColor(56, 189, 248))   # Sky Cyan
            grad_diag.setColorAt(0.5, QColor(0, 120, 212))    # Fluent Azure
            grad_diag.setColorAt(1.0, QColor(30, 64, 175))    # Deep Indigo

            # Draw Left & Right
            painter.setBrush(QBrush(grad_pillar))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPath(path_left)
            painter.drawPath(path_right)

            # Draw Diagonal Bridge
            painter.setBrush(QBrush(grad_diag))
            painter.drawPath(path_diag)

            # Central Cyber Nexus Aperture
            node_center = QPointF(cx, cy)
            
            # Outer Ring Cutout
            painter.setBrush(QBrush(QColor(11, 12, 16)))
            painter.setPen(QPen(QColor(56, 189, 248), s * 0.04))
            painter.drawEllipse(node_center, s * 0.14, s * 0.14)

            # Inner Core Pulse
            core_grad = QRadialGradient(cx, cy, s * 0.07)
            core_grad.setColorAt(0.0, QColor(255, 255, 255))
            core_grad.setColorAt(0.5, QColor(56, 189, 248))
            core_grad.setColorAt(1.0, QColor(0, 120, 212))
            painter.setBrush(QBrush(core_grad))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(node_center, s * 0.065, s * 0.065)

        else:
            # Monolithic Black / Obsidian
            grad_pillar_l = QLinearGradient(cx, cy - h_bar * 0.5, cx, cy + h_bar * 0.5)
            grad_pillar_l.setColorAt(0.0, QColor(10, 10, 14))
            grad_pillar_l.setColorAt(1.0, QColor(30, 32, 40))

            grad_diag_l = QLinearGradient(p1.x(), p1.y(), p2.x(), p2.y())
            grad_diag_l.setColorAt(0.0, QColor(0, 120, 212))
            grad_diag_l.setColorAt(1.0, QColor(10, 10, 14))

            painter.setBrush(QBrush(grad_pillar_l))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPath(path_left)
            painter.drawPath(path_right)

            painter.setBrush(QBrush(grad_diag_l))
            painter.drawPath(path_diag)

            # Center Aperture
            node_center = QPointF(cx, cy)
            painter.setBrush(QBrush(QColor(255, 255, 255)))
            painter.setPen(QPen(QColor(10, 10, 14), s * 0.04))
            painter.drawEllipse(node_center, s * 0.14, s * 0.14)

            painter.setBrush(QBrush(QColor(0, 120, 212)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(node_center, s * 0.065, s * 0.065)

    # 1. Dark Mode Square Logo (1024x1024)
    img_dark = QImage(1024, 1024, QImage.Format.Format_ARGB32_Premultiplied)
    img_dark.fill(QColor(0, 0, 0, 0))
    p_dark = QPainter(img_dark)
    p_dark.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    
    bg_path = QPainterPath()
    bg_path.addRoundedRect(QRectF(32, 32, 960, 960), 220, 220)
    bg_grad = QLinearGradient(0, 0, 1024, 1024)
    bg_grad.setColorAt(0.0, QColor(24, 26, 34))
    bg_grad.setColorAt(0.5, QColor(14, 15, 20))
    bg_grad.setColorAt(1.0, QColor(8, 9, 12))
    p_dark.setBrush(QBrush(bg_grad))
    p_dark.setPen(QPen(QColor(48, 52, 68), 4))
    p_dark.drawPath(bg_path)

    draw_nazak_symbol(p_dark, 512, 512, 560, dark_mode=True)
    p_dark.end()
    img_dark.save(str(assets_dir / "logo_dark.png"))
    print("Saved logo_dark.png")

    # 2. Light Mode Square Logo (1024x1024)
    img_light = QImage(1024, 1024, QImage.Format.Format_ARGB32_Premultiplied)
    img_light.fill(QColor(0, 0, 0, 0))
    p_light = QPainter(img_light)
    p_light.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    
    bg_path_l = QPainterPath()
    bg_path_l.addRoundedRect(QRectF(32, 32, 960, 960), 220, 220)
    bg_grad_l = QLinearGradient(0, 0, 1024, 1024)
    bg_grad_l.setColorAt(0.0, QColor(255, 255, 255))
    bg_grad_l.setColorAt(1.0, QColor(242, 245, 250))
    p_light.setBrush(QBrush(bg_grad_l))
    p_light.setPen(QPen(QColor(215, 220, 230), 4))
    p_light.drawPath(bg_path_l)

    draw_nazak_symbol(p_light, 512, 512, 560, dark_mode=False)
    p_light.end()
    img_light.save(str(assets_dir / "logo_light.png"))
    print("Saved logo_light.png")

    # 3. Transparent Logos
    img_trans_d = QImage(1024, 1024, QImage.Format.Format_ARGB32_Premultiplied)
    img_trans_d.fill(QColor(0, 0, 0, 0))
    p_td = QPainter(img_trans_d)
    draw_nazak_symbol(p_td, 512, 512, 620, dark_mode=True)
    p_td.end()
    img_trans_d.save(str(assets_dir / "logo_dark_transparent.png"))

    img_trans_l = QImage(1024, 1024, QImage.Format.Format_ARGB32_Premultiplied)
    img_trans_l.fill(QColor(0, 0, 0, 0))
    p_tl = QPainter(img_trans_l)
    draw_nazak_symbol(p_tl, 512, 512, 620, dark_mode=False)
    p_tl.end()
    img_trans_l.save(str(assets_dir / "logo_light_transparent.png"))

    # 4. Multi-Resolution Windows .ICO
    pil_img = Image.open(str(assets_dir / "logo_dark.png"))
    icon_sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)]
    pil_img.save(str(assets_dir / "icon.ico"), format="ICO", sizes=icon_sizes)
    pil_img.resize((256, 256), Image.Resampling.LANCZOS).save(str(assets_dir / "app_icon.png"))
    print("Saved icon.ico and app_icon.png")

    # 5. Wide High-Resolution GitHub Repository Banner (1280x420)
    img_banner = QImage(1280, 420, QImage.Format.Format_ARGB32_Premultiplied)
    img_banner.fill(QColor(10, 11, 15))
    p_ban = QPainter(img_banner)
    p_ban.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p_ban.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    glow_bg = QRadialGradient(240, 210, 450)
    glow_bg.setColorAt(0.0, QColor(0, 120, 212, 55))
    glow_bg.setColorAt(0.6, QColor(56, 189, 248, 15))
    glow_bg.setColorAt(1.0, QColor(0, 0, 0, 0))
    p_ban.setBrush(QBrush(glow_bg))
    p_ban.setPen(Qt.PenStyle.NoPen)
    p_ban.drawRect(0, 0, 1280, 420)

    p_ban.setPen(QPen(QColor(35, 38, 48), 2))
    p_ban.setBrush(Qt.BrushStyle.NoBrush)
    p_ban.drawRoundedRect(QRectF(1, 1, 1278, 418), 16, 16)

    # Symbol on left
    draw_nazak_symbol(p_ban, 220, 210, 290, dark_mode=True)

    # Wordmark
    font_title = QFont("Segoe UI Variable Display", 36, QFont.Weight.Bold)
    font_title.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, -1.0)
    p_ban.setFont(font_title)
    p_ban.setPen(QColor(255, 255, 255))
    p_ban.drawText(400, 165, "NAZAK BROWSER STUDIO")

    # Pro Pill
    p_ban.setBrush(QBrush(QColor(0, 120, 212, 40)))
    p_ban.setPen(QPen(QColor(56, 189, 248), 1.5))
    p_ban.drawRoundedRect(QRectF(1030, 124, 75, 34), 6, 6)
    font_pro = QFont("Segoe UI Variable Text", 13, QFont.Weight.Bold)
    p_ban.setFont(font_pro)
    p_ban.setPen(QColor(56, 189, 248))
    p_ban.drawText(1048, 147, "PRO")

    # Tagline
    font_sub = QFont("Segoe UI Variable Text", 16, QFont.Weight.Medium)
    p_ban.setFont(font_sub)
    p_ban.setPen(QColor(161, 161, 170))
    p_ban.drawText(400, 215, "Next-Gen Anti-Detect Browser  •  Total Hardware Shield")

    font_bullets = QFont("Segoe UI Variable Text", 13, QFont.Weight.Normal)
    p_ban.setFont(font_bullets)
    p_ban.setPen(QColor(113, 113, 122))
    p_ban.drawText(400, 265, "100% GPU / WebGL / Canvas Isolation  •  RFC 6238 2FA Engine")
    p_ban.drawText(400, 295, "YouTube Shorts Stealth Autoposter  •  FFmpeg Video Uniqueizer")

    p_ban.end()
    img_banner.save(str(assets_dir / "banner.png"))
    print("Saved banner.png")

if __name__ == "__main__":
    create_brand_assets()
