"""文献模块界面：文献列表、文献详情（元数据 / 摘要 / 附件 / 关联笔记 / 引用格式）。"""
from __future__ import annotations


from PySide6.QtCore import QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPlainTextEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .. import icons
from ..models import ENTRY_TYPES, READ_STATES, Reference
from ..services.assets import format_duration
from ..services.literature import export_bibtex
from ..theme import tokens
from ..widgets.card_list import CardList
from ..widgets.common import (
    EmptyState,
    HRule,
    IconButton,
    Pill,
    StarRating,
    TextButton,
    elide,
)
from ..widgets.flow_layout import FlowLayout

SORT_OPTIONS = [
    ("added_desc", "加入时间"),
    ("year_desc", "年份 ↓"),
    ("year_asc", "年份 ↑"),
    ("title_asc", "标题 A→Z"),
    ("authors_asc", "作者 A→Z"),
]

READ_COLORS = {0: "#8B9AAB", 1: "#D0854C", 2: "#57896A"}


# --------------------------------------------------------------------------- #
class RefCard(QWidget):
    starredToggled = Signal(int, bool)
    doubleClicked = Signal(int)

    def __init__(self, ref: Reference, theme: str = "light", parent=None):
        super().__init__(parent)
        self.setObjectName("RefCard")
        self.ref_id = ref.id
        self._theme = theme
        self._selected = False
        # 选中态由全局 QSS 的 #RefCard[sel="true"] 驱动，避免逐卡 setStyleSheet
        self.setProperty("sel", "false")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(13, 9, 11, 9)
        lay.setSpacing(4)

        top = QHBoxLayout()
        top.setSpacing(7)
        self.type_pill = Pill(ref.type_text, tokens(theme)["blue"], theme, parent=self)
        top.addWidget(self.type_pill, 0, Qt.AlignTop)
        self.title = QLabel(self)
        self.title.setWordWrap(True)
        self.title.setProperty("role", "cardTitle")
        top.addWidget(self.title, 1)
        self.star = IconButton("star", theme, 22, 15, parent=self)
        self.star.setCheckable(True)
        self.star.clicked.connect(
            lambda: self.starredToggled.emit(self.ref_id, self.star.isChecked()))
        top.addWidget(self.star, 0, Qt.AlignTop)
        lay.addLayout(top)

        self.authors = QLabel(self)
        self.authors.setProperty("role", "secondary")
        lay.addWidget(self.authors)

        meta = QHBoxLayout()
        meta.setSpacing(8)
        self.venue = QLabel(self)
        self.venue.setProperty("role", "muted")
        meta.addWidget(self.venue, 1)
        self.badges = QLabel(self)
        self.badges.setProperty("role", "muted")
        meta.addWidget(self.badges, 0, Qt.AlignRight)
        lay.addLayout(meta)

        self.set_ref(ref)
        self.refresh(theme)

    def set_ref(self, ref: Reference) -> None:
        self.ref_id = ref.id
        self.title.setText(elide(ref.title or "（无标题）", 340))
        self.title.setToolTip(ref.title)
        self.authors.setText(elide(
            ", ".join(ref.author_list[:4]) + (" 等" if len(ref.author_list) > 4 else ""), 300)
            or "佚名")
        venue = ref.venue_short
        self.venue.setText(elide(f"{venue} · {ref.year_text}", 260))
        bad = []
        if ref.pdf_count:
            bad.append(f"PDF {ref.pdf_count}")
        if ref.read_state:
            bad.append(READ_STATES.get(ref.read_state, ""))
        if ref.rating:
            bad.append("★" * ref.rating)
        if ref.tags:
            bad.append(" ".join("#" + t for t in ref.tags[:2]))
        self.badges.setText("   ".join(bad))
        self.star.setChecked(ref.is_starred)
        self._refresh_star()

    def _refresh_star(self) -> None:
        t = tokens(self._theme)
        on = self.star.isChecked()
        self.star.setIcon(icons.icon("star_fill" if on else "star",
                                     t["orange"] if on else t["text_muted"], 15))

    def refresh(self, theme: str) -> None:
        self._theme = theme
        self.type_pill.set_colors(tokens(theme)["blue"], theme)
        self.star.refresh(theme)
        self._refresh_star()
        self._sync_style()

    def set_selected(self, value: bool) -> None:
        self._selected = value
        self._sync_style()

    def _sync_style(self) -> None:
        """按选中态刷新背景（动态属性 + 全局 QSS，不用 setStyleSheet）。"""
        want = "true" if self._selected else "false"
        if self.property("sel") == want:
            return
        self.setProperty("sel", want)
        self.style().unpolish(self)
        self.style().polish(self)

    _apply_bg = _sync_style

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        self.doubleClicked.emit(self.ref_id)
        super().mouseDoubleClickEvent(event)


