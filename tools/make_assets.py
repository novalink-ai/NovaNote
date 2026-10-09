"""从 logo.svg 生成多尺寸 PNG 与 Windows .ico，并输出一张品牌横幅图。

使用：
    python tools/make_assets.py
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QPainter  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

ASSETS = ROOT / "novanote" / "assets"
ICONS = ASSETS / "icons"
SIZES = [16, 20, 24, 32, 40, 48, 64, 96, 128, 180, 256, 512]


def render_svg(svg_path: Path, size: int) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    r = QSvgRenderer(str(svg_path))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.SmoothPixmapTransform, True)
    r.render(p, QRectF(0, 0, size, size))
    p.end()
    return img


def write_ico(path: Path, images: list[QImage]) -> None:
    """写 PNG 压缩的 ICO（Vista+ 支持）。"""
    pngs: list[bytes] = []
    for img in images:
        tmp = path.with_suffix(f".{img.width()}.tmp.png")
        img.save(str(tmp), "PNG")
        pngs.append(tmp.read_bytes())
        tmp.unlink(missing_ok=True)

    n = len(pngs)
    header = struct.pack("<HHH", 0, 1, n)
    offset = 6 + 16 * n
    entries = b""
    for img, data in zip(images, pngs):
        w = 0 if img.width() >= 256 else img.width()
        h = 0 if img.height() >= 256 else img.height()
        entries += struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    path.write_bytes(header + entries + b"".join(pngs))


def make_banner(path: Path, mark: Path) -> None:
    w, h = 1280, 400
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(QColor("#F2F5F9"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)

    # 柔和的蓝橘光晕
    from PySide6.QtGui import QRadialGradient

    g1 = QRadialGradient(210, 130, 420)
    g1.setColorAt(0.0, QColor(76, 130, 168, 46))
    g1.setColorAt(1.0, QColor(76, 130, 168, 0))
    p.fillRect(0, 0, w, h, g1)
    g2 = QRadialGradient(1090, 300, 400)
    g2.setColorAt(0.0, QColor(217, 138, 82, 40))
    g2.setColorAt(1.0, QColor(217, 138, 82, 0))
    p.fillRect(0, 0, w, h, g2)

    r = QSvgRenderer(str(mark))
    r.render(p, QRectF(90, 110, 180, 180))

    p.setPen(QColor("#1D2936"))
    f = QFont("Microsoft YaHei UI", 62)
    f.setWeight(QFont.Bold)
    p.setFont(f)
    p.drawText(310, 205, "NovaNote")

    p.setPen(QColor("#3A6E93"))
    f2 = QFont("Microsoft YaHei UI", 24)
    p.setFont(f2)
    p.drawText(312, 248, "星笺 · 本地优先的知识与文献工作台")

    p.setPen(QColor("#8B9AAB"))
    f3 = QFont("Microsoft YaHei UI", 16)
    p.setFont(f3)
    p.drawText(312, 292, "文字 / 图片 / 视频笔记    ·    学术文献管理    ·    独立工作空间")
    p.end()
    img.save(str(path), "PNG")


def main() -> int:
    app = QApplication.instance() or QApplication([])
    ICONS.mkdir(parents=True, exist_ok=True)

    svg = ASSETS / "logo.svg"
    if not svg.exists():
        print(f"找不到 {svg}")
        return 1

    images: list[QImage] = []
    for s in SIZES:
        img = render_svg(svg, s)
        out = ICONS / f"logo_{s}.png"
        img.save(str(out), "PNG")
        images.append(img)
        print(f"  ✓ {out.relative_to(ROOT)}")

    ico_sizes = [16, 24, 32, 48, 64, 128, 256]
    render_svg(svg, 512).save(str(ASSETS / "logo_512.png"), "PNG")
    write_ico(ASSETS / "logo.ico", [render_svg(svg, s) for s in ico_sizes])
    print(f"  ✓ {(ASSETS / 'logo.ico').relative_to(ROOT)}")

    make_banner(ROOT / "docs" / "banner.png", svg)
    print("  ✓ docs/banner.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
