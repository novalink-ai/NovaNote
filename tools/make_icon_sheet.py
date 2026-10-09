"""生成图标系统总览图（docs/icon_set.png）。

把 `novanote.icons` 中的全部线性图标按名称排成网格，便于快速核验
每个图标的描边是否完整、比例是否统一。

用法：
    python tools/make_icon_sheet.py [--dark]
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from novanote import icons

# 明 / 暗两套配色，与 theme.py 的主色保持一致
LIGHT = {"bg": "#FAFBFC", "ink": "#2A4256", "label": "#5B6B76"}
DARK = {"bg": "#14181E", "ink": "#D7E2EC", "label": "#8B9AA8"}

ICON_SIZE = 40
CELL = 74
COLS = 12
PAD = 16


def build_sheet(dark: bool = False) -> QPixmap:
    palette = DARK if dark else LIGHT
    names = sorted(set(list(icons._S.keys()) + list(icons._F.keys())))

    rows = (len(names) + COLS - 1) // COLS
    width = PAD * 2 + COLS * CELL
    height = PAD * 2 + rows * CELL

    sheet = QPixmap(width, height)
    sheet.fill(QColor(palette["bg"]))

    p = QPainter(sheet)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setFont(QFont("Segoe UI", 7))
    p.setPen(QColor(palette["label"]))

    for i, name in enumerate(names):
        r, c = divmod(i, COLS)
        x = PAD + c * CELL
        y = PAD + r * CELL

        pm = icons.render_pixmap(name, palette["ink"], ICON_SIZE, 2.0)
        p.drawPixmap(int(x + (CELL - ICON_SIZE) / 2), int(y + 6),
                     ICON_SIZE, ICON_SIZE, pm)
        p.drawText(QRectF(x, y + 50, CELL, 18),
                   Qt.AlignHCenter | Qt.AlignTop, name)

    p.end()
    return sheet


def main() -> int:
    dark = "--dark" in sys.argv
    app = QApplication.instance() or QApplication([])

    out = ROOT / "docs" / ("icon_set_dark.png" if dark else "icon_set.png")
    sheet = build_sheet(dark)
    sheet.save(str(out))

    total = len(set(list(icons._S.keys()) + list(icons._F.keys())))
    print(f"ok {total} icons -> {out} ({sheet.width()}x{sheet.height()})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
