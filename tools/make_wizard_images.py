"""生成 Inno Setup 安装向导的品牌化图片。

产物（BMP，Inno Setup 全版本支持）：
    installer/wizard-large.bmp   左侧欢迎/完成页大图
    installer/wizard-small.bmp   右上角小图

用 Qt 绘制，配色取自项目 logo.svg 的橘蓝双色体系。
运行：
    python tools/make_wizard_images.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QBrush,
    QColor,
    QFont,
    QGuiApplication,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

# 品牌色（与 novanote/theme.py 的黛蓝 / 陶橘一致）
BLUE_DEEP = QColor("#24455F")
BLUE = QColor("#3A6E93")
BLUE_LIGHT = QColor("#5E93B5")
ORANGE = QColor("#D0854C")
CREAM = QColor("#FBF7F0")

OUT_DIR = ROOT / "installer"
# Inno 的基准尺寸为 100% 缩放；这里按 2× 输出，安装器会按 DPI 缩放，
# 在高分屏上依然锐利。
LARGE = (328, 628)   # 基准 164×314
SMALL = (110, 110)   # 基准 55×55


def _bg(p: QPainter, w: int, h: int) -> None:
    g = QLinearGradient(0, 0, w * 0.6, h)
    g.setColorAt(0.0, BLUE_DEEP)
    g.setColorAt(0.55, BLUE)
    g.setColorAt(1.0, QColor("#2E5872"))
    p.fillRect(QRectF(0, 0, w, h), QBrush(g))

    # 右上角柔光
    glow = QLinearGradient(w, 0, w * 0.2, h * 0.6)
    glow.setColorAt(0.0, QColor(127, 182, 217, 70))
    glow.setColorAt(1.0, QColor(127, 182, 217, 0))
    p.fillRect(QRectF(0, 0, w, h), QBrush(glow))


def _star(p: QPainter, cx: float, cy: float, r: float, color: QColor) -> None:
    """绘制四角星芒（与 logo 中的 nova spark 同形）。"""
    path = QPainterPath()
    path.moveTo(cx, cy - r)
    path.cubicTo(cx + r * 0.10, cy - r * 0.34, cx + r * 0.34, cy - r * 0.10, cx + r, cy)
    path.cubicTo(cx + r * 0.34, cy + r * 0.10, cx + r * 0.10, cy + r * 0.34, cx, cy + r)
    path.cubicTo(cx - r * 0.10, cy + r * 0.34, cx - r * 0.34, cy + r * 0.10, cx - r, cy)
    path.cubicTo(cx - r * 0.34, cy - r * 0.10, cx - r * 0.10, cy - r * 0.34, cx, cy - r)
    p.setPen(Qt.NoPen)
    p.setBrush(color)
    p.drawPath(path)


def draw_large() -> QImage:
    w, h = LARGE
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.SmoothPixmapTransform, True)
    _bg(p, w, h)

    # 顶部品牌标识
    svg = ROOT / "novanote" / "assets" / "logo.svg"
    if svg.is_file():
        r = QSvgRenderer(str(svg))
        badge = 132
        r.render(p, QRectF((w - badge) / 2, 56, badge, badge))

    # 标题
    cx = w / 2
    p.setPen(QColor("#FFFFFF"))
    f = QFont("Microsoft YaHei UI", 17, QFont.Weight.Bold)
    p.setFont(f)
    p.drawText(QRectF(0, 214, w, 34), Qt.AlignHCenter, "NovaNote")
    p.setPen(QColor(255, 255, 255, 215))
    f2 = QFont("Microsoft YaHei UI", 11)
    p.setFont(f2)
    p.drawText(QRectF(0, 246, w, 26), Qt.AlignHCenter, "星笺")

    # 分隔细线
    p.setPen(QPen(QColor(255, 255, 255, 60), 1))
    p.drawLine(QPointF(w * 0.28, 292), QPointF(w * 0.72, 292))

    # 标语
    p.setPen(QColor(226, 238, 247, 235))
    p.setFont(QFont("Microsoft YaHei UI", 9))
    p.drawText(QRectF(24, 310, w - 48, 60), Qt.AlignHCenter | Qt.TextWordWrap,
               "本地优先的知识与文献工作台")

    # 特性列表
    p.setFont(QFont("Microsoft YaHei UI", 8))
    feats = [
        ("图文视频笔记", BLUE_LIGHT),
        ("学术文献管理", ORANGE),
        ("GB/T 7714 引用", BLUE_LIGHT),
        ("BibTeX / DOI", ORANGE),
    ]
    y = 404
    for text, dot in feats:
        p.setPen(Qt.NoPen)
        p.setBrush(dot)
        p.drawEllipse(QPointF(46, y + 8), 3.6, 3.6)
        p.setPen(QColor(233, 243, 250, 235))
        p.drawText(QRectF(60, y, w - 80, 20), Qt.AlignVCenter | Qt.AlignLeft, text)
        y += 30

    # 底部装饰星芒
    _star(p, 74, h - 108, 15, QColor(242, 184, 124, 210))
    _star(p, w - 66, h - 176, 9, QColor(242, 184, 124, 150))

    # 底部版本条
    p.setPen(QColor(220, 236, 246, 190))
    p.setFont(QFont("Microsoft YaHei UI", 7))
    p.drawText(QRectF(0, h - 52, w, 20), Qt.AlignHCenter, "v1.0.0")

    p.end()
    return img


def draw_small() -> QImage:
    w, h = SMALL
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.SmoothPixmapTransform, True)

    # 圆角底 + 品牌 logo
    p.setPen(Qt.NoPen)
    p.setBrush(BLUE)
    p.drawRoundedRect(QRectF(2, 2, w - 4, h - 4), 18, 18)

    svg = ROOT / "novanote" / "assets" / "logo.svg"
    if svg.is_file():
        QSvgRenderer(str(svg)).render(p, QRectF(12, 12, w - 24, h - 24))
    p.end()
    return img


def main() -> int:
    # 必须在任何字体渲染之前建立 QGuiApplication：
    # 没有应用实例时，Qt 的字体引擎未初始化，drawText/QFont 会导致进程崩溃。
    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, img in (("wizard-large.bmp", draw_large()), ("wizard-small.bmp", draw_small())):
        out = OUT_DIR / name
        if not img.save(str(out), "BMP"):
            print(f"写入 {out} 失败")
            return 1
        print(f"已生成 {out.relative_to(ROOT)}  ({img.width()}×{img.height()})")
    del app
    return 0


if __name__ == "__main__":
    sys.exit(main())
