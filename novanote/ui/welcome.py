"""欢迎页 / 工作台概览。"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from .. import icons
from ..config import APP_NAME, APP_NAME_CN, APP_TAGLINE
from ..services.assets import human_size
from ..theme import tokens
from ..widgets.common import TextButton, elide


class _ActionCard(QWidget):
    clicked = Signal()

    def __init__(self, icon_name: str, title: str, desc: str, theme: str,
                 accent: str, parent=None):
        super().__init__(parent)
        self._theme = theme
        self._accent = accent
        self._icon_name = icon_name
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(104)
        self.setObjectName("ActionCard")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(15, 13, 15, 13)
        lay.setSpacing(7)

        self.icon = QLabel()
        self.icon.setFixedSize(22, 22)
        lay.addWidget(self.icon)

        self.title = QLabel(title)
        self.title.setStyleSheet("font-size: 14px; font-weight: 700;")
        lay.addWidget(self.title)

        self.desc = QLabel(desc)
        self.desc.setProperty("role", "muted")
        self.desc.setWordWrap(True)
        lay.addWidget(self.desc)
        lay.addStretch(1)
        self.refresh(theme)

    def refresh(self, theme: str) -> None:
        self._theme = theme
        t = tokens(theme)
        self.icon.setPixmap(icons.render_pixmap(self._icon_name, self._accent, 22))
        self.setStyleSheet(
            f"QWidget#ActionCard {{ background: {t['bg_surface']};"
            f" border: 1px solid {t['border']}; border-radius: 12px; }}"
            f"QWidget#ActionCard:hover {{ border: 1px solid {self._accent};"
            f" background: {t['bg_hover']}; }}"
            f"QLabel {{ background: transparent; }}"
        )

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class WelcomeView(QWidget):
    newNote = Signal()
    newRef = Signal()
    quickCapture = Signal()
    importRequested = Signal()
    openNote = Signal(int)
    openWorkspaceDir = Signal()
    switchWorkspace = Signal()

    def __init__(self, theme: str = "light", parent=None):
        super().__init__(parent)
        self._theme = theme
        self._recent_buttons: list = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(46, 40, 46, 30)
        outer.setSpacing(0)
        outer.addStretch(1)

        col = QVBoxLayout()
        col.setSpacing(0)

        # ---- 品牌区 ---- #
        hero = QHBoxLayout()
        hero.setSpacing(18)
        logo = QLabel()
        self.logo = logo
        logo.setFixedSize(84, 84)
        hero.addWidget(logo, 0, Qt.AlignTop)

        txt = QVBoxLayout()
        txt.setSpacing(5)
        self.name_label = QLabel(f"{APP_NAME}  {APP_NAME_CN}")
        self.name_label.setProperty("role", "display")
        self.tag_label = QLabel(APP_TAGLINE)
        self.tag_label.setProperty("role", "secondary")
        self.ws_label = QLabel("")
        self.ws_label.setProperty("role", "muted")
        txt.addWidget(self.name_label)
        txt.addWidget(self.tag_label)
        txt.addSpacing(3)
        txt.addWidget(self.ws_label)
        hero.addLayout(txt, 1)
        col.addLayout(hero)

        col.addSpacing(26)

        # ---- 快捷入口 ---- #
        cards = QHBoxLayout()
        cards.setSpacing(12)
        self.card_note = _ActionCard("note", "写一篇笔记",
                                     "支持标题层级、待办、表格与代码块", theme, tokens(theme)["blue"])
        self.card_ref = _ActionCard("book", "添加文献",
                                    "DOI 抓取 / BibTeX 导入 / 引用格式化", theme, tokens(theme)["orange"])
        self.card_quick = _ActionCard("spark", "快速记录",
                                      "Ctrl+Shift+N 随手记一句，再慢慢整理", theme, tokens(theme)["success"])
        self.card_note.clicked.connect(self.newNote.emit)
        self.card_ref.clicked.connect(self.newRef.emit)
        self.card_quick.clicked.connect(self.quickCapture.emit)
        for c in (self.card_note, self.card_ref, self.card_quick):
            cards.addWidget(c, 1)
        col.addLayout(cards)

        col.addSpacing(26)

        # ---- 最近笔记 ---- #
        recent_head = QHBoxLayout()
        rl = QLabel("最近编辑")
        rl.setProperty("role", "h3")
        recent_head.addWidget(rl)
        recent_head.addStretch(1)
        self.btn_dir = TextButton("打开数据目录", "folder", theme, "ghost")
        self.btn_dir.clicked.connect(self.openWorkspaceDir.emit)
        self.btn_switch = TextButton("切换工作空间", "workspace", theme, "ghost")
        self.btn_switch.clicked.connect(self.switchWorkspace.emit)
        recent_head.addWidget(self.btn_dir)
        recent_head.addWidget(self.btn_switch)
        col.addLayout(recent_head)
        col.addSpacing(9)

        self.recent_host = QWidget()
        self.recent_grid = QGridLayout(self.recent_host)
        self.recent_grid.setContentsMargins(0, 0, 0, 0)
        self.recent_grid.setHorizontalSpacing(10)
        self.recent_grid.setVerticalSpacing(8)
        col.addWidget(self.recent_host)

        self.empty_hint = QLabel("还没有笔记 —— 从上面挑一个入口开始吧。")
        self.empty_hint.setProperty("role", "muted")
        col.addWidget(self.empty_hint)

        outer.addLayout(col)
        outer.addStretch(2)
        self.refresh(theme)

    # ------------------------------------------------------------------ #
    def set_data(self, workspace_name: str, stats: dict, recent: list) -> None:
        self.ws_label.setText(
            f"工作空间「{workspace_name}」  ·  {stats.get('notes', 0)} 篇笔记  ·  "
            f"{stats.get('refs', 0)} 条文献  ·  {stats.get('assets', 0)} 个附件  ·  "
            f"占用 {human_size(stats.get('total_assets_bytes', 0))}"
        )
        while self.recent_grid.count():
            item = self.recent_grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._recent_buttons = []
        self.empty_hint.setVisible(not recent)

        t = tokens(self._theme)
        for i, note in enumerate(recent[:6]):
            btn = TextButton(elide(note.title, 190), "note", self._theme, "subtle")
            btn.setMinimumHeight(34)
            btn.setToolTip(f"{note.title}\n更新于 {note.full_time}")
            btn.clicked.connect(lambda _=False, nid=note.id: self.openNote.emit(nid))
            self.recent_grid.addWidget(btn, i // 2, i % 2)
            self._recent_buttons.append(btn)

    def refresh(self, theme: str) -> None:
        self._theme = theme
        self.logo.setPixmap(icons.logo_pixmap(84))
        for c in (self.card_note, self.card_ref, self.card_quick):
            c.refresh(theme)
        for b in (self.btn_dir, self.btn_switch):
            b.refresh(theme)
        for b in self._recent_buttons:
            b.refresh(theme)
