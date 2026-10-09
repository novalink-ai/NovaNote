"""笔记列表面板：富卡片列表、紧凑列表、媒体网格三种视图。"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import icons
from ..models import Note
from ..theme import tokens
from ..widgets.card_list import CardList
from ..widgets.common import EmptyState, IconButton, StarButton, elide

SORT_OPTIONS = [
    ("updated_desc", "最近修改"),
    ("created_desc", "创建时间"),
    ("title_asc", "标题 A→Z"),
]

KIND_ICON = {"image": "image", "video": "video", "mixed": "layers", "text": "note"}

# 卡片尺寸（同时用于 item 的 sizeHint 与可视区估算）
_CARD_SIZE = {"list": (10, 96), "media": (162, 172)}

# 视口外额外渲染的行数：太小会在滚动时露白，太大则浪费构造成本
_BUFFER_ROWS = {"list": 12, "media": 3}


def _luminance_ok(color: str) -> str:
    return color or "#3A6E93"


class NoteCard(QWidget):
    """列表视图下的笔记卡片。"""

    starredToggled = Signal(int, bool)
    doubleClicked = Signal(int)

    def __init__(self, note: Note, theme: str = "light", compact: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("NoteCard")
        self.note_id = note.id
        self._theme = theme
        self._compact = compact
        self._selected = False
        self._starred = note.is_starred
        # 选中态走动态属性（样式定义在全局 QSS 的 #NoteCard[sel="true"] 中）。
        # 这里在首次 polish 之前就把属性设好，因此不需要额外的 repolish。
        self.setProperty("sel", "false")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(13, 9, 11, 9)
        lay.setSpacing(4)

        top = QHBoxLayout()
        top.setSpacing(7)
        self.kind_icon = QLabel(self)
        self.kind_icon.setFixedSize(15, 15)
        self.title = QLabel(self)
        self.title.setProperty("role", "cardTitle")
        self.star = StarButton(note.is_starred, theme, 22, parent=self)
        self.star.toggledStar.connect(lambda v: self.starredToggled.emit(self.note_id, v))
        top.addWidget(self.kind_icon)
        top.addWidget(self.title, 1)
        top.addWidget(self.star)
        lay.addLayout(top)

        # ★ 必须在构造时就传 parent：否则下面的 setVisible() 会让这个还没有父控件的
        #   QLabel 变成顶层窗口，触发原生窗口创建（实测约 27ms），随后 addWidget
        #   又要把它重新挂回父控件（约 13ms）。单张卡片因此凭空多出约 40ms。
        self.preview = QLabel(note.preview or "（空白笔记）", self)
        self.preview.setWordWrap(False)
        self.preview.setProperty("role", "secondary")
        self.preview.setVisible(not compact)
        lay.addWidget(self.preview)

        meta = QHBoxLayout()
        meta.setSpacing(8)
        self.meta = QLabel(self)
        self.meta.setProperty("role", "muted")
        self.meta.setText(self._meta_text(note))
        meta.addWidget(self.meta, 1)
        self.badges = QLabel(self)
        self.badges.setProperty("role", "muted")
        meta.addWidget(self.badges, 0, Qt.AlignRight)
        lay.addLayout(meta)

        self.set_note(note)
        self.refresh(theme)

    def _meta_text(self, note: Note) -> str:
        parts = [note.display_time]
        if note.notebook_name:
            parts.append(note.notebook_name)
        if note.word_count:
            parts.append(f"{note.word_count} 字")
        return "  ·  ".join(parts)

    def set_note(self, note: Note) -> None:
        self.note_id = note.id
        self._starred = note.is_starred
        self.title.setText(elide(note.title, 320))
        self.preview.setText(elide(note.preview, 420) or "（空白笔记）")
        self.meta.setText(self._meta_text(note))
        badges = []
        if note.asset_count:
            badges.append(f"⧉ {note.asset_count}")
        if note.ref_count:
            badges.append(f"❝ {note.ref_count}")
        if note.tags:
            badges.append(" ".join("#" + t for t in note.tags[:2]))
        self.badges.setText("   ".join(badges))
        self.star.set_checked_silent(note.is_starred)
        self.kind_icon.setToolTip({
            "image": "图片笔记", "video": "视频笔记", "mixed": "多媒体笔记", "text": "文字笔记",
        }.get(note.kind, "笔记"))

    def refresh(self, theme: str) -> None:
        self._theme = theme
        t = tokens(theme)
        self.kind_icon.setPixmap(icons.render_pixmap(
            KIND_ICON.get(self._note_kind or "text", "note"), t["text_muted"], 15))
        self.star.refresh(theme)
        self._apply_bg()

    @property
    def _note_kind(self) -> str:
        return getattr(self, "_kind_cache", "text")

    def set_kind(self, kind: str) -> None:
        self._kind_cache = kind

    def set_selected(self, value: bool) -> None:
        self._selected = value
        self._sync_style()

    def _sync_style(self) -> None:
        """按选中态刷新背景。

        刻意不用 setStyleSheet()：那会让 Qt 为整棵子树重新解析样式表并重跑
        级联匹配（实测单卡约 20ms，滚动一屏就要几百毫秒）。这里只改一个动态
        属性，并且仅在真的变化时才 repolish。
        """
        want = "true" if self._selected else "false"
        if self.property("sel") == want:
            return
        self.setProperty("sel", want)
        self.style().unpolish(self)
        self.style().polish(self)

    # 兼容旧调用点
    _apply_bg = _sync_style

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        self.doubleClicked.emit(self.note_id)
        super().mouseDoubleClickEvent(event)


class MediaCard(QWidget):
    """媒体网格视图下的缩略图卡片。"""

    doubleClicked = Signal(int)

    def __init__(self, note: Note, thumb: QPixmap | None, theme: str = "light", parent=None):
        super().__init__(parent)
        self.setObjectName("MediaCard")
        self.note_id = note.id
        self._theme = theme
        self._selected = False
        self.setProperty("sel", "false")
        self.setFixedSize(158, 168)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(7, 7, 7, 7)
        lay.setSpacing(5)

        t = tokens(theme)
        holder = QLabel(self)
        holder.setObjectName("MediaHolder")
        holder.setFixedSize(144, 112)
        holder.setAlignment(Qt.AlignCenter)
        if thumb is not None and not thumb.isNull():
            holder.setPixmap(thumb.scaled(144, 112, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            holder.setPixmap(icons.render_pixmap(
                "video" if note.kind == "video" else "image", t["text_muted"], 34))
        lay.addWidget(holder, 0, Qt.AlignHCenter)

        self.title = QLabel(elide(note.title, 160), self)
        self.title.setProperty("role", "cardTitleSm")
        self.sub = QLabel(note.display_time, self)
        self.sub.setProperty("role", "muted")
        lay.addWidget(self.title)
        lay.addWidget(self.sub)

    def set_selected(self, value: bool) -> None:
        self._selected = value
        self._sync_style()

    def _sync_style(self) -> None:
        want = "true" if self._selected else "false"
        if self.property("sel") == want:
            return
        self.setProperty("sel", want)
        self.style().unpolish(self)
        self.style().polish(self)

    _apply_bg = _sync_style

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        self.doubleClicked.emit(self.note_id)
        super().mouseDoubleClickEvent(event)


class NoteListPane(QFrame):
    noteSelected = Signal(int)
    noteStarred = Signal(int, bool)
    noteContextRequested = Signal(int, QPoint)
    newNoteRequested = Signal()
    sortChanged = Signal(str)
    viewChanged = Signal(str)
    emptyActionRequested = Signal()

    def __init__(self, theme: str = "light", parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")
        self.setMinimumWidth(268)
        self._theme = theme
        self._mode = "list"
        self._notes: list[Note] = []
        self._thumbs: dict[int, QPixmap] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- 头部 ---- #
        head = QWidget()
        head_lay = QVBoxLayout(head)
        head_lay.setContentsMargins(13, 11, 11, 8)
        head_lay.setSpacing(8)

        r1 = QHBoxLayout()
        r1.setSpacing(6)
        self.list_title = QLabel("全部笔记")
        self.list_title.setProperty("role", "h1")
        self.count_label = QLabel("0")
        self.count_label.setProperty("role", "muted")
        r1.addWidget(self.list_title)
        r1.addWidget(self.count_label)
        r1.addStretch(1)
        self.btn_new = IconButton("plus", theme, 28, 17, tip="新建笔记（Ctrl+N）")
        self.btn_new.clicked.connect(self.newNoteRequested.emit)
        r1.addWidget(self.btn_new)
        head_lay.addLayout(r1)

        r2 = QHBoxLayout()
        r2.setSpacing(4)
        self.sort_box = QComboBox()
        for key, label in SORT_OPTIONS:
            self.sort_box.addItem(label, key)
        self.sort_box.setFixedHeight(28)
        self.sort_box.currentIndexChanged.connect(
            lambda i: self.sortChanged.emit(self.sort_box.itemData(i)))
        r2.addWidget(self.sort_box, 1)

        self.view_group: list[IconButton] = []
        for key, icn, tip in (("list", "rows", "列表视图"),
                              ("media", "grid", "媒体网格")):
            b = IconButton(icn, theme, 28, 16, tip=tip)
            b.setCheckable(True)
            b.setChecked(key == "list")
            b.clicked.connect(lambda _=False, k=key: self.set_mode(k))
            r2.addWidget(b)
            self.view_group.append(b)
        head_lay.addLayout(r2)
        root.addWidget(head)

        # ---- 列表 ---- #
        # 用 CardList：只实例化可视区附近的卡片，控件数与列表长度解耦。
        self.list = CardList(
            factory=self._make_card,
            size_hint=QSize(*_CARD_SIZE["list"]),
            id_of=lambda note: note.id,
            buffer_rows=_BUFFER_ROWS["list"],
            max_cards=240,
        )
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._on_ctx)
        self.list.itemClicked.connect(self._on_item_clicked)
        root.addWidget(self.list, 1)

        # ---- 空状态 ---- #
        self.empty = EmptyState("note", "这里还没有笔记",
                                "点击右上角 + 新建一篇，或直接把图片/视频拖进来。",
                                theme, "新建笔记")
        self.empty.action.clicked.connect(self.emptyActionRequested.emit)
        root.addWidget(self.empty, 1)
        self.empty.setVisible(False)

    # ------------------------------------------------------------------ #
    def _make_card(self, note: Note, parent) -> QWidget:
        """CardList 的卡片工厂。

        `parent` 必须透传给卡片构造函数——否则卡片内部对尚无父控件的 QLabel
        调用 setVisible(True) 会触发原生顶层窗口创建，单卡多出约 40ms。
        """
        if self._mode == "media":
            return MediaCard(note, self._thumbs.get(note.id), self._theme, parent=parent)
        card = NoteCard(note, self._theme, compact=False, parent=parent)
        card.set_kind(note.kind)
        card.refresh(self._theme)
        card.doubleClicked.connect(self.noteSelected.emit)
        card.starredToggled.connect(self.noteStarred.emit)
        return card
    def set_mode(self, mode: str) -> None:
        self._mode = mode
        for b, k in zip(self.view_group, ("list", "media")):
            b.setChecked(k == mode)
        self.viewChanged.emit(mode)
        self.list.setViewMode(QListWidget.IconMode if mode == "media" else QListWidget.ListMode)
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setWrapping(mode == "media")
        self.list.setSpacing(4 if mode == "media" else 0)
        self.list.setMovement(QListWidget.Static)
        # 两种视图的卡片尺寸不同：切换后需同步占位尺寸并重建可视区卡片
        self.list.set_size_hint(QSize(*_CARD_SIZE[mode]))
        self.list.release_all()
        self.list.sync_visible()

    def set_title(self, text: str) -> None:
        self.list_title.setText(text)

    def set_notes(self, notes: list[Note], thumbs: dict[int, QPixmap] | None = None) -> None:
        """填入笔记列表。

        只创建占位 item，卡片控件由 CardList 按可视区惰性实例化。
        旧实现为每篇笔记都建一个完整卡片控件（单卡约 40ms），
        2000 篇会产生约 6 万个控件、阻塞界面数十秒。
        """
        self._notes = list(notes)
        self._thumbs = dict(thumbs or {})

        has = bool(self._notes)
        self.list.setVisible(has)
        self.empty.setVisible(not has)
        self.count_label.setText(str(len(self._notes)))

        self.list.set_rows(self._notes)

    def set_current(self, note_id: int | None) -> None:
        """设置当前选中项（O(1) 定位，只更新已实例化的卡片）。"""
        self.list.set_current(note_id)

    def current_id(self) -> int | None:
        return self.list.current_id()

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        self.noteSelected.emit(int(item.data(Qt.UserRole)))

    def _on_ctx(self, pos: QPoint) -> None:
        item = self.list.itemAt(pos)
        if item is None:
            return
        self.noteContextRequested.emit(int(item.data(Qt.UserRole)),
                                       self.list.viewport().mapToGlobal(pos))

    def set_empty_text(self, icon: str, title: str, subtitle: str = "") -> None:
        """参数顺序与 EmptyState 保持一致：图标、标题、副标题。"""
        self.empty.set_texts(title, subtitle, icon)

    def refresh(self, theme: str) -> None:
        self._theme = theme
        for b in [self.btn_new, *self.view_group]:
            b.refresh(theme)
        self.empty.refresh(theme)
        # 只有可视区内的卡片需要重新着色（选中态由全局 QSS 负责）
        for card in self.list.cards():
            if isinstance(card, NoteCard):
                card.refresh(theme)
            elif isinstance(card, MediaCard):
                card._sync_style()
        self.style().unpolish(self)
        self.style().polish(self)
