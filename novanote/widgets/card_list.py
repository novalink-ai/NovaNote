"""按可视区惰性实例化卡片的列表控件。

为什么需要它
------------
`QListWidget.setItemWidget()` 会为**每一条** item 常驻一个真实 QWidget。
笔记 / 文献列表动辄上千条，逐条建控件会让界面卡死几十秒——实测 1000 篇笔记
耗时 17.4 秒、创建 3 万个控件，2000 篇直接把进程拖垮。

这里的做法是：item 只做占位（带 sizeHint 与 id），卡片控件延后到
`sync_visible()` 时按可视区实例化，滚出窗口较远的再释放。
于是控件数量与"列表长度"解耦，只与"视口高度"有关。

使用约束（踩过的坑）
--------------------
1. `factory(row, parent)` 必须把 `parent` 传给卡片的构造函数。
   卡片内部若对**还没有父控件**的 QLabel 调用 `setVisible(True)`，
   Qt 会把它当成顶层窗口并创建原生窗口句柄（实测单卡约 27ms），
   随后被 layout 收养时又要重新挂载（约 13ms）——单卡凭空多出 40ms。
2. 卡片内不要用 `setStyleSheet()` 表达选中态，改用动态属性 + 全局 QSS，
   否则每次选中都会让整棵子树重跑样式级联。
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QListWidget,
    QListWidgetItem,
    QWidget,
)


class CardList(QListWidget):
    """只保留可视区卡片控件的 QListWidget。

    参数
      factory       callable(row, parent) -> QWidget，必须使用传入的 parent
      size_hint     每条 item 的尺寸（决定滚动范围与可视区估算）
      id_of         callable(row) -> int，取该行的唯一 id
      buffer_rows   视口外额外渲染的行数
      max_cards     同时存在的卡片控件硬上限
    """

    def __init__(self, factory, size_hint: QSize, id_of,
                 buffer_rows: int = 12, max_cards: int = 240, parent=None):
        super().__init__(parent)
        self._factory = factory
        self._size_hint = size_hint
        self._id_of = id_of
        self._buffer_rows = buffer_rows
        self._max_cards = max_cards

        self._rows: list = []
        self._row_of: dict[int, int] = {}
        self._cards: dict[int, QWidget] = {}
        self._current_id: int | None = None
        self._syncing = False

        self.setFrameShape(QFrame.NoFrame)
        self.verticalScrollBar().valueChanged.connect(self.sync_visible)

    # ------------------------------------------------------------------ #
    # 数据
    # ------------------------------------------------------------------ #
    def rows(self) -> list:
        return self._rows

    def cards(self) -> list[QWidget]:
        return list(self._cards.values())

    def live_card_count(self) -> int:
        return len(self._cards)

    def set_size_hint(self, size_hint: QSize) -> None:
        self._size_hint = size_hint
        for i in range(self.count()):
            self.item(i).setSizeHint(size_hint)

    def set_rows(self, rows: list, scroll_top: bool = True) -> None:
        self.release_all()
        self.clear()

        self._rows = list(rows)
        self._row_of = {self._id_of(r): i for i, r in enumerate(self._rows)}
        if self._current_id is not None and self._current_id not in self._row_of:
            self._current_id = None

        self.setUpdatesEnabled(False)
        try:
            for r in self._rows:
                item = QListWidgetItem()
                item.setSizeHint(self._size_hint)
                item.setData(Qt.UserRole, self._id_of(r))
                self.addItem(item)
        finally:
            self.setUpdatesEnabled(True)

        row = self._row_of.get(self._current_id) if self._current_id is not None else None
        if row is None:
            self.clearSelection()
            if scroll_top:
                self.verticalScrollBar().setValue(0)
        else:
            self._select_row(row, scroll=True)
        self.sync_visible()

    def row_of(self, key: int) -> int | None:
        return self._row_of.get(key)

    # ------------------------------------------------------------------ #
    # 当前项
    # ------------------------------------------------------------------ #
    def current_id(self) -> int | None:
        return self._current_id

    def _select_row(self, row: int, scroll: bool) -> None:
        item = self.item(row)
        if item is None:
            return
        self.clearSelection()
        self.setCurrentRow(row)
        item.setSelected(True)
        card = self._cards.get(row)
        if card is not None and hasattr(card, "set_selected"):
            card.set_selected(True)
        if scroll:
            self.scrollToItem(item, QAbstractItemView.EnsureVisible)

    def set_current(self, key: int | None) -> None:
        """O(1) 定位当前项，只更新已实例化的卡片选中态。

        旧实现遍历全部 item 并逐个 set_selected，几千条时是明显的卡顿来源。
        """
        prev = self._current_id
        self._current_id = key
        if prev is not None and prev != key:
            row = self._row_of.get(prev)
            card = self._cards.get(row) if row is not None else None
            if card is not None and hasattr(card, "set_selected"):
                card.set_selected(False)

        if key is None:
            self.clearSelection()
            return
        row = self._row_of.get(key)
        if row is None:
            return
        self._select_row(row, scroll=True)
        self.sync_visible()

    # ------------------------------------------------------------------ #
    # 虚拟化
    # ------------------------------------------------------------------ #
    def _visible_range(self) -> tuple[int, int]:
        n = len(self._rows)
        if n == 0:
            return (0, -1)

        vp = self.viewport()
        vh = max(vp.height(), 1)
        vw = max(vp.width(), 1)
        buf = self._buffer_rows

        lows: list[int] = []
        highs: list[int] = []

        # ① 命中测试
        for y in (1, vh // 2, vh - 2):
            for x in (2, vw // 2, vw - 2):
                idx = self.indexAt(QPoint(x, y))
                if idx.isValid():
                    lows.append(idx.row())
                    highs.append(idx.row())

        # ② 按滚动像素推算（兜底，保证网格模式"部分填充的末行"也不会漏渲染）
        item = self.item(0)
        if item is not None and n:
            cell_h = max(item.sizeHint().height(), 1)
            scrolled = self.verticalScrollBar().value()
            top_row = scrolled // cell_h
            bot_row = (scrolled + vh) // cell_h
            if self.isWrapping():
                spacing = self.spacing()
                cell_w = max(item.sizeHint().width(), 1) + spacing
                per_row = max(1, (vw + spacing) // max(cell_w, 1))
                lows.append(top_row * per_row)
                highs.append((bot_row + 1) * per_row + per_row - 1)
            else:
                lows.append(top_row)
                highs.append(bot_row)

        if not lows:
            return (0, min(n - 1, buf))
        start = max(0, min(lows) - buf)
        end = min(n - 1, max(highs) + buf)
        return (start, max(start, end))

    def _make_card(self, row: int) -> QWidget | None:
        item = self.item(row)
        if item is None:
            return None
        card = self._factory(self._rows[row], self)   # ← parent 必须传进去
        if hasattr(card, "set_selected"):
            card.set_selected(self._id_of(self._rows[row]) == self._current_id)
        self.setItemWidget(item, card)
        self._cards[row] = card
        return card

    def _release(self, row: int) -> None:
        card = self._cards.pop(row, None)
        if card is None:
            return
        item = self.item(row)
        if item is not None:
            self.setItemWidget(item, None)
        card.setParent(None)
        card.deleteLater()

    def release_all(self) -> None:
        for row in list(self._cards):
            self._release(row)

    def sync_visible(self) -> None:
        """把卡片补齐到可视区，并释放窗口外过远的卡片。"""
        if self._syncing or not self._rows:
            return
        self._syncing = True
        try:
            start, end = self._visible_range()
            n = len(self._rows)
            buf = self._buffer_rows
            keep_lo = max(0, start - 2 * buf)
            keep_hi = min(n - 1, end + 2 * buf)

            for row in range(start, end + 1):
                if row not in self._cards and len(self._cards) < self._max_cards:
                    self._make_card(row)

            for row in [r for r in self._cards if r < keep_lo or r > keep_hi]:
                self._release(row)
        finally:
            self._syncing = False

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self.sync_visible()