# --------------------------------------------------------------------------- #
class RefListPane(QFrame):
    refSelected = Signal(int)
    refStarred = Signal(int, bool)
    refContextRequested = Signal(int, QPoint)
    newRefRequested = Signal()
    importBibRequested = Signal()
    doiRequested = Signal()
    exportBibRequested = Signal()
    sortChanged = Signal(str)

    def __init__(self, theme: str = "light", parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")
        self.setMinimumWidth(288)
        self._theme = theme

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        head = QWidget()
        hl = QVBoxLayout(head)
        hl.setContentsMargins(13, 11, 11, 8)
        hl.setSpacing(8)

        r1 = QHBoxLayout()
        r1.setSpacing(6)
        self.list_title = QLabel("全部文献")
        self.list_title.setProperty("role", "h1")
        self.count_label = QLabel("0")
        self.count_label.setProperty("role", "muted")
        r1.addWidget(self.list_title)
        r1.addWidget(self.count_label)
        r1.addStretch(1)
        self.btn_add = IconButton("plus", theme, 28, 17, tip="新增文献条目")
        self.btn_add.clicked.connect(self._show_add_menu)
        r1.addWidget(self.btn_add)
        hl.addLayout(r1)

        r2 = QHBoxLayout()
        r2.setSpacing(4)
        self.sort_box = QComboBox()
        for key, label in SORT_OPTIONS:
            self.sort_box.addItem(label, key)
        self.sort_box.setFixedHeight(28)
        self.sort_box.currentIndexChanged.connect(
            lambda i: self.sortChanged.emit(self.sort_box.itemData(i)))
        r2.addWidget(self.sort_box, 1)
        self.btn_import = IconButton("import", theme, 28, 16, tip="导入 BibTeX / RIS 文件")
        self.btn_import.clicked.connect(self.importBibRequested.emit)
        r2.addWidget(self.btn_import)
        self.btn_export = IconButton("export", theme, 28, 16, tip="导出 BibTeX")
        self.btn_export.clicked.connect(self.exportBibRequested.emit)
        r2.addWidget(self.btn_export)
        hl.addLayout(r2)
        root.addWidget(head)

        self.list = CardList(
            factory=self._make_card,
            size_hint=QSize(10, 100),
            id_of=lambda ref: ref.id,
            buffer_rows=12,
            max_cards=240,
        )
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._on_ctx)
        self.list.itemClicked.connect(
            lambda it: self.refSelected.emit(int(it.data(Qt.UserRole))))
        root.addWidget(self.list, 1)

        self.empty = EmptyState("book", "文献库还是空的",
                                "支持手动录入、DOI 一键抓取、BibTeX 批量导入。",
                                theme, "添加文献")
        self.empty.action.clicked.connect(self._show_add_menu)
        root.addWidget(self.empty, 1)
        self.empty.setVisible(False)

    # ------------------------------------------------------------------ #
    def _show_add_menu(self) -> None:
        menu = QMenu(self)
        menu.addAction("手动新增条目", self.newRefRequested.emit)
        menu.addAction("通过 DOI 抓取元数据", self.doiRequested.emit)
        menu.addSeparator()
        menu.addAction("从 BibTeX / RIS 文件导入", self.importBibRequested.emit)
        menu.exec(self.btn_add.mapToGlobal(QPoint(0, self.btn_add.height() + 4)))

    def set_title(self, text: str) -> None:
        self.list_title.setText(text)

    def _make_card(self, ref: Reference, parent) -> QWidget:
        """CardList 的卡片工厂；parent 必须透传（见 CardList 文档）。"""
        card = RefCard(ref, self._theme, parent=parent)
        card.starredToggled.connect(self.refStarred.emit)
        card.doubleClicked.connect(self.refSelected.emit)
        return card

    def set_refs(self, refs: list[Reference]) -> None:
        has = bool(refs)
        self.list.setVisible(has)
        self.empty.setVisible(not has)
        self.count_label.setText(str(len(refs)))
        self.list.set_rows(refs)

    def set_current(self, ref_id: int | None) -> None:
        self.list.set_current(ref_id)

    def current_id(self) -> int | None:
        return self.list.current_id()

    def _on_ctx(self, pos: QPoint) -> None:
        item = self.list.itemAt(pos)
        if item is None:
            return
        self.refContextRequested.emit(int(item.data(Qt.UserRole)),
                                      self.list.viewport().mapToGlobal(pos))

    def refresh(self, theme: str) -> None:
        self._theme = theme
        for b in (self.btn_add, self.btn_import, self.btn_export):
            b.refresh(theme)
        self.empty.refresh(theme)
        for c in self.list.cards():
            c.refresh(theme)


