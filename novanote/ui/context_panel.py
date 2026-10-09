"""左侧上下文面板：笔记本、标签、文献筛选维度。"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import icons
from ..services.assets import human_size
from ..theme import tokens
from ..widgets.common import HRule, IconButton, SectionLabel, TagChip
from ..widgets.flow_layout import FlowLayout

ROW_H = 34


class NavRow(QWidget):
    """列表行：图标 + 标题 + 计数。"""

    def __init__(self, text: str, icon_name: str = "folder", color: str = "#3A6E93",
                 count: int | None = None, theme: str = "light", bold: bool = False,
                 parent=None):
        super().__init__(parent)
        self._icon_name = icon_name
        self._color = color
        self._theme = theme
        lay = QHBoxLayout(self)
        lay.setContentsMargins(9, 0, 10, 0)
        lay.setSpacing(9)
        self.icon = QLabel()
        self.icon.setFixedSize(16, 16)
        self.label = QLabel(text)
        self.label.setStyleSheet(
            f"font-weight: {'700' if bold else '500'}; font-size: 13px;"
        )
        self.count = QLabel("" if count is None else str(count))
        self.count.setProperty("role", "muted")
        lay.addWidget(self.icon)
        lay.addWidget(self.label, 1)
        lay.addWidget(self.count, 0, Qt.AlignRight)
        self.set_tint(color)
        if theme:
            self.refresh(theme)

    def set_tint(self, color: str) -> None:
        self._color = color

    def refresh(self, theme: str) -> None:
        self._theme = theme
        t = tokens(theme)
        px = icons.render_pixmap(self._icon_name, self._color, 16)
        self.icon.setPixmap(px)

    def set_count(self, n: int) -> None:
        self.count.setText("" if n is None else str(n))


class _NavList(QListWidget):
    activated = Signal(object)      # payload
    contextRequested = Signal(object, QPoint)

    def __init__(self, theme: str, parent=None):
        super().__init__(parent)
        self._theme = theme
        self.setFrameShape(QFrame.NoFrame)
        self.setSpacing(1)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setUniformItemSizes(True)
        self.itemClicked.connect(self._on_click)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_ctx)

    def add_row(self, row: NavRow, payload) -> QListWidgetItem:
        item = QListWidgetItem()
        item.setSizeHint(QSize(10, ROW_H))
        item.setData(Qt.UserRole, payload)
        self.addItem(item)
        self.setItemWidget(item, row)
        return item

    def _on_click(self, item: QListWidgetItem) -> None:
        self.activated.emit(item.data(Qt.UserRole))

    def _on_ctx(self, pos: QPoint) -> None:
        item = self.itemAt(pos)
        if item is None:
            return
        self.contextRequested.emit(item.data(Qt.UserRole), self.viewport().mapToGlobal(pos))

    def refresh(self, theme: str) -> None:
        self._theme = theme
        for i in range(self.count()):
            w = self.itemWidget(self.item(i))
            if isinstance(w, NavRow):
                w.refresh(theme)


# --------------------------------------------------------------------------- #
def _header(text: str, theme: str, add_tip: str = "") -> tuple[QWidget, IconButton | None]:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(12, 4, 8, 2)
    lay.setSpacing(4)
    lab = SectionLabel(text)
    lay.addWidget(lab)
    lay.addStretch(1)
    btn = None
    if add_tip:
        btn = IconButton("plus", theme, 24, 14, tip=add_tip)
        lay.addWidget(btn)
    return w, btn


class NotebookPanel(QWidget):
    notebookSelected = Signal(object)       # int | None
    tagSelected = Signal(str)
    addNotebookRequested = Signal()
    notebookContextRequested = Signal(int, QPoint)
    tagContextRequested = Signal(str, QPoint)
    addTagRequested = Signal()

    def __init__(self, theme: str = "light", parent=None):
        super().__init__(parent)
        self._theme = theme
        self._current: object = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(2)

        head, self.btn_add_nb = _header("笔记本", theme, "新建笔记本")
        self.btn_add_nb.clicked.connect(self.addNotebookRequested.emit)
        lay.addWidget(head)

        self.nb_list = _NavList(theme)
        self.nb_list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.nb_list.setMinimumHeight(ROW_H * 2)
        self.nb_list.activated.connect(self._on_nb)
        self.nb_list.contextRequested.connect(self._on_nb_ctx)
        self.nb_list.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        lay.addWidget(self.nb_list)

        lay.addSpacing(6)
        head2, self.btn_add_tag = _header("标签", theme, "新建标签")
        self.btn_add_tag.clicked.connect(self.addTagRequested.emit)
        lay.addWidget(head2)

        self.tag_area = QScrollArea()
        self.tag_area.setWidgetResizable(True)
        self.tag_area.setFrameShape(QFrame.NoFrame)
        self.tag_host = QWidget()
        self.tag_flow = FlowLayout(self.tag_host, margin=6, h_spacing=5, v_spacing=5)
        self.tag_area.setWidget(self.tag_host)
        self.tag_area.setMinimumHeight(56)
        self.tag_area.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        lay.addWidget(self.tag_area, 1)

        self.footer = QLabel("")
        self.footer.setProperty("role", "muted")
        self.footer.setWordWrap(True)
        self.footer.setContentsMargins(12, 4, 12, 8)
        lay.addWidget(self.footer)

    # ------------------------------------------------------------------ #
    def set_data(self, notebooks, tags, stats: dict) -> None:
        self.nb_list.clear()
        all_row = NavRow("全部笔记", "layers", tokens(self._theme)["blue"],
                         sum(n.note_count for n in notebooks), self._theme, bold=True)
        self.nb_list.add_row(all_row, None)
        for nb in notebooks:
            row = NavRow(nb.name, nb.icon, nb.color, nb.note_count, self._theme)
            self.nb_list.add_row(row, nb.id)
        self.nb_list.setFixedHeight(min(6, self.nb_list.count()) * ROW_H + 4)
        self.nb_list.setMinimumHeight(self.nb_list.count() * ROW_H + 4)

        # 标签
        self.tag_flow.clear()
        if not tags:
            hint = QLabel("暂无标签，在笔记中添加 #标签")
            hint.setProperty("role", "muted")
            hint.setWordWrap(True)
            self.tag_flow.addWidget(hint)
        for tg in tags:
            chip = TagChip(tg.name, tg.color, self._theme, removable=True)
            chip.clickedTag.connect(self.tagSelected.emit)
            chip.removed.connect(lambda nm: self.tagContextRequested.emit(nm, QCursor.pos()))
            self.tag_flow.addWidget(chip)

        words = stats.get("words", 0)
        self.footer.setText(
            f"{stats.get('notes', 0)} 篇笔记 · {stats.get('assets', 0)} 个附件 · "
            f"约 {words:,} 字\n占用 {human_size(stats.get('total_assets_bytes', 0) or stats.get('size', 0))}"
        )

    def set_selected(self, payload) -> None:
        self._current = payload

    def _on_nb(self, payload) -> None:
        self._current = payload
        self.notebookSelected.emit(payload)

    def _on_nb_ctx(self, payload, pos: QPoint) -> None:
        if payload is None:
            return
        self.notebookContextRequested.emit(int(payload), pos)

    def refresh(self, theme: str) -> None:
        self._theme = theme
        self.nb_list.refresh(theme)
        for b in (self.btn_add_nb, self.btn_add_tag):
            b.refresh(theme)


# --------------------------------------------------------------------------- #
class LiteraturePanel(QWidget):
    filterSelected = Signal(str, object)     # key, value
    tagSelected = Signal(str)
    tagContextRequested = Signal(str, QPoint)

    def __init__(self, theme: str = "light", parent=None):
        super().__init__(parent)
        self._theme = theme
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(2)

        head, _ = _header("文献库", theme)
        lay.addWidget(head)

        self.state_list = _NavList(theme)
        self.state_list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.state_list.activated.connect(
            lambda v: self.filterSelected.emit(v[0], v[1]) if isinstance(v, tuple) else None)
        lay.addWidget(self.state_list)

        head2, _ = _header("年份", theme)
        lay.addWidget(head2)
        self.year_list = _NavList(theme)
        self.year_list.setMinimumHeight(90)
        self.year_list.setMaximumHeight(190)
        self.year_list.activated.connect(
            lambda v: self.filterSelected.emit("year", v))
        lay.addWidget(self.year_list)

        head3, _ = _header("来源 / 出版物", theme)
        lay.addWidget(head3)
        self.venue_list = _NavList(theme)
        self.venue_list.setMinimumHeight(80)
        self.venue_list.setMaximumHeight(170)
        self.venue_list.activated.connect(
            lambda v: self.filterSelected.emit("container", v))
        lay.addWidget(self.venue_list)

        head4, _ = _header("标签", theme)
        lay.addWidget(head4)
        self.tag_area = QScrollArea()
        self.tag_area.setWidgetResizable(True)
        self.tag_area.setFrameShape(QFrame.NoFrame)
        self.tag_host = QWidget()
        self.tag_flow = FlowLayout(self.tag_host, margin=6, h_spacing=5, v_spacing=5)
        self.tag_area.setWidget(self.tag_host)
        self.tag_area.setMinimumHeight(56)
        lay.addWidget(self.tag_area, 1)

    # ------------------------------------------------------------------ #
    def set_data(self, refs, tags, years, venues, stats: dict) -> None:
        t = tokens(self._theme)
        self.state_list.clear()
        total = stats.get("refs", 0)
        rows = [
            (("all", None), "全部文献", "book", t["blue"], total),
            (("starred", True), "星标文献", "star", t["orange"],
             sum(1 for r in refs if r.is_starred)),
            (("has_pdf", True), "含 PDF 全文", "paperclip", t["success"],
             sum(1 for r in refs if r.pdf_count)),
        ]
        for st, label in ((0, "未读"), (1, "在读"), (2, "已读")):
            rows.append((("read_state", st), label, "eye", t["text_secondary"],
                         sum(1 for r in refs if r.read_state == st)))
        for payload, label, icn, color, cnt in rows:
            row = NavRow(label, icn, color, cnt, self._theme)
            self.state_list.add_row(row, payload)
        self.state_list.setFixedHeight(len(rows) * ROW_H + 4)

        self.year_list.clear()
        for year, cnt in years[:60]:
            self.year_list.add_row(NavRow(year, "calendar", t["text_secondary"], cnt, self._theme), year)
        if not years:
            self.year_list.add_row(NavRow("暂无年份数据", "calendar", t["text_muted"], None, self._theme), None)

        self.venue_list.clear()
        for name, cnt in venues[:60]:
            row = NavRow(name if len(name) <= 26 else name[:25] + "…", "globe",
                         t["text_secondary"], cnt, self._theme)
            self.venue_list.add_row(row, name)
        if not venues:
            self.venue_list.add_row(NavRow("暂无来源数据", "globe", t["text_muted"], None, self._theme), None)

        self.tag_flow.clear()
        if not tags:
            hint = QLabel("暂无标签")
            hint.setProperty("role", "muted")
            self.tag_flow.addWidget(hint)
        for tg in tags:
            chip = TagChip(tg.name, tg.color, self._theme)
            chip.clickedTag.connect(self.tagSelected.emit)
            self.tag_flow.addWidget(chip)

    def refresh(self, theme: str) -> None:
        self._theme = theme
        for lst in (self.state_list, self.year_list, self.venue_list):
            lst.refresh(theme)


# --------------------------------------------------------------------------- #
class SimplePanel(QWidget):
    """收藏 / 回收站模式下的说明面板。"""

    def __init__(self, theme: str = "light", parent=None):
        super().__init__(parent)
        self._theme = theme
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        self.title = SectionLabel("说明")
        lay.addWidget(self.title)
        self.body = QLabel("")
        self.body.setWordWrap(True)
        self.body.setProperty("role", "secondary")
        lay.addWidget(self.body)
        lay.addWidget(HRule())
        self.extra = QLabel("")
        self.extra.setWordWrap(True)
        self.extra.setProperty("role", "muted")
        lay.addWidget(self.extra)
        lay.addStretch(1)

    def set_content(self, title: str, body: str, extra: str = "") -> None:
        self.title.setText(title)
        self.body.setText(body)
        self.extra.setText(extra)

    def refresh(self, theme: str) -> None:
        self._theme = theme


# --------------------------------------------------------------------------- #
class ContextPanel(QFrame):
    notebookSelected = Signal(object)
    tagSelected = Signal(str)
    filterSelected = Signal(str, object)
    addNotebookRequested = Signal()
    addTagRequested = Signal()
    notebookContextRequested = Signal(int, QPoint)
    tagContextRequested = Signal(str, QPoint)

    def __init__(self, theme: str = "light", parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")
        self.setMinimumWidth(216)
        self._theme = theme

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.stack = QStackedWidget()
        self.notebook_panel = NotebookPanel(theme)
        self.literature_panel = LiteraturePanel(theme)
        self.simple_panel = SimplePanel(theme)
        for w in (self.notebook_panel, self.literature_panel, self.simple_panel):
            self.stack.addWidget(w)
        lay.addWidget(self.stack)

        self.notebook_panel.notebookSelected.connect(self.notebookSelected.emit)
        self.notebook_panel.tagSelected.connect(self.tagSelected.emit)
        self.notebook_panel.addNotebookRequested.connect(self.addNotebookRequested.emit)
        self.notebook_panel.addTagRequested.connect(self.addTagRequested.emit)
        self.notebook_panel.notebookContextRequested.connect(self.notebookContextRequested.emit)
        self.notebook_panel.tagContextRequested.connect(self.tagContextRequested.emit)

        self.literature_panel.filterSelected.connect(self.filterSelected.emit)
        self.literature_panel.tagSelected.connect(self.tagSelected.emit)
        self.literature_panel.tagContextRequested.connect(self.tagContextRequested.emit)

    def show_page(self, index: int) -> None:
        self.stack.setCurrentIndex(index)

    def refresh(self, theme: str) -> None:
        self._theme = theme
        self.notebook_panel.refresh(theme)
        self.literature_panel.refresh(theme)
        self.simple_panel.refresh(theme)
        self.style().unpolish(self)
        self.style().polish(self)