# --------------------------------------------------------------------------- #
class _Field(QWidget):
    """标签 + 单行输入。"""

    edited = Signal(str)

    def __init__(self, label: str, value: str = "", placeholder: str = "",
                 theme: str = "light", width: int = 88, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        self.label = QLabel(label)
        self.label.setProperty("role", "muted")
        self.label.setFixedWidth(width)
        self.label.setAlignment(Qt.AlignRight | Qt.AlignTop)
        self.edit = QLineEdit(value)
        self.edit.setPlaceholderText(placeholder)
        self.edit.setMinimumHeight(30)
        self.edit.textEdited.connect(self.edited.emit)
        lay.addWidget(self.label, 0, Qt.AlignTop)
        lay.addWidget(self.edit, 1)

    def set_value(self, value: str) -> None:
        self.edit.blockSignals(True)
        self.edit.setText(value or "")
        # 长值（作者列表、URL 等）设值后会把可见区滚到末尾，这里回到开头
        self.edit.setCursorPosition(0)
        self.edit.blockSignals(False)

    def value(self) -> str:
        return self.edit.text().strip()


class _Section(QWidget):
    def __init__(self, title: str, theme: str = "light", parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(8)
        self.title = QLabel(title)
        self.title.setProperty("role", "h3")
        head.addWidget(self.title)
        head.addStretch(1)
        self.head_extra = head
        lay.addLayout(head)
        self.body = QVBoxLayout()
        self.body.setSpacing(7)
        lay.addLayout(self.body)
        self._lay = lay

    def add(self, w: QWidget) -> None:
        self.body.addWidget(w)

    def add_layout(self, lay) -> None:
        self.body.addLayout(lay)


class ReferenceDetail(QWidget):
    changed = Signal(int, dict)          # ref_id, fields
    starToggled = Signal(int, bool)
    readStateChanged = Signal(int, int)
    ratingChanged = Signal(int, int)
    deleted = Signal(int)
    attachRequested = Signal(int)
    attachOpened = Signal(int)
    attachRemoved = Signal(int)
    createNoteRequested = Signal(int)
    openNote = Signal(int)
    unlinkNote = Signal(int, int)
    tagsEdited = Signal(int, list)
    doiLookupRequested = Signal(int)
    moreActionRequested = Signal(int, str)

    def __init__(self, theme: str = "light", parent=None):
        super().__init__(parent)
        self._theme = theme
        self._ref: Reference | None = None
        self._loading = False
        self._assets: list = []
        self._notes: list = []
        self._tags: list[str] = []

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(700)
        self._save_timer.timeout.connect(self._flush)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---------- 头部 ---------- #
        head = QWidget()
        hl = QVBoxLayout(head)
        hl.setContentsMargins(28, 16, 24, 8)
        hl.setSpacing(8)

        r1 = QHBoxLayout()
        r1.setSpacing(8)
        self.type_pill = Pill("期刊论文", tokens(theme)["blue"], theme)
        r1.addWidget(self.type_pill, 0, Qt.AlignTop)
        self.title_edit = QLineEdit()
        self.title_edit.setObjectName("TitleEdit")
        self.title_edit.setPlaceholderText("文献标题")
        self.title_edit.textEdited.connect(lambda t: self._queue("title", t))
        r1.addWidget(self.title_edit, 1)
        self.star = IconButton("star", theme, 30, 19, tip="收藏")
        self.star.setCheckable(True)
        self.star.clicked.connect(lambda: self.starToggled.emit(self._ref.id, self.star.isChecked())
                                  if self._ref else None)
        r1.addWidget(self.star, 0, Qt.AlignTop)
        self.btn_more = IconButton("more", theme, 30, 18, tip="更多")
        self.btn_more.clicked.connect(self._show_more)
        r1.addWidget(self.btn_more, 0, Qt.AlignTop)
        hl.addLayout(r1)

        r2 = QHBoxLayout()
        r2.setSpacing(10)
        self.sub_label = QLabel("")
        self.sub_label.setProperty("role", "muted")
        r2.addWidget(self.sub_label)
        r2.addStretch(1)

        self.read_buttons: dict[int, TextButton] = {}
        for state, label in READ_STATES.items():
            b = TextButton(label, "", theme, "segment")
            b.setCheckable(True)
            b.setProperty("segment", "true")
            b.setFixedHeight(26)
            b.clicked.connect(lambda _=False, s=state: self._set_read(s))
            r2.addWidget(b)
            self.read_buttons[state] = b

        r2.addWidget(_vsep(theme))
        self.rating = StarRating(0, theme, 17)
        self.rating.ratingChanged.connect(
            lambda v: self.ratingChanged.emit(self._ref.id, v) if self._ref else None)
        r2.addWidget(self.rating)
        hl.addLayout(r2)
        root.addWidget(head)

        # ---------- 滚动表单 ---------- #
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        host = QWidget()
        self.form = QVBoxLayout(host)
        self.form.setContentsMargins(28, 6, 24, 20)
        self.form.setSpacing(16)

        # 基本信息
        sec1 = _Section("元数据", theme)
        self.f_authors = _Field("作者", placeholder="多位作者用 and 或 ; 分隔", theme=theme)
        self.f_year = _Field("年份", placeholder="2024", theme=theme)
        self.f_container = _Field("期刊 / 会议", placeholder="期刊名或会议名", theme=theme)
        self.f_publisher = _Field("出版方", placeholder="出版社 / 机构", theme=theme)
        volume_row = QHBoxLayout()
        volume_row.setSpacing(10)
        self.f_volume = _Field("卷", theme=theme, width=42)
        self.f_issue = _Field("期", theme=theme, width=42)
        self.f_pages = _Field("页码", placeholder="1-12", theme=theme, width=52)
        volume_row.addWidget(self.f_volume, 1)
        volume_row.addWidget(self.f_issue, 1)
        volume_row.addWidget(self.f_pages, 2)
        self.f_doi = _Field("DOI", theme=theme)
        doi_row = QHBoxLayout()
        doi_row.setSpacing(6)
        doi_row.addWidget(self.f_doi, 1)
        self.btn_doi = TextButton("抓取", "download", theme, "subtle")
        self.btn_doi.setFixedHeight(30)
        self.btn_doi.setToolTip("根据 DOI 从 Crossref 补全元数据")
        self.btn_doi.clicked.connect(
            lambda: self.doiLookupRequested.emit(self._ref.id) if self._ref else None)
        doi_row.addWidget(self.btn_doi)
        self.f_url = _Field("链接", placeholder="https://", theme=theme)
        self.f_citekey = _Field("引用键", placeholder="自动生成", theme=theme, width=52)

        for f, key in ((self.f_authors, "authors"), (self.f_year, "year"),
                       (self.f_container, "container"), (self.f_publisher, "publisher"),
                       (self.f_doi, "doi"), (self.f_url, "url"), (self.f_citekey, "citekey")):
            f.edited.connect(lambda v, k=key: self._queue(k, v))
        self.f_volume.edited.connect(lambda v: self._queue("volume", v))
        self.f_issue.edited.connect(lambda v: self._queue("issue", v))
        self.f_pages.edited.connect(lambda v: self._queue("pages", v))

        sec1.add(self.f_authors)
        sec1.add(self.f_year)
        sec1.add(self.f_container)
        sec1.add(self.f_publisher)
        sec1.add_layout(volume_row)
        sec1.add_layout(doi_row)
        sec1.add(self.f_url)
        sec1.add(self.f_citekey)
        self.form.addWidget(sec1)
        self.form.addWidget(HRule())

        # 类型
        sec2 = _Section("类型与语言", theme)
        trow = QHBoxLayout()
        trow.setSpacing(10)
        self.type_combo = QComboBox()
        for key, label in ENTRY_TYPES:
            self.type_combo.addItem(label, key)
        self.type_combo.setFixedHeight(30)
        self.type_combo.activated.connect(
            lambda i: self._queue("entry_type", self.type_combo.itemData(i)))
        lab_type = QLabel("文献类型")
        lab_type.setProperty("role", "muted")
        lab_type.setFixedWidth(88)
        lab_type.setAlignment(Qt.AlignRight)
        trow.addWidget(lab_type)
        trow.addWidget(self.type_combo, 1)
        sec2.add_layout(trow)
        self.f_language = _Field("语言", placeholder="zh / en", theme=theme)
        self.f_language.edited.connect(lambda v: self._queue("language", v))
        sec2.add(self.f_language)

        krow = QHBoxLayout()
        krow.setSpacing(8)
        klab = QLabel("关键词")
        klab.setProperty("role", "muted")
        klab.setFixedWidth(88)
        klab.setAlignment(Qt.AlignRight | Qt.AlignTop)
        krow.addWidget(klab, 0, Qt.AlignTop)
        kcol = QVBoxLayout()
        kcol.setSpacing(6)
        self.f_keywords = QLineEdit()
        self.f_keywords.setPlaceholderText("用 ; 分隔多个关键词")
        self.f_keywords.setMinimumHeight(30)
        self.f_keywords.textEdited.connect(self._on_keywords)
        kcol.addWidget(self.f_keywords)
        self.kw_host = QWidget()
        self.kw_flow = FlowLayout(self.kw_host, margin=0, h_spacing=5, v_spacing=5)
        kcol.addWidget(self.kw_host)
        krow.addLayout(kcol, 1)
        sec2.add_layout(krow)
        self.form.addWidget(sec2)
        self.form.addWidget(HRule())

        # 摘要 / 备注
        sec3 = _Section("摘要", theme)
        self.abstract = QPlainTextEdit()
        self.abstract.setPlaceholderText("粘贴或自动抓取摘要…")
        self.abstract.setFixedHeight(140)
        self.abstract.textChanged.connect(lambda: self._queue("abstract", self.abstract.toPlainText()))
        sec3.add(self.abstract)
        self.form.addWidget(sec3)

        sec4 = _Section("我的备注", theme)
        self.note_edit = QPlainTextEdit()
        self.note_edit.setPlaceholderText("阅读心得、可复现要点、待验证问题…")
        self.note_edit.setFixedHeight(110)
        self.note_edit.textChanged.connect(lambda: self._queue("note", self.note_edit.toPlainText()))
        sec4.add(self.note_edit)
        self.form.addWidget(sec4)
        self.form.addWidget(HRule())

        # 附件
        sec5 = _Section("全文附件", theme)
        self.btn_attach = TextButton("添加 PDF / 附件", "paperclip", theme, "subtle")
        self.btn_attach.clicked.connect(
            lambda: self.attachRequested.emit(self._ref.id) if self._ref else None)
        sec5.head_extra.addWidget(self.btn_attach)
        self.attach_list = QListWidget()
        self.attach_list.setFrameShape(QFrame.NoFrame)
        self.attach_list.setMaximumHeight(150)
        self.attach_list.itemDoubleClicked.connect(
            lambda it: self.attachOpened.emit(int(it.data(Qt.UserRole))))
        self.attach_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.attach_list.customContextMenuRequested.connect(self._attach_ctx)
        sec5.add(self.attach_list)
        self.form.addWidget(sec5)
        self.form.addWidget(HRule())

        # 引用格式
        sec6 = _Section("引用格式", theme)
        self.cite_apa = self._cite_block("APA", sec6)
        self.cite_gbt = self._cite_block("GB/T 7714", sec6)
        self.cite_bib = self._cite_block("BibTeX", sec6)
        self.form.addWidget(sec6)
        self.form.addWidget(HRule())

        # 关联笔记
        sec7 = _Section("关联笔记", theme)
        self.btn_new_note = TextButton("据此新建笔记", "plus", theme, "subtle")
        self.btn_new_note.clicked.connect(
            lambda: self.createNoteRequested.emit(self._ref.id) if self._ref else None)
        sec7.head_extra.addWidget(self.btn_new_note)
        self.note_list = QListWidget()
        self.note_list.setFrameShape(QFrame.NoFrame)
        self.note_list.setMaximumHeight(160)
        self.note_list.itemDoubleClicked.connect(
            lambda it: self.openNote.emit(int(it.data(Qt.UserRole))))
        self.note_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.note_list.customContextMenuRequested.connect(self._note_ctx)
        sec7.add(self.note_list)
        self.form.addWidget(sec7)

        self.form.addStretch(1)
        self.scroll.setWidget(host)
        root.addWidget(self.scroll, 1)

    # ------------------------------------------------------------------ #
    def _cite_block(self, label: str, parent_section: _Section):
        box = QWidget()
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(4)
        head = QHBoxLayout()
        head.setSpacing(6)
        lab = QLabel(label)
        lab.setProperty("role", "muted")
        head.addWidget(lab)
        head.addStretch(1)
        btn = IconButton("copy", self._theme, 24, 14, tip=f"复制{label}格式")
        head.addWidget(btn)
        bl.addLayout(head)
        edit = QPlainTextEdit()
        edit.setObjectName("Code")
        edit.setReadOnly(True)
        edit.setFixedHeight(74 if label != "BibTeX" else 116)
        edit.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        bl.addWidget(edit)
        btn.clicked.connect(lambda: self._copy(edit.toPlainText(), label))
        parent_section.add(box)
        return edit

    def _copy(self, text: str, label: str) -> None:
        QGuiApplication.clipboard().setText(text)
        self.moreActionRequested.emit(self._ref.id if self._ref else 0, f"copied:{label}")

    # ------------------------------------------------------------------ #
    def load(self, ref: Reference, assets: list, notes: list) -> None:
        self._loading = True
        self._ref = ref
        self._assets = assets
        self._notes = notes
        self._tags = list(ref.tags)

        self.title_edit.setText(ref.title)
        # 设值后 QLineEdit 会把光标留在末尾并自动滚到右边，导致长标题只看得见
        # 尾部。这里显式把光标移回开头，让标题从首字开始显示。
        self.title_edit.setCursorPosition(0)
        self.type_pill.setText(ref.type_text)
        self.type_pill.set_colors(tokens(self._theme)["blue"], self._theme)
        self.star.setChecked(ref.is_starred)
        self._refresh_star()
        self.rating.set_rating(ref.rating)

        self.f_authors.set_value(ref.authors)
        self.f_year.set_value(ref.year)
        self.f_container.set_value(ref.container)
        self.f_publisher.set_value(ref.publisher)
        self.f_volume.set_value(ref.volume)
        self.f_issue.set_value(ref.issue)
        self.f_pages.set_value(ref.pages)
        self.f_doi.set_value(ref.doi)
        self.f_url.set_value(ref.url)
        self.f_citekey.set_value(ref.citekey)
        self.f_language.set_value(ref.language)
        self.f_keywords.setText(ref.keywords)

        idx = self.type_combo.findData(ref.entry_type)
        self.type_combo.setCurrentIndex(max(0, idx))
        for state, b in self.read_buttons.items():
            b.setChecked(state == ref.read_state)

        self.abstract.setPlainText(ref.abstract)
        self.note_edit.setPlainText(ref.note)

        self.sub_label.setText(
            f"{ref.authors_short} · {ref.year_text} · {ref.venue_short}"
            + (f"  ·  加入 {ref.added_at[:10]}" if ref.added_at else "")
        )

        self.cite_apa.setPlainText(ref.citation_apa())
        self.cite_gbt.setPlainText(ref.citation_gbt())
        self.cite_bib.setPlainText(export_bibtex([ref]).strip())

        self._rebuild_keywords()
        self._rebuild_attachments()
        self._rebuild_notes()
        self._loading = False

    def _rebuild_keywords(self) -> None:
        self.kw_flow.clear()
        for kw in self._ref.keyword_list if self._ref else []:
            chip = Pill(kw, tokens(self._theme)["orange"], self._theme)
            self.kw_flow.addWidget(chip)

    def _rebuild_attachments(self) -> None:
        self.attach_list.clear()
        for a in self._assets:
            icon = {"image": "image", "video": "video", "pdf": "book"}.get(a.kind, "paperclip")
            text = f"{a.filename}    {a.size_text}"
            if a.duration_ms:
                text += f"    {format_duration(a.duration_ms)}"
            item = QListWidgetItem(icons.icon(icon, tokens(self._theme)["text_secondary"], 16), text)
            item.setData(Qt.UserRole, a.id)
            self.attach_list.addItem(item)
        if not self._assets:
            item = QListWidgetItem("暂无附件，点击右上角「添加 PDF / 附件」")
            item.setFlags(Qt.NoItemFlags)
            self.attach_list.addItem(item)

    def _rebuild_notes(self) -> None:
        self.note_list.clear()
        for n in self._notes:
            item = QListWidgetItem(icons.icon("note", tokens(self._theme)["text_secondary"], 16), n.title)
            item.setData(Qt.UserRole, n.id)
            self.note_list.addItem(item)
        if not self._notes:
            item = QListWidgetItem("还没有关联笔记")
            item.setFlags(Qt.NoItemFlags)
            self.note_list.addItem(item)

    # ------------------------------------------------------------------ #
    def _queue(self, key: str, value) -> None:
        if self._loading or not self._ref:
            return
        self._save_timer.start()
        self._pending = getattr(self, "_pending", {})
        self._pending[key] = value

    def _flush(self) -> None:
        pending = getattr(self, "_pending", {})
        if not pending or not self._ref:
            return
        self._pending = {}
        self.changed.emit(self._ref.id, pending)
        if "citekey" not in pending and any(
                k in pending for k in ("authors", "year", "title")):
            pass

    def flush_now(self) -> None:
        if self._save_timer.isActive():
            self._save_timer.stop()
            self._flush()

    def _on_keywords(self, text: str) -> None:
        self._queue("keywords", text)
        if self._ref:
            self._ref.keywords = text
        self._rebuild_keywords()

    def _set_read(self, state: int) -> None:
        if not self._ref:
            return
        for s, b in self.read_buttons.items():
            b.setChecked(s == state)
        self.readStateChanged.emit(self._ref.id, state)

    def set_read_state(self, state: int) -> None:
        for s, b in self.read_buttons.items():
            b.setChecked(s == state)

    def _refresh_star(self) -> None:
        t = tokens(self._theme)
        on = self.star.isChecked()
        self.star.setIcon(icons.icon("star_fill" if on else "star",
                                     t["orange"] if on else t["text_muted"], 19))

    def set_starred(self, value: bool) -> None:
        self.star.setChecked(value)
        self._refresh_star()

    # ------------------------------------------------------------------ #
    def _attach_ctx(self, pos: QPoint) -> None:
        item = self.attach_list.itemAt(pos)
        if item is None or item.data(Qt.UserRole) is None:
            return
        aid = int(item.data(Qt.UserRole))
        menu = QMenu(self)
        menu.addAction("打开", lambda: self.attachOpened.emit(aid))
        menu.addAction("移除", lambda: self.attachRemoved.emit(aid))
        menu.exec(self.attach_list.viewport().mapToGlobal(pos))

    def _note_ctx(self, pos: QPoint) -> None:
        item = self.note_list.itemAt(pos)
        if item is None or item.data(Qt.UserRole) is None:
            return
        nid = int(item.data(Qt.UserRole))
        menu = QMenu(self)
        menu.addAction("打开笔记", lambda: self.openNote.emit(nid))
        if self._ref:
            menu.addAction("取消关联",
                           lambda: self.unlinkNote.emit(self._ref.id, nid))
        menu.exec(self.note_list.viewport().mapToGlobal(pos))

    def _show_more(self) -> None:
        if not self._ref:
            return
        menu = QMenu(self)
        for label, key in (("复制 APA 引用", "copy_apa"),
                           ("复制 GB/T 7714 引用", "copy_gbt"),
                           ("复制 BibTeX", "copy_bib"),
                           ("复制 DOI 链接", "copy_doi")):
            menu.addAction(label, lambda k=key: self.moreActionRequested.emit(self._ref.id, k))
        menu.addSeparator()
        menu.addAction("据此新建笔记",
                       lambda: self.createNoteRequested.emit(self._ref.id))
        menu.addAction("用 DOI 补全元数据",
                       lambda: self.doiLookupRequested.emit(self._ref.id))
        menu.addSeparator()
        menu.addAction("删除该文献条目",
                       lambda: self.deleted.emit(self._ref.id))
        menu.exec(self.btn_more.mapToGlobal(QPoint(0, self.btn_more.height() + 4)))

    # ------------------------------------------------------------------ #
    def refresh(self, theme: str) -> None:
        self._theme = theme
        t = tokens(theme)
        for b in (self.star, self.btn_more, self.btn_doi):
            b.refresh(theme)
        for b in self.read_buttons.values():
            b.refresh(theme)
        self.type_pill.set_colors(t["blue"], theme)
        self._refresh_star()
        self._rebuild_keywords()
        if self._ref:
            self._rebuild_attachments()
            self._rebuild_notes()

    def focus_title(self) -> None:
        self.title_edit.setFocus()
        self.title_edit.selectAll()


def _vsep(theme: str) -> QFrame:
    f = QFrame()
    f.setFixedWidth(1)
    f.setFixedHeight(18)
    f.setStyleSheet(f"background: {tokens(theme)['border']};")
    return f
